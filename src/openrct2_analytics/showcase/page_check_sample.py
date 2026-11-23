"""Check the page's sample statement against the served sample record."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

from openrct2_analytics.showcase.page_check_site import PageCheckFailed, _require
from openrct2_analytics.showcase.page_check_text import STALE_SAMPLE_PHRASES

_VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
)
# Inline tags join their text to the neighbours without a space: head<em>less</em> reads headless.
_INLINE = frozenset(
    {"a", "abbr", "b", "bdi", "bdo", "cite", "code", "data", "dfn", "em", "i", "kbd", "mark"}
    | {"q", "s", "small", "span", "strong", "sub", "sup", "time", "u", "var"}
)
PENDING_TEXT = "figure pending"
PARK_SCOPE = "the parks listed in the park-years table"
ZERO_PARK_SCOPE = "parks with no closed monthly statement yet"
_ATTRIBUTES = {
    "data-data-set": "data_set",
    "data-parks": "parks",
    "data-sessions": "sessions",
    "data-player-played": "player_played",
}


class _Open:
    """One open element: its text so far and whether it is the statement or the sample figure."""

    def __init__(self, tag: str, attrs: dict[str, str | None]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parts: list[str] = []
        # Text outside any statement element: an ancestor's own text, not the statement's.
        self.outside: list[str] = []
        self.is_statement = "data-sample-statement" in attrs
        self.is_figure = attrs.get("data-figure") == "sample"


class _SampleParser(HTMLParser):
    """Collect every statement element and count other elements whose text begins "Sample:".

    An element's text leaves out its figure unit lines. The states of the sample figures inside
    the statement are kept, so the check can tell a live figure from a pending one. Only the
    statement and its own sample figure may begin "Sample:"; an element holding the statement
    counts by its text outside the statement.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.statements: list[tuple[dict[str, str | None], str]] = []
        self.other_samples = 0
        self.sample_states: list[str | None] = []
        self.text: list[str] = []
        self._stack: list[_Open] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID:
            return
        element = _Open(tag, dict(attrs))
        if element.is_figure and self._in_statement():
            self.sample_states.append(element.attrs.get("data-figure-state"))
        else:
            element.is_figure = False
        if tag not in _INLINE:
            self.text.append(" ")
        self._stack.append(element)

    def _in_statement(self) -> bool:
        return any(element.is_statement for element in self._stack)

    def _in_figure(self) -> bool:
        return any(element.is_figure for element in self._stack)

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if any("data-figure-unit" in element.attrs for element in self._stack):
            return
        first = next((i for i, element in enumerate(self._stack) if element.is_statement), None)
        for index, element in enumerate(self._stack):
            element.parts.append(data)
            if first is None or index >= first:
                element.outside.append(data)

    def handle_endtag(self, tag: str) -> None:
        if any(element.tag == tag for element in self._stack):
            while self._pop() != tag:
                pass

    def _pop(self) -> str:
        element = self._stack.pop()
        if element.is_statement:
            self.statements.append((element.attrs, _flat(element.parts)))
        elif self._in_statement():
            if (
                not element.is_figure
                and not self._in_figure()
                and _flat(element.parts).startswith("Sample:")
            ):
                self.other_samples += 1
        elif _flat(element.outside).startswith("Sample:"):
            self.other_samples += 1
        if element.tag not in _INLINE:
            self.text.append(" ")
        return element.tag

    def finish(self) -> None:
        self.close()
        while self._stack:
            self._pop()


def _flat(parts: list[str]) -> str:
    return " ".join("".join(parts).split())


def _scalar(value: object) -> str:
    return json.dumps(value) if isinstance(value, bool) else str(value)


def _record(served_dir: Path) -> dict[str, object]:
    path = served_dir / "sample.json"
    if not path.is_file():
        raise PageCheckFailed("sample statement: sample.json is missing")
    try:
        rows = json.loads(path.read_text())["rows"]
        record = rows[0]
        data_set, parks, sessions, played = (record[name] for name in _ATTRIBUTES.values())
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise PageCheckFailed(
            f"sample statement: sample.json holds no valid record ({error!r})"
        ) from error
    _require(
        isinstance(data_set, str)
        and type(parks) is int
        and type(sessions) is int
        and isinstance(played, bool),
        "sample statement: sample.json holds no valid record (a field has the wrong type)",
    )
    return dict(record)


def _served_parks(served_dir: Path) -> int:
    path = served_dir / "park_year.json"
    if not path.is_file():
        raise PageCheckFailed("sample statement: park_year.json is missing")
    return len({row["park_id"] for row in json.loads(path.read_text())["rows"]})


def check_sample(html: str, served_dir: Path) -> None:
    """Require one statement element that agrees with `sample.json` and `park_year.json`."""
    record = _record(served_dir)
    parser = _SampleParser()
    parser.feed(html)
    parser.finish()
    _require(
        len(parser.statements) == 1,
        f"sample statement: exactly one element must carry data-sample-statement "
        f"(found {len(parser.statements)})",
    )
    attrs, text = parser.statements[0]
    for attribute, name in _ATTRIBUTES.items():
        _require(
            attrs.get(attribute) == _scalar(record[name]),
            f"sample statement: {attribute} is {attrs.get(attribute)!r}, "
            f"the record holds {_scalar(record[name])}",
        )
    _require(
        parser.other_samples == 0,
        "sample statement: another element's text begins 'Sample:'",
    )
    if record["sessions"] == 0:
        _check_pending(parser, text)
    else:
        _check_live(parser, text, record)
    parks = _served_parks(served_dir)
    _require(
        record["parks"] == parks,
        f"sample statement: the record holds {record['parks']} parks, park_year.json holds {parks}",
    )
    page = _flat(parser.text).lower()
    _require(
        not any(phrase in page for phrase in STALE_SAMPLE_PHRASES),
        "sample statement: the page holds a stale sample sentence",
    )


def _check_pending(parser: _SampleParser, text: str) -> None:
    """A record with no session leaves the sample figure pending and no numeral."""
    _require(
        parser.sample_states == ["pending"],
        "sample statement: the record holds no session, so the statement must hold "
        "one pending sample figure",
    )
    _require(
        not re.search(r"\d", text),
        "sample statement: the record holds no session, so the text must hold no numeral",
    )
    _require(
        text == PENDING_TEXT,
        "sample statement: the record holds no session, so the statement must hold "
        "only its pending figure",
    )


def _check_live(parser: _SampleParser, text: str, record: dict[str, object]) -> None:
    _require(
        "pending" not in parser.sample_states,
        "sample statement: the record holds sessions, so the sample figure must not be pending",
    )
    _require(
        parser.sample_states == ["live"],
        "sample statement: the record holds sessions, so the statement must hold "
        "one live sample figure",
    )
    lowered = text.lower()
    _require(text.startswith("Sample:"), "sample statement: the text must begin 'Sample:'")
    _require(
        text.count("Sample:") == 1,
        "sample statement: the text must hold one 'Sample:' sentence",
    )
    tokens = re.findall(r"\S*\d\S*", text)
    _require(
        tokens == [str(record["sessions"])]
        and bool(re.search(rf"(?<!\S){record['sessions']} (?:headless )?sessions\b", lowered)),
        "sample statement: the text must hold the sessions numeral and no other numeral",
    )
    _require("observational" in lowered, "sample statement: the word observational is missing")
    if record["parks"] == 0:
        _require(
            ZERO_PARK_SCOPE in lowered and "park-years table" not in lowered,
            "sample statement: the record holds no park, so the text must name parks with no "
            "closed monthly statement yet and not the park-years table",
        )
    else:
        _require(
            PARK_SCOPE in lowered,
            "sample statement: the text must name the parks listed in the park-years table",
        )
    if record["player_played"]:
        _require(
            "headless" not in lowered and "no player" not in lowered,
            "sample statement: a player played, so headless and no player must not appear",
        )
        _require(
            "at least one with a player" in lowered,
            "sample statement: a player played, so 'at least one with a player' is required",
        )
    else:
        _require(
            "headless" in lowered and "no player" in lowered,
            "sample statement: no player played, so headless and no player are required",
        )

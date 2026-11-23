"""Proof by data swap (R28): the real site built over empty exports and over two fixture sets.

Every live figure region shows only formatted values and row keys of its build's exports, pending
regions say "figure pending", and the numbers outside figure regions are the same in every build
and are exactly the "Numbers kept as copy" entries of `tests/site_copy_figures/` plus the pinned
not-a-figure patterns.
"""

from __future__ import annotations

import re
import tomllib
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from openrct2_analytics.showcase.page_check import main as page_check_main
from tests.page_check_support import render_page
from tests.site_fixtures import MONEY_COLUMNS, ROOT, SETS, fixture_rows, usd, write_set

COPY_FIGURES = ROOT / "tests/site_copy_figures"
NUMBER = re.compile(r"(?<![\w.$-])-?\$?\d[\d,]*(?:\.\d+)?")
# Not figures, so not "Numbers kept as copy" (spec, "Not figures, so not in the list").
NOT_FIGURES = (
    re.compile(r"\bNo\. 0[1-9]\b"),  # section numbers
    re.compile(r"(?<![\w.,$-])0[1-7](?![\d.,])"),  # the menu's 01 to 07
    re.compile(r"\bStep [1-9] of [1-9]\b"),
    re.compile(r"(?<![\d.])(?:0|12|1\.5) ms\b"),  # the gauges' axis ends
    re.compile(r"\bADR \d{4}\b"),
    # Model names; text nodes are joined without a space, so a name can touch the text around it.
    re.compile(r"(?:Opus|Sonnet|Haiku) 5\.5(?![.\d])"),
    re.compile(r"Gemini 3\.8(?![.\d])"),
    re.compile(r"\bas of October 2026\b"),  # the "models as of" line
)
_VOID = {"meta", "link", "img", "br", "hr", "input", "source", "wbr", "col", "area", "base", "use"}


class _Regions(HTMLParser):
    """Split the page text into figure regions (id, state, unit, body) and the text outside them."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.figures: list[dict[str, Any]] = []
        self.outside: list[str] = []
        self.ids: set[str] = set()
        self.tables: dict[str, list[list[str]]] = {}
        self._stack: list[tuple[str, list[list[str]], dict[str, Any] | None]] = []
        self._skip = 0
        self._table: str | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        self.ids.update(filter(None, [values.get("id")]))
        captures: list[list[str]] = []
        figure: dict[str, Any] | None = None
        if "data-figure" in values:
            figure = {"id": values["data-figure"], "state": values.get("data-figure-state")}
            figure.update(text=[], unit=[], body=[])
            self.figures.append(figure)
            captures.append(figure["text"])
        owner = figure or next((f[2] for f in reversed(self._stack) if f[2] is not None), None)
        for attribute, key in (("data-figure-unit", "unit"), ("data-figure-body", "body")):
            if owner is not None and attribute in values:
                captures.append(owner[key])
        if tag in {"script", "style"}:
            self._skip += 1
        if tag == "table" and values.get("id"):
            self._table = values["id"]
            self.tables[self._table] = []
        if self._table and tag == "tr":
            self.tables[self._table].append([])
        if self._table and tag in {"td", "th"}:
            self._cell = []
        if tag not in _VOID:
            self._stack.append((tag, captures, figure))

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._skip -= 1
        if self._cell is not None and tag in {"td", "th"} and self._table:
            self.tables[self._table][-1].append(" ".join("".join(self._cell).split()))
            self._cell = None
        if tag == "table":
            self._table = None
        if any(frame[0] == tag for frame in self._stack):
            while self._stack.pop()[0] != tag:
                pass

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._cell is not None:
            self._cell.append(data)
        for _, captures, _ in self._stack:
            for parts in captures:
                parts.append(data)
        if all(frame[2] is None for frame in self._stack):
            self.outside.append(data)


def _text(parts: object) -> str:
    assert isinstance(parts, list)
    # Text nodes are joined with a space, so adjacent table cells never run together.
    return " ".join(" ".join(parts).split())


@pytest.fixture(scope="module")
def builds(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[Path, Path, _Regions]]:
    built: dict[str, tuple[Path, Path, _Regions]] = {}
    for name in SETS:
        work = tmp_path_factory.mktemp(f"site-{name}")
        served = write_set(name, work / "served")
        site = render_page(served, work)
        parser = _Regions()
        parser.feed((site / "index.html").read_text())
        built[name] = (site, served, parser)
    return built


def _allowed_tokens(name: str) -> set[str]:
    """Every formatted value and row-key number of one fixture set."""
    allowed: set[str] = set()
    for rows in fixture_rows(name).values():
        for row in rows:
            for column, value in row.items():
                if isinstance(value, bool):
                    continue
                if column in MONEY_COLUMNS:
                    allowed.add(usd(float(value)))  # a money column, formatted as on the page
                elif isinstance(value, int):
                    allowed.add(str(value))  # an integer column value: a count or a row key
                elif isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    allowed.add(value[:4])  # the year of a date column, as a row key
    return allowed


# Live in every build: its counts come from `site/figures/built-counts.mjs`, not from the exports.
COUNTS_FIGURE = "built-numbers"


@pytest.mark.parametrize("name", SETS, ids=SETS)
def test_build_passes_the_page_check_and_its_regions_follow_the_data(
    builds: dict[str, tuple[Path, Path, _Regions]], name: str
) -> None:
    site, served, parser = builds[name]
    assert page_check_main(["--site", str(site), "--served-dir", str(served)]) == 0
    figures = {str(f["id"]): f for f in parser.figures}
    assert len(figures) == len(parser.figures), "a figure id appears twice"
    for figure in parser.figures:
        assert figure["state"] in {"live", "pending"}
        assert "unit:" in _text(figure["unit"]) and "clock:" in _text(figure["unit"])
    if name == "empty":
        assert parser.tables["park-month-table"][1:] == []
        assert parser.tables["park-year-table"][1:] == []
        assert "company-year-table" not in parser.ids
        assert _text(figures["company-year"]["body"]) == "No company year has closed yet."
        for figure_id, figure in figures.items():
            if figure_id in {"company-year", "park-year", "park-month", COUNTS_FIGURE}:
                assert figure["state"] == "live"
                continue
            assert figure["state"] == "pending", figure_id
            assert _text(figure["body"]) == "figure pending", figure_id
            assert not re.search(r"\d", _text(figure["text"])), figure_id
        return
    allowed = _allowed_tokens(name)
    live = [f for f in parser.figures if f["state"] == "live"]
    assert {"company-years", "company-year", "park-year", "park-month"} <= {f["id"] for f in live}
    for figure in live:
        if figure["id"] == COUNTS_FIGURE:
            continue
        text = re.sub(r"k\d{13}-[a-z0-9]{6}", " ", _text(figure["text"]))
        text = re.sub(r"\bPark [1-9]\d?\b", " ", text)  # park labels by order, checked below
        for token in NUMBER.findall(text):
            assert token in allowed, (figure["id"], token)
    parks = {row["park_id"] for row in fixture_rows(name)["park_month"]}
    openings = _text(figures["park-openings"]["text"])
    assert re.findall(r"\bPark ([1-9]\d?)\b", openings) == [
        str(number) for number in range(1, len(parks) + 1)
    ]
    month_rows = parser.tables["park-month-table"][1:]
    assert len(month_rows) == len(fixture_rows(name)["park_month"])
    assert [row[1] for row in month_rows] == [
        usd(float(row["operating_profit"])) for row in fixture_rows(name)["park_month"]
    ]


def _live_text(parser: _Regions) -> str:
    return " ".join(_text(f["text"]) for f in parser.figures if f["state"] == "live")


def test_no_money_value_or_count_of_build_a_shows_in_build_b(
    builds: dict[str, tuple[Path, Path, _Regions]],
) -> None:
    _, _, a = builds["A"]
    _, _, b = builds["B"]
    a_money = {t for t in NUMBER.findall(_live_text(a)) if t.lstrip("-").startswith("$")}
    b_money = {t for t in NUMBER.findall(_live_text(b)) if t.lstrip("-").startswith("$")}
    assert a_money and b_money and not a_money & b_money
    # Count columns: company-year parks reporting, partial seasons, months checked; park-year
    # statements kept (a complete year's "8 of 8" excluded: both sets share the expected count)
    # and months checked.
    columns = {"company-year-table": (1, 2, 3), "park-year-table": (2, 3)}
    for table, indexes in columns.items():
        for index in indexes:
            values = []
            for parser in (a, b):
                cells = {row[index] for row in parser.tables[table][1:]}
                values.append(cells - {"8 of 8"})
            assert values[0] and values[1] and not values[0] & values[1], (table, index)


def _contracts_line() -> str:
    """The contracts line the page shows, computed from the contract files (K13)."""
    files = sorted((ROOT / "contracts").glob("*.odcs.yaml"))
    versions = {
        match.group(1)
        for path in files
        if (match := re.search(r"^version: (\S+)", path.read_text(), re.MULTILINE))
    }
    assert len(versions) == 1, f"the contracts do not share one version: {sorted(versions)}"
    return f"{len(files)} contracts share one version line, {versions.pop()}"


def _kept_entries() -> list[tuple[str, dict[str, Any]]]:
    entries = []
    for path in sorted(COPY_FIGURES.glob("*.toml")):
        for entry in tomllib.loads(path.read_text()).get("kept", []):
            if entry.get("dynamic") == "contracts":
                entry = {**entry, "shown": [_contracts_line()]}
            entries.append((path.name, entry))
    return entries


def _outside_numbers(parser: _Regions) -> list[str]:
    text = " ".join("".join(parser.outside).split())
    for _, entry in _kept_entries():
        for shown in entry["shown"]:
            text = text.replace(str(shown), " ")
    for pattern in NOT_FIGURES:
        text = pattern.sub(" ", text)
    return NUMBER.findall(text)


def test_numbers_outside_figure_regions_are_kept_copy_only(
    builds: dict[str, tuple[Path, Path, _Regions]],
) -> None:
    texts = {
        name: " ".join("".join(parser.outside).split()) for name, (_, _, parser) in builds.items()
    }
    numbers = {name: NUMBER.findall(text) for name, text in texts.items()}
    assert numbers["empty"] == numbers["A"] == numbers["B"]
    for name, (_, _, parser) in builds.items():
        assert _outside_numbers(parser) == [], name
        for file, entry in _kept_entries():
            for shown in entry["shown"]:
                assert str(shown) in texts[name], (file, entry["id"], shown)


def test_each_kept_number_phrase_is_in_its_source_file() -> None:
    entries = _kept_entries()
    assert entries, "no kept-number entry is listed"
    for file, entry in entries:
        if "dynamic" in entry:
            continue  # shown text computed from its source files; no fixed phrase to find
        source = (ROOT / str(entry["source"])).read_text()
        for phrase in entry["phrases"]:
            assert str(phrase) in source, (file, entry["id"], phrase)


def test_an_unlisted_number_outside_the_regions_fails(
    builds: dict[str, tuple[Path, Path, _Regions]],
) -> None:
    parser = _Regions()
    page = (builds["empty"][0] / "index.html").read_text()
    parser.feed(page.replace("</footer>", "<p>Opened 3 rides.</p></footer>"))
    assert _outside_numbers(parser) == ["3"]


def test_the_built_page_has_no_link_placeholder_and_links_to_the_repository_and_author(
    builds: dict[str, tuple[Path, Path, _Regions]],
) -> None:
    site, _, _ = builds["empty"]
    html = (site / "index.html").read_text()
    assert "[link:" not in html
    for url in ("https://github.com/jcabiles/openrct2-analytics", "https://github.com/jcabiles"):
        assert html.count(f'href="{url}" rel="noopener noreferrer"') == 3, url
    built = html.split('id="built"')[1].split("</section>")[0]
    assert 'data-figure-state="pending"' not in built

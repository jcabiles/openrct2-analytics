"""Case 20: the page check pins the page's sample statement to the served sample record."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openrct2_analytics.showcase.page_check_sample import check_sample
from openrct2_analytics.showcase.page_check_site import PageCheckFailed
from tests.page_check_support import (
    FIGURE_OPEN,
    ROOT,
    SAMPLE_STATEMENT,
    Fault,
    _html,
    _run,
    _site,
    render_page,
    write_sample_record,
)
from tests.site_fixtures import write_set

PLAYER_RECORD = {"data_set": "company", "parks": 1, "sessions": 5, "player_played": True}
_PLAYER_OPEN = (
    '<p data-sample-statement data-data-set="company" data-parks="1" data-sessions="5" '
    'data-player-played="true">'
)
PLAYER_BODY = (
    "Sample: the parks listed in the park-years table, 5 sessions, at least one with a player;"
    " observational."
)


def _figure(body: str, state: str = "live") -> str:
    return FIGURE_OPEN.format(state=state, period="this build", body=body)


PLAYER_STATEMENT = _PLAYER_OPEN + _figure(PLAYER_BODY) + "</p>"


ZERO_RECORD = {"data_set": "sample", "parks": 1, "sessions": 0, "player_played": False}
_ZERO_OPEN = (
    '<p data-sample-statement data-data-set="sample" data-parks="1" data-sessions="0" '
    'data-player-played="false">'
)
PENDING_FIGURE = FIGURE_OPEN.format(state="pending", period="figure pending", body="figure pending")
ZERO_STATEMENT = _ZERO_OPEN + PENDING_FIGURE + "</p>"
LIVE_STATEMENT = SAMPLE_STATEMENT


def _zero_page(site: Path, served: Path, statement: str = ZERO_STATEMENT) -> None:
    write_sample_record(served, ZERO_RECORD)
    _html(SAMPLE_STATEMENT, statement)(site, served)


def _player_page(site: Path, served: Path, statement: str = PLAYER_STATEMENT) -> None:
    write_sample_record(served, PLAYER_RECORD)
    _html(SAMPLE_STATEMENT, statement)(site, served)


def _two_parks_in_the_record(site: Path, served: Path) -> None:
    write_sample_record(
        served, {"data_set": "sample", "parks": 2, "sessions": 3, "player_played": False}
    )
    _html('data-parks="1"', 'data-parks="2"')(site, served)


def _missing_record(site: Path, served: Path) -> None:
    (served / "sample.json").unlink()


FAULTS: list[tuple[str, Fault, str]] = [
    (
        "attribute differs from the record",
        _html('data-sessions="3"', 'data-sessions="4"'),
        "sample statement: data-sessions is '4', the record holds 3",
    ),
    (
        "player flag differs from the record",
        _html('data-player-played="false"', 'data-player-played="true"'),
        "sample statement: data-player-played is 'true', the record holds false",
    ),
    (
        "text does not begin with Sample",
        _html("Sample: the parks", "The parks"),
        "sample statement: the text must begin 'Sample:'",
    ),
    (
        "observational missing",
        _html("observational.", "descriptive."),
        "sample statement: the word observational is missing",
    ),
    (
        "second numeral",
        _html("observational.", "observational, 7 times."),
        "sample statement: the text must hold the sessions numeral and no other numeral",
    ),
    (
        "sessions numeral missing from the text",
        _html("3 headless", "three headless"),
        "sample statement: the text must hold the sessions numeral and no other numeral",
    ),
    (
        "headless while a player played",
        lambda site, served: _player_page(
            site, served, PLAYER_STATEMENT.replace("5 sessions,", "5 headless sessions,")
        ),
        "sample statement: a player played, so headless and no player must not appear",
    ),
    (
        "player record with a bare sentence",
        lambda site, served: _player_page(
            site,
            served,
            _PLAYER_OPEN + _figure("Sample: 5 sessions; observational.") + "</p>",
        ),
        "sample statement: the text must name the parks listed in the park-years table",
    ),
    (
        "no-player record without the headless wording",
        _html("headless sessions with no player", "sessions"),
        "sample statement: no player played, so headless and no player are required",
    ),
    (
        "second element beginning Sample",
        _html("</p><p>No company year", "</p><p>Sample: another sentence.</p><p>No company year"),
        "sample statement: another element's text begins 'Sample:'",
    ),
    (
        "second statement element",
        _html("</p><p>No company year", f"</p>{SAMPLE_STATEMENT}<p>No company year"),
        "sample statement: exactly one element must carry data-sample-statement (found 2)",
    ),
    (
        "no statement element",
        _html(SAMPLE_STATEMENT, ""),
        "sample statement: exactly one element must carry data-sample-statement (found 0)",
    ),
    (
        "stale sentence elsewhere on the page",
        _html(
            "</p><p>No company year",
            "</p><p>Earlier build: three headless sessions with no player.</p><p>No company year",
        ),
        "sample statement: the page holds a stale sample sentence",
    ),
    (
        "record parks differ from the distinct parks of park_year.json",
        _two_parks_in_the_record,
        "sample statement: the record holds 2 parks, park_year.json holds 1",
    ),
    (
        "zero sessions with a numeral in the statement",
        lambda site, served: _zero_page(
            site, served, ZERO_STATEMENT.replace("figure pending</span></span>", "0</span></span>")
        ),
        "sample statement: the record holds no session, so the text must hold no numeral",
    ),
    (
        "zero sessions with no statement element",
        lambda site, served: _zero_page(site, served, ""),
        "sample statement: exactly one element must carry data-sample-statement (found 0)",
    ),
    (
        "zero sessions with a live figure",
        lambda site, served: _zero_page(
            site,
            served,
            _ZERO_OPEN + PENDING_FIGURE.replace('state="pending"', 'state="live"') + "</p>",
        ),
        "sample statement: the record holds no session, so the statement must hold "
        "one pending sample figure",
    ),
    (
        "one or more sessions with a pending figure",
        lambda site, served: _html(
            SAMPLE_STATEMENT,
            LIVE_STATEMENT.replace('data-figure-state="live"', 'data-figure-state="pending"'),
        )(site, served),
        "sample statement: the record holds sessions, so the sample figure must not be pending",
    ),
    (
        "no-player record without the park-years reference",
        _html("the parks listed in the park-years table, ", ""),
        "sample statement: the text must name the parks listed in the park-years table",
    ),
    (
        "player record without the park-years reference",
        lambda site, served: _player_page(
            site, served, PLAYER_STATEMENT.replace("the parks listed in the park-years table, ", "")
        ),
        "sample statement: the text must name the parks listed in the park-years table",
    ),
    (
        "data-set label differs from the record (page says company)",
        _html('data-data-set="sample"', 'data-data-set="company"'),
        "sample statement: data-data-set is 'company', the record holds sample",
    ),
    (
        "data-set label differs from the record (record says company)",
        lambda site, served: _player_page(
            site,
            served,
            PLAYER_STATEMENT.replace('data-data-set="company"', 'data-data-set="sample"'),
        ),
        "sample statement: data-data-set is 'sample', the record holds company",
    ),
    (
        "sessions numeral is negative",
        _html("3 headless sessions", "-3 headless sessions"),
        "sample statement: the text must hold the sessions numeral and no other numeral",
    ),
    (
        "sessions numeral is fractional",
        _html("3 headless sessions", "3.3 headless sessions"),
        "sample statement: the text must hold the sessions numeral and no other numeral",
    ),
    (
        "sessions numeral only ends with the record's digit",
        _html("3 headless sessions", "13 headless sessions"),
        "sample statement: the text must hold the sessions numeral and no other numeral",
    ),
    (
        "player prose contradicts the player flag",
        lambda site, served: _player_page(
            site,
            served,
            PLAYER_STATEMENT.replace(
                "at least one with a player;",
                "at least one player was expected, but nobody played;",
            ),
        ),
        "sample statement: a player played, so 'at least one with a player' is required",
    ),
    (
        "stale sentence split by an inline tag",
        _html(
            "</p><p>No company year",
            "</p><p>Earlier build: three head<em>less</em> sessions with no player.</p>"
            "<p>No company year",
        ),
        "sample statement: the page holds a stale sample sentence",
    ),
    (
        "stale sentence split by an inline tag inside a paragraph",
        _html(
            "</p><p>No company year",
            "</p><p>Note that the earlier build had three <b>head</b>less sessions with no "
            "player here.</p><p>No company year",
        ),
        "sample statement: the page holds a stale sample sentence",
    ),
    (
        "sibling Sample sentence inside a zero-session statement",
        lambda site, served: _zero_page(
            site,
            served,
            ZERO_STATEMENT.replace(
                "</p>",
                "<span>Sample: dozens of headless sessions with no player;"
                " observational.</span></p>",
            ),
        ),
        "sample statement: another element's text begins 'Sample:'",
    ),
    (
        "other text beside the pending figure",
        lambda site, served: _zero_page(
            site, served, ZERO_STATEMENT.replace("</p>", "<span>dozens of sessions</span></p>")
        ),
        "sample statement: the record holds no session, so the statement must hold "
        "only its pending figure",
    ),
    (
        "bare Sample text in a parent element before the statement",
        _html(SAMPLE_STATEMENT, "<div>Sample: an earlier note. " + SAMPLE_STATEMENT + "</div>"),
        "sample statement: another element's text begins 'Sample:'",
    ),
    (
        "second Sample sentence inside the statement",
        _html("observational.</span>", "observational. Sample: also more.</span>"),
        "sample statement: the text must hold one 'Sample:' sentence",
    ),
    (
        "sessions with no sample figure",
        _html(
            SAMPLE_STATEMENT,
            '<p data-sample-statement data-data-set="sample" data-parks="1" data-sessions="3" '
            'data-player-played="false">Sample: the parks listed in the park-years table, 3 '
            "headless sessions with no player; observational.</p>",
        ),
        "sample statement: the record holds sessions, so the statement must hold "
        "one live sample figure",
    ),
    (
        "park-years table named for a record with parks",
        _html(
            "the parks listed in the park-years table", "parks with no closed monthly statement yet"
        ),
        "sample statement: the text must name the parks listed in the park-years table",
    ),
    (
        "sample.json missing",
        _missing_record,
        "sample statement: sample.json is missing",
    ),
]


@pytest.mark.parametrize(
    ("fault", "message"),
    [(fault, message) for _, fault, message in FAULTS],
    ids=[f[0] for f in FAULTS],
)
def test_a_broken_sample_statement_fails_the_page_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fault: Fault, message: str
) -> None:
    site, served = _site(tmp_path)
    fault(site, served)
    assert _run(site, served) == 1
    assert f"page check failed: {message}" in capsys.readouterr().out


def test_zero_sessions_with_a_pending_figure_pass(tmp_path: Path) -> None:
    site, served = _site(tmp_path)
    _zero_page(site, served)
    assert _run(site, served) == 0


def test_one_session_with_a_live_figure_passes(tmp_path: Path) -> None:
    site, served = _site(tmp_path)
    write_sample_record(
        served, {"data_set": "sample", "parks": 1, "sessions": 1, "player_played": False}
    )
    live = LIVE_STATEMENT.replace('data-sessions="3"', 'data-sessions="1"').replace(
        "3 headless sessions", "1 headless sessions"
    )
    _html(SAMPLE_STATEMENT, live)(site, served)
    assert _run(site, served) == 0


def test_a_player_record_with_its_own_sentence_passes(tmp_path: Path) -> None:
    site, served = _site(tmp_path)
    _player_page(site, served)
    assert _run(site, served) == 0


def test_the_committed_sample_record_and_its_rendered_page_pass(tmp_path: Path) -> None:
    committed = json.loads((ROOT / "site/_data/sample.json").read_text())
    assert committed["rows"] == [
        {"data_set": "sample", "parks": 1, "sessions": 3, "player_played": False}
    ]
    built = render_page(ROOT / "site/_data", tmp_path)
    statement = (built / "index.html").read_text()
    assert (
        "Sample: the parks listed in the park-years table, 3 headless sessions with no player;"
        " observational." in statement
    )
    assert statement.count("data-sample-statement") == 1
    assert _run(built, ROOT / "site/_data") == 0


def _direct(tmp_path: Path, record: dict[str, object], html: str, park_ids: list[int]) -> None:
    """Run the sample check over a statement alone and a served folder holding `park_ids`."""
    write_sample_record(tmp_path, record)
    rows = [{"park_id": park, "company_year": 2000} for park in park_ids]
    (tmp_path / "park_year.json").write_text(json.dumps({"rows": rows}))
    check_sample(html, tmp_path)


ZERO_PARK_PLAYER = {"data_set": "company", "parks": 0, "sessions": 2, "player_played": True}
ZERO_PARK_HEADLESS = {"data_set": "company", "parks": 0, "sessions": 2, "player_played": False}
ZERO_PARK_PLAYER_BODY = (
    "Sample: parks with no closed monthly statement yet, 2 sessions, at least one with a player;"
    " observational."
)
ZERO_PARK_HEADLESS_BODY = (
    "Sample: parks with no closed monthly statement yet, 2 headless sessions with no player;"
    " observational."
)


def _zero_park_statement(record: dict[str, object], body: str) -> str:
    return (
        f'<p data-sample-statement data-data-set="company" data-parks="0" data-sessions="2" '
        f'data-player-played="{str(record["player_played"]).lower()}">' + _figure(body) + "</p>"
    )


@pytest.mark.parametrize(
    ("record", "body"),
    [(ZERO_PARK_PLAYER, ZERO_PARK_PLAYER_BODY), (ZERO_PARK_HEADLESS, ZERO_PARK_HEADLESS_BODY)],
    ids=["with a player", "headless"],
)
def test_sessions_before_any_statement_state_that_in_their_own_wording(
    tmp_path: Path, record: dict[str, object], body: str
) -> None:
    _direct(tmp_path, record, _zero_park_statement(record, body), [])


@pytest.mark.parametrize(
    ("record", "body"),
    [
        (ZERO_PARK_PLAYER, PLAYER_BODY.replace("5 sessions", "2 sessions")),
        (
            ZERO_PARK_HEADLESS,
            "Sample: the parks listed in the park-years table, 2 headless "
            "sessions with no player; observational.",
        ),
        (ZERO_PARK_PLAYER, "Sample: 2 sessions, at least one with a player; observational."),
    ],
    ids=["player with park-years reference", "headless with park-years reference", "no scope"],
)
def test_zero_parks_with_sessions_fails_without_the_no_statement_wording(
    tmp_path: Path, record: dict[str, object], body: str
) -> None:
    with pytest.raises(PageCheckFailed) as failure:
        _direct(tmp_path, record, _zero_park_statement(record, body), [])
    assert str(failure.value) == (
        "sample statement: the record holds no park, so the text must name parks with no "
        "closed monthly statement yet and not the park-years table"
    )


def test_a_park_with_two_years_counts_once(tmp_path: Path) -> None:
    record = {"data_set": "sample", "parks": 1, "sessions": 3, "player_played": False}
    write_sample_record(tmp_path, record)
    years = [{"park_id": 7, "company_year": 2000}, {"park_id": 7, "company_year": 2001}]
    (tmp_path / "park_year.json").write_text(json.dumps({"rows": years}))
    check_sample(SAMPLE_STATEMENT, tmp_path)


@pytest.mark.parametrize(
    ("record", "player"),
    [(ZERO_PARK_PLAYER, True), (ZERO_PARK_HEADLESS, False)],
    ids=["with a player", "headless"],
)
def test_the_template_words_a_record_with_no_park_without_the_park_years_table(
    tmp_path: Path, record: dict[str, object], player: bool
) -> None:
    served = write_set("A", tmp_path / "served")
    write_sample_record(served, record)
    page = (render_page(served, tmp_path) / "index.html").read_text()
    body = ZERO_PARK_PLAYER_BODY if player else ZERO_PARK_HEADLESS_BODY
    assert f"<span data-figure-body>{body}</span>" in page
    assert "park-years table, 2" not in page

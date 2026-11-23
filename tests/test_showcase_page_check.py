"""Tests for the built showcase page contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.page_check_support import (
    COMPANY_TABLE,
    COMPANY_YEAR_ROW,
    EMPTY_STATE,
    PARK_YEAR_ROW,
    PARK_YEAR_TABLE_ROW,
    SECOND_TABLE_ROW,
    Fault,
    _fails,
    _html,
    _html_append,
    _run,
    _site,
    write_sample_record,
)

CLOSE_RULE_FAULT = "close rule: required sentence is missing"
NO_COUNT = "sample note: the page text must not state a park count"
EMPTY_STATE_FAULT = "closed years: the empty-state sentence shows"
PARK_YEARS_NOT_LISTED = "park-years table: parks in park_month.json are missing (['2'])"


def test_built_page_matches_served_files(tmp_path: Path) -> None:
    site, served = _site(tmp_path)
    assert _run(site, served) == 0


CHART_IDS = "chart module: must name exactly park-month-data and park-month-chart"
CHART_API = "chart module: fetch, XMLHttpRequest, and dynamic import are forbidden"


def _module(old: str, new: str) -> Fault:
    def fault(site: Path, served: Path) -> None:
        module = site / "assets/park-month-chart.mjs"
        text = module.read_text()
        assert old in text
        module.write_text(text.replace(old, new))

    return fault


def _module_append(text: str) -> Fault:
    def fault(site: Path, served: Path) -> None:
        module = site / "assets/park-month-chart.mjs"
        module.write_text(module.read_text() + text)

    return fault


def _module_prepend(text: str) -> Fault:
    def fault(site: Path, served: Path) -> None:
        module = site / "assets/park-month-chart.mjs"
        module.write_text(text + module.read_text())

    return fault


def _unlink(relative: str, *, served_file: bool = False) -> Fault:
    def fault(site: Path, served: Path) -> None:
        ((served if served_file else site) / relative).unlink()

    return fault


def _extra_tag(value: str, tag: str = "script", attribute: str = "src") -> Fault:
    return _html_append(f'<{tag} {attribute}="{value}"></{tag}>')


FAILURES = [
    _fails(
        "embedded rows: differ from served park_month.json",
        _html("4073.6", "4073.7"),
        "embedded rows",
    ),
    _fails("unit label: US dollars is missing", _html("unit: US dollars", "unit: dollars"), "unit"),
    _fails(
        "clock label: company month is missing",
        _html("clock: company month", "clock: game day"),
        "clock",
    ),
    _fails(
        "vendor file: assets/vendor/d3.min.js is missing",
        _unlink("assets/vendor/d3.min.js"),
        "missing d3 file",
    ),
    _fails(
        "vendor file: assets/vendor/plot.umd.min.js is missing",
        _unlink("assets/vendor/plot.umd.min.js"),
        "missing plot file",
    ),
    _fails(
        "vendor file: assets/park-month-chart.mjs is missing",
        _unlink("assets/park-month-chart.mjs"),
        "missing chart file",
    ),
    _fails(
        "vendor scripts: d3, Plot, and chart module are not in required order",
        _html(
            '<script src="assets/vendor/d3.min.js"></script>'
            '<script src="assets/vendor/plot.umd.min.js"></script>',
            '<script src="assets/vendor/plot.umd.min.js"></script>'
            '<script src="assets/vendor/d3.min.js"></script>',
        ),
        "script order",
    ),
    _fails(
        "vendor scripts: a required script path is missing",
        _html('<script src="assets/vendor/d3.min.js"></script>', ""),
        "missing d3 script tag",
    ),
    _fails(CHART_IDS, _module("park-month-chart", "park-month-extra"), "chart ids"),
    _fails(
        CHART_IDS,
        _module_append('document.getElementById("other");\n'),
        "extra element id",
    ),
    _fails(
        CHART_IDS,
        _module(
            'const chart = document.getElementById("park-month-chart");',
            'const chart = document.getElementById("d"); // park-month-chart',
        ),
        "second id replaced and named in a comment",
    ),
    _fails(CHART_IDS, _module_append('document.querySelector("#x");\n'), "querySelector"),
    _fails(CHART_IDS, _module_append("document.getElementById(name);\n"), "non-literal id"),
    _fails(CHART_API, _module_append('fetch("data.json");\n'), "fetch"),
    _fails(CHART_API, _module_append('fetch ("data.json");\n'), "fetch with a space"),
    _fails(CHART_API, _module_append("new XMLHttpRequest();\n"), "XMLHttpRequest"),
    _fails(CHART_API, _module_append('import("./x.js");\n'), "dynamic import"),
    _fails(CHART_API, _module_append('import ("./x.js");\n'), "dynamic import with a space"),
    _fails(
        "chart module URL: import specifier is not local (https://example.test/chart.js)",
        _module_prepend('import "https://example.test/chart.js";\n'),
        "module URL",
    ),
    _fails(
        "chart module URL: import specifier is not local (https://e.test/a.js)",
        _module_prepend('import x from "https://e.test/a.js";\n'),
        "module from https",
    ),
    _fails(
        "chart module URL: import specifier is not local (//e.test/a.js)",
        _module_prepend('import x from "//e.test/a.js";\n'),
        "module from protocol-relative",
    ),
    _fails(
        "chart module URL: import specifier is not local (https://e.test/a.js)",
        _module_prepend('import{x}from"https://e.test/a.js";\n'),
        "module from without spaces",
    ),
    _fails(
        "chart module URL: import specifier is not local (https://e.test/a.js)",
        _module_prepend('import"https://e.test/a.js";\n'),
        "module bare import without spaces",
    ),
    _fails(
        "chart module URL: import specifier is not local (HTTPS://e.test/a.js)",
        _module_prepend('import x from "HTTPS://e.test/a.js";\n'),
        "module from upper-case scheme",
    ),
    _fails(
        "page URL: src starts with a forbidden root or host (http://e.test/x.js)",
        _extra_tag("http://e.test/x.js"),
        "page URL http",
    ),
    _fails(
        "page URL: src starts with a forbidden root or host (https://e.test/x.js)",
        _extra_tag("https://e.test/x.js"),
        "page URL https",
    ),
    _fails(
        "page URL: src starts with a forbidden root or host (//e.test/x.js)",
        _extra_tag("//e.test/x.js"),
        "page URL protocol-relative",
    ),
    _fails(
        "page URL: href starts with a forbidden root or host (/x.css)",
        _extra_tag("/x.css", "link", "href"),
        "page URL root",
    ),
    _fails(
        "page URL: src starts with a forbidden root or host (HTTPS://e.test/x.js)",
        _extra_tag("HTTPS://e.test/x.js"),
        "page URL upper-case scheme",
    ),
    _fails(
        "page URL: src starts with a forbidden root or host ( https://e.test/x.js)",
        _extra_tag(" https://e.test/x.js"),
        "page URL leading space",
    ),
    _fails(
        "page URL: src starts with a forbidden root or host (\\\\e.test/x.js)",
        _extra_tag("\\\\e.test/x.js"),
        "page URL backslashes",
    ),
    _fails(
        "embedded rows: park-month-data element is missing",
        _html('id="park-month-data"', 'id="park-month-rows"'),
        "embedded element missing",
    ),
    _fails(
        "chart mount: park-month-chart element is missing",
        _html('<figure id="park-month-chart"></figure>', ""),
        "chart mount missing",
    ),
    _fails("built site: index.html is missing", _unlink("index.html"), "index.html missing"),
    _fails(
        "park_month: file is missing (park_month.json)",
        _unlink("park_month.json", served_file=True),
        "served park_month.json missing",
    ),
]


@pytest.mark.parametrize(("fault", "message"), FAILURES)
def test_each_page_contract_failure_exits_one_with_its_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fault: Fault, message: str
) -> None:
    site, served = _site(tmp_path)
    fault(site, served)
    assert _run(site, served) == 1
    assert f"page check failed: {message}" in capsys.readouterr().out


def _written(name: str, rows: str) -> Fault:
    def fault(site: Path, served: Path) -> None:
        (served / name).write_text('{"rows":[' + rows + "]}\n")

    return fault


def _combined(*faults: Fault) -> Fault:
    def fault(site: Path, served: Path) -> None:
        for each in faults:
            each(site, served)

    return fault


def _two_parks_over_two_years(site: Path, served: Path) -> None:
    """Park 1 closed 2000; park 2 is open in 2001; the company year 2000 has closed."""
    second_park_row = PARK_YEAR_ROW.replace('"park_id":1', '"park_id":2').replace(
        '"company_year":2000', '"company_year":2001'
    )
    _written("park_year.json", PARK_YEAR_ROW.replace("open", "complete") + "," + second_park_row)(
        site, served
    )
    _written("company_year.json", COMPANY_YEAR_ROW)(site, served)
    write_sample_record(
        served, {"data_set": "sample", "parks": 2, "sessions": 3, "player_played": False}
    )
    _html('data-parks="1"', 'data-parks="2"')(site, served)
    closed_row = PARK_YEAR_TABLE_ROW.replace("not closed", "complete")
    second_row = PARK_YEAR_TABLE_ROW.replace("2000", "2001").replace("<td>1</td>", "<td>2</td>")
    _html(PARK_YEAR_TABLE_ROW, closed_row + second_row)(site, served)
    _html(EMPTY_STATE, COMPANY_TABLE)(site, served)
    _written(
        "park_month.json",
        '{"park_month_key":1,"park_id":1,"statement_company_date":"2000-03-01",'
        '"operating_profit":4073.60},{"park_month_key":2,"park_id":1,'
        '"statement_company_date":"2000-04-01","operating_profit":10043.60},'
        '{"park_month_key":3,"park_id":2,"statement_company_date":"2001-03-01",'
        '"operating_profit":1.00}',
    )(site, served)
    _html(
        '"operating_profit":10043.60}]',
        '"operating_profit":10043.60},{"park_month_key":3,"park_id":2,'
        '"statement_company_date":"2001-03-01","operating_profit":1.00}]',
    )(site, served)
    _html(
        SECOND_TABLE_ROW + "</tbody>",
        SECOND_TABLE_ROW
        + '<tr><th scope="row">Mar 2001 <span>(not checked: first month)</span></th>'
        "<td>$1.00</td></tr></tbody>",
    )(site, served)


def test_two_parks_over_two_years_with_a_closed_year_pass(tmp_path: Path) -> None:
    site, served = _site(tmp_path)
    _two_parks_over_two_years(site, served)
    assert _run(site, served) == 0


def test_closed_years_table_followed_by_the_park_years_heading_passes(tmp_path: Path) -> None:
    site, served = _site(tmp_path)
    _two_parks_over_two_years(site, served)
    _html(
        '<table id="park-year-table">',
        '<h2>Park-years (unit: US dollars; clock: company year)</h2><table id="park-year-table">',
    )(site, served)
    assert _run(site, served) == 0


def test_zero_closed_years_with_the_empty_state_sentence_pass(tmp_path: Path) -> None:
    site, served = _site(tmp_path)
    assert "No company year has closed yet." in (site / "index.html").read_text()
    assert _run(site, served) == 0


def test_empty_state_sentence_beside_a_closed_year_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site, served = _site(tmp_path)
    _two_parks_over_two_years(site, served)
    _html_append(EMPTY_STATE)(site, served)
    assert _run(site, served) == 1
    assert "closed years: the empty-state sentence shows" in capsys.readouterr().out


def test_missing_empty_state_sentence_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site, served = _site(tmp_path)
    _html(EMPTY_STATE, "")(site, served)
    assert _run(site, served) == 1
    assert "closed years: the empty-state sentence shows" in capsys.readouterr().out


def test_page_saying_one_park_while_two_parks_are_present_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site, served = _site(tmp_path)
    _two_parks_over_two_years(site, served)
    _html("observational.", "observational. One park is shown.")(site, served)
    assert _run(site, served) == 1
    assert f"page check failed: {NO_COUNT}" in capsys.readouterr().out


def test_park_missing_from_the_park_years_table_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site, served = _site(tmp_path)
    _two_parks_over_two_years(site, served)
    _written("park_year.json", PARK_YEAR_ROW)(site, served)
    second_row = PARK_YEAR_TABLE_ROW.replace("2000", "2001").replace("<td>1</td>", "<td>2</td>")
    _html(PARK_YEAR_TABLE_ROW.replace("not closed", "complete") + second_row, PARK_YEAR_TABLE_ROW)(
        site, served
    )
    assert _run(site, served) == 1
    assert PARK_YEARS_NOT_LISTED in capsys.readouterr().out


def test_year_money_header_without_not_yet_reconciled_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site, served = _site(tmp_path)
    _html("Operating profit (not yet reconciled)", "Operating profit")(site, served)
    assert _run(site, served) == 1
    assert "park-year-table: header row expected" in capsys.readouterr().out


def test_closed_year_money_header_without_not_yet_reconciled_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site, served = _site(tmp_path)
    _two_parks_over_two_years(site, served)
    _html(
        "Operating profit (not yet reconciled)</th></tr></thead><tbody><tr><td>2000</td><td>2",
        "Operating profit</th></tr></thead><tbody><tr><td>2000</td><td>2",
    )(site, served)
    assert _run(site, served) == 1
    assert "company-year-table: header row expected" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        (_html("A company year closes when", "A company year closes if"), CLOSE_RULE_FAULT),
        (_html("March to October, and", "March to October and"), CLOSE_RULE_FAULT),
        (
            _html("; at least one expected park must also be complete", ""),
            CLOSE_RULE_FAULT,
        ),
        (_html("<td>3 of 8</td>", "<td>3 of 7</td>"), "park-year-table: rows expected"),
        (_html("<td>not closed</td>", "<td>closed</td>"), "park-year-table: rows expected"),
        (
            _combined(
                _written("park_year.json", PARK_YEAR_ROW.replace("open", "complete")),
                _html("<td>not closed</td>", "<td>closed</td>"),
            ),
            "park-year-table: rows expected",
        ),
        (
            _html("Each park's first month", "The park's first month"),
            "first-month sentence: required R10 sentence is missing",
        ),
        (
            _html(
                "Operating profit per park and company year, in US dollars",
                "Operating profit per park and calendar year, in euros",
            ),
            "park-year-table: caption expected",
        ),
        (
            _html(
                "Operating profit per park and company year, in US dollars",
                "Operating profit of the one park, in US dollars",
            ),
            NO_COUNT,
        ),
        (
            _html(
                "Park-years (unit: US dollars; clock: company year)",
                "Park-years (unit: US dollars)",
            ),
            "park-year-table: heading must carry",
        ),
        (_html("$14,117.20", "$14,117.30"), "park-year-table: rows expected"),
        (_html("observational.", "observational, 3 parks."), NO_COUNT),
        (_html("observational.", "observational, two parks."), NO_COUNT),
        (_html("observational.", "observational. This page covers a single park."), NO_COUNT),
        (_html("observational.", "observational. Park 1 Park 2 are listed."), NO_COUNT),
        (_html(EMPTY_STATE, EMPTY_STATE + COMPANY_TABLE), EMPTY_STATE_FAULT),
        (
            _html("<tr><td>2000</td><td>1</td>", "<tr>stray<td>2000</td><td>1</td>"),
            "park-year-table: a row has text outside its cells",
        ),
        (
            _written("park_year.json", PARK_YEAR_ROW.replace("open", "incomplete")),
            "park-year-table: rows expected",
        ),
        (
            _combined(
                _written("park_year.json", PARK_YEAR_ROW.replace("open", "partial_first_season")),
                _html("<td>not closed</td>", "<td>closed</td>"),
            ),
            "park-year-table: rows expected",
        ),
    ],
    ids=[
        "close rule worded differently",
        "close rule punctuation",
        "close rule without the at-least-one-complete clause",
        "statements expected",
        "status word",
        "complete status shown as closed",
        "first-month sentence in the singular",
        "park-year caption changed",
        "park count in a caption",
        "park-year heading without the clock label",
        "park-year profit",
        "numeric park count",
        "number word park count",
        "a single park",
        "adjacent park position labels",
        "zero closed years beside a closed-years table",
        "text outside the cells of a year-table row",
        "incomplete row with the wrong status word",
        "partial first season row with the wrong status word",
    ],
)
def test_year_copy_and_table_faults_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fault: Fault, message: str
) -> None:
    site, served = _site(tmp_path)
    fault(site, served)
    assert _run(site, served) == 1
    assert f"page check failed: {message}" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        (
            _html("Closed company years, operating profit in US dollars", "Company years"),
            "company-year-table: caption expected",
        ),
        (
            _html(
                "Closed company years (unit: US dollars; clock: company year)",
                "Closed company years (unit: US dollars)",
            ),
            "company-year-table: heading must carry",
        ),
    ],
    ids=["closed-years caption changed", "closed-years heading without the clock label"],
)
def test_closed_year_caption_and_heading_clock_are_pinned(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fault: Fault, message: str
) -> None:
    site, served = _site(tmp_path)
    _two_parks_over_two_years(site, served)
    fault(site, served)
    assert _run(site, served) == 1
    assert f"page check failed: {message}" in capsys.readouterr().out

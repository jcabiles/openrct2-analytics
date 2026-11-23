"""Tests for the month table of the built showcase page."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.page_check_support import (
    FIRST_TABLE_ROW,
    MONTH_TABLE,
    SECOND_TABLE_ROW,
    Fault,
    _fails,
    _html,
    _html_append,
    _run,
    _served_park_rows,
    _site,
)


def test_month_table_accepts_a_mark_per_park_while_park_years_table_misses_park_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site, served = _site(tmp_path)
    second_row = (
        '{"park_month_key":2,"park_id":2,"statement_company_date":"2000-04-01",'
        '"operating_profit":10043.60}'
    )
    _served_park_rows(
        '{"park_month_key":1,"park_id":1,"statement_company_date":"2000-03-01",'
        '"operating_profit":4073.60},' + second_row
    )(site, served)
    _html('"park_month_key":2,"park_id":1', '"park_month_key":2,"park_id":2')(site, served)
    _html(
        SECOND_TABLE_ROW,
        SECOND_TABLE_ROW.replace("Apr 2000", "Apr 2000 <span>(not checked: first month)</span>"),
    )(site, served)
    assert _run(site, served) == 1
    output = capsys.readouterr().out
    assert "park-years table: parks in park_month.json are missing" in output
    assert "month table: " not in output


def _non_numeric_park_month_value() -> Fault:
    def fault(site: Path, served: Path) -> None:
        for old in ('"operating_profit":4073.60', '"operating_profit":4073.6'):
            for page in (served / "park_month.json", site / "index.html"):
                text = page.read_text()
                page.write_text(text.replace(old, '"operating_profit":"n/a"'))

    return fault


def _move_first_month_mark() -> Fault:
    def fault(site: Path, served: Path) -> None:
        _html(
            FIRST_TABLE_ROW,
            '<tr><th scope="row">Mar 2000</th><td>$4,073.60</td></tr>',
        )(site, served)
        _html(
            SECOND_TABLE_ROW,
            '<tr><th scope="row">Apr 2000 <span>(not checked: first month)</span></th>'
            "<td>$10,043.60</td></tr>",
        )(site, served)

    return fault


FAILURES = [
    _fails(
        MONTH_TABLE + "missing table",
        _html('<table id="park-month-table"', '<table id="missing-park-month-table"'),
        "month table missing",
    ),
    _fails(
        MONTH_TABLE + "row count 1 vs 2",
        _html(SECOND_TABLE_ROW, ""),
        "month table row missing",
    ),
    _fails(
        MONTH_TABLE + "row 1 value cell",
        _html("$4,073.60", "$4,073.61"),
        "month table value changed",
    ),
    _fails(
        MONTH_TABLE + "row 1 month cell",
        _html("Mar 2000", "May 2000"),
        "month table month changed",
    ),
    _fails(
        MONTH_TABLE + "row 1 month cell",
        _html(" <span>(not checked: first month)</span>", ""),
        "month table mark removed",
    ),
    _fails(
        MONTH_TABLE + "row 1 month cell",
        _move_first_month_mark(),
        "month table mark moved from first row",
    ),
    _fails(
        MONTH_TABLE + "caption expected 'Operating profit by company month, in US dollars'",
        _html("Operating profit by company month, in US dollars</caption>", "Profit</caption>"),
        "month table caption changed",
    ),
    _fails(
        MONTH_TABLE + "header row expected",
        _html("Company month</th>", "Month</th>"),
        "month table header changed",
    ),
    _fails(
        MONTH_TABLE + "row count 3 vs 2 (expected 2, actual 3)",
        _html("</tbody>", "</tbody><tfoot>" + SECOND_TABLE_ROW + "</tfoot>"),
        "month table row in tfoot",
    ),
    _fails(
        MONTH_TABLE + "row count 3 vs 2 (expected 2, actual 3)",
        _html("<tbody>", SECOND_TABLE_ROW + "<tbody>"),
        "month table row outside tbody",
    ),
    _fails(
        MONTH_TABLE + "row 1 cells expected a th scope=row then a td",
        _html("</th><td>$4,073.60", "</th><td>x</td><td>$4,073.60"),
        "month table extra td before the value",
    ),
    _fails(
        MONTH_TABLE + "row 1 cells expected a th scope=row then a td",
        _html('<tr><th scope="row">Mar', '<tr><th scope="row">x</th><th scope="row">Mar'),
        "month table second th before the month cell",
    ),
    _fails(
        MONTH_TABLE + "row 2 has text outside its cells",
        _html('<tr><th scope="row">Apr', '<tr>stray<th scope="row">Apr'),
        "month table bare text in a row",
    ),
    _fails(
        MONTH_TABLE + "row 2 month cell expected 'Apr 2000', actual 'Apr 2000 (not checked",
        _html(
            SECOND_TABLE_ROW,
            SECOND_TABLE_ROW.replace(
                "Apr 2000", "Apr 2000 <span>(not checked: first month)</span>"
            ),
        ),
        "month table mark on row 2 while row 1 keeps it",
    ),
    _fails(
        MONTH_TABLE + "mark count 2 vs 1",
        _html(
            '<figure id="park-month-chart">',
            '<figure aria-label="not checked: first month" id="park-month-chart">',
        ),
        "mark in an aria-label",
    ),
    _fails(
        MONTH_TABLE + "mark count 2 vs 1",
        _html("<h1>", '<h1 title="not checked: first month">'),
        "mark in a title attribute",
    ),
    _fails(
        MONTH_TABLE + "row 1 value cell (park_month: operating_profit is not numeric)",
        _non_numeric_park_month_value(),
        "month table park_month value not numeric",
    ),
    _fails(
        MONTH_TABLE + "mark count 2 vs 1",
        _html_append("<p>not checked: first month</p>"),
        "extra first month mark elsewhere",
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

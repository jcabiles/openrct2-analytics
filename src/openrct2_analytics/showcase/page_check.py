"""Check that the built showcase page agrees with its served data and assets."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from typing import cast

from openrct2_analytics.showcase.page_check_guide import check_guide
from openrct2_analytics.showcase.page_check_sample import check_sample
from openrct2_analytics.showcase.page_check_site import (
    PageCheckFailed,
    _is_remote,
    _require,
    check_chart_module,
    check_site,
    is_public_link,
)
from openrct2_analytics.showcase.page_check_text import (
    CAPTION,
    CLOSE_RULE,
    HEADERS,
    MARK,
    MONTH_NAMES,
    PARK_COUNT,
    STATUS_WORDS,
    YEAR_CLOCK,
    YEAR_TABLES,
)


@dataclass
class _Row:
    """One table row: its cells as (tag, scope, text) and any text outside the cells."""

    cells: list[tuple[str, str | None, str]] = field(default_factory=list)
    stray: list[str] = field(default_factory=list)


@dataclass
class _Table:
    """One table: its caption text and its header and body rows."""

    caption: list[str] = field(default_factory=list)
    header_rows: list[_Row] = field(default_factory=list)
    body_rows: list[_Row] = field(default_factory=list)


def _normalize(parts: list[str]) -> str:
    return " ".join("".join(parts).split())


class _PageParser(HTMLParser):
    """Collect page text, attributes, embedded data, script paths, and every table with an id."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.prose: list[str] = []
        self.attribute_values: list[str] = []
        self.elements: dict[str, list[str]] = {}
        self.sources: list[str] = []
        self.json_script_ids: list[str] = []
        self.table_headings: dict[str, str] = {}
        self._last_heading = ""
        self._heading: list[str] | None = None
        self._element_id: str | None = None
        self.tables: dict[str, _Table] = {}
        self._table: _Table | None = None
        self._in_caption = False
        self._in_head = False
        self._row: _Row | None = None
        self._row_is_header = False
        self._cell: tuple[str, str | None, list[str]] | None = None

    def _end_cell(self) -> None:
        if self._cell is not None and self._row is not None:
            tag, scope, parts = self._cell
            self._row.cells.append((tag, scope, _normalize(parts)))
        self._cell = None

    def _end_row(self) -> None:
        self._end_cell()
        if self._row is not None:
            assert self._table is not None
            table = self._table
            (table.header_rows if self._row_is_header else table.body_rows).append(self._row)
        self._row = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        self.attribute_values.extend(value for _, value in attrs if value is not None)
        element_id = values.get("id")
        if element_id is not None:
            self.elements.setdefault(element_id, [])
            self._element_id = element_id
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading = []
        if tag == "table" and element_id is not None:
            self._table = self.tables.setdefault(element_id, _Table())
            self.table_headings[element_id] = self._last_heading
        elif self._table is not None and tag == "caption":
            self._in_caption = True
        elif self._table is not None and tag == "thead":
            self._in_head = True
        elif self._table is not None and tag == "tr":
            self._end_row()
            self._row = _Row()
            self._row_is_header = self._in_head
        elif self._row is not None and tag in {"th", "td"}:
            self._end_cell()
            self._cell = (tag, values.get("scope"), [])
        source = values.get("src")
        if tag == "script" and source is not None:
            self.sources.append(source)
        if tag == "script" and element_id is not None and values.get("type") == "application/json":
            self.json_script_ids.append(element_id)

    def handle_endtag(self, tag: str) -> None:
        if self._heading is not None and tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._last_heading = _normalize(self._heading)
            self._heading = None
        if self._table is not None and tag in {"th", "td"}:
            self._end_cell()
        elif self._table is not None and tag == "tr":
            self._end_row()
        elif self._table is not None and tag == "caption":
            self._in_caption = False
        elif self._table is not None and tag == "thead":
            self._end_row()
            self._in_head = False
        elif tag == "table" and self._table is not None:
            self._end_row()
            self._table = None
        self._element_id = None

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self._heading is not None:
            self._heading.append(data)
        if self._table is None:
            self.prose.append(data)
        if self._element_id is not None:
            self.elements[self._element_id].append(data)
        if self._in_caption and self._table is not None:
            self._table.caption.append(data)
        elif self._cell is not None:
            self._cell[2].append(data)
        elif self._row is not None and data.strip():
            self._row.stray.append(" ".join(data.split()))


def _load_json(path: Path, label: str) -> object:
    if not path.is_file():
        raise PageCheckFailed(f"{label}: file is missing ({path.name})")
    try:
        return json.loads(path.read_text(), parse_float=Decimal, parse_int=Decimal)
    except json.JSONDecodeError as error:
        raise PageCheckFailed(f"{label}: invalid JSON ({error})") from error


def _document_rows(document: object, label: str) -> list[object]:
    if not isinstance(document, dict) or not isinstance(document.get("rows"), list):
        raise PageCheckFailed(f"{label}: rows are missing")
    return cast(list[object], document["rows"])


def _number(row: dict[str, object], name: str, label: str) -> Decimal:
    value = row.get(name)
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise PageCheckFailed(f"{label}: {name} is not numeric")
    return Decimal(value)


def _usd(value: Decimal) -> str:
    return f"-${-value:,.2f}" if value < 0 else f"${value:,.2f}"


def _month_label(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise PageCheckFailed("month table: statement_company_date is not YYYY-MM-DD")
    month = int(value[5:7])
    if not 1 <= month <= len(MONTH_NAMES):
        raise PageCheckFailed("month table: statement_company_date has an invalid month")
    return f"{MONTH_NAMES[month - 1]} {value[:4]}"


def check_page(site: Path, served_dir: Path) -> None:
    """Check the built HTML, chart module, and vendored assets."""
    html_file = site / "index.html"
    if not html_file.is_file():
        raise PageCheckFailed("built site: index.html is missing")
    html = html_file.read_text()
    parser = _PageParser()
    parser.feed(html)
    text = " ".join(" ".join(parser.text).split())

    for element, attribute, value in _attribute_values(html):
        if _is_remote(value, ("http:", "https:", "//", "/")) and not is_public_link(
            element, attribute, value
        ):
            raise PageCheckFailed(
                f"page URL: {attribute} starts with a forbidden root or host ({value})"
            )

    _require("park-data" in parser.elements, "embedded rows: park-data element is missing")
    _require(
        parser.json_script_ids.count("park-data") == 1,
        "embedded rows: park-data must be exactly one application/json script block",
    )
    _require(
        "park-month-data" in parser.elements, "embedded rows: park-month-data element is missing"
    )
    _require(
        "park-month-chart" in parser.elements, "chart mount: park-month-chart element is missing"
    )
    try:
        embedded = json.loads(
            "".join(parser.elements["park-month-data"]),
            parse_float=Decimal,
            parse_int=Decimal,
        )
    except json.JSONDecodeError as error:
        raise PageCheckFailed(f"embedded rows: invalid JSON ({error})") from error
    served_park = _load_json(served_dir / "park_month.json", "park_month")
    if not isinstance(embedded, list):
        raise PageCheckFailed("embedded park-month-data: rows are missing")
    _require(
        embedded == _document_rows(served_park, "park_month"),
        "embedded rows: differ from served park_month.json",
    )

    _require("unit: US dollars" in text, "unit label: US dollars is missing")
    _require("clock: company month" in text, "clock label: company month is missing")

    _check_month_table(parser, served_park, text)
    _check_years(parser, served_dir, text, served_park)
    check_sample(html, served_dir)

    expected_sources = [
        "assets/vendor/d3.min.js",
        "assets/vendor/plot.umd.min.js",
        "assets/park-month-chart.mjs",
    ]
    _require(
        all(source in parser.sources for source in expected_sources),
        "vendor scripts: a required script path is missing",
    )
    positions = [parser.sources.index(source) for source in expected_sources]
    _require(
        positions == sorted(positions),
        "vendor scripts: d3, Plot, and chart module are not in required order",
    )
    for source in expected_sources:
        _require((site / source).is_file(), f"vendor file: {source} is missing")
    check_chart_module(site / "assets/park-month-chart.mjs")
    check_site(site, served_dir, html, expected_sources)
    check_guide(site)


def _check_month_table(parser: _PageParser, served_park: object, text: str) -> None:
    """Check rendered company-month rows against the same served rows as the chart."""
    if "park-month-table" not in parser.tables:
        raise PageCheckFailed("month table: missing table")
    table = parser.tables["park-month-table"]
    caption = _normalize(table.caption)
    _require(
        caption == CAPTION,
        f"month table: caption expected {CAPTION!r}, actual {caption!r}",
    )
    headers = [[cell[2] for cell in row.cells] for row in table.header_rows]
    _require(
        headers == [list(HEADERS)],
        f"month table: header row expected {[list(HEADERS)]!r}, actual {headers!r}",
    )
    park_rows = _document_rows(served_park, "park_month")
    body_rows = table.body_rows
    _require(
        len(body_rows) == len(park_rows),
        f"month table: row count {len(body_rows)} vs {len(park_rows)}"
        f" (expected {len(park_rows)}, actual {len(body_rows)})",
    )
    previous_park: object = object()
    expected_mark_count = 0
    for index, (table_row, served_row) in enumerate(zip(body_rows, park_rows, strict=True), 1):
        if not isinstance(served_row, dict):
            raise PageCheckFailed(f"month table: row {index} served row is invalid")
        layout = [(tag, scope) for tag, scope, _ in table_row.cells]
        _require(
            layout == [("th", "row"), ("td", None)],
            f"month table: row {index} cells expected a th scope=row then a td, actual {layout!r}",
        )
        _require(
            not table_row.stray,
            f"month table: row {index} has text outside its cells ({table_row.stray!r})",
        )
        park_id = served_row.get("park_id")
        first_for_park = park_id != previous_park
        if first_for_park:
            expected_mark_count += 1
        previous_park = park_id
        expected_month = _month_label(served_row.get("statement_company_date"))
        if first_for_park:
            expected_month += f" ({MARK})"
        month_cell, value_cell = table_row.cells[0][2], table_row.cells[1][2]
        _require(
            month_cell == expected_month,
            f"month table: row {index} month cell expected {expected_month!r},"
            f" actual {month_cell!r}",
        )
        try:
            expected_value = _usd(_number(served_row, "operating_profit", "park_month"))
        except PageCheckFailed as error:
            raise PageCheckFailed(f"month table: row {index} value cell ({error})") from error
        _require(
            value_cell == expected_value,
            f"month table: row {index} value cell expected {expected_value!r},"
            f" actual {value_cell!r}",
        )
    mark_count = text.count(MARK) + sum(value.count(MARK) for value in parser.attribute_values)
    _require(
        mark_count == expected_mark_count,
        f"month table: mark count {mark_count} vs {expected_mark_count}"
        f" (expected {expected_mark_count}, actual {mark_count})",
    )


def _cell(row: dict[str, object], name: str, label: str) -> str:
    """Render a served value the way the page prints it: whole numbers and text as is."""
    value = row.get(name)
    if isinstance(value, str):
        return value
    number = _number(row, name, label)
    if number != number.to_integral_value():
        raise PageCheckFailed(f"{label}: {name} is not a whole number")
    return str(int(number))


def _dict_rows(document: object, label: str) -> list[dict[str, object]]:
    rows = _document_rows(document, label)
    if not all(isinstance(row, dict) for row in rows):
        raise PageCheckFailed(f"{label}: a row is not an object")
    return cast(list[dict[str, object]], rows)


def _check_table(parser: _PageParser, table_id: str, expected: list[list[str]]) -> None:
    """Check a year table's caption, heading clock label, header row and body rows in order."""
    if table_id not in parser.tables:
        raise PageCheckFailed(f"{table_id}: table is missing")
    table = parser.tables[table_id]
    caption, headers = YEAR_TABLES[table_id]
    actual_caption = _normalize(table.caption)
    _require(
        actual_caption == caption,
        f"{table_id}: caption expected {caption!r}, actual {actual_caption!r}",
    )
    heading = parser.table_headings[table_id]
    _require(YEAR_CLOCK in heading, f"{table_id}: heading must carry {YEAR_CLOCK!r}: {heading!r}")
    actual_headers = [[cell[2] for cell in row.cells] for row in table.header_rows]
    _require(
        actual_headers == [headers],
        f"{table_id}: header row expected {[headers]!r}, actual {actual_headers!r}",
    )
    _require(
        all(not row.stray for row in table.body_rows),
        f"{table_id}: a row has text outside its cells",
    )
    actual = [[cell[2] for cell in row.cells] for row in table.body_rows]
    _require(actual == expected, f"{table_id}: rows expected {expected!r}, actual {actual!r}")


def _check_years(parser: _PageParser, served_dir: Path, text: str, served_park: object) -> None:
    """Check the closed-years table, the park-years table, and the copy that frames them."""
    company = _dict_rows(
        _load_json(served_dir / "company_year.json", "company_year"), "company_year"
    )
    parks = _dict_rows(_load_json(served_dir / "park_year.json", "park_year"), "park_year")
    lowered = text.lower()
    captions = [_normalize(table.caption) for table in parser.tables.values()]
    prose = " ".join(" ".join([*parser.prose, *captions]).split()).lower()
    _require(CLOSE_RULE in lowered, "close rule: required sentence is missing")
    _require(
        "operating profit plus capital spending plus interest equals the change in cash less loan,"
        " less the money already booked to the new month, from the previous month, with no month"
        " missing in between" in lowered,
        "check explanation: required reconciliation sentence is missing",
    )
    _require(
        "each park's first month has no earlier statement to reconcile, so its bar is not checked"
        in lowered,
        "first-month sentence: required R10 sentence is missing",
    )
    _require(
        re.search(PARK_COUNT, prose) is None,
        "sample note: the page text must not state a park count",
    )
    _require(
        ("No company year has closed yet." in text) == (not company)
        and ("company-year-table" in parser.tables) == bool(company),
        "closed years: the empty-state sentence shows, and the table is absent, only with no rows",
    )
    if company:
        _check_table(
            parser,
            "company-year-table",
            [
                [
                    _cell(row, "company_year", "company_year"),
                    _cell(row, "parks_reporting", "company_year"),
                    _cell(row, "parks_partial_first_season", "company_year"),
                    _cell(row, "months_checked", "company_year"),
                    _usd(_number(row, "operating_profit", "company_year")),
                ]
                for row in company
            ],
        )
    _check_table(
        parser,
        "park-year-table",
        [
            [
                _cell(row, "company_year", "park_year"),
                _cell(row, "park_id", "park_year"),
                f"{_cell(row, 'statements_kept', 'park_year')} of"
                f" {_cell(row, 'statements_expected', 'park_year')}",
                _cell(row, "months_checked", "park_year"),
                _usd(_number(row, "operating_profit", "park_year")),
                STATUS_WORDS.get(str(row.get("close_status")), "unknown status"),
            ]
            for row in parks
        ],
    )
    listed = {cell[1][2] for cell in (r.cells for r in parser.tables["park-year-table"].body_rows)}
    month_parks = {
        _cell(row, "park_id", "park_month") for row in _dict_rows(served_park, "park_month")
    }
    missing = sorted(month_parks - listed)
    _require(not missing, f"park-years table: parks in park_month.json are missing ({missing})")


def _attribute_values(html: str) -> list[tuple[str, str, str]]:
    """Return (tag, attribute, value) for every src and href attribute in the HTML."""
    attributes: list[tuple[str, str, str]] = []

    class AttributeParser(HTMLParser):
        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            attributes.extend(
                (tag, name, value) for name, value in attrs if name in {"src", "href"} and value
            )

    parser = AttributeParser()
    parser.feed(html)
    return attributes


def main(argv: list[str] | None = None) -> int:
    """Check the built page and return 0 on success, 1 on a page mismatch."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--served-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        check_page(args.site, args.served_dir)
    except PageCheckFailed as error:
        print(f"page check failed: {error}")
        return 1
    print("showcase page: checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

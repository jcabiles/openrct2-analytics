"""Refusal order and input bounds of the start year (review findings SY2R-1 to SY2R-3).

Each order case fails exactly the two refusals under test and shows only the earlier one. Texts
are copied from the spec's section 4. The shared fixtures are in
``tests/test_register_parks_start_year.py``.
"""

from __future__ import annotations

import json

from tests.test_register_parks_start_year import (
    ADR,
    Company,
    World,
    _first_park,
    overlap,
    park_one,
)
from tests.test_register_parks_start_year import company as company  # noqa: F401  (fixture)

NOT_CONVERTED = (
    "events-2026-11-13.jsonl holds a session that was never converted, so the latest "
    "managed year is unknown; run make convert DATA_SET=company first"
)


def _origin_five() -> World:
    """Park 1 registered; Park 2 waits to register, captured from game year 5."""
    world = park_one()
    world["sessions"][1] = ("park-2", "s2", (5, 0, 1), 2)
    return world


def _plant_unconverted_raw_file(company: Company) -> None:
    raw = company.root / "company" / "raw" / "v1" / "events-2026-11-13.jsonl"
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps({"session_id": "s9", "park_id": "park-1"}) + "\n")


# SY2R-1: refusal 11 (origin) comes after refusals 6, 9 and 10.


def test_first_park_refusal_comes_before_the_origin_refusal(company: Company) -> None:
    company.plant(_first_park(5))
    company.refused(
        ["--start-year", "2001"],
        "start-year-first-park",
        "Park park-2 is the first company park, which starts in company year 2000; drop START_YEAR",
    )


def test_overlap_refusal_comes_before_the_origin_refusal(company: Company) -> None:
    company.plant(_origin_five())
    company.refused(
        ["--start-year", "2000"], "start-year-overlap", overlap("2000", "park-1", 2000, "park-2")
    )


def test_gap_refusal_comes_before_the_origin_refusal(company: Company) -> None:
    company.plant(_origin_five())
    company.refused(
        ["--start-year", "2002"],
        "start-year-gap",
        "Company year 2002 would leave company year 2001 with no managed park; the next park "
        "starts the March after 2000, which park park-1 sets, so START_YEAR must be 2001; "
        f"if 2000 looks too high, {ADR}",
    )


# SY2R-2: refusal 7 without START_YEAR, before refusal 8; the first park reads no park data.


def test_unconverted_raw_file_is_refused_before_a_missing_start_year(company: Company) -> None:
    company.plant(park_one())
    _plant_unconverted_raw_file(company)
    company.refused([], "not-converted", NOT_CONVERTED)


def test_first_company_park_reads_no_park_data(company: Company) -> None:
    company.plant(_first_park(1))
    _plant_unconverted_raw_file(company)
    for table in ("park_snapshot", "save_written"):
        (company.root / "company" / "parquet" / "v1" / f"{table}.parquet").write_bytes(b"corrupt")
    assert company.run() == 0
    assert company.written() == [("park-2", "2000", "1", "")]


# SY2R-3: a START_YEAR too long to be a year is refused like any value that is not a year.


def test_five_thousand_digit_start_year_is_refused(company: Company) -> None:
    company.plant(park_one())
    typed = "1" * 5000
    company.refused(
        ["--start-year", typed],
        "start-year",
        f"START_YEAR must be a year written in digits, such as 2001; got '{typed}'",
    )


def test_four_digit_start_year_above_the_floor_is_still_accepted(company: Company) -> None:
    company.plant(park_one())
    company.accepted("park-2", "2001")

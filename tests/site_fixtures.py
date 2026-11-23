"""Fixture export sets for the site tests: an empty set and two sets, A and B, of different values.

Each set holds the export files with the exact column lists of `site/exports.toml`. A and B
each have two parks, months across two company years and one closed company year. They share
dates, years and `statements_expected`; no money value of A is a money value of B, and each
count column holds different values in A and in B (a complete park-year's "8 of 8" aside, since
a complete year keeps every expected statement in both sets). No value is a "Numbers kept as
copy" entry.

Two more sets, `numbered` and `numbered-no-park-one`, hold three numbered parks whose number order
differs from their ID order and their first-month order; the second leaves Park 1 without month
rows. They are not in `SETS`: only the tests of the park number use them.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SETS = ("empty", "A", "B")
MONEY_COLUMNS = {"operating_profit"}

Rows = dict[str, list[dict[str, Any]]]


def _months(year: int, first: int, count: int) -> list[str]:
    return [f"{year}-{month:02d}-01" for month in range(first, first + count)]


def _park_months(parks: dict[str, list[str]], base: float, step: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for park_id, dates in sorted(parks.items()):
        for date in dates:
            rows.append(
                {
                    "park_month_key": f"{park_id}|{date[:4]}|{date[5:7]}",
                    "park_id": park_id,
                    "statement_company_date": date,
                    "operating_profit": round(base + step * (len(rows) + 1), 2),
                }
            )
    return rows


def _parks(park_ids: list[str]) -> list[dict[str, Any]]:
    return [
        {"park_id": park_id, "park_number": number} for number, park_id in enumerate(park_ids, 1)
    ]


def _park_years(
    entries: list[tuple[int, str, int, str, int, float]],
) -> list[dict[str, Any]]:
    return [
        {
            "park_year_key": f"{park_id}|{year}",
            "park_id": park_id,
            "company_year": year,
            "statements_kept": kept,
            "statements_expected": 8,
            "close_status": status,
            "is_partial_first_season": status == "partial_first_season",
            "months_checked": checked,
            "operating_profit": profit,
        }
        for year, park_id, kept, status, checked, profit in sorted(entries)
    ]


def _set_a() -> Rows:
    one, two = "k1000000000001-fxa001", "k1000000000002-fxa002"
    months = {
        one: _months(2000, 3, 8) + _months(2001, 3, 2),
        two: _months(2000, 8, 3) + _months(2001, 3, 1),
    }
    return {
        "park": _parks([one, two]),
        "park_month": _park_months(months, 1000.0, 37.21),
        "park_year": _park_years(
            [
                (2000, one, 8, "complete", 7, 2111.11),
                (2000, two, 3, "partial_first_season", 2, 2222.22),
                (2001, one, 2, "open", 1, 2333.33),
                (2001, two, 1, "open", 1, 2444.44),
            ]
        ),
        "company_year": [
            {
                "company_year": 2000,
                "parks_reporting": 2,
                "parks_partial_first_season": 1,
                "statements_kept": 11,
                "months_checked": 9,
                "operating_profit": 3555.55,
            }
        ],
    }


def _set_b() -> Rows:
    one, two = "k2000000000001-fxb001", "k2000000000002-fxb002"
    months = {
        one: _months(2000, 3, 8) + _months(2001, 3, 4),
        two: _months(2001, 3, 5),
    }
    return {
        "park": _parks([one, two]),
        "park_month": _park_months(months, 7000.0, 41.37),
        "park_year": _park_years(
            [
                (2000, one, 8, "complete", 6, 8111.11),
                (2001, one, 4, "open", 4, 8222.22),
                (2001, two, 5, "partial_first_season", 4, 8333.33),
            ]
        ),
        "company_year": [
            {
                "company_year": 2000,
                "parks_reporting": 1,
                "parks_partial_first_season": 0,
                "statements_kept": 8,
                "months_checked": 6,
                "operating_profit": 9555.55,
            }
        ],
    }


NUMBERED_PARKS = (
    "k4000000000001-fxd001",
    "k4000000000002-fxd002",
    "k4000000000003-fxd003",
)
NUMBERS = (2, 1, 3)


def numbered_park_rows() -> list[dict[str, Any]]:
    """Return the `park` rows of three numbered parks, in the export's `park_number` order.

    By ID the parks run 1, 2, 3 and carry the numbers 2, 1, 3, so the rows run ID 2, ID 1, ID 3.
    """
    ranked = sorted(zip(NUMBERS, NUMBERED_PARKS, strict=True))
    return [{"park_id": park_id, "park_number": number} for number, park_id in ranked]


def numbered_park_months(*, park_one: bool = True) -> list[dict[str, Any]]:
    """Return park-month rows for the numbered parks; `park_one=False` leaves Park 1 without rows.

    By first company month the parks run ID 1 (Mar), ID 3 (May), ID 2 (Aug), so the month order, the
    ID order and the number order all differ. ID 2 is Park 1; with `park_one=False` it has no rows.
    """
    one, two, three = NUMBERED_PARKS
    months = {one: _months(2000, 3, 4), three: _months(2000, 5, 3)}
    if park_one:
        months[two] = _months(2000, 8, 3)
    return _park_months(months, 4000.0, 29.13)


def fixture_rows(name: str) -> Rows:
    """Return the rows of one fixture set, keyed by export name.

    The ride and revenue exports are empty in every set: no page region reads them yet.
    """
    if name == "empty":
        rows: Rows = {"park": [], "park_month": [], "park_year": [], "company_year": []}
    elif name == "A":
        rows = _set_a()
    elif name == "B":
        rows = _set_b()
    elif name in ("numbered", "numbered-no-park-one"):
        rows = {
            "park": numbered_park_rows(),
            "park_month": numbered_park_months(park_one=name == "numbered"),
            "park_year": [],
            "company_year": [],
        }
    elif name == "ride-row-no-statement":
        one, two = NUMBERED_PARKS[:2]
        rows = {
            "park": _parks([one, two]),
            "park_month": _park_months({two: _months(2000, 3, 3)}, 4000.0, 29.13),
            "park_year": [],
            "company_year": [],
        }
        ride_month = {
            "ride_month_key": f"{one}|ride-1|2000-03-01",
            "ride_key": f"{one}|ride-1",
            "park_id": one,
            "ride_name": "Maze 1",
            "company_year": 2000,
            "company_date": "2000-03-01",
            "ride_days": 20,
            "average_availability_from_downtime_pct": 97.5,
            "longest_queue_seen_minutes": 12,
            "riders": 340,
        }
        return {
            **rows,
            "ride_month": [ride_month],
            "ride_year": [],
            "park_month_revenue": [],
            "sample": _sample(name, rows),
        }
    else:
        raise ValueError(f"unknown fixture set {name}")
    return {
        **rows,
        "ride_month": [],
        "ride_year": [],
        "park_month_revenue": [],
        "sample": _sample(name, rows),
    }


def _sample(name: str, rows: Rows) -> list[dict[str, Any]]:
    """Return the set's sample record: the empty set holds no session, every other set holds 3."""
    return [
        {
            "data_set": "sample",
            "parks": len({row["park_id"] for row in rows["park_year"]}),
            "sessions": 0 if name == "empty" else 3,
            "player_played": False,
        }
    ]


def write_set(name: str, folder: Path) -> Path:
    """Write one fixture set's export files into `folder`, columns as `site/exports.toml`."""
    exports = tomllib.loads((ROOT / "site/exports.toml").read_text())["export"]
    rows = fixture_rows(name)
    folder.mkdir(parents=True)
    for export in exports:
        for row in rows[export["name"]]:
            assert list(row) == export["columns"], (export["name"], list(row))
        document = {
            "name": export["name"],
            "relation": export["relation"],
            "columns": export["columns"],
            "rows": rows[export["name"]],
        }
        (folder / export["output"]).write_text(json.dumps(document, indent=2) + "\n")
    record = rows["sample"][0]
    document = {
        "name": "sample",
        "relation": "marts.obt_park_year, marts.fct_park_day, staging.stg_session_start",
        "columns": list(record),
        "rows": rows["sample"],
    }
    (folder / "sample.json").write_text(json.dumps(document, indent=2) + "\n")
    return folder


def usd(value: float) -> str:
    """Format dollars the way the site's `usd` filter does."""
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"

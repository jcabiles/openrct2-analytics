"""The data builder leaves Sandbox (throwaway practice) parks out of "All parks" by default."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from openrct2_analytics.dashboard import data
from openrct2_analytics.ingest import registry_feed
from tests.test_dashboard_data import Figures, Options, _month_row, make_warehouse

PRACTICE = registry_feed.PRACTICE_NOTE
# The 2026-11-15 case: one company park and two same-named Sandbox parks.
R1: Options = {
    "parks": (("p1", "Alpha Park"), ("s1", "Bumbly Bazaar"), ("s2", "Bumbly Bazaar")),
    "notes": ("", PRACTICE, PRACTICE),
}
ONLY_P1: Options = {"parks": (("p1", "Alpha Park"),)}
TWO_COMPANY: Options = {"parks": (("p1", "Alpha Park"), ("p2", "Beta Park"))}
MONEY = (
    "profit", "rev", "rides", "food", "merch", "entrance", "running", "staff", "stock", "mkt",
    "research", "capital", "costs", "visits", "opdays", "cash", "guests",
)  # fmt: skip


def _build(tmp_path: Path, options: Options, name: str = "w.duckdb") -> Figures:
    return data.build(make_warehouse(tmp_path / name, **options))


def _scope(figures: Figures, name: str) -> dict[str, Any]:
    scope: dict[str, Any] = figures["scopes"][name]
    return scope


def _month(scope: dict[str, Any], year: int, month: int) -> dict[str, Any]:
    (record,) = [m for m in scope["months"] if (m["y"], m["m"]) == (year, month)]
    assert isinstance(record, dict)
    return record


def _total(rides: list[dict[str, Any]]) -> list[int]:
    """The ride day counts of ``rides`` added up month by month."""
    total = [0] * len(rides[0]["n"])
    for ride in rides:
        total = [a + (b or 0) for a, b in zip(total, ride["n"], strict=True)]
    return total


def test_sandbox_parks_are_marked_from_the_park_number(tmp_path: Path) -> None:
    figures = _build(tmp_path, R1)

    assert [(p["id"], p["name"], p["sandbox"]) for p in figures["parks"]] == [
        ("p1", "Alpha Park", False),
        ("s1", "Bumbly Bazaar", True),
        ("s2", "Bumbly Bazaar", True),
    ]


def test_a_park_without_a_name_is_named_by_its_id(tmp_path: Path) -> None:
    figures = _build(tmp_path, {"parks": (("p1", None),)})

    assert [(p["id"], p["name"], p["sandbox"]) for p in figures["parks"]] == [("p1", "p1", False)]
    assert len(_scope(figures, "all")["months"]) == 16
    assert _scope(figures, "all")["park_ids"] == ["p1"]


def test_an_unregistered_park_and_a_statement_without_a_company_date_are_left_out(
    tmp_path: Path,
) -> None:
    path = make_warehouse(tmp_path / "w.duckdb", **R1)
    before: Figures = data.build(path)
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            "insert into marts.obt_park_month values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?, ?)",
            ["zz", None, None, None, *_month_row(date(2001, 3, 1), 999.0, 1)[1:]],
        )
    finally:
        connection.close()
    after: Figures = data.build(path)

    assert [p["id"] for p in after["parks"]] == ["p1", "s1", "s2"]
    for name in after["scopes"]:
        assert "zz" not in _scope(after, name)["park_ids"], name
    assert after["scopes"] == before["scopes"]


def test_the_default_total_leaves_two_sandbox_parks_out(tmp_path: Path) -> None:
    figures = _build(tmp_path, R1)
    everything, first = _scope(figures, "all"), _scope(figures, "p1")

    assert everything["parks"] == 1
    assert len(everything["months"]) == 16
    for total, own in zip(everything["months"], first["months"], strict=True):
        assert {key: total[key] for key in ("y", "m", *MONEY)} == {
            key: own[key] for key in ("y", "m", *MONEY)
        }
    march = everything["months"][0]
    assert (march["profit"], march["rev"], march["costs"]) == (100.5, 600.5, 500.0)
    assert (march["visits"], march["opdays"], march["cash"], march["guests"]) == (40, 2, 1001.0, 21)


def test_the_default_total_is_the_same_with_or_without_two_sandbox_parks(tmp_path: Path) -> None:
    with_sandbox = _build(tmp_path, R1, "a.duckdb")
    only = _build(tmp_path, ONLY_P1, "b.duckdb")

    assert _scope(with_sandbox, "all") == _scope(only, "all")


def test_a_month_only_sandbox_parks_closed_is_left_out(tmp_path: Path) -> None:
    figures = _build(tmp_path, {**R1, "starts": (6, 3, 3)})
    everything, shown = _scope(figures, "all"), _scope(figures, "with_sandbox")

    assert (everything["months"][0]["y"], everything["months"][0]["m"]) == (2001, 6)
    assert everything["dates"][0] == "2001-06-01"
    assert all(day >= "2001-06-01" for day in everything["dates"])
    assert (shown["months"][0]["y"], shown["months"][0]["m"]) == (2001, 3)
    assert shown["dates"][0] == "2001-03-01"


def _assert_every_day_once(figures: Figures, scope: str, singles: dict[str, str]) -> None:
    """``scope`` holds each park's days and rides once; ``singles`` maps park ID to its name."""
    both = _scope(figures, scope)
    pairs = list(zip(both["days"]["date"], both["days"]["park"], strict=True))
    assert len(pairs) == len(set(pairs))
    assert len(pairs) == sum(len(_scope(figures, park)["days"]["date"]) for park in singles)
    by_name = {ride["name"]: ride["n"] for ride in both["rides"]}
    for park, name in singles.items():
        for ride in _scope(figures, park)["rides"]:
            assert by_name[f"{ride['name']} ({name})"] == ride["n"]
    assert _total(both["rides"]) == [
        sum(parts)
        for parts in zip(*(_total(_scope(figures, park)["rides"]) for park in singles), strict=True)
    ]


def test_the_month_gate_repeats_no_day(tmp_path: Path) -> None:
    company = _build(tmp_path, TWO_COMPANY, "a.duckdb")
    mixed = _build(
        tmp_path,
        {
            "parks": (("p1", "Alpha Park"), ("p2", "Beta Park"), ("s1", "Bumbly Bazaar")),
            "notes": ("", "", PRACTICE),
        },
        "b.duckdb",
    )

    _assert_every_day_once(company, "all", {"p1": "Alpha Park", "p2": "Beta Park"})
    _assert_every_day_once(
        mixed, "with_sandbox", {"p1": "Alpha Park", "p2": "Beta Park", "s1": "Bumbly Bazaar"}
    )
    assert len(_scope(company, "all")["days"]["date"]) == 64


def test_the_shown_total_equals_the_company_month_mart(tmp_path: Path) -> None:
    path = make_warehouse(tmp_path / "w.duckdb", **R1)
    figures = data.build(path)
    connection = duckdb.connect(str(path), read_only=True)
    try:
        rows = connection.execute(
            "select company_date, operating_profit, operating_revenue, ride_revenue, "
            "food_drink_revenue, merchandise_revenue, entrance_revenue, ride_running_costs, "
            "staff_wages, stock_costs, marketing_costs, research_costs, capital_spending, "
            "operating_costs, guest_visits, operating_days "
            "from marts.obt_company_month order by company_date"
        ).fetchall()
    finally:
        connection.close()

    months = _scope(figures, "with_sandbox")["months"]
    assert len(months) == len(rows) == 16
    keys = (*MONEY[:6], *MONEY[6:13], "visits", "opdays")
    for record, row in zip(months, rows, strict=True):
        assert (record["y"], record["m"]) == (row[0].year, row[0].month)
        for key, value in zip(keys, row[1:], strict=True):
            if key in MONEY[6:13]:  # cost lines are stored negative in the marts
                expected: float = -float(value) + 0.0
            elif key in ("visits", "opdays"):
                expected = value
            else:
                expected = float(value)
            assert record[key] == expected, (record["y"], record["m"], key)
    assert months[0]["profit"] == 100.5 * 3
    assert months[0]["opdays"] == 6


def test_no_sandbox_park_means_no_shown_scope(tmp_path: Path) -> None:
    one = _build(tmp_path, ONLY_P1, "a.duckdb")
    several = _build(tmp_path, TWO_COMPANY, "b.duckdb")

    assert sorted(one["scopes"]) == ["all"]
    assert _scope(one, "all")["park_ids"] == ["p1"]
    assert sorted(several["scopes"]) == ["all", "p1", "p2"]
    assert "with_sandbox" not in one["scopes"] and "with_sandbox" not in several["scopes"]


def test_each_scope_lists_its_parks(tmp_path: Path) -> None:
    figures = _build(tmp_path, R1, "a.duckdb")
    alone = _build(
        tmp_path, {"parks": (("s1", "Bumbly Bazaar"),), "notes": (PRACTICE,)}, "b.duckdb"
    )

    assert {name: scope["park_ids"] for name, scope in figures["scopes"].items()} == {
        "all": ["p1"],
        "with_sandbox": ["p1", "s1", "s2"],
        "p1": ["p1"],
        "s1": ["s1"],
        "s2": ["s2"],
    }
    assert _scope(figures, "with_sandbox")["parks"] == 3
    assert sorted(alone["scopes"]) == ["all", "s1", "with_sandbox"]
    assert _scope(alone, "all")["park_ids"] == [] and _scope(alone, "all")["parks"] == 0
    assert _scope(alone, "all")["months"] == []
    assert _scope(alone, "with_sandbox")["park_ids"] == ["s1"]
    assert len(_scope(alone, "with_sandbox")["months"]) == 16


def test_ride_names_carry_the_park_only_when_the_scope_has_several_parks(tmp_path: Path) -> None:
    figures = _build(tmp_path, R1)

    assert [ride["name"] for ride in _scope(figures, "all")["rides"]] == [
        "Alpha Coaster 1",
        "Beta Ship 1",
    ]
    assert [ride["name"] for ride in _scope(figures, "with_sandbox")["rides"]] == [
        "Alpha Coaster 1 (Alpha Park)",
        "Alpha Coaster 1 (Bumbly Bazaar)",
        "Alpha Coaster 1 (Bumbly Bazaar)",
        "Beta Ship 1 (Alpha Park)",
        "Beta Ship 1 (Bumbly Bazaar)",
        "Beta Ship 1 (Bumbly Bazaar)",
    ]
    assert [ride["name"] for ride in _scope(figures, "s1")["rides"]] == [
        "Alpha Coaster 1",
        "Beta Ship 1",
    ]


# p1 and s1 each add a later kept day: p1 on the 20th (cash 5020, guests 520) and s1 on the 28th
# (cash 5128, guests 538).
LAST_READINGS: Options = {
    "parks": (("p1", "Alpha Park"), ("s1", "Bumbly Bazaar")),
    "notes": ("", PRACTICE),
    "last_days": (20, 28),
}


def test_cash_and_guests_are_each_parks_last_reading_with_one_closing_park(
    tmp_path: Path,
) -> None:
    figures = _build(tmp_path, {**LAST_READINGS, "gaps": ((), (4,))})
    both, company = _scope(figures, "with_sandbox"), _scope(figures, "all")

    # April: only p1 has a statement; s1 still has kept days.
    april = _month(both, 2001, 4)
    assert (april["cash"], april["guests"]) == (10148.0, 1058)
    assert (april["visits"], april["opdays"]) == (40, 2)
    april = _month(company, 2001, 4)
    assert (april["cash"], april["guests"]) == (5020.0, 520)
    assert (april["visits"], april["opdays"]) == (40, 2)
    # March: both closed it.
    march = _month(both, 2001, 3)
    assert (march["cash"], march["guests"], march["visits"], march["opdays"]) == (
        10148.0,
        1058,
        80,
        4,
    )


def test_a_month_closed_only_by_a_sandbox_park_opens_when_included(tmp_path: Path) -> None:
    figures = _build(tmp_path, {**LAST_READINGS, "gaps": ((5,), ())})

    assert (2001, 5) not in [(m["y"], m["m"]) for m in _scope(figures, "all")["months"]]
    may = _month(_scope(figures, "with_sandbox"), 2001, 5)
    assert (may["cash"], may["guests"]) == (10148.0, 1058)
    assert (may["visits"], may["opdays"]) == (40, 2)


def test_the_month_record_holds_only_the_additive_fields(tmp_path: Path) -> None:
    figures = _build(tmp_path, R1)

    expected = sorted(
        ["y", "m", "profit", "rev", "rides", "food", "merch", "entrance", "running", "staff"]
        + ["stock", "mkt", "research", "capital", "costs", "visits", "opdays", "cash", "guests"]
    )
    assert sorted(figures["scopes"]) == ["all", "p1", "s1", "s2", "with_sandbox"]
    for name, scope in figures["scopes"].items():
        assert scope["months"], name
        for record in scope["months"]:
            assert sorted(record) == expected, name

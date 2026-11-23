"""The dashboard's data builder over a fixture warehouse with the marts it reads."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, TypedDict, Unpack

import duckdb
import pytest

from openrct2_analytics.dashboard import data
from openrct2_analytics.ingest import registry_feed

SEASON = range(3, 11)  # March to October, the months of a company year.
# Operating profit of each month of the season, in dollars; a later year repeats the last list.
PROFITS = {
    2001: (100.5, 200.25, -50.25, 300.0, 410.0, 120.0, 80.0, 40.0),
    2002: (400.0, -50.25, 150.0, 220.5, 600.0, 330.0, 90.0, 60.0),
}
_FIGURE_COLUMNS = (
    "operating_profit decimal(18,2), "
    "operating_revenue decimal(18,2), "
    "ride_revenue decimal(18,2), food_drink_revenue decimal(18,2), "
    "merchandise_revenue decimal(18,2), entrance_revenue decimal(18,2), "
    "ride_running_costs decimal(18,2), staff_wages decimal(18,2), stock_costs decimal(18,2), "
    "marketing_costs decimal(18,2), research_costs decimal(18,2), "
    "capital_spending decimal(18,2), operating_costs decimal(18,2), guest_visits bigint, "
    "operating_days integer"
)
# obt_company_month has no game year; obt_park_month adds statement_year and company_year, the
# year of company_date (as the mart defines it).
_COMPANY_COLUMNS = f"company_date date, {_FIGURE_COLUMNS}"
_PARK_COLUMNS = (
    f"park_id varchar, company_date date, statement_year integer, company_year integer, "
    f"{_FIGURE_COLUMNS}"
)
# (name, ride key in the first year, ride key in later years, ride type, classification)
_RIDES = (
    ("Alpha Coaster 1", "r1", "r1b", 52, "ride"),  # rebuilt in its second year: same name
    ("Beta Ship 1", "r2", "r2", 26, "ride"),
    ("Gamma Twist 1", "r3", "r3", 99, "ride"),  # never carries a rider
    ("Burger Bar 1", "s1", "s1", 0, "stall"),
)

# The additive columns of obt_park_month that sum into the fixture's obt_company_month.
_SUMMED_COLUMNS = (
    "operating_profit", "operating_revenue", "ride_revenue", "food_drink_revenue",
    "merchandise_revenue", "entrance_revenue", "ride_running_costs", "staff_wages", "stock_costs",
    "marketing_costs", "research_costs", "capital_spending", "operating_costs", "guest_visits",
    "operating_days",
)  # fmt: skip

Figures = dict[str, Any]


class Options(TypedDict, total=False):
    """The optional arguments of ``make_warehouse``, for helpers that pass them on."""

    years: tuple[int, ...]
    parks: tuple[tuple[str, str | None], ...]
    notes: tuple[str, ...]
    gaps: tuple[tuple[int, ...], ...]
    gap_years: tuple[int, ...]
    last_days: tuple[int | None, ...]
    game_years: tuple[tuple[int | None, ...], ...]
    starts: tuple[int, ...]
    unmapped: bool
    data_set: str


def _month_row(month: date, profit: float, parks: int) -> tuple[object, ...]:
    """One statement: revenue is profit + $500, costs are $500, marketing is paid in April."""
    paid = month.month == 4
    return (
        month, profit * parks, (profit + 500) * parks, (profit + 300) * parks,
        100 * parks,
        50 * parks, 50 * parks, -200 * parks, -150 * parks, -50 * parks,
        (-100 if paid else 0) * parks, (0 if paid else -100) * parks, 0, -500 * parks,
        40 * parks, 2,
    )  # fmt: skip


def _ride_day(park: str, day: date, first_year: int, kept: bool) -> list[tuple[object, ...]]:
    """Every ride's reading of one park day; days that do not count carry 100 riders."""
    age = day.month - 3
    rows: list[tuple[object, ...]] = []
    for name, key, rebuilt, ride_type, classification in _RIDES:
        riders = 0 if name == "Gamma Twist 1" else 5 if name.startswith("Alpha") else 3
        profit = 10.0 if name.startswith("Alpha") else 4.5
        if name == "Beta Ship 1" and (day.year, day.month) == (first_year, 4):
            riders, profit = 0, -1.0  # open but idle for a month
        if not kept and riders:
            riders = 100
        price = 1.0 if name == "Beta Ship 1" and (day.year, day.month) >= (2002, 4) else 1.5
        rows.append(
            (
                f"{park}-{key if day.year == first_year else rebuilt}", park, day, ride_type,
                True, riders, profit, price, age, 70, 95, 4, classification,
            )
        )  # fmt: skip
    return rows


def _insert_rows(
    connection: duckdb.DuckDBPyConnection, sql: str, rows: list[tuple[object, ...]]
) -> None:
    """Insert ``rows``; a park with every month a gap has none, and DuckDB refuses no rows."""
    if rows:
        connection.executemany(sql, rows)


def make_warehouse(
    path: Path,
    **options: Unpack[Options],
) -> Path:
    """Write a warehouse with the marts the dashboard reads.

    Each park has the months of ``SEASON`` in every year of ``years``, two kept days a month, one
    day that is not kept (the 3rd of its first March) and a partial trailing year (1 and 2 March
    of the year after the last) that has no statement yet. ``notes`` gives each park's registry
    note, in the order of ``parks``.

    ``game_years`` gives each park's game year per company year (``None`` for a year the park
    has no game year in; its statement rows keep a null game year); it defaults to 1, 2, ... for
    every park.
    ``starts`` gives each park's first month in its first mapped year; later years start in
    March. It defaults to March.
    ``unmapped`` adds two park month rows that lack a company date or a game year.
    A park whose note is the practice note has a null ``park_number`` (a Sandbox park); the other
    parks are numbered 1, 2, ... A ``None`` name writes a null ``park_name``.
    ``gaps`` gives each park's company months (numbers 3 to 10) that have no statement row, in
    every year, or only in the years of ``gap_years``; its kept days stay. ``last_days`` gives
    each park's extra kept day of the month in every season month (a later last reading, with
    its own cash and guest amounts), or ``None``.
    ``obt_company_month`` is the sum of the park rows that have a company date.
    """
    years = options.get("years", (2001, 2002))
    parks = options.get("parks", (("p1", "Alpha Park"),))
    notes = options.get("notes", ())
    game_years = options.get("game_years")
    starts = options.get("starts")
    unmapped = options.get("unmapped", False)
    gaps = options.get("gaps", ())
    gap_years = options.get("gap_years", years)
    last_days = options.get("last_days", ())
    data_set = options.get("data_set", "company")
    connection = duckdb.connect(str(path))
    try:
        for schema in ("marts", "intermediate"):
            connection.execute(f"create schema {schema}")
        connection.execute(f"create table marts.obt_company_month ({_COMPANY_COLUMNS})")
        connection.execute(f"create table marts.obt_park_month ({_PARK_COLUMNS})")
        connection.execute(
            "create table marts.fct_park_day (park_id varchar, company_date date, "
            "is_kept_operating_day boolean, cash_usd decimal(18,2), guests_in_park integer, "
            "admissions_increase bigint, weather varchar, temperature_c integer)"
        )
        connection.execute(
            "create table marts.fct_ride_day (ride_key varchar, park_id varchar, "
            "company_date date, ride_type integer, is_open_day boolean, customers_increase bigint, "
            "profit_usd decimal(18,2), ride_price_listed_usd decimal(18,2), "
            "ride_age_months integer, guest_rating_pct integer, "
            "availability_from_downtime_pct integer, longest_queue_seen_minutes integer, "
            "classification varchar)"
        )
        connection.execute(
            "create table marts.dim_ride (ride_key varchar, park_id varchar, ride_name varchar)"
        )
        connection.execute(
            "create table marts.dim_park (park_id varchar, park_name varchar, "
            "first_company_date date, data_set varchar, park_number integer)"
        )
        connection.execute(
            "create table intermediate.int_park_registry__current (park_id varchar, note varchar)"
        )
        years_game = game_years or tuple(
            tuple(year - years[0] + 1 for year in years) for _ in parks
        )
        park_starts = starts or tuple(3 for _ in parks)
        months = [date(year, month, 1) for year in years for month in SEASON]
        if unmapped:
            for missing_date, missing_year in ((True, False), (False, True)):
                month = date(years[0], 3, 1)
                row = _month_row(month, PROFITS[years[0]][0], 1)
                connection.execute(
                    "insert into marts.obt_park_month values "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        parks[0][0],
                        None if missing_date else month,
                        None if missing_year else 1,
                        None if missing_date else month.year,
                        *row[1:],
                    ],
                )
        days = [
            *[(date(month.year, month.month, day), True) for month in months for day in (1, 2)],
            (date(years[0], 3, 3), False),
            (date(years[-1] + 1, 3, 1), True),
            (date(years[-1] + 1, 3, 2), True),
        ]
        company_number = 0
        for number, (park, name) in enumerate(parks):
            park_gaps = gaps[number] if number < len(gaps) else ()
            first_year_index = next(
                (i for i, game_year in enumerate(years_game[number]) if game_year is not None),
                None,
            )
            _insert_rows(
                connection,
                "insert into marts.obt_park_month values "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        park,
                        month,
                        years_game[number][year_index],
                        month.year,
                        *_month_row(month, profit, 1)[1:],
                    )
                    for year_index, year in enumerate(years)
                    for month_number in range(
                        park_starts[number] if year_index == first_year_index else 3, 11
                    )
                    if not (month_number in park_gaps and year in gap_years)
                    for month in [date(year, month_number, 1)]
                    for profit in [PROFITS.get(year, PROFITS[2002])[month_number - 3]]
                ],
            )
            connection.executemany(
                "insert into marts.fct_park_day values (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        park,
                        day,
                        kept,
                        1000 + i,
                        20 + i,
                        8 if i % 2 else 2,
                        "sunny" if i % 2 else "rain",
                        18,
                    )
                    for i, (day, kept) in enumerate(days)
                ],  # fmt: skip
            )
            last_day = last_days[number] if number < len(last_days) else None
            if last_day is not None:
                connection.executemany(
                    "insert into marts.fct_park_day values (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (park, date(m.year, m.month, last_day), True,
                         5000 + 100 * number + last_day, 500 + 10 * number + last_day,
                         2, "rain", 18)
                        for m in months
                    ],
                )  # fmt: skip
            connection.executemany(
                "insert into marts.fct_ride_day values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [row for day, kept in days for row in _ride_day(park, day, years[0], kept)],
            )
            connection.executemany(
                "insert into marts.dim_ride values (?, ?, ?)",
                [
                    (f"{park}-{key}", park, ride)
                    for ride, first, rebuilt, _, _ in _RIDES
                    for key in dict.fromkeys((first, rebuilt))
                ],
            )
            note = notes[number] if number < len(notes) else ""
            sandbox = note == registry_feed.PRACTICE_NOTE
            if not sandbox:
                company_number += 1
            connection.execute(
                "insert into marts.dim_park values (?, ?, ?, ?, ?)",
                [
                    park,
                    name,
                    date(years[0], 3, 1 + number),
                    data_set,
                    None if sandbox else company_number,
                ],
            )
            connection.execute(
                "insert into intermediate.int_park_registry__current values (?, ?)", [park, note]
            )
        sums = ", ".join(f"sum({column})" for column in _SUMMED_COLUMNS)
        connection.execute(
            f"insert into marts.obt_company_month select company_date, {sums} "
            "from marts.obt_park_month where company_date is not null group by company_date"
        )
    finally:
        connection.close()
    return path


@pytest.fixture
def figures(tmp_path: Path) -> Figures:
    return data.build(make_warehouse(tmp_path / "w.duckdb"))


def _scope(figures: Figures, name: str = data.ALL) -> dict[str, Any]:
    scope: dict[str, Any] = figures["scopes"][name]
    return scope


def test_the_output_holds_every_key_each_page_reads(figures: Figures) -> None:
    scope = _scope(figures)

    assert sorted(figures) == ["parks", "scopes"]
    assert figures["parks"] == [
        {
            "id": "p1",
            "name": "Alpha Park",
            "sandbox": False,
            "game_years": {
                2001: {"game_year": 1, "from_month": 3},
                2002: {"game_year": 2, "from_month": 3},
            },
        }
    ]
    assert sorted(figures["scopes"]) == ["all"]
    assert sorted(scope) == [
        "by_age", "dates", "days", "months", "park_ids", "parks", "ride_days", "rides",
    ]  # fmt: skip
    assert sorted(scope["months"][0]) == sorted(
        ["y", "m", "profit", "rev", "rides", "food", "merch", "entrance", "running", "staff"]
        + ["stock", "mkt", "research", "capital", "costs", "visits", "opdays", "cash", "guests"]
    )
    assert sorted(scope["rides"][0]) == sorted(
        ["name", "short", "fam", "reset", "n", "open", "riders", "profit", "price", "pmode"]
        + ["age", "rating", "avail", "q"]
    )
    assert sorted(scope["days"]) == ["arr", "date", "guests", "park", "since", "temp", "w"]
    assert sorted(scope["ride_days"][0]) == ["first", "open", "price", "profit", "riders"]
    assert sorted(scope["by_age"][0]) == ["age", "avail", "n", "riders"]


def test_monthly_profit_of_each_year_sums_to_the_yearly_profit(
    figures: Figures,
) -> None:
    months = _scope(figures)["months"]
    yearly: dict[int, float] = {}
    for month in months:
        yearly[month["y"]] = yearly.get(month["y"], 0.0) + month["profit"]

    assert yearly == {2001: 1200.5, 2002: 1800.25}
    assert [(month["y"], month["m"]) for month in months][:2] == [(2001, 3), (2001, 4)]


def test_costs_are_positive_dollars_and_cash_is_the_last_reading(
    figures: Figures,
) -> None:
    march, april = _scope(figures)["months"][:2]

    assert (march["rev"], march["costs"], march["running"]) == (600.5, 500.0, 200.0)
    assert (march["mkt"], april["mkt"], april["research"]) == (0.0, 100.0, 0.0)
    # 1 and 2 March are kept (cash 1000 and 1001); 3 March is not kept (cash 1032).
    assert (march["cash"], march["guests"]) == (1001.0, 21)


def test_only_rides_that_carried_a_rider_are_shown(figures: Figures) -> None:
    rides = _scope(figures)["rides"]

    assert [(ride["name"], ride["short"], ride["fam"]) for ride in rides] == [
        ("Alpha Coaster 1", "Alpha Coaster", "Coaster"),
        ("Beta Ship 1", "Beta Ship", "Thrill"),
    ]


def test_an_idle_month_shows_zero_riders_and_its_loss(figures: Figures) -> None:
    beta = _scope(figures)["rides"][1]

    assert beta["riders"][:3] == [6, 0, 6]
    assert beta["profit"][:3] == [9.0, -2.0, 9.0]
    assert beta["open"][:3] == [2, 2, 2]
    assert (beta["price"][8], beta["price"][9]) == (1.5, 1.0)


def test_a_partial_trailing_year_and_days_not_kept_are_left_out(
    figures: Figures,
) -> None:
    scope = _scope(figures)

    assert len(scope["months"]) == 16
    assert len(scope["dates"]) == 32
    assert scope["dates"][0] == "2001-03-01" and scope["dates"][-1] == "2002-10-02"
    assert sum(scope["rides"][0]["riders"]) == 160


def test_a_rebuilt_ride_keeps_its_name_and_an_age_drop_is_a_reset(
    figures: Figures,
) -> None:
    alpha = _scope(figures)["rides"][0]

    assert alpha["reset"] == ["2002-03-01"]
    assert alpha["age"][7:9] == [7, 0]


def test_daily_series_marketing_and_age_figures(figures: Figures) -> None:
    scope = _scope(figures)
    days = scope["days"]

    assert days["since"][:6] == [None, None, 0, 0, 1, 1]
    assert days["since"][16:20] == [7, 7, 0, 0]
    assert (days["arr"][:2], days["w"][:2]) == ([2, 8], ["rain", "sunny"])
    assert scope["ride_days"][1]["riders"][2:4] == [0, 0]
    assert scope["ride_days"][0]["first"] == 0
    assert scope["by_age"][:2] == [
        {"age": 0, "n": 8, "avail": 95.0, "riders": 4.0},
        {"age": 1, "n": 8, "avail": 95.0, "riders": 3.25},
    ]


def test_one_year_of_data_builds(tmp_path: Path) -> None:
    scope = _scope(data.build(make_warehouse(tmp_path / "w.duckdb", years=(2001,))))

    assert {month["y"] for month in scope["months"]} == {2001}
    assert scope["rides"][0]["reset"] == []


def test_several_parks_get_one_scope_each_and_park_names_on_rides(tmp_path: Path) -> None:
    figures: Figures = data.build(
        make_warehouse(tmp_path / "w.duckdb", parks=(("p1", "Alpha Park"), ("p2", "Beta Park")))
    )

    assert sorted(figures["scopes"]) == ["all", "p1", "p2"]
    everything, first = _scope(figures), _scope(figures, "p1")
    assert everything["months"][0]["profit"] == 201.0
    assert first["months"][0]["profit"] == 100.5
    assert [ride["name"] for ride in everything["rides"]] == [
        "Alpha Coaster 1 (Alpha Park)",
        "Alpha Coaster 1 (Beta Park)",
        "Beta Ship 1 (Alpha Park)",
        "Beta Ship 1 (Beta Park)",
    ]
    assert [ride["name"] for ride in first["rides"]] == ["Alpha Coaster 1", "Beta Ship 1"]


def test_parks_get_game_years_and_their_first_company_month(tmp_path: Path) -> None:
    figures: Figures = data.build(
        make_warehouse(
            tmp_path / "w.duckdb",
            parks=(("p1", "Alpha Park"), ("p2", "Beta Park")),
            game_years=((1, 2), (None, 7)),
            starts=(3, 6),
        )
    )

    assert figures["parks"][0]["game_years"] == {
        2001: {"game_year": 1, "from_month": 3},
        2002: {"game_year": 2, "from_month": 3},
    }
    assert figures["parks"][1]["game_years"] == {2002: {"game_year": 7, "from_month": 6}}


def test_each_company_year_has_its_own_first_month(tmp_path: Path) -> None:
    figures: Figures = data.build(
        make_warehouse(
            tmp_path / "w.duckdb",
            parks=(("p1", "Alpha Park"), ("p2", "Beta Park")),
            game_years=((1, 2), (7, 8)),
            starts=(3, 6),
        )
    )

    assert figures["parks"][1]["game_years"] == {
        2001: {"game_year": 7, "from_month": 6},
        2002: {"game_year": 8, "from_month": 3},
    }


def test_unmapped_park_month_rows_do_not_create_game_year_keys(tmp_path: Path) -> None:
    figures: Figures = data.build(make_warehouse(tmp_path / "w.duckdb", unmapped=True))

    assert figures["parks"][0]["game_years"] == {
        2001: {"game_year": 1, "from_month": 3},
        2002: {"game_year": 2, "from_month": 3},
    }


def test_game_year_units_are_named_in_the_docstrings() -> None:
    assert "game_years" in data.__doc__
    assert "company date" in data.__doc__
    assert "game calendar" in data.__doc__
    assert data.build.__doc__ is not None
    assert "game_years" in data.build.__doc__


def test_short_names_abbreviate_and_keep_numbers_only_when_needed() -> None:
    assert data._short_names(["Wild Mouse 1", "Wild Mouse 2", "Spiral Roller Coaster 1"]) == {
        "Wild Mouse 1": "Mouse 1",
        "Wild Mouse 2": "Mouse 2",
        "Spiral Roller Coaster 1": "Spiral RC",
    }

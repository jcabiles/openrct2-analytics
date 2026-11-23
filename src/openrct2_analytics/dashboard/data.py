"""Build the dashboard's data from a copy of the development warehouse.

``build`` opens the copy read-only, runs plain SQL over the ``marts`` schema only, and returns one
JSON-able dict that the five pages in ``app/`` read as ``window.DASHBOARD``. Every figure comes
from the marts; the pages compute their sentences from these figures.

Rules the SQL states:

- Every scope is one set of parks, and every figure of a scope is a sum over its parks'
  ``marts.obt_park_month`` rows that have a company date. ``all`` covers the company parks (a park
  with a null ``dim_park.park_number`` is a Sandbox park, a throwaway practice park);
  ``with_sandbox`` covers every park and exists only when a Sandbox park does; each park also has
  its own scope when there is more than one park or any Sandbox park.
- A day counts only when its month has a monthly statement of at least one park in the scope (the
  statement table's ``company_date``) and the park day is kept (``is_kept_operating_day``). Days
  recorded after the last statement, such as the first days of a season whose March has not closed
  yet, are left out until their month closes.
- A month's ``cash`` and ``guests`` are the sum over each park in the scope of its last kept
  reading of the month (a park need not have closed the month); ``visits`` and ``opdays`` are the
  sum over the parks that closed it.
- A ride is a ``fct_ride_day`` row classified ``ride`` (stalls and facilities are left out), named
  by park and ride name (a rebuilt ride keeps its name and gets a new key), and shown only when it
  carried at least one rider on a counted day.
- An age reset is a counted day on which a ride's recorded age is lower than the day before.

Units: ``game_years`` uses the company date year as its key and stores the game calendar year
(``statement_year``) and first company date month. Every money key (``profit``, ``rev``,
``rides``, ``food``, ``merch``, ``entrance``, ``running``, ``staff``, ``stock``, ``mkt``,
``research``, ``capital``, ``costs``, ``cash``, ``price``, ``pmode``) is US dollars; cost keys
are positive amounts (the marts store costs as negative numbers). ``visits``, ``riders``, ``arr``
and ``guests`` are guest counts; ``opdays``, ``open`` and ``n`` are days; ``age`` and ``since``
are months; ``avail`` and ``rating`` are percent; ``q`` is minutes; ``temp`` is degrees Celsius.
Monthly arrays follow ``months``; daily ride arrays start at index ``first`` of ``dates``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

import duckdb

ALL = "all"
# The game's ride categories by OpenRCT2 ride type number; any other type shows as "Other".
_FAMILY_TYPES = {
    "Coaster": (0, 1, 2, 3, 4, 7, 9, 10, 13, 15, 17, 19, 42, 44, 51, 52, 53, 54, 55, 57, 59, 62)
    + (65, 66, 68, 73, 74, 75, 76, 86, 87, 88, 90),
    "Thrill": (12, 22, 26, 27, 38, 39, 40, 46, 69, 77, 81),
    "Gentle": (11, 14, 20, 21, 25, 33, 37, 41, 47, 49, 50, 61, 67, 70, 71, 72),
    "Water": (8, 16, 23, 24, 60, 78, 79),
}
_FAMILY = {ride_type: name for name, types in _FAMILY_TYPES.items() for ride_type in types}
_SHORT_WORDS = (("Roller Coaster", "RC"), ("Wild Mouse", "Mouse"))

WITH_SANDBOX = "with_sandbox"
_AGGREGATE_SCOPES = (ALL, WITH_SANDBOX)


class ReservedParkIdError(duckdb.Error):
    """A park ID equals an aggregate scope key.

    A ``duckdb.Error`` so the server's rebuild handler shows it in the banner and keeps the last
    good build.
    """


_MONTH_COLUMNS = (
    "operating_profit", "operating_revenue", "ride_revenue", "food_drink_revenue",
    "merchandise_revenue", "entrance_revenue", "ride_running_costs", "staff_wages", "stock_costs",
    "marketing_costs", "research_costs", "capital_spending", "operating_costs", "guest_visits",
    "operating_days",
)  # fmt: skip
_MONTHS = f"""
select company_date, {", ".join(f"sum({column})" for column in _MONTH_COLUMNS)}
from marts.obt_park_month
where list_contains($parks, park_id) and company_date is not null
group by company_date order by company_date
"""
_KEPT_DAY = """
with statement_month as (
    select distinct company_date as month_start from marts.obt_park_month
    where list_contains($parks, park_id) and company_date is not null
),
kept_day as (
    select park_day.*
    from marts.fct_park_day as park_day
    inner join statement_month
        on statement_month.month_start = date_trunc('month', park_day.company_date)::date
    where park_day.is_kept_operating_day and list_contains($parks, park_day.park_id)
),
ride_day as (
    select
        ride.park_id, ride.ride_name, ride_fact.company_date, ride_fact.ride_type,
        ride_fact.is_open_day, ride_fact.customers_increase, ride_fact.profit_usd,
        ride_fact.ride_price_listed_usd, ride_fact.ride_age_months, ride_fact.guest_rating_pct,
        ride_fact.availability_from_downtime_pct, ride_fact.longest_queue_seen_minutes,
        date_trunc('month', ride_fact.company_date)::date as month_start
    from marts.fct_ride_day as ride_fact
    inner join marts.dim_ride as ride on ride.ride_key = ride_fact.ride_key
    inner join kept_day
        on kept_day.park_id = ride_fact.park_id and kept_day.company_date = ride_fact.company_date
    where ride_fact.classification = 'ride'
),
ridden as (
    select park_id, ride_name from ride_day
    group by park_id, ride_name having sum(customers_increase) > 0
),
shown_ride_day as (
    select ride_day.* from ride_day semi join ridden using (park_id, ride_name)
)
"""
_MONTH_TOTALS = """,
last_reading as (
    select
        park_id, date_trunc('month', company_date)::date as month_start,
        last(cash_usd order by company_date) as cash,
        last(guests_in_park order by company_date) as guests
    from kept_day group by all
)
select month_start, sum(cash) as cash, sum(guests) as guests
from last_reading group by month_start
"""
_RIDE_MONTHS = """
select
    park_id, ride_name, month_start, count(*) as days,
    count(*) filter (where is_open_day) as open_days,
    coalesce(sum(customers_increase), 0) as riders, coalesce(sum(profit_usd), 0) as profit,
    last(ride_price_listed_usd order by company_date) as price,
    mode(ride_price_listed_usd) filter (where is_open_day) as price_mode,
    last(ride_age_months order by company_date) as age,
    last(guest_rating_pct order by company_date) as rating,
    avg(availability_from_downtime_pct) filter (where is_open_day) as availability,
    max(longest_queue_seen_minutes) as queue,
    last(ride_type order by company_date) as ride_type
from shown_ride_day group by all order by ride_name, park_id, month_start
"""
_RESETS = """,
aged as (
    select
        park_id, ride_name, company_date, ride_age_months,
        lag(ride_age_months) over (
            partition by park_id, ride_name order by company_date
        ) as previous_age
    from shown_ride_day
)
select park_id, ride_name, company_date from aged
where ride_age_months < previous_age order by company_date
"""
_RIDE_DAYS = """
select
    park_id, ride_name, company_date, sum(customers_increase) as riders,
    sum(profit_usd) as profit, max(ride_price_listed_usd) as price, bool_or(is_open_day) as open
from shown_ride_day group by all order by ride_name, park_id, company_date
"""
_DAYS = """,
park_month as (
    select
        park_id, company_date as month_start, marketing_costs <> 0 as paid,
        row_number() over (partition by park_id order by company_date) as month_number
    from marts.obt_park_month where list_contains($parks, park_id)
),
since_marketing as (
    select
        park_id, month_start,
        month_number - max(case when paid then month_number end) over (
            partition by park_id order by month_start
            rows between unbounded preceding and current row
        ) as months_since
    from park_month
)
select
    kept_day.company_date, kept_day.park_id, kept_day.admissions_increase, kept_day.weather,
    kept_day.temperature_c, kept_day.guests_in_park, since_marketing.months_since
from kept_day
left join since_marketing
    on since_marketing.park_id = kept_day.park_id
    and since_marketing.month_start = date_trunc('month', kept_day.company_date)::date
order by kept_day.company_date, kept_day.park_id
"""
_BY_AGE = """
select
    ride_age_months as age, count(*) as days,
    avg(availability_from_downtime_pct) as availability, avg(customers_increase) as riders
from shown_ride_day where is_open_day group by ride_age_months order by ride_age_months
"""

Row = tuple[object, ...]
Record = dict[str, object]
_RIDE_FIELDS = ("n", "open", "riders", "profit", "price", "pmode", "age", "rating", "avail", "q")
_DAY_FIELDS = ("date", "park", "arr", "w", "temp", "guests", "since")


def _number(value: object, digits: int | None = None) -> float | None:
    """A number from DuckDB as a float, rounded when ``digits`` is given; zero never prints -0."""
    if value is None:
        return None
    number = float(cast(Decimal | float | int, value)) + 0.0
    return number if digits is None else round(number, digits) + 0.0


def _cost(value: object) -> float | None:
    """A cost from the marts (a negative amount) as a positive number of dollars."""
    amount = _number(value)
    return None if amount is None else -amount + 0.0


def _iso(day: object) -> str:
    return cast(date, day).isoformat()


def _short_names(names: list[str]) -> dict[str, str]:
    """Abbreviate common words, and drop the number of a ride whose base name is unique."""

    def base(name: str) -> str:
        head, _, number = name.rpartition(" ")
        return head if head and number.isdigit() else name

    counts: dict[str, int] = defaultdict(int)
    for name in names:
        counts[base(name)] += 1
    shorts = {}
    for name in names:
        short = base(name) if counts[base(name)] == 1 else name
        for words, abbreviation in _SHORT_WORDS:
            short = short.replace(words, abbreviation)
        shorts[name] = short
    return shorts


class _Scope:
    """The queries of one scope: the parks ``park_ids``, summed together."""

    def __init__(
        self, connection: duckdb.DuckDBPyConnection, names: dict[str, str], park_ids: list[str]
    ) -> None:
        self.connection = connection
        self.park_names = names
        self.park_ids = park_ids
        self.several = len(park_ids) > 1

    def rows(self, sql: str, *, shared: bool = True) -> list[Row]:
        """Run ``sql`` over this scope's parks, after the shared CTEs when ``shared``."""
        query = _KEPT_DAY + sql if shared else sql
        return self.connection.execute(query, {"parks": self.park_ids}).fetchall()

    def build(self) -> Record:
        """Every page's data for this scope."""
        months = self.months()
        rides = self.rides(months)
        days = self.days()
        dates = sorted(set(cast(list[str], days["date"])))
        return {
            "parks": len(self.park_ids),
            "park_ids": self.park_ids,
            "months": months,
            "rides": [ride for ride, _ in rides],
            "dates": dates,
            "days": days,
            "ride_days": self.ride_days([key for _, key in rides], dates),
            "by_age": self.by_age(),
        }

    def months(self) -> list[Record]:
        """One monthly statement per month of the scope, with its last cash and guest readings."""
        totals = {row[0]: row[1:] for row in self.rows(_MONTH_TOTALS)}
        out = []
        for row in self.rows(_MONTHS, shared=False):
            month = cast(date, row[0])
            cash, guests = totals.get(month, (None, None))
            income = ("profit", "rev", "rides", "food", "merch", "entrance")
            costs = ("running", "staff", "stock", "mkt", "research", "capital", "costs")
            record: Record = {"y": month.year, "m": month.month}
            record.update(
                {key: _number(value) for key, value in zip(income, row[1:7], strict=True)}
            )
            record.update({key: _cost(value) for key, value in zip(costs, row[7:14], strict=True)})
            record.update(
                {"visits": row[14], "opdays": row[15], "cash": _number(cash), "guests": guests}
            )
            out.append(record)
        return out

    def _label(self, park: object, name: str) -> str:
        return f"{name} ({self.park_names[str(park)]})" if self.several else name

    def rides(self, months: list[Record]) -> list[tuple[Record, tuple[object, object]]]:
        """Each shown ride with its monthly arrays, and its (park, ride name) key."""
        index = {(month["y"], month["m"]): i for i, month in enumerate(months)}
        resets: dict[tuple[object, object], list[str]] = defaultdict(list)
        for park, name, day in self.rows(_RESETS):
            resets[(park, name)].append(_iso(day))
        arrays: dict[tuple[object, object], dict[str, list[object]]] = {}
        types: dict[tuple[object, object], object] = {}
        for park, name, month, *values, ride_type in self.rows(_RIDE_MONTHS):
            key = (park, name)
            series = arrays.setdefault(key, {field: [None] * len(months) for field in _RIDE_FIELDS})
            types[key] = ride_type
            days, opened, riders, profit, price, mode, age, rating, availability, queue = values
            converted = (
                days, opened, int(cast(int, riders)), _number(profit, 1), _number(price),
                _number(mode), age, rating, _number(availability, 1), queue,
            )  # fmt: skip
            i = index[(cast(date, month).year, cast(date, month).month)]
            for field, value in zip(_RIDE_FIELDS, converted, strict=True):
                series[field][i] = value
        shorts = _short_names([str(name) for _, name in arrays])
        return [
            (
                {
                    "name": self._label(park, str(name)),
                    "short": self._label(park, shorts[str(name)]),
                    "fam": _FAMILY.get(cast(int, types[(park, name)]), "Other"),
                    "reset": resets[(park, name)],
                    **series,
                },
                (park, name),
            )
            for (park, name), series in arrays.items()
        ]

    def days(self) -> Record:
        """One entry per kept park day, as parallel arrays."""
        columns: dict[str, list[object]] = {field: [] for field in _DAY_FIELDS}
        for row in self.rows(_DAYS):
            for field, value in zip(_DAY_FIELDS, (_iso(row[0]), *row[1:]), strict=True):
                columns[field].append(value)
        return dict(columns)

    def ride_days(self, keys: list[tuple[object, object]], dates: list[str]) -> list[Record]:
        """Each ride's daily readings from its first day, with null on a day it has no reading."""
        index = {day: i for i, day in enumerate(dates)}
        series: dict[tuple[object, object], dict[str, list[object]]] = {}
        first: dict[tuple[object, object], int] = {}
        for park, name, day, riders, profit, price, is_open in self.rows(_RIDE_DAYS):
            key = (park, name)
            at = index[_iso(day)]
            entry = series.setdefault(key, {"riders": [], "profit": [], "price": [], "open": []})
            start = first.setdefault(key, at)
            for values in entry.values():
                values.extend([None] * (at - start - len(values)))
            entry["riders"].append(None if riders is None else int(cast(int, riders)))
            entry["profit"].append(_number(profit, 1))
            entry["price"].append(_number(price))
            entry["open"].append(1 if is_open else 0)
        return [{"first": first[key], **series[key]} for key in keys]

    def by_age(self) -> list[Record]:
        """Riders per open day and availability by ride age, over every shown ride's open days."""
        return [
            {"age": age, "n": days, "avail": _number(avail, 2), "riders": _number(riders, 2)}
            for age, days, avail, riders in self.rows(_BY_AGE)
        ]


def build(warehouse: Path) -> Record:
    """Read the warehouse copy read-only and return the data of every page.

    The result holds ``parks`` (each registered park's ``id``, ``name`` (the ID when the park has
    no name), ``sandbox`` and ``game_years``) and ``scopes``, each with its ``park_ids``: ``all``
    (the company parks, summed from ``obt_park_month``), ``with_sandbox`` (every park, only when a
    Sandbox park exists) and, when there is more than one park or any Sandbox park, one scope per
    park ID.
    """
    connection = duckdb.connect(str(warehouse), read_only=True)
    try:
        parks = {
            str(park_id): (str(name) if name is not None else str(park_id), bool(sandbox))
            for park_id, name, sandbox in connection.execute(
                "select park_id, park_name, park_number is null as sandbox from marts.dim_park "
                "order by first_company_date, park_id"
            ).fetchall()
        }
        for park in parks:
            if park in _AGGREGATE_SCOPES:
                raise ReservedParkIdError(
                    f"park ID {park!r} is reserved by the dashboard for an aggregate view"
                )
        names = {park: name for park, (name, _) in parks.items()}
        game_years: dict[str, dict[int, Record]] = {park: {} for park in parks}
        for park_id, company_year, game_year, from_month in connection.execute(
            """
            select
                park_id, company_year, statement_year,
                min(month(company_date)) as from_month
            from marts.obt_park_month
            where company_date is not null and statement_year is not null
            group by park_id, company_year, statement_year
            order by park_id, company_year
            """
        ).fetchall():
            game_years[str(park_id)][int(company_year)] = {
                "game_year": int(game_year),
                "from_month": int(from_month),
            }
        any_sandbox = any(sandbox for _, sandbox in parks.values())
        groups = {ALL: [park for park, (_, sandbox) in parks.items() if not sandbox]}
        if any_sandbox:
            groups[WITH_SANDBOX] = list(parks)
        if len(parks) > 1 or any_sandbox:
            groups.update({park: [park] for park in parks})
        scopes = {scope: _Scope(connection, names, ids).build() for scope, ids in groups.items()}
    finally:
        connection.close()
    return {
        "parks": [
            {"id": park, "name": name, "sandbox": sandbox, "game_years": game_years[park]}
            for park, (name, sandbox) in parks.items()
        ],
        "scopes": scopes,
    }

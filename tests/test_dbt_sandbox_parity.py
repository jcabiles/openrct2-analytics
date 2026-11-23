"""The dashboard builder's company sums match the real company mart, Sandbox hidden and included."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

from openrct2_analytics.dashboard import data as dashboard_data
from tests import test_dbt_environments as environments
from tests.two_park_support import (
    FIRST_PARK,
    SANDBOX_ONE,
    SANDBOX_TWO,
    TwoParks,
    build_company_and_two_sandbox_parks,
    query,
)

project = environments.project  # the fixture, re-exported so pytest finds it here

# data.py's month record keys, each with its obt_company_month column and whether it is a cost
# (a negative amount in the marts, shown positive).
MONTH_FIELDS = (
    ("profit", "operating_profit", False),
    ("rev", "operating_revenue", False),
    ("rides", "ride_revenue", False),
    ("food", "food_drink_revenue", False),
    ("merch", "merchandise_revenue", False),
    ("entrance", "entrance_revenue", False),
    ("running", "ride_running_costs", True),
    ("staff", "staff_wages", True),
    ("stock", "stock_costs", True),
    ("mkt", "marketing_costs", True),
    ("research", "research_costs", True),
    ("capital", "capital_spending", True),
    ("costs", "operating_costs", True),
    ("visits", "guest_visits", False),
    ("opdays", "operating_days", False),
)


def month_rows(
    two: TwoParks, table: str, where: str = "true"
) -> dict[tuple[int, int], dict[str, float]]:
    """Each company month's fields of `table`, as data.py shows them, by (year, month)."""
    columns = ", ".join(column for _, column, _ in MONTH_FIELDS)
    rows = query(
        two.warehouse,
        f"select company_date, {columns} from marts.{table} where {where} order by company_date",
    )
    return {
        (cast(date, row[0]).year, cast(date, row[0]).month): {
            key: -float(cast(Decimal, value)) + 0.0 if is_cost else float(cast(Decimal, value))
            for (key, _, is_cost), value in zip(MONTH_FIELDS, row[1:], strict=True)
        }
        for row in rows
    }


def test_the_builder_matches_the_company_mart_with_sandbox_hidden_and_included(
    project: Path, tmp_path: Path
) -> None:
    three = build_company_and_two_sandbox_parks(
        project, tmp_path, "+obt_park_month +obt_company_month +dim_park +fct_ride_day +dim_ride"
    )

    assert query(
        three.warehouse,
        "select count(*) from (select company_date from marts.obt_park_month "
        "group by company_date having count(*) >= 2)",
    ) == [(2,)], "two company dates must hold two or more park rows"
    expected_company = month_rows(three, "obt_company_month")
    assert len(expected_company) == 3
    expected_first = month_rows(three, "obt_park_month", f"park_id = '{FIRST_PARK}'")
    assert len(expected_first) == 3
    assert expected_first != expected_company

    scopes = dashboard_data.build(three.warehouse)["scopes"]
    assert isinstance(scopes, dict)

    for scope, expected in (
        (dashboard_data.WITH_SANDBOX, expected_company),
        (dashboard_data.ALL, expected_first),
    ):
        shown = {(month["y"], month["m"]): month for month in scopes[scope]["months"]}
        assert set(shown) == set(expected), f"{scope}: the months differ"
        for month, fields in expected.items():
            for key, value in fields.items():
                assert shown[month][key] == value, f"{scope} {month} {key}"
    assert scopes[dashboard_data.ALL]["park_ids"] == [FIRST_PARK]
    assert sorted(scopes[dashboard_data.WITH_SANDBOX]["park_ids"]) == sorted(
        [FIRST_PARK, SANDBOX_ONE, SANDBOX_TWO]
    )

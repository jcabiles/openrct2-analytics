"""A second park registered as company builds and closes its year in dbt (spec R14).

Both parks are planted from game year 1, as `make register-parks` requires of a later company
park. The second park's start year is what the real rule gives over the planted files while the
first park's year 2000 is unfinished.
"""

from __future__ import annotations

from pathlib import Path

from openrct2_analytics.ingest.start_year import next_start_year
from tests import test_dbt_environments as environments
from tests.test_dbt_two_parks import CLOSE, close_failures, close_run
from tests.two_park_support import (
    FIRST_PARK,
    REGISTRY_FILE,
    SECOND_PARK,
    plant_two_parks,
    query,
    second_park_registry,
)

project = environments.project  # the fixture, re-exported so pytest finds it here

FIRST_REGISTRY_FILE = "registry/v1/park_registry_2026-10-21_01.csv"
# Monthly statements owed per year, March to October: `8 - first_reportable_month` and
# `generate_series(0,7)` in models/intermediate/int_park_years__year_close.sql.
STATEMENTS_PER_YEAR = 8
FIRST_PARK_ROW = (
    "park_id,company_start_year,game_year_origin,data_set,note,delivered_on\n"
    f"{FIRST_PARK},2000,1,company,,2026-10-21\n"
)
EXPECTED_START_YEAR = 2001
RUN_ID = "second-company-park"


def test_second_park_registered_as_company(project: Path, tmp_path: Path) -> None:
    data = tmp_path / "company-two-park-sample"
    plant_two_parks(data, first_game_year=1)
    (data / FIRST_REGISTRY_FILE).write_text(FIRST_PARK_ROW)
    raw = tmp_path / "raw"
    raw.mkdir()

    start_year = next_start_year(data / "registry" / "v1", data, raw)

    assert start_year == EXPECTED_START_YEAR
    (data / REGISTRY_FILE).write_text(
        second_park_registry(EXPECTED_START_YEAR, game_year_origin=1, data_set="company")
    )

    code, _, warehouse, output = close_run(
        project, "company", data, "run", "--select", f"+{CLOSE}", run_id=RUN_ID
    )
    assert code == 0, output
    assert query(
        warehouse,
        "select park_id, count(*) from marts.fct_park_month group by park_id order by park_id",
    ) == [(FIRST_PARK, 3), (SECOND_PARK, 3)]
    assert query(
        warehouse,
        "select park_id, company_year, statements_kept, statements_expected, close_status "
        "from intermediate.int_park_years__year_close order by park_id, company_year",
    ) == [
        (FIRST_PARK, 2000, 3, STATEMENTS_PER_YEAR, "open"),
        (FIRST_PARK, 2001, 0, STATEMENTS_PER_YEAR, "open"),
        (SECOND_PARK, 2001, 3, STATEMENTS_PER_YEAR, "open"),
    ]

    code, status, warehouse, output = close_run(
        project, "company", data, "test", "--select", CLOSE, run_id=RUN_ID
    )
    assert (code, status) == (0, "PASS"), output
    assert close_failures(warehouse) == []
    assert query(
        warehouse,
        "select park_id, company_start_year, game_year_origin, data_set "
        "from intermediate.int_park_registry__current order by park_id",
    ) == [(FIRST_PARK, 2000, 1, "company"), (SECOND_PARK, 2001, 1, "company")]

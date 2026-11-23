"""The company-year model maps every landed park-year; one that cannot map fails the build.

Real dbt runs in a temporary project copy over the committed sample and a copy of its Parquet.
"""

from __future__ import annotations

import contextlib
import re
import shutil
from pathlib import Path

import duckdb
import pytest

from tests import test_dbt_environments as environments
from tests.test_dbt_environments import SAMPLE, dbt

project = environments.project  # the fixture, re-exported so pytest finds it here

MODEL = "int_park_years__company_year"
SINGULAR_TEST = "assert_every_park_year_has_a_company_year"
SAMPLE_START_YEAR = 2000  # the committed sample feed's start year for its one park
PLANTED_EVENT_ID = "planted-1"


def build_company_year(project: Path, parquet_root: Path) -> tuple[str, int]:
    """Build the model and its ancestors on the dev target; return dbt's output and exit code."""
    (project / "warehouse" / "dev").mkdir(parents=True, exist_ok=True)
    done = dbt(
        project,
        "build",
        "--target",
        "dev",
        "--select",
        f"+{MODEL}",
        # Eager selection would also run staging tests whose other parents are not built.
        "--indirect-selection",
        "cautious",
        "--vars",
        f"{{parquet_root: {parquet_root}, registry_root: {SAMPLE / 'registry'}}}",
        registry=False,
        parquet=False,
    )
    return done.stdout, done.returncode


def plant_row(parquet_root: Path, **overrides: str | int) -> None:
    """Add one finance_month row, a copy of the first with `overrides`, to a Parquet copy."""
    path = parquet_root / "v1" / "finance_month.parquet"
    replaced = ", ".join(f"{value!r} as {column}" for column, value in overrides.items())
    planted = parquet_root / "planted.parquet"
    with contextlib.closing(duckdb.connect()) as db:
        db.execute(
            f"copy (select * from read_parquet('{path}') "
            f"union all by name select * replace ({replaced}, "
            f"'{PLANTED_EVENT_ID}' as event_id) "
            f"from (select * from read_parquet('{path}') limit 1)) "
            f"to '{planted}' (format parquet)"
        )
    planted.replace(path)


def test_sample_company_year_maps_every_park_year_to_the_start_year_plus_the_offset(
    project: Path,
) -> None:
    output, code = build_company_year(project, SAMPLE)

    assert code == 0, output
    with contextlib.closing(
        duckdb.connect(str(project / "warehouse" / "dev" / "dev.duckdb"), read_only=True)
    ) as db:
        rows = db.execute(
            "select park_id, game_year, mapping_status, company_year, game_year_origin "
            f"from intermediate.{MODEL} order by park_id, game_year"
        ).fetchall()
        landed = db.execute(
            "select count(*) from (select distinct park_id, game_year from staging.stg_envelope)"
        ).fetchone()
        earliest = db.execute("select min(game_year) from staging.stg_envelope").fetchone()
    assert landed is not None
    assert earliest is not None
    assert len(rows) == landed[0] > 0
    assert len({(row[0], row[1]) for row in rows}) == len(rows)
    for _, game_year, status, company_year, origin in rows:
        assert status == "mapped"
        assert origin == earliest[0]
        assert company_year == SAMPLE_START_YEAR + (game_year - earliest[0])


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"park_id": "unregistered-park"}, id="unregistered_park"),
        pytest.param({"game_year": 8}, id="game_year_before_origin"),
        pytest.param({"game_month": 8}, id="game_month_8"),
    ],
)
def test_company_year_unmapped_park_year_fails_the_build_through_the_singular_test(
    project: Path, tmp_path: Path, overrides: dict[str, str | int]
) -> None:
    parquet_root = tmp_path / "sample"
    shutil.copytree(SAMPLE, parquet_root)
    plant_row(parquet_root, **overrides)

    output, code = build_company_year(project, parquet_root)

    assert code != 0, output
    found = re.search(rf"of \d+ (PASS|WARN|FAIL)\b[^\n]*?\b{SINGULAR_TEST}", output)
    assert found, output
    assert found.group(1) == "FAIL"

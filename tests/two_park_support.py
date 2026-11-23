"""A two-park copy of the one-park sample, built in a temporary folder for the dbt pytests.

The second park is a relabelled copy of the first (D12 of the portfolio spec): its game year 9 is
company year 2001, the first park's is 2000. The committed sample is never written.
"""

from __future__ import annotations

import contextlib
import re
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

import duckdb

from tests.test_dbt_environments import SAMPLE, dbt


def sample_park_and_sessions() -> tuple[str, tuple[str, ...]]:
    """Read the sample park and its session IDs in game-time order."""
    with contextlib.closing(duckdb.connect()) as connection:
        relation = connection.read_parquet((SAMPLE / "v1" / "session_start.parquet").as_posix())
        rows = relation.order("game_ticks_elapsed").select("park_id, session_id").fetchall()
    return rows[0][0], tuple(row[1] for row in rows)


FIRST_PARK = sample_park_and_sessions()[0]
# Real park IDs are "k" + epoch milliseconds; this one must sort after any real ID, so a rebuilt
# sample never reorders the two parks (rows are read in park_id order).
SECOND_PARK = "k9999999999999-zzzzzz"
SUFFIX = "-b"
SUFFIXED = ("session_id", "event_id", "save_id", "loaded_save_id", "loaded_save_session_id")
REGISTRY_FILE = "registry/v1/park_registry_2026-10-11_01.csv"
SECOND_COMPANY_START_YEAR = 2001
SAMPLE_GAME_YEAR = 9
# action_game_year stays: the models only pass it through, and no year mapping reads it.
YEAR_COLUMNS = ("game_year", "statement_year")
REHEARSAL_NOTE = "Rehearsal copy of the first park; not company data."


def second_park_registry(
    company_start_year: int,
    game_year_origin: int = SAMPLE_GAME_YEAR,
    data_set: str = "rehearsal",
    *,
    park_id: str = SECOND_PARK,
    note: str | None = None,
) -> str:
    """A planted park's registry delivery; a rehearsal row carries a note, a company row none.

    `note` replaces that default (the Sandbox parks carry the practice note).
    """
    if note is None:
        note = REHEARSAL_NOTE if data_set == "rehearsal" else ""
    return (
        "park_id,company_start_year,game_year_origin,data_set,note,delivered_on\n"
        f"{park_id},{company_start_year},{game_year_origin},{data_set},{note},2026-10-11\n"
    )


class TwoParks(NamedTuple):
    project: Path
    data: Path
    warehouse: Path


def plant_two_parks(
    destination: Path,
    first_game_year: int = SAMPLE_GAME_YEAR,
    extra_parks: tuple[tuple[str, str], ...] = ((SECOND_PARK, SUFFIX),),
) -> None:
    """Copy the sample to `destination` and append each extra park's relabelled rows.

    No registry row is written for an extra park. `first_game_year` moves every park's game
    years (the sample's year 9) to that year, so 1 plants the parks from the game's first year.
    `extra_parks` pairs each extra park's ID with the suffix that keeps its event IDs unique.
    """
    shutil.copytree(SAMPLE, destination)
    shift = SAMPLE_GAME_YEAR - first_game_year
    for path in sorted((destination / "v1").glob("*.parquet")):
        staged = path.with_name("staged.parquet")
        with contextlib.closing(duckdb.connect()) as db:
            db.execute(f"create view src as select * from read_parquet('{path}')")
            columns = [row[0] for row in db.execute("describe src").fetchall()]
            copies = "".join(
                " union all select * replace ("
                + ", ".join(
                    [f"'{park}' as park_id"]
                    + [f"{name} || '{suffix}' as {name}" for name in columns if name in SUFFIXED]
                )
                + ") from shifted"
                for park, suffix in extra_parks
            )
            shifted = [f"{name} - {shift} as {name}" for name in columns if name in YEAR_COLUMNS]
            db.execute(
                f"create view shifted as select * replace ({', '.join(shifted)}) from src"
                if shifted
                else "create view shifted as select * from src"
            )
            db.execute(f"copy (select * from shifted{copies}) to '{staged}' (format parquet)")
        staged.replace(path)


def copy_with_second_park(
    destination: Path,
    second_company_start_year: int = SECOND_COMPANY_START_YEAR,
    second_game_year_origin: int = SAMPLE_GAME_YEAR,
    data_set: str = "rehearsal",
) -> None:
    """Copy the sample to `destination`, append the second park's rows and register it.

    The second park's game year 9 is company year `second_company_start_year`; pass 2000 to put
    both parks in one company year. `second_game_year_origin` and `data_set` default to the
    rehearsal values.
    """
    plant_two_parks(destination)
    (destination / REGISTRY_FILE).write_text(
        second_park_registry(second_company_start_year, second_game_year_origin, data_set)
    )


def run_dbt(two: TwoParks, *args: str) -> subprocess.CompletedProcess[str]:
    """Run dbt on the `dev` target over the copy, so a failing error-severity test fails."""
    variables = f"{{parquet_root: {two.data}, registry_root: {two.data / 'registry'}}}"
    return dbt(
        two.project,
        *args,
        "--target",
        "dev",
        "--no-partial-parse",
        "--vars",
        variables,
        parquet=False,
        registry=False,
    )


def query(warehouse: Path, sql: str) -> list[tuple[object, ...]]:
    with contextlib.closing(duckdb.connect(str(warehouse), read_only=True)) as db:
        return db.execute(sql).fetchall()


def build_two_parks(
    project: Path,
    tmp_path: Path,
    select: str,
    second_company_start_year: int = SECOND_COMPANY_START_YEAR,
) -> TwoParks:
    """Copy the sample with two parks, `dbt run` the `select`ed models on `dev`, check the build."""
    data = tmp_path / "two-park-sample"
    copy_with_second_park(data, second_company_start_year)
    (project / "warehouse" / "dev").mkdir(parents=True)
    two = TwoParks(project, data, project / "warehouse" / "dev" / "dev.duckdb")
    built = run_dbt(two, "run", "--select", select)
    assert built.returncode == 0, built.stdout
    kept = query(
        two.warehouse,
        "select park_id, count(*) from marts.fct_park_month group by park_id order by park_id",
    )
    assert kept == [(FIRST_PARK, 3), (SECOND_PARK, 3)]
    return two


def run_test(two: TwoParks, test: str) -> tuple[int, str]:
    """Run only `test`; return dbt's exit code and the PASS, WARN or FAIL it printed."""
    done = run_dbt(two, "test", "--select", test)
    found = re.search(rf"of \d+ (PASS|WARN|FAIL)\b[^\n]*?\b{test}\b", done.stdout)
    assert found, done.stdout
    return done.returncode, found.group(1)


PRACTICE_NOTE = "Throwaway practice park; not company data."
SANDBOX_ONE = "k9999999999998-sandbox1"
SANDBOX_TWO = SECOND_PARK
# Each park's money columns are scaled by its factor, so a sum (6x), a maximum (3x) and the
# company park's own figure (1x) differ in every amount the dashboard builder reads.
AMOUNT_FACTORS = {FIRST_PARK: 1, SANDBOX_ONE: 2, SANDBOX_TWO: 3}
SCALED_TENTHS = (
    "ride_construction_tenths",
    "ride_runningcosts_tenths",
    "park_entrance_tickets_tenths",
    "park_ride_tickets_tenths",
    "shop_sales_tenths",
    "shop_stock_tenths",
    "food_drink_sales_tenths",
    "food_drink_stock_tenths",
    "wages_tenths",
)
# The sample books no land, landscaping, marketing or research spending; these give each a
# nonzero amount (times the park's factor) so those fields are proven too.
PLANTED_TENTHS = {
    "land_purchase_tenths": -5000,
    "landscaping_tenths": -300,
    "marketing_tenths": -1000,
    "research_tenths": -400,
}
LAST_STATEMENT_MONTH = 2


def plant_company_and_two_sandbox_parks(destination: Path) -> None:
    """Plant company park p1 (the sample park) and Sandbox parks s1 and s2, all from year 2000.

    All three share the company calendar, so their months overlap. Each park's money amounts are
    scaled by its factor, and only p1 closes the last month (the Sandbox parks lose that
    statement). p1 is registered by the sample's own row; s1 and s2 by rows with the practice note.
    """
    plant_two_parks(
        destination,
        extra_parks=((SANDBOX_ONE, "-s1"), (SANDBOX_TWO, SUFFIX)),
    )
    for number, park in enumerate((SANDBOX_ONE, SANDBOX_TWO), start=1):
        rows = second_park_registry(
            2000, SAMPLE_GAME_YEAR, "company", park_id=park, note=PRACTICE_NOTE
        )
        (destination / f"registry/v1/park_registry_2026-10-11_0{number}.csv").write_text(rows)
    path = destination / "v1" / "finance_month.parquet"
    staged = path.with_name("staged.parquet")
    factor = "case " + " ".join(f"when park_id = '{p}' then {f}" for p, f in AMOUNT_FACTORS.items())
    scaled = [f"{name} * ({factor} end) as {name}" for name in SCALED_TENTHS]
    scaled += [f"{value} * ({factor} end) as {name}" for name, value in PLANTED_TENTHS.items()]
    with contextlib.closing(duckdb.connect()) as db:
        db.execute(
            f"copy (select * replace ({', '.join(scaled)}) from read_parquet('{path}') "
            f"where park_id = '{FIRST_PARK}' or statement_month < {LAST_STATEMENT_MONTH}) "
            f"to '{staged}' (format parquet)"
        )
    staged.replace(path)


def build_company_and_two_sandbox_parks(project: Path, tmp_path: Path, select: str) -> TwoParks:
    """Plant the three parks, `dbt run` the `select`ed models on `dev`, check the build."""
    data = tmp_path / "three-park-sample"
    plant_company_and_two_sandbox_parks(data)
    (project / "warehouse" / "dev").mkdir(parents=True)
    three = TwoParks(project, data, project / "warehouse" / "dev" / "dev.duckdb")
    built = run_dbt(three, "run", "--select", select)
    assert built.returncode == 0, built.stdout
    return three

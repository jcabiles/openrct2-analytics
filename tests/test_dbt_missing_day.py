"""A day that was never captured fails real-data builds and only warns on `ci`.

Real dbt runs per target in a temporary project copy. The planted folder is a copy of the committed
sample with one mid-month snapshot row removed; the sample itself is never written.
"""

from __future__ import annotations

import contextlib
import json
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import NamedTuple

import duckdb

from tests import test_dbt_environments as environments
from tests.test_dbt_environments import SAMPLE, dbt
from tests.two_park_support import sample_park_and_sessions

project = environments.project  # the fixture, re-exported so pytest finds it here

NEVER_CAPTURED = "assert_every_day_of_a_closed_month_was_captured"
NOT_KEPT = "assert_every_captured_day_of_a_closed_month_is_kept"
PARK, SESSION_IDS = sample_park_and_sessions()
SESSION_1, SESSION_2, SESSION_3 = SESSION_IDS
RUN_ID = "run1"


class Outcome(NamedTuple):
    code: int
    statuses: dict[str, str]
    warehouse: Path
    output: str


def rewrite(path: Path, query: str) -> None:
    """Replace the Parquet file at `path` with the result of `query`, which selects from `src`."""
    staged = path.with_name("staged.parquet")
    with contextlib.closing(duckdb.connect()) as db:
        db.execute(f"create view src as select * from read_parquet('{path}')")
        db.execute(f"copy ({query}) to '{staged}' (format parquet)")
    staged.replace(path)


def row_count(path: Path) -> int:
    with contextlib.closing(duckdb.connect()) as db:
        found = db.execute(f"select count(*) from read_parquet('{path}')").fetchone()
    assert found is not None
    return int(found[0])


def planted_copy(tmp_path: Path) -> Path:
    """A copy of the sample without the snapshot row of game year 9, month 1, day 20."""
    planted = tmp_path / "planted"
    shutil.copytree(SAMPLE, planted)
    snapshot = planted / "v1" / "park_snapshot.parquet"
    assert row_count(snapshot) == 108
    rewrite(
        snapshot, "select * from src where not (game_year = 9 and game_month = 1 and game_day = 20)"
    )
    assert row_count(snapshot) == 107
    return planted


def setup_target(project: Path, tmp_path: Path, target: str) -> tuple[dict[str, str], Path]:
    """Create what the target needs; return its environment and the file dbt writes."""
    if target == "ci":
        ci_dir = tmp_path / "ci-out"
        ci_dir.mkdir(exist_ok=True)
        return {"OPENRCT2_CI_DIR": str(ci_dir)}, ci_dir / "ci.duckdb"
    if target == "dev":
        (project / "warehouse" / "dev").mkdir(parents=True, exist_ok=True)
        return {}, project / "warehouse" / "dev" / "dev.duckdb"
    candidate = project / "warehouse" / "candidate" / f"run-{RUN_ID}"
    candidate.mkdir(parents=True, exist_ok=True)
    return {"OPENRCT2_PUBLISH_RUN_ID": RUN_ID}, candidate / f"{target}.duckdb"


def dbt_with_roots(
    project: Path,
    target: str,
    env: dict[str, str],
    roots: tuple[str | None, Path],
    *args: str,
) -> subprocess.CompletedProcess[str]:
    """Run dbt with `roots` as (parquet_root or None for unset, registry_root)."""
    parquet_root, registry_root = roots
    variables = [f"registry_root: {registry_root}"]
    if parquet_root is not None:
        variables.append(f"parquet_root: {parquet_root}")
    return dbt(
        project,
        *args,
        "--target",
        target,
        "--no-partial-parse",
        "--vars",
        f"{{{', '.join(variables)}}}",
        env=env,
        parquet=False,
        registry=False,
    )


def run_missing_day(project: Path, tmp_path: Path, target: str, folder: Path) -> Outcome:
    """Build both tests' ancestors on `target`, test the two, and read each PASS, WARN or FAIL."""
    env, warehouse = setup_target(project, tmp_path, target)
    registry = folder / "registry"
    built = dbt_with_roots(
        project,
        target,
        env,
        (str(folder), registry),
        "run",
        "--select",
        f"+{NEVER_CAPTURED}",
        f"+{NOT_KEPT}",
    )
    assert built.returncode == 0, built.stdout
    done = dbt_with_roots(
        project, target, env, (str(folder), registry), "test", "--select", NEVER_CAPTURED, NOT_KEPT
    )
    statuses = {}
    for test in (NEVER_CAPTURED, NOT_KEPT):
        found = re.search(rf"of \d+ (PASS|WARN|FAIL)\b[^\n]*?\b{test}\b", done.stdout)
        assert found, done.stdout
        statuses[test] = found.group(1)
    return Outcome(done.returncode, statuses, warehouse, done.stdout)


def stored_rows(warehouse: Path, test: str, columns: str) -> list[tuple[object, ...]]:
    with contextlib.closing(duckdb.connect(str(warehouse), read_only=True)) as db:
        return db.execute(
            f"select {columns} from dbt_test__audit.{test} order by game_year, game_month, game_day"
        ).fetchall()


def test_planted_day_warns_on_ci_and_names_the_day_and_the_save_to_replay(
    project: Path, tmp_path: Path
) -> None:
    planted = planted_copy(tmp_path)

    outcome = run_missing_day(project, tmp_path, "ci", planted)

    assert outcome.code == 0, outcome.output
    assert outcome.statuses[NEVER_CAPTURED] == "WARN"
    rows = stored_rows(
        outcome.warehouse,
        NEVER_CAPTURED,
        "park_id, game_year, game_month, game_day, "
        "session_id_before, session_id_after, save_to_replay",
    )
    with contextlib.closing(duckdb.connect()) as db:
        loaded = db.execute(
            f"select loaded_save_id from read_parquet('{planted}/v1/session_start.parquet') "
            f"where session_id = '{SESSION_2}'"
        ).fetchone()
    assert loaded is not None
    assert rows == [(PARK, 9, 1, 20, SESSION_2, SESSION_2, loaded[0])]


def test_planted_day_fails_a_dev_build_on_a_folder_other_than_the_sample(
    project: Path, tmp_path: Path
) -> None:
    outcome = run_missing_day(project, tmp_path, "dev", planted_copy(tmp_path))

    assert outcome.code != 0, outcome.output
    assert outcome.statuses[NEVER_CAPTURED] == "FAIL"


def test_planted_day_warns_on_ci_then_fails_rehearsal_in_the_same_project_copy(
    project: Path, tmp_path: Path
) -> None:
    planted = planted_copy(tmp_path)

    on_ci = run_missing_day(project, tmp_path, "ci", planted)
    on_rehearsal = run_missing_day(project, tmp_path, "rehearsal", planted)

    assert on_ci.code == 0, on_ci.output
    assert on_ci.statuses[NEVER_CAPTURED] == "WARN"
    assert on_rehearsal.code != 0, on_rehearsal.output
    assert on_rehearsal.statuses[NEVER_CAPTURED] == "FAIL"


def test_committed_sample_passes_the_capture_test_and_warns_on_its_two_save_boundaries(
    project: Path, tmp_path: Path
) -> None:
    outcome = run_missing_day(project, tmp_path, "ci", SAMPLE)

    assert outcome.code == 0, outcome.output
    assert outcome.statuses == {NEVER_CAPTURED: "PASS", NOT_KEPT: "WARN"}
    rows = stored_rows(
        outcome.warehouse,
        NOT_KEPT,
        "park_id, statement_year, statement_month, game_year, game_month, game_day, company_date, "
        "session_id, reason",
    )
    assert rows == [
        (PARK, 9, 1, 9, 1, 11, date(2000, 4, 11), SESSION_1, "save_boundary"),
        (PARK, 9, 2, 9, 2, 17, date(2000, 5, 17), SESSION_2, "save_boundary"),
    ]


def test_planted_session_without_save_gets_no_cut_reason(project: Path, tmp_path: Path) -> None:
    edited = tmp_path / "edited"
    shutil.copytree(SAMPLE, edited)
    saves = edited / "v1" / "save_written.parquet"
    saves_before = row_count(saves)
    rewrite(saves, f"select * from src where session_id <> '{SESSION_3}'")
    assert row_count(saves) < saves_before
    # Removing the save alone leaves month 2 unclosed; relabelling session 2's statement closes it.
    finance = edited / "v1" / "finance_month.parquet"
    rewrite(
        finance,
        f"select * replace (case when session_id = '{SESSION_2}' then 2 else statement_month end "
        "as statement_month) from src",
    )

    outcome = run_missing_day(project, tmp_path, "ci", edited)

    assert outcome.code == 0, outcome.output
    assert outcome.statuses[NOT_KEPT] == "WARN"
    rows = stored_rows(outcome.warehouse, NOT_KEPT, "session_id, game_month, game_day, reason")
    assert len(rows) == 15
    no_cut = [row for row in rows if row[3] == "no_cut"]
    assert len(no_cut) == 14
    assert {row[0] for row in no_cut} == {SESSION_3}
    assert {row[1] for row in no_cut} == {2}
    assert [row[2] for row in no_cut] == list(range(18, 32))
    assert [row for row in rows if row[3] == "save_boundary"] == [
        (SESSION_2, 2, 17, "save_boundary")
    ]


def shifted(year: str, month: str) -> str:
    """A `replace` clause moving a (year, month) pair seven game months later, rolling over at 8."""
    return f"{year} + ({month} + 7) // 8 as {year}, ({month} + 7) % 8 as {month}"


def test_gap_in_a_second_game_year_is_found_across_the_month_7_rollover(
    project: Path, tmp_path: Path
) -> None:
    carried = tmp_path / "carried"
    shutil.copytree(SAMPLE, carried)
    # Shift the sample's park and ride snapshots and its statements seven game months later: its
    # months 0 to 3 become month 7 of year 9 and months 0 to 2 of year 10, so the statements stay
    # consecutive across the rollover. Month lengths follow the new months: old month 1 (30 days)
    # becomes a 31-day month, so day 30 is copied as day 31, and old month 2 (31 days) becomes a
    # 30-day month, so its day 31 is dropped. The snapshot of year 10, month 0, day 15 is removed.
    rewrite(
        carried / "v1" / "park_snapshot.parquet",
        f"select * replace ({shifted('game_year', 'game_month')}) from "
        "(select * from src where not (game_month = 1 and game_day = 15) "
        "and not (game_month = 2 and game_day = 31) "
        "union all select * replace (31 as game_day, event_id || 'x' as event_id) from src "
        "where game_month = 1 and game_day = 30)",
    )
    rewrite(
        carried / "v1" / "ride_snapshot.parquet",
        f"select * replace ({shifted('game_year', 'game_month')}) from src "
        "where not (game_month = 2 and game_day = 31)",
    )
    rewrite(
        carried / "v1" / "finance_month.parquet",
        f"select * replace ({shifted('game_year', 'game_month')}, "
        f"{shifted('statement_year', 'statement_month')}) from src",
    )

    outcome = run_missing_day(project, tmp_path, "ci", carried)

    assert outcome.code == 0, outcome.output
    assert outcome.statuses[NEVER_CAPTURED] == "WARN"
    rows = stored_rows(
        outcome.warehouse, NEVER_CAPTURED, "park_id, game_year, game_month, game_day"
    )
    assert rows == [(PARK, 10, 0, 15)]


def severity_of(project: Path, tmp_path: Path, target: str, parquet_root: str | None) -> str:
    """Parse on `target` and read the first test's severity from the manifest."""
    env, _ = setup_target(project, tmp_path, target)
    done = dbt_with_roots(project, target, env, (parquet_root, SAMPLE / "registry"), "parse")
    assert done.returncode == 0, done.stdout
    manifest = json.loads((project / "target" / "manifest.json").read_text())
    nodes = [node for key, node in manifest["nodes"].items() if key.endswith(f".{NEVER_CAPTURED}")]
    assert len(nodes) == 1
    return str(nodes[0]["config"]["severity"]).lower()


def test_severity_follows_the_target_and_the_data_folder(project: Path, tmp_path: Path) -> None:
    planted = tmp_path / "planted"
    resolved_sample = str(Path(project).resolve() / "data" / "sample" / "rehearsal")
    cases = [
        ("ci", str(SAMPLE), "warn"),
        ("ci", str(planted), "warn"),
        ("dev", None, "warn"),
        ("dev", "data/sample/rehearsal", "warn"),
        ("dev", "data/sample/rehearsal/", "warn"),
        ("dev", resolved_sample, "warn"),
        ("dev", str(planted), "error"),
        ("rehearsal", str(planted), "error"),
        ("company", str(planted), "error"),
    ]

    found = [
        (target, root, severity_of(project, tmp_path, target, root)) for target, root, _ in cases
    ]

    assert found == cases

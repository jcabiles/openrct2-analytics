"""The dbt targets, the data-root guard and the park registry, with real dbt in a project copy."""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parent.parent
COPIED = ("dbt_project.yml", "profiles.yml", "models", "macros", "tests/dbt")
SAMPLE = ROOT / "data" / "sample" / "rehearsal"
REGISTRY = SAMPLE / "registry"
PUBLISHED = ("rehearsal.duckdb", "company.duckdb")
DBT = "import sys; from dbt.cli.main import cli; cli.main(args=sys.argv[1:], prog_name='dbt')"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A copy of the dbt project under a temporary folder."""
    work = tmp_path / "project"
    for name in COPIED:
        source = ROOT / name
        target = work / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    return work


def dbt(
    project: Path,
    *args: str,
    env: dict[str, str] | None = None,
    parquet: bool = True,
    registry: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run `dbt <args>` in the project copy with the sample as the Parquet and feed folders.

    The folders go in one `--vars`; dbt keeps only the last `--vars`, so a caller passing its own
    must turn both flags off.
    """
    base = {k: v for k, v in os.environ.items() if not k.startswith("OPENRCT2_")}
    command = [sys.executable, "-c", DBT, *args, "--profiles-dir", ".", "--no-use-colors"]
    variables = [f"parquet_root: {SAMPLE}"] * parquet + [f"registry_root: {REGISTRY}"] * registry
    if variables:
        command += ["--vars", f"{{{', '.join(variables)}}}"]
    return subprocess.run(
        command,
        cwd=project,
        env={**base, **(env or {})},
        capture_output=True,
        text=True,
        check=False,
    )


def stand_ins(folder: Path) -> dict[str, bytes]:
    """Write 0444 stand-ins of both published files into folder."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in PUBLISHED:
        path = folder / name
        path.write_bytes(f"stand-in {name}".encode())
        path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    return {name: (folder / name).read_bytes() for name in PUBLISHED}


def test_ci_build_passes_with_the_registry_and_writes_only_its_own_file(
    project: Path, tmp_path: Path
) -> None:
    ci_dir = tmp_path / "ci"
    before = stand_ins(ci_dir)

    done = dbt(project, "build", "--target", "ci", env={"OPENRCT2_CI_DIR": str(ci_dir)})

    assert done.returncode == 0, done.stdout
    assert "park_registry" in done.stdout
    assert sorted(path.name for path in ci_dir.iterdir()) == sorted([*PUBLISHED, "ci.duckdb"])
    assert {name: (ci_dir / name).read_bytes() for name in PUBLISHED} == before


def test_dev_build_writes_only_the_dev_file_under_warehouse(project: Path) -> None:
    warehouse = project / "warehouse"
    stand_ins(warehouse)
    (warehouse / "dev").mkdir()

    done = dbt(
        project,
        "build",
        "--target",
        "dev",
        "--select",
        "stg_park_registry",
        "--indirect-selection",
        "cautious",
    )

    assert done.returncode == 0, done.stdout
    files = sorted(
        str(path.relative_to(warehouse)) for path in warehouse.rglob("*") if path.is_file()
    )
    assert files == sorted([*PUBLISHED, "dev/dev.duckdb"])


@pytest.mark.parametrize("run_id", [None, "../..", "a/b", ""])
def test_rehearsal_build_refuses_an_unsafe_run_id_and_creates_nothing(
    project: Path, tmp_path: Path, run_id: str | None
) -> None:
    env = {} if run_id is None else {"OPENRCT2_PUBLISH_RUN_ID": run_id}
    if run_id is not None:
        # The folder an unguarded path would use exists, so only the guard stops the build.
        (project / "warehouse" / "candidate" / f"run-{run_id}").mkdir(parents=True, exist_ok=True)

    done = dbt(project, "build", "--target", "rehearsal", "--select", "stg_park_registry", env=env)

    assert done.returncode != 0
    assert not list(tmp_path.rglob("*.duckdb"))


def test_company_build_refuses_an_unsafe_run_id(project: Path, tmp_path: Path) -> None:
    (project / "warehouse" / "candidate" / "run-../..").mkdir(parents=True, exist_ok=True)

    done = dbt(
        project,
        "build",
        "--target",
        "company",
        "--select",
        "stg_park_registry",
        env={"OPENRCT2_PUBLISH_RUN_ID": "../.."},
    )

    assert done.returncode != 0
    assert not list(tmp_path.rglob("*.duckdb"))


def test_production_build_without_a_parquet_folder_fails(project: Path) -> None:
    (project / "warehouse" / "candidate" / "run-run1").mkdir(parents=True)

    done = dbt(
        project,
        "build",
        "--target",
        "rehearsal",
        env={"OPENRCT2_PUBLISH_RUN_ID": "run1"},
        parquet=False,
    )

    assert done.returncode != 0
    assert "invalid-parquet-root" in done.stdout


@pytest.mark.parametrize("target", ["rehearsal", "company"])
def test_production_build_without_a_registry_root_fails(project: Path, target: str) -> None:
    (project / "warehouse" / "candidate" / "run-run1").mkdir(parents=True)

    done = dbt(
        project,
        "build",
        "--target",
        target,
        "--select",
        "stg_park_registry",
        env={"OPENRCT2_PUBLISH_RUN_ID": "run1"},
        registry=False,
    )

    assert done.returncode != 0
    assert "invalid-registry-root" in done.stdout


HEADER = "park_id,company_start_year,game_year_origin,data_set,note,delivered_on\n"
FIRST_DELIVERY = HEADER + "p1,2000,9,rehearsal,n1,2026-10-10\n"


# dbt selects a test whose parents are not all selected unless --indirect-selection cautious; the
# history-reading pattern test would otherwise run here without its model.
def build_staged_registry(
    project: Path, tmp_path: Path, second: str
) -> tuple[int, list[tuple[str, str, str | None]]]:
    """Build stg_park_registry over a two-file feed; return the exit code and the staged rows."""
    feed = tmp_path / "feed" / "v1"
    feed.mkdir(parents=True)
    (feed / "park_registry_2026-10-10_01.csv").write_text(FIRST_DELIVERY, encoding="utf-8")
    (feed / "park_registry_2026-10-12_01.csv").write_text(second, encoding="utf-8")
    (project / "warehouse" / "dev").mkdir(parents=True)

    done = dbt(
        project,
        "build",
        "--target",
        "dev",
        "--select",
        "stg_park_registry",
        "--indirect-selection",
        "cautious",
        "--vars",
        f"{{registry_root: {feed.parent}}}",
        registry=False,
        parquet=False,
    )
    if done.returncode != 0:
        return done.returncode, []
    with contextlib.closing(
        duckdb.connect(str(project / "warehouse" / "dev" / "dev.duckdb"), read_only=True)
    ) as db:
        rows = db.execute(
            "select park_id, data_set, note from staging.stg_park_registry order by park_id"
        ).fetchall()
    return done.returncode, rows


def test_registry_later_delivery_with_quoted_text_cells_is_read_unquoted(
    project: Path, tmp_path: Path
) -> None:
    second = HEADER + '"p2",2002,1,"company","x",2026-10-12\n'

    code, rows = build_staged_registry(project, tmp_path, second)

    assert code == 0
    assert rows == [("p1", "rehearsal", "n1"), ("p2", "company", "x")]


def test_registry_later_delivery_without_the_note_column_builds_with_a_null_note(
    project: Path, tmp_path: Path
) -> None:
    second = (
        "park_id,company_start_year,game_year_origin,data_set,delivered_on\n"
        "p2,2002,1,company,2026-10-12\n"
    )

    code, rows = build_staged_registry(project, tmp_path, second)

    assert code == 0
    assert rows == [("p1", "rehearsal", "n1"), ("p2", "company", None)]


def test_registry_root_default_reads_the_feed_in_the_project_on_dev(project: Path) -> None:
    shutil.copytree(REGISTRY, project / "data" / "sample" / "rehearsal" / "registry")
    (project / "warehouse" / "dev").mkdir(parents=True)

    done = dbt(
        project,
        "build",
        "--target",
        "dev",
        "--select",
        "stg_park_registry",
        "--indirect-selection",
        "cautious",
        registry=False,
        parquet=False,
    )

    assert done.returncode == 0, done.stdout
    with contextlib.closing(
        duckdb.connect(str(project / "warehouse" / "dev" / "dev.duckdb"), read_only=True)
    ) as db:
        files = [
            f
            for (f,) in db.execute("select delivery_file from staging.stg_park_registry").fetchall()
        ]
    assert files
    assert all(not Path(f).is_absolute() for f in files)


def test_production_build_with_a_safe_run_id_reaches_the_candidate_path(project: Path) -> None:
    (project / "warehouse" / "candidate" / "run-ok-1").mkdir(parents=True)

    done = dbt(
        project,
        "build",
        "--target",
        "company",
        "--select",
        "stg_park_registry",
        "--indirect-selection",
        "cautious",
        env={"OPENRCT2_PUBLISH_RUN_ID": "ok-1"},
    )

    assert done.returncode == 0, done.stdout
    assert (project / "warehouse" / "candidate" / "run-ok-1" / "company.duckdb").is_file()


DELIVERY_TESTS = (
    "assert_park_registry_current_delivery_date_matches_file_name",
    "assert_park_registry_superseded_delivery_date_matches_file_name",
    "assert_park_registry_delivered_on_in_bounds",
    "assert_park_registry_file_name_matches_pattern",
)


def delivery_row(delivered_on: str, park: str = "p1", data_set: str = "rehearsal") -> str:
    return f"{park},2000,9,{data_set},n,{delivered_on}\n"


def build_deliveries(
    project: Path,
    tmp_path: Path,
    files: dict[str, str],
    *,
    target: str = "dev",
    also: tuple[str, ...] = (),
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    """Build the history model, the four delivery tests and any `also` selectors over a feed.

    Failures are stored so a test's rows can be read back. Returns the dbt result and each
    delivery test's status (PASS, WARN or FAIL) from its output line.
    """
    feed = tmp_path / "feed" / "v1"
    feed.mkdir(parents=True)
    for name, body in files.items():
        (feed / name).write_text(HEADER + body, encoding="utf-8")
    (project / "warehouse" / "dev").mkdir(parents=True)
    (project / "warehouse" / "candidate" / "run-run1").mkdir(parents=True)

    done = dbt(
        project,
        "build",
        "--target",
        target,
        "--select",
        "stg_park_registry",
        "int_park_registry__history",
        *DELIVERY_TESTS,
        *also,
        # Run tests only when all their parent models are selected.
        "--indirect-selection",
        "cautious",
        "--store-failures",
        "--vars",
        f"{{registry_root: {feed.parent}}}",
        env={"OPENRCT2_PUBLISH_RUN_ID": "run1"},
        registry=False,
        parquet=False,
    )
    statuses = {}
    for test in DELIVERY_TESTS:
        found = re.search(rf"of \d+ (PASS|WARN|FAIL)\b[^\n]*?\b{test}\b", done.stdout)
        assert found, done.stdout
        statuses[test] = found.group(1)
    return done, statuses


def stored_failures(project: Path, test: str) -> list[tuple[object, ...]]:
    with contextlib.closing(
        duckdb.connect(str(project / "warehouse" / "dev" / "dev.duckdb"), read_only=True)
    ) as db:
        return db.execute(f"select * from dbt_test__audit.{test}").fetchall()


def test_delivery_current_file_name_date_that_differs_fails_the_build(
    project: Path, tmp_path: Path
) -> None:
    done, statuses = build_deliveries(
        project, tmp_path, {"park_registry_2026-10-10_01.csv": delivery_row("2026-10-11")}
    )

    assert done.returncode != 0
    assert statuses[DELIVERY_TESTS[0]] == "FAIL"


def test_delivery_superseded_file_name_date_that_differs_only_warns(
    project: Path, tmp_path: Path
) -> None:
    done, statuses = build_deliveries(
        project,
        tmp_path,
        {
            "park_registry_2026-10-10_01.csv": delivery_row("2026-10-11"),
            "park_registry_2026-10-12_01.csv": delivery_row("2026-10-12"),
        },
    )

    assert done.returncode == 0, done.stdout
    assert statuses[DELIVERY_TESTS[0]] == "PASS"
    assert statuses[DELIVERY_TESTS[1]] == "WARN"


def test_delivery_newest_file_with_an_earlier_delivered_on_fails_the_build(
    project: Path, tmp_path: Path
) -> None:
    done, statuses = build_deliveries(
        project,
        tmp_path,
        {
            "park_registry_2026-10-10_01.csv": delivery_row("2026-10-10"),
            "park_registry_2026-10-11_01.csv": delivery_row("2026-10-01"),
        },
    )

    assert done.returncode != 0
    assert statuses[DELIVERY_TESTS[0]] == "FAIL"
    failures = stored_failures(project, DELIVERY_TESTS[0])
    assert [Path(str(row[1])).name for row in failures] == ["park_registry_2026-10-11_01.csv"]


@pytest.mark.parametrize("delivered_on", ["2025-12-31", "2999-01-01"])
def test_delivery_date_out_of_bounds_warns(
    project: Path, tmp_path: Path, delivered_on: str
) -> None:
    done, statuses = build_deliveries(
        project, tmp_path, {f"park_registry_{delivered_on}_01.csv": delivery_row(delivered_on)}
    )

    assert done.returncode == 0, done.stdout
    assert statuses[DELIVERY_TESTS[2]] == "WARN"
    assert statuses[DELIVERY_TESTS[0]] == "PASS"


def test_delivery_file_with_a_misnamed_file_warns_and_names_it(
    project: Path, tmp_path: Path
) -> None:
    done, statuses = build_deliveries(
        project,
        tmp_path,
        {
            "park_registry_2026-10-10_01.csv": delivery_row("2026-10-10"),
            "park_registry_2026-10-12_1.csv": delivery_row("2026-10-12", park="p2"),
            "park_registry_2026-10-1005_.csv": delivery_row("2026-10-12", park="p3"),
        },
    )

    assert done.returncode == 0, done.stdout
    assert statuses[DELIVERY_TESTS[3]] == "WARN"
    failures = stored_failures(project, DELIVERY_TESTS[3])
    assert sorted(Path(str(name)).name for (name,) in failures) == [
        "park_registry_2026-10-1005_.csv",
        "park_registry_2026-10-12_1.csv",
    ]


def test_delivery_file_with_sequence_00_warns_as_misnamed(project: Path, tmp_path: Path) -> None:
    done, statuses = build_deliveries(
        project,
        tmp_path,
        {
            "park_registry_2026-10-10_01.csv": delivery_row("2026-10-10"),
            "park_registry_2026-10-12_00.csv": delivery_row("2026-10-12", park="p2"),
        },
    )

    assert done.returncode == 0, done.stdout
    assert statuses[DELIVERY_TESTS[3]] == "WARN"
    failures = stored_failures(project, DELIVERY_TESTS[3])
    assert [Path(str(name)).name for (name,) in failures] == ["park_registry_2026-10-12_00.csv"]


def test_delivery_files_that_match_their_dates_pass_every_rule(
    project: Path, tmp_path: Path
) -> None:
    done, statuses = build_deliveries(
        project,
        tmp_path,
        {
            "park_registry_2026-10-10_01.csv": delivery_row("2026-10-10"),
            "park_registry_2026-10-10_02.csv": delivery_row("2026-10-10"),
        },
    )

    assert done.returncode == 0, done.stdout
    assert set(statuses.values()) == {"PASS"}


# WEAKENED-OK: seeds/park_registry.yml (deleted) and its environment test went with the seed;
# tests/test_dbt_registry_current.py and tests/test_registry_feed.py cover what they checked.
def test_layers_build_into_schemas_named_after_them_with_no_target_prefix(
    project: Path, tmp_path: Path
) -> None:
    done = dbt(project, "build", "--target", "ci", env={"OPENRCT2_CI_DIR": str(tmp_path)})

    assert done.returncode == 0, done.stdout
    with duckdb.connect(str(tmp_path / "ci.duckdb"), read_only=True) as con:
        rows = con.execute(
            "select table_schema, table_name from information_schema.tables"
            " where table_schema not in ('information_schema', 'pg_catalog')"
        ).fetchall()
    # `dbt_test__audit` holds rows stored by tests with `store_failures: true`
    # (tests/dbt/generic/repeat_delivery_payload_differs.sql).
    assert {schema for schema, _ in rows} == {
        "staging",
        "intermediate",
        "marts",
        "dbt_test__audit",
    }
    assert ("staging", "stg_park_registry") in rows
    assert ("intermediate", "int_park_registry__current") in rows
    assert ("marts", "fct_park_month") in rows
    assert all(not schema.startswith("main_") for schema, _ in rows)

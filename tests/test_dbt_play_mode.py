"""The play-mode label feed in the warehouse, with real dbt in a project copy.

A data set may hold no label file yet (company before its first autopilot run; rehearsal), so
`stg_session_play_mode` names its source only when a label file exists; every session without a
label row is `managed`.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import duckdb
import pytest

from tests.test_dbt_environments import COPIED, REGISTRY, ROOT, SAMPLE, dbt

PARK = "k1792587321039-h8a4t4"
SESSIONS = ("s1792587321039-i0ssmf", "s1792587801446-3lzf29", "s1792588287868-xzldcs")
LABEL_HEADER = "session_id,park_id,play_mode,ready_confirmation,data_set,delivered_on\n"
LABEL_FILE = "session_play_mode_2026-11-13_01.csv"
UNIT_TESTS = (
    "stg_session_start_keeps_first_delivery_by_received_file_line",
    "stg_session_start_passes_climate_and_loaded_save_fields_through",
    "stg_session_start_labels_play_mode_and_defaults_to_managed",
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A copy of the dbt project, with its SQL lint settings, under a temporary folder."""
    work = tmp_path / "project"
    for name in (*COPIED, ".sqlfluff"):
        source, target = ROOT / name, work / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    return work


def registry_folder(tmp_path: Path, label_rows: str | None, label_file: str = LABEL_FILE) -> Path:
    """A registry root holding the sample park registry and, unless None, one label file."""
    root = tmp_path / "registry"
    (root / "v1").mkdir(parents=True)
    shutil.copy2(next((REGISTRY / "v1").glob("park_registry_*.csv")), root / "v1")
    if label_rows is not None:
        (root / "v1" / label_file).write_text(LABEL_HEADER + label_rows, encoding="utf-8")
    return root


def ci_env(tmp_path: Path) -> dict[str, str]:
    folder = tmp_path / "ci"
    folder.mkdir(exist_ok=True)
    return {"OPENRCT2_CI_DIR": str(folder)}


def run_dbt(project: Path, tmp_path: Path, registry: Path, *args: str) -> str:
    """Run dbt on the ci target over the sample Parquet and `registry`; return its output."""
    done = dbt(
        project,
        *args,
        "--target",
        "ci",
        "--vars",
        f"{{parquet_root: {SAMPLE}, registry_root: {registry}}}",
        env=ci_env(tmp_path),
        parquet=False,
        registry=False,
    )
    assert done.returncode == 0, done.stdout
    return done.stdout


def rows(tmp_path: Path, query: str) -> list[tuple[object, ...]]:
    with contextlib.closing(
        duckdb.connect(str(tmp_path / "ci" / "ci.duckdb"), read_only=True)
    ) as db:
        return db.execute(query).fetchall()


def play_modes(tmp_path: Path) -> dict[str, str]:
    query = "select session_id, play_mode from staging.stg_session_start"
    return {str(session): str(mode) for session, mode in rows(tmp_path, query)}


def test_duckdb_fails_a_label_read_that_sql_filters_out_on_a_folder_with_no_label_file(
    tmp_path: Path,
) -> None:
    """The failure the guard exists for: a SQL-level switch cannot skip the read, only Jinja can.

    DuckDB binds the read even when a filter keeps every row out, so the guard must choose the
    branch before the SQL runs, from DuckDB's glob() count.
    """
    pattern = f"{tmp_path}/v1/session_play_mode_*.csv"
    (tmp_path / "v1").mkdir()
    read = f"read_csv('{pattern}', header=true, all_varchar=true)"
    with contextlib.closing(duckdb.connect()) as db:
        with pytest.raises(duckdb.IOException, match="No files found"):
            db.execute(
                f"with labels as (select session_id from {read})"
                f" select session_id from labels where (select count(*) from glob('{pattern}')) > 0"
            )
        assert db.execute(f"select count(*) from glob('{pattern}')").fetchall() == [(0,)]


def test_a_build_over_a_registry_folder_with_no_label_file_labels_every_session_managed(
    project: Path, tmp_path: Path
) -> None:
    registry = registry_folder(tmp_path, None)

    run_dbt(project, tmp_path, registry, "build")

    assert play_modes(tmp_path) == dict.fromkeys(SESSIONS, "managed")
    assert rows(tmp_path, "select count(*) from staging.stg_session_play_mode") == [(0,)]
    columns = (
        "select column_name, data_type from information_schema.columns"
        " where table_name = 'stg_session_play_mode' order by ordinal_position"
    )
    assert rows(tmp_path, columns) == [
        ("session_id", "VARCHAR"),
        ("park_id", "VARCHAR"),
        ("play_mode", "VARCHAR"),
        ("ready_confirmation", "VARCHAR"),
        ("data_set", "VARCHAR"),
        ("delivered_on", "DATE"),
        ("delivery_file", "VARCHAR"),
    ]
    run_dbt(project, tmp_path, registry, "docs", "generate")


def test_the_sql_lint_passes_on_the_no_label_file_branch(project: Path, tmp_path: Path) -> None:
    registry = registry_folder(tmp_path, None)
    settings = project / ".sqlfluff"
    settings.write_text(
        settings.read_text(encoding="utf-8")
        + f"\n[sqlfluff:templater:dbt:context]\nregistry_root = {registry}\n",
        encoding="utf-8",
    )
    model = "models/staging/stg_session_play_mode.sql"

    def sqlfluff(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "sqlfluff", *args],
            cwd=project,
            env={
                **{k: v for k, v in os.environ.items() if not k.startswith("OPENRCT2_")},
                **ci_env(tmp_path),
            },
            capture_output=True,
            text=True,
            check=False,
        )

    rendered = sqlfluff("render", model)
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    assert "session_play_mode_*.csv" not in rendered.stdout
    assert "where false" in rendered.stdout
    linted = sqlfluff("lint", model, "models/staging/stg_session_start.sql")
    assert linted.returncode == 0, linted.stdout + linted.stderr


def test_a_label_file_marks_its_session_autopilot_and_leaves_the_rest_managed(
    project: Path, tmp_path: Path
) -> None:
    registry = registry_folder(tmp_path, f"{SESSIONS[1]},{PARK},autopilot,,rehearsal,2026-11-13\n")

    run_dbt(
        project,
        tmp_path,
        registry,
        "build",
        "--select",
        "+stg_session_start",
        "--indirect-selection",
        "cautious",
    )

    assert play_modes(tmp_path) == {
        SESSIONS[0]: "managed",
        SESSIONS[1]: "autopilot",
        SESSIONS[2]: "managed",
    }
    labels = rows(
        tmp_path,
        "select session_id, park_id, play_mode, ready_confirmation, data_set, delivered_on"
        " from staging.stg_session_play_mode",
    )
    assert labels == [(SESSIONS[1], PARK, "autopilot", None, "rehearsal", date(2026, 11, 13))]


@pytest.mark.parametrize(
    "bad_name",
    ["session_play_mode_2026-11-13_00.csv", "session_play_mode_2026-11-13.csv"],
    ids=["sequence_00", "missing_sequence_part"],
)
def test_a_misnamed_label_file_adds_no_rows_and_leaves_its_session_managed(
    project: Path, tmp_path: Path, bad_name: str
) -> None:
    registry = registry_folder(
        tmp_path, f"{SESSIONS[0]},{PARK},autopilot,,rehearsal,2026-11-13\n", bad_name
    )

    run_dbt(
        project,
        tmp_path,
        registry,
        "build",
        "--select",
        "+stg_session_start",
        "--indirect-selection",
        "cautious",
    )

    assert play_modes(tmp_path) == dict.fromkeys(SESSIONS, "managed")
    assert rows(tmp_path, "select count(*) from staging.stg_session_play_mode") == [(0,)]


def test_a_correctly_named_label_file_beside_misnamed_ones_still_marks_its_session(
    project: Path, tmp_path: Path
) -> None:
    registry = registry_folder(tmp_path, f"{SESSIONS[1]},{PARK},autopilot,,rehearsal,2026-11-13\n")
    for name, session in (
        ("session_play_mode_2026-11-13_00.csv", SESSIONS[0]),
        ("session_play_mode_2026-11-13.csv", SESSIONS[2]),
    ):
        (registry / "v1" / name).write_text(
            LABEL_HEADER + f"{session},{PARK},autopilot,,rehearsal,2026-11-13\n", encoding="utf-8"
        )

    run_dbt(
        project,
        tmp_path,
        registry,
        "build",
        "--select",
        "+stg_session_start",
        "--indirect-selection",
        "cautious",
    )

    assert play_modes(tmp_path) == {
        SESSIONS[0]: "managed",
        SESSIONS[1]: "autopilot",
        SESSIONS[2]: "managed",
    }


def test_a_sample_build_runs_the_session_start_unit_tests(project: Path, tmp_path: Path) -> None:
    output = run_dbt(
        project,
        tmp_path,
        REGISTRY,
        "build",
        "--select",
        "+stg_session_start",
        "--indirect-selection",
        "cautious",
    )

    for name in UNIT_TESTS:
        assert f"PASS stg_session_start::{name} " in output
    assert play_modes(tmp_path) == dict.fromkeys(SESSIONS, "managed")

"""Each staging model declares a minimum row count, and the committed sample meets it."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from tests.test_dbt_environments import dbt, project  # noqa: F401  (project is a pytest fixture)

# stg_guest_refused may have zero rows: a short session can see no refusal
# (project owner ruling, 2026-10-14). stg_game_action may have zero rows: a session with no player
# action sends none, and the committed sample holds none.
EXPECTED_MIN_ROWS = {
    "stg_session_start": 1,
    "stg_park_snapshot": 1,
    "stg_finance_month": 1,
    "stg_guest_arrived": 1,
    "stg_guest_boarded": 1,
    "stg_guest_left": 1,
    "stg_guest_refused": 0,
    "stg_guest_snapshot": 1,
    "stg_envelope": 1,
    "stg_park_registry": 1,
    "stg_ride_snapshot": 1,
    "stg_save_written": 1,
    "stg_game_action": 0,
}


def test_staging_models_declare_a_floor_the_sample_meets(project: Path, tmp_path: Path) -> None:  # noqa: F811
    parsed = dbt(project, "parse")
    assert parsed.returncode == 0, parsed.stdout
    nodes = json.loads((project / "target" / "manifest.json").read_text(encoding="utf-8"))["nodes"]
    floors = {
        name: nodes[f"model.openrct2_analytics.{name}"]["meta"]["expected_min_rows"]
        for name in EXPECTED_MIN_ROWS
    }
    assert floors == EXPECTED_MIN_ROWS

    ci_dir = tmp_path / "ci"
    ci_dir.mkdir()
    built = dbt(project, "build", "--target", "ci", env={"OPENRCT2_CI_DIR": str(ci_dir)})
    assert built.returncode == 0, built.stdout
    with duckdb.connect(str(ci_dir / "ci.duckdb"), read_only=True) as con:
        for name in EXPECTED_MIN_ROWS:
            count = con.execute(f"select count(*) from staging.{name}").fetchone()
            assert count is not None and count[0] >= floors[name], name

"""The tenths_to_usd macro converts the game's tenths of a dollar exactly and keeps nulls."""

from __future__ import annotations

import json
from pathlib import Path

from tests import test_dbt_environments as environments
from tests.test_dbt_environments import dbt

project = environments.project  # the fixture, re-exported so pytest finds it here


def test_tenths_to_usd_is_exact_and_keeps_nulls(project: Path, tmp_path: Path) -> None:
    sql = (
        "select cast({{ tenths_to_usd('c') }} as varchar) as v from"
        " (values (12345::bigint), (-5), (null), (9007199254740993)) as x(c)"
    )

    done = dbt(
        project,
        "show",
        "--target",
        "ci",
        "--output",
        "json",
        "--inline",
        sql,
        env={"OPENRCT2_CI_DIR": str(tmp_path)},
    )

    assert done.returncode == 0, done.stdout
    shown = json.loads(done.stdout[done.stdout.index("{\n") :])["show"]
    assert [row["v"] for row in shown] == ["1234.50", "-0.50", None, "900719925474099.30"]

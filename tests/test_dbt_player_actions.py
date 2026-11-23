"""Previews and predictions never count as player actions, proved with real dbt on planted rows.

Each test copies the committed sample (whose game_action file holds no rows), writes game_action
rows into the copy and builds `int_game_actions__labeled` on the `ci` target. The sample is never
written.
"""

from __future__ import annotations

import contextlib
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

import duckdb

from tests import test_dbt_environments as environments
from tests.test_dbt_environments import SAMPLE
from tests.test_dbt_missing_day import dbt_with_roots, setup_target
from tests.two_park_support import sample_park_and_sessions

project = environments.project  # the fixture, re-exported so pytest finds it here

NOT_PLAYER = "assert_previews_never_player_actions"
LABEL = "assert_game_action_label_matches_flags"
PARK, SESSION_IDS = sample_park_and_sessions()
SESSION = SESSION_IDS[0]
STAMP = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class Outcome(NamedTuple):
    code: int
    statuses: dict[str, str]
    warehouse: Path
    output: str


def action(seq: int, label: str, **changes: object) -> dict[str, object]:
    """A game_action row whose label is `label`, with `changes` over the plain executed one."""
    row: dict[str, object] = {
        "schema_version": 1,
        "event_type": "game_action",
        "plugin_version": "0.7.0",
        "park_id": PARK,
        "session_id": SESSION,
        "seq": seq,
        "event_id": f"{SESSION}-a{seq}",
        "game_year": 9,
        "game_month": 0,
        "game_day": seq,
        "game_ticks_elapsed": 1000 + seq,
        "emitted_at": STAMP,
        "received_at": STAMP,
        "_raw_file": "planted.jsonl",
        "_raw_line": seq,
        "hook": "execute",
        "action": "ridesetprice",
        "action_label": label,
        "args_flags": None,
        "is_client_only": False,
        "player": -1,
        "type": 20,
        "args_json": "{}",
        "action_at_ticks": 1000 + seq,
        "action_game_year": 9,
        "action_game_month": 0,
        "action_game_day": seq,
    }
    return {**row, **changes}


def plant(folder: Path, rows: list[dict[str, object]]) -> None:
    """Write `rows` into the empty game_action file of the sample copy in `folder`."""
    path = folder / "v1" / "game_action.parquet"
    staged = path.with_name("staged.parquet")
    with contextlib.closing(duckdb.connect()) as db:
        db.execute(f"create table landed as select * from read_parquet('{path}')")
        for row in rows:
            names = ", ".join(f'"{name}"' for name in row)
            marks = ", ".join("?" for _ in row)
            db.execute(f"insert into landed ({names}) values ({marks})", list(row.values()))
        db.execute(f"copy landed to '{staged}' (format parquet)")
    staged.replace(path)


def build_and_test(project: Path, tmp_path: Path, rows: list[dict[str, object]]) -> Outcome:
    """Plant `rows`, build the two models on `ci`, test the two singular tests, read each status."""
    folder = tmp_path / "planted"
    shutil.copytree(SAMPLE, folder)
    plant(folder, rows)
    env, warehouse = setup_target(project, tmp_path, "ci")
    roots = (str(folder), folder / "registry")
    built = dbt_with_roots(
        project, "ci", env, roots, "run", "--select", "stg_game_action", "int_game_actions__labeled"
    )
    assert built.returncode == 0, built.stdout
    done = dbt_with_roots(project, "ci", env, roots, "test", "--select", NOT_PLAYER, LABEL)
    statuses = {}
    for test in (NOT_PLAYER, LABEL):
        found = re.search(rf"of \d+ (PASS|WARN|FAIL)\b[^\n]*?\b{test}\b", done.stdout)
        assert found, done.stdout
        statuses[test] = found.group(1)
    return Outcome(done.returncode, statuses, warehouse, done.stdout)


def test_correct_rows_of_each_label_pass_both_tests_and_only_the_confirmed_one_counts(
    project: Path, tmp_path: Path
) -> None:
    rows = [
        action(1, "confirmed"),
        action(2, "preview", args_flags=64, is_client_only=True),
        action(3, "preview", args_flags=-1),
        action(4, "prediction", is_client_only=True),
        action(5, "confirmed", hook="query"),
        action(6, "confirmed", args_json='{"analytics_issued_by": "bench-helper"}'),
        action(7, "confirmed", args_flags=0, result_error=5),
    ]

    outcome = build_and_test(project, tmp_path, rows)

    assert outcome.code == 0, outcome.output
    assert outcome.statuses == {NOT_PLAYER: "PASS", LABEL: "PASS"}
    with contextlib.closing(duckdb.connect(str(outcome.warehouse), read_only=True)) as db:
        found = db.execute(
            "select seq, is_player_action, is_plugin_issued, is_refused "
            "from intermediate.int_game_actions__labeled order by seq"
        ).fetchall()
    assert found == [
        (1, True, False, False),
        (2, False, False, False),
        (3, False, False, False),
        (4, False, False, False),
        (5, False, False, False),
        (6, False, True, False),
        (7, True, False, True),
    ]


def test_a_bit_64_row_labeled_confirmed_fails_both_tests(project: Path, tmp_path: Path) -> None:
    outcome = build_and_test(project, tmp_path, [action(1, "confirmed", args_flags=64)])

    assert outcome.code != 0, outcome.output
    assert outcome.statuses == {NOT_PLAYER: "FAIL", LABEL: "FAIL"}


def test_a_client_only_row_labeled_confirmed_fails_both_tests(
    project: Path, tmp_path: Path
) -> None:
    outcome = build_and_test(project, tmp_path, [action(1, "confirmed", is_client_only=True)])

    assert outcome.code != 0, outcome.output
    assert outcome.statuses == {NOT_PLAYER: "FAIL", LABEL: "FAIL"}

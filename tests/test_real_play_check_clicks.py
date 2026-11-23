"""Real-play result command: the click query filters and malformed rows, on real Parquet."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_real_play_check import (
    CLICKS,
    PREBUILT,
    SESSION,
    STALL,
    Rows,
    action,
    data,
    go,
    price,
    scenario,
)

play_data = data  # the fixture of the main test file, under a name this file's tests can take

# A malformed ridesetsetting row is a failed read (exit 1) that names the row.
BAD_ARGS = ["null", "[]"]


def test_a_query_hook_row_per_click_is_not_a_second_click(
    play_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A real capture holds a query-hook row (seq just before) and an execute-hook row per click.
    tables = scenario()
    tables["game_action"] += [price(seq - 1, hook="query") for seq in CLICKS]
    code, out = go(play_data, capsys, tables)
    assert code == 0
    assert "cannot classify" not in out


def test_a_client_only_copy_of_each_click_is_not_a_second_click(
    play_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tables = scenario()
    tables["game_action"] += [price(seq + 1, action_label="prediction") for seq in CLICKS]
    code, out = go(play_data, capsys, tables)
    assert code == 0
    assert "cannot classify" not in out


@pytest.mark.parametrize("args_json", BAD_ARGS)
def test_a_ridesetsetting_row_whose_args_are_not_an_object_fails_naming_the_row(
    play_data: Path,
    capsys: pytest.CaptureFixture[str],
    args_json: str,
) -> None:
    tables = scenario()
    tables["game_action"].append(
        price(500, ride=1) | {"action": "ridesetsetting", "args_json": args_json}
    )
    code, out = go(play_data, capsys, tables)
    assert code == 1
    assert "failed" in out
    assert "game_action row seq 500 (ridesetsetting): args_json is not an object" in out


def test_a_ride_snapshot_without_a_ride_id_fails_naming_the_row(
    play_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tables = scenario()
    tables["ride_snapshot"].append(
        {"session_id": SESSION, "seq": 9, "event_id": "ride-null", "ride_id": None}
    )
    code, out = go(play_data, capsys, tables)
    assert code == 1
    assert "failed" in out
    assert "ride_snapshot row seq 9 has no ride_id" in out


@pytest.mark.parametrize(
    "extra",
    [
        price(CLICKS[0]),  # the same click delivered twice
        price(150, result_error=2),  # a refused click
        action(150, "ridesetprice", args_ride=STALL, player=0),  # issued by the plugin
        action(
            150,
            "ridesetprice",
            args_ride=STALL,
            args_json=json.dumps({"analytics_issued_by": "plugin"}),
        ),
    ],
)
def test_a_click_that_is_not_a_player_price_click_does_not_shift_the_checkpoints(
    play_data: Path, capsys: pytest.CaptureFixture[str], extra: dict[str, object]
) -> None:
    tables = scenario()
    tables["game_action"].append(extra)
    code, out = go(play_data, capsys, tables)
    assert code == 0
    assert "cannot classify" not in out


@pytest.mark.parametrize(
    ("actions", "count"),
    [
        ([price(100), price(150, ride=PREBUILT), price(200)], 2),  # a missing click and a stray one
        ([price(100), price(200)], 2),
        ([price(100), price(200), price(300), price(400)], 4),
    ],
)
def test_a_click_count_other_than_three_cannot_classify(
    play_data: Path, capsys: pytest.CaptureFixture[str], actions: Rows, count: int
) -> None:
    tables = scenario()
    tables["game_action"] = actions
    code, out = go(play_data, capsys, tables)
    assert code == 1
    expected = f"check 1 (Save Game As): cannot classify ({count} price clicks on the new stall"
    assert expected in out

"""Behavior tests for the benchmark action helper and fixed workload."""

# WEAKENED-OK: spec R15 removes flag 64, the markers and the label refusal; R2 skips previews

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from openrct2_analytics.ingest.bench_actions import (
    ACTION_ROWS,
    BURST_OFFSET_TICKS,
    SPIKE_TICK,
    TICKS_PER_BURST,
    Workload,
    action_helper,
    calls_per_tick,
    workload_reasons,
)


@pytest.mark.parametrize(("rows_per_call", "allowed"), [(1, {3, 4}), (2, {1, 2})])
def test_schedule_sums_to_target_rows_and_uses_expected_calls(
    rows_per_call: int, allowed: set[int]
) -> None:
    calls = [calls_per_tick(tick, rows_per_call) for tick in range(TICKS_PER_BURST)]

    assert set(calls[:SPIKE_TICK] + calls[SPIKE_TICK + 1 :]) == allowed
    assert sum(calls) * rows_per_call == ACTION_ROWS
    assert calls[SPIKE_TICK] == (131 if rows_per_call == 1 else 66)


def test_action_helper_has_burst_days_offset_and_sends_no_preview_flag() -> None:
    helper = action_helper()

    assert "var BURST_DAYS = [1, 6, 11, 16, 21, 26, 31];" in helper
    assert f"var OFFSET_TICKS = {BURST_OFFSET_TICKS};" in helper
    assert "flags" not in helper
    assert "analytics_issued_by" not in helper
    assert "isPrimaryPrice: true" in helper
    assert "__" not in helper
    assert "flags" not in action_helper(2)


_NODE_SCRIPT = """
var fs = require("fs");
var vm = require("vm");
var sandbox = { registerPlugin: function () {} };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), sandbox);
var out = [];
for (var t = 0; t < 2400; t += 1) {
  out.push(sandbox.callsAt(t));
}
console.log(JSON.stringify(out));
"""


@pytest.mark.parametrize("rows_per_call", [1, 2])
def test_helper_javascript_schedule_matches_python_schedule(
    rows_per_call: int, tmp_path: Path
) -> None:
    helper_file = tmp_path / "helper.js"
    helper_file.write_text(action_helper(rows_per_call), encoding="utf-8")

    result = subprocess.run(
        ["node", "-e", _NODE_SCRIPT, str(helper_file)],
        capture_output=True,
        text=True,
        check=True,
    )

    expected = [calls_per_tick(tick, rows_per_call) for tick in range(TICKS_PER_BURST)]
    assert json.loads(result.stdout) == expected


def _row(hook: str, seq: int, tick: int) -> dict[str, object]:
    """A recorded helper row: a confirmed, plugin-issued ridesetprice call."""
    return {
        "hook": hook,
        "seq": seq,
        "action_at_ticks": tick,
        "action": "ridesetprice",
        "player": 0,
        "action_label": "confirmed",
    }


def delivered_workload(rows_per_call: int = 1) -> Workload:
    """Right aggregate counts only: one execute and one query row per call.

    Ticks are not spread over seven burst days; the checks that use it count rows.
    """
    calls = 7 * ACTION_ROWS // rows_per_call
    actions = [_row("execute", i + 1, 100 + i % 3000) for i in range(calls)]
    actions += [_row("query", calls + 1 + i, 100 + i % 3000) for i in range(calls)]
    stats = tuple(
        {
            "seq": len(actions) + 100 + day,
            "period_start_ticks": day * 100,
            "period_end_ticks": (day + 1) * 100 if day < 35 else 4000,
            "lines_dropped_total": 0,
            "game_actions_dropped_preview_total": 0,
            "game_actions_dropped_prediction_total": 0,
            "game_actions_dropped_confirmed_total": 0,
            "game_actions_sent_preview_total": 0,
            "game_actions_sent_prediction_total": 0,
            "game_actions_sent_confirmed_total": len(actions),
        }
        for day in range(36)
    )
    return Workload(tuple(actions), stats)


@pytest.mark.parametrize("rows_per_call", [1, 2])
def test_workload_accepts_complete_delivery(rows_per_call: int) -> None:
    assert workload_reasons(delivered_workload(rows_per_call), 35, rows_per_call) == []


def _replace_first(workload: Workload, hook: str, **changes: object) -> Workload:
    """The workload with the first row of one hook changed."""
    actions = list(workload.actions)
    index = next(i for i, row in enumerate(actions) if row["hook"] == hook)
    actions[index] = dict(actions[index], **changes)
    return Workload(tuple(actions), workload.stats)


def test_workload_rejects_no_rows_and_a_dropped_counter() -> None:
    delivered = delivered_workload()
    assert "no rows" in " ".join(workload_reasons(Workload((), delivered.stats), 35, 1))
    dropped = dict(delivered.stats[-1], game_actions_dropped_preview_total=1)
    assert "void:" in " ".join(
        workload_reasons(Workload(delivered.actions, (*delivered.stats[:-1], dropped)), 35, 1)
    )
    line_drop = dict(delivered.stats[-1], lines_dropped_total=1)
    assert "void: emitter dropped lines" in workload_reasons(
        Workload(delivered.actions, (*delivered.stats[:-1], line_drop)), 35, 1
    )


@pytest.mark.parametrize("hook", ["execute", "query"])
def test_one_row_short_fails(hook: str) -> None:
    delivered = delivered_workload()
    index = next(i for i, row in enumerate(delivered.actions) if row["hook"] == hook)
    short = Workload((*delivered.actions[:index], *delivered.actions[index + 1 :]), delivered.stats)

    reasons = workload_reasons(short, 35, 1)

    expected = 7 * ACTION_ROWS
    assert f"action {hook} rows: got {expected - 1}, expected {expected}" in reasons


@pytest.mark.parametrize("hook", ["execute", "query"])
def test_a_preview_row_fails(hook: str) -> None:
    changed = _replace_first(delivered_workload(), hook, action_label="preview")

    reasons = workload_reasons(changed, 35, 1)

    assert f"action {hook} rows have a wrong label" in reasons


@pytest.mark.parametrize("hook", ["execute", "query"])
def test_a_row_with_a_non_plugin_player_value_fails(hook: str) -> None:
    changed = _replace_first(delivered_workload(), hook, player=-1)

    reasons = workload_reasons(changed, 35, 1)

    assert "action rows have a player value outside (0,)" in reasons


def test_a_sent_total_that_disagrees_with_the_rows_fails() -> None:
    delivered = delivered_workload()
    sent = dict(
        delivered.stats[-1],
        game_actions_sent_confirmed_total=len(delivered.actions) + 1,
    )

    reasons = workload_reasons(Workload(delivered.actions, (*delivered.stats[:-1], sent)), 35, 1)

    assert "confirmed sent total disagrees with rows before last plugin_stats" in reasons


def test_an_extra_query_row_fails() -> None:
    delivered = delivered_workload()
    extra = _row("query", 90_000, 100)

    reasons = workload_reasons(Workload((*delivered.actions, extra), delivered.stats), 35, 1)

    expected = 7 * ACTION_ROWS
    assert f"action query rows: got {expected + 1}, expected {expected}" in reasons


def test_query_rows_are_not_expected_when_the_dry_run_saw_none() -> None:
    delivered = delivered_workload()
    execute = tuple(row for row in delivered.actions if row["hook"] == "execute")
    stats = tuple(
        dict(row, game_actions_sent_confirmed_total=len(execute)) for row in delivered.stats
    )
    workload = Workload(execute, stats)

    assert workload_reasons(workload, 35, 1, expect_query=False) == []
    expected = 7 * ACTION_ROWS
    assert f"action query rows: got 0, expected {expected}" in workload_reasons(workload, 35, 1)


def test_a_row_of_another_action_fails() -> None:
    changed = _replace_first(delivered_workload(), "execute", action="parkmarketing")

    reasons = workload_reasons(changed, 35, 1)

    assert "action rows include an action other than ridesetprice" in reasons


def test_rows_outside_the_judged_window_are_not_counted() -> None:
    delivered = delivered_workload()
    first_tick = delivered.stats[1]["period_start_ticks"]
    end_tick = delivered.stats[35]["period_end_ticks"]
    assert isinstance(first_tick, int) and isinstance(end_tick, int)
    # Sent after the last plugin_stats row, so the sent-total identity does not see them.
    outside = tuple(
        dict(delivered.actions[1], seq=10**9 + offset, action_at_ticks=tick)
        for offset, tick in enumerate((first_tick - 1, end_tick))
    )

    reasons = workload_reasons(Workload((*delivered.actions, *outside), delivered.stats), 35, 1)

    assert reasons == []


@pytest.mark.parametrize(
    "field",
    [
        "lines_dropped_total",
        "game_actions_dropped_preview_total",
        "game_actions_sent_confirmed_total",
    ],
)
def test_a_missing_counter_is_its_own_reason_not_zero_and_not_void(field: str) -> None:
    delivered = delivered_workload()
    last = {key: value for key, value in delivered.stats[-1].items() if key != field}

    reasons = workload_reasons(Workload(delivered.actions, (*delivered.stats[:-1], last)), 35, 1)

    assert f"plugin_stats lacks {field}" in reasons
    assert not any(reason.startswith("void:") for reason in reasons)

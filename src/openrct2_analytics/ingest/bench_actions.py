"""Benchmark action helper, call schedule, and delivered-workload check."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import duckdb

from openrct2_analytics.ingest.contracts import LANDING_FOLDER
from openrct2_analytics.ingest.plugin_issued import PLUGIN_ISSUED_PLAYER_VALUES

ACTION_HELPER_FILE = "openrct2-analytics-bench-actions.js"
BURST_DAYS = (1, 6, 11, 16, 21, 26, 31)
TICKS_PER_BURST = 2_400
BURST_OFFSET_TICKS = 100
SPIKE_TICK = 1_200
ACTION_ROWS = 8_576
_SCHEDULES = {1: (131, 8_445), 2: (66, 4_222)}
_TICK_COUNT = TICKS_PER_BURST - 1
VOID_PREFIX = (
    "void:"  # starts each reason for a run that lost output; its cost is not a speed result
)
HELPER_ACTION = "ridesetprice"
LABELS = ("preview", "prediction", "confirmed")
DROP_FIELDS = tuple(f"game_actions_dropped_{label}_total" for label in LABELS)
SENT_FIELDS = tuple(f"game_actions_sent_{label}_total" for label in LABELS)

ACTION_HELPER = """// Benchmark action helper, written into one run's plugin folder.
// It runs seven one-minute bursts and changes each selected ride's price to its current price.
// Every call is a plain, non-preview call, so the plugin keeps and labels each one confirmed.
var SPIKE_CALLS = __SPIKE_CALLS__;
var DISTRIBUTED_CALLS = __DISTRIBUTED_CALLS__;
var TICK_COUNT = __TICK_COUNT__;
var BURST_DAYS = [1, 6, 11, 16, 21, 26, 31];
var OFFSET_TICKS = 100;
var SPIKE_TICK = 1200;

function callsAt(tick) {
  if (tick === SPIKE_TICK) {
    return SPIKE_CALLS;
  }
  var u = tick < SPIKE_TICK ? tick : tick - 1;
  return Math.floor((u + 1) * DISTRIBUTED_CALLS / TICK_COUNT) -
    Math.floor(u * DISTRIBUTED_CALLS / TICK_COUNT);
}

function firstPricedRide() {
  var rides = map.rides;
  for (var i = 0; i < rides.length; i += 1) {
    var ride = rides[i];
    if (ride.price !== null && ride.price.length > 0) {
      return ride;
    }
  }
  return null;
}

function main() {
  var daysSeen = 0;
  var burstDay = 0;
  var ticksAfterDay = 0;
  var burstTick = -1;
  context.subscribe("interval.day", function () {
    daysSeen += 1;
    if (burstDay < BURST_DAYS.length && daysSeen === BURST_DAYS[burstDay]) {
      burstDay += 1;
      ticksAfterDay = 0;
      burstTick = -2;
    }
  });
  context.subscribe("interval.tick", function () {
    if (burstTick === -2) {
      ticksAfterDay += 1;
      if (ticksAfterDay >= OFFSET_TICKS) {
        burstTick = 0;
      }
    }
    if (burstTick < 0) {
      return;
    }
    var ride = firstPricedRide();
    if (ride !== null) {
      var count = callsAt(burstTick);
      for (var call = 0; call < count; call += 1) {
        context.executeAction("ridesetprice", {
          ride: ride.id,
          price: ride.price[0],
          isPrimaryPrice: true
        });
      }
    }
    burstTick += 1;
    if (burstTick >= 2400) {
      burstTick = -1;
    }
  });
}

registerPlugin({
  name: "openrct2-analytics-bench-actions",
  version: "0.1.0",
  authors: ["John Cabiles"],
  type: "local",
  licence: "MIT",
  targetApiVersion: 122,
  main: main
});
"""


def action_helper(rows_per_call: int = 1) -> str:
    """Return the action helper plugin text for one or two rows per call."""
    if rows_per_call not in _SCHEDULES:
        raise ValueError("rows_per_call must be 1 or 2")
    spike, distributed = _SCHEDULES[rows_per_call]
    return (
        ACTION_HELPER.replace("__SPIKE_CALLS__", str(spike))
        .replace("__DISTRIBUTED_CALLS__", str(distributed))
        .replace("__TICK_COUNT__", str(_TICK_COUNT))
    )


def calls_per_tick(tick: int, rows_per_call: int) -> int:
    """Return the scheduled action-call count for a burst tick and measured row rate."""
    if tick < 0 or tick >= TICKS_PER_BURST:
        raise ValueError("tick must be in the burst range 0..2399")
    try:
        spike, distributed = _SCHEDULES[rows_per_call]
    except KeyError as error:
        raise ValueError("rows_per_call must be 1 or 2") from error
    if tick == SPIKE_TICK:
        return spike
    u = tick if tick < SPIKE_TICK else tick - 1
    return ((u + 1) * distributed // _TICK_COUNT) - (u * distributed // _TICK_COUNT)


Row = Mapping[str, object]


@dataclass(frozen=True)
class Workload:
    """Converted action rows and daily statistics from one run."""

    actions: tuple[Row, ...]
    stats: tuple[Row, ...]


def _parquet_rows(connection: duckdb.DuckDBPyConnection, path: Path) -> tuple[Row, ...]:
    quoted = path.as_posix().replace("'", "''")
    result = connection.execute(f"SELECT * FROM read_parquet('{quoted}')")
    names = [column[0] for column in result.description]
    return tuple(dict(zip(names, values, strict=True)) for values in result.fetchall())


def read_workload(parquet_dir: Path) -> Workload:
    """Read converted workload rows; an absent action file represents zero helper rows."""
    folder = parquet_dir / LANDING_FOLDER
    connection = duckdb.connect(":memory:")
    try:
        stats = _parquet_rows(connection, folder / "plugin_stats.parquet")
        action_file = folder / "game_action.parquet"
        actions = _parquet_rows(connection, action_file) if action_file.exists() else ()
        return Workload(actions, stats)
    finally:
        connection.close()


def _number(row: Row, field: str) -> int | None:
    value = row.get(field)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _action_reasons(actions: list[Row], rows_per_call: int, expect_query: bool) -> list[str]:
    reasons: list[str] = []
    if not actions:
        reasons.append("action helper produced no rows in judged periods")
    expected = len(BURST_DAYS) * ACTION_ROWS // rows_per_call
    counts = Counter(str(row.get("hook")) for row in actions)
    required_by_hook = (("execute", expected), ("query", expected if expect_query else 0))
    for hook, required in required_by_hook:
        if counts[hook] != required:
            reasons.append(f"action {hook} rows: got {counts[hook]}, expected {required}")
    if sum(counts.values()) != counts["execute"] + counts["query"]:
        reasons.append("action workload has an unknown hook")
    if any(row.get("action") != HELPER_ACTION for row in actions):
        reasons.append(f"action rows include an action other than {HELPER_ACTION}")
    if any(row.get("player") not in PLUGIN_ISSUED_PLAYER_VALUES for row in actions):
        reasons.append(f"action rows have a player value outside {PLUGIN_ISSUED_PLAYER_VALUES}")
    for hook, required in required_by_hook:
        if required and any(
            row.get("action_label") != "confirmed" for row in actions if row.get("hook") == hook
        ):
            reasons.append(f"action {hook} rows have a wrong label")
    return reasons


def _counter_reasons(workload: Workload, stats: list[Row], last_seq: int) -> list[str]:
    reasons: list[str] = []
    for field in (*DROP_FIELDS, "lines_dropped_total"):
        values = [_number(row, field) for row in stats]
        if None in values:
            reasons.append(f"plugin_stats lacks {field}")
        elif field == "lines_dropped_total" and any(values):
            reasons.append(f"{VOID_PREFIX} emitter dropped lines")
        elif any(values):
            reasons.append(f"{VOID_PREFIX} {field} is nonzero")
    sent_rows = [row for row in workload.actions if (_number(row, "seq") or 0) < last_seq]
    sent = Counter(str(row.get("action_label")) for row in sent_rows)
    for label, field in zip(LABELS, SENT_FIELDS, strict=True):
        total = _number(stats[-1], field)
        if total is None:
            reasons.append(f"plugin_stats lacks {field}")
        elif sent[label] != total:
            reasons.append(f"{label} sent total disagrees with rows before last plugin_stats")
    return reasons


def workload_reasons(
    workload: Workload, judged_days: int, rows_per_call: int, *, expect_query: bool = True
) -> list[str]:
    """Return completion failures for the seven action bursts and emitter counters."""
    if rows_per_call not in _SCHEDULES:
        raise ValueError("rows_per_call must be 1 or 2")
    stats = sorted(workload.stats, key=lambda row: _number(row, "seq") or -1)
    if len(stats) < judged_days + 1:
        return ["action workload has too few plugin_stats rows"]
    judged = stats[1 : judged_days + 1]
    first_tick = _number(judged[0], "period_start_ticks")
    end_tick = _number(judged[-1], "period_end_ticks")
    last_seq = _number(stats[-1], "seq")
    if first_tick is None or end_tick is None or last_seq is None:
        return ["action workload has missing period or seq fields"]
    actions = [
        row
        for row in workload.actions
        if (tick := _number(row, "action_at_ticks")) is not None and first_tick <= tick < end_tick
    ]
    return _action_reasons(actions, rows_per_call, expect_query) + _counter_reasons(
        workload, stats, last_seq
    )

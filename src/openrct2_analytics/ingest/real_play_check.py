"""Print whether the plugin captured what it should in one practice play session.

Run with ``python -m openrct2_analytics.ingest.real_play_check`` (``make real-play-check``). It
reads the converted Parquet of the latest session of one data set (or ``--session``) and prints
the kept ride builds (from the daily ride snapshots), whether any dropped build action was sent,
the save hook per checkpoint (found from stall price clicks) and supporting tables, then the
session ID and the command that deletes the session. It never writes.

Exit codes: 0 every verdict passed, 1 a verdict failed or a file could not be read, 2 refused
(no ``--data-set`` or no session), 130 interrupted. The module ignores the environment: the
Makefile refuses an exported ``DATA_SET`` before this module runs.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Never

import duckdb

from openrct2_analytics.config import DATA_SETS, ConfigError, landing_dirs
from openrct2_analytics.ingest import lock
from openrct2_analytics.ingest.action_names import (
    SUBTYPE_FILTERED_ACTION_NAMES,
    dropped_action_row,
)
from openrct2_analytics.ingest.plugin_issued import PLUGIN_ISSUED_PLAYER_VALUES

CHECKPOINTS = (
    (1, "check 1", "Save Game As"),
    (2, "check 2", "plain Save Game"),
    (3, "check 3", "quit save"),
)
STOP_LINE = (
    "The save hook was not seen for plain Save Game or for the quit save. Stop: "
    "the save watcher needs a redesign (roadmap item 3b, save hook)."
)
_SKIPPED_TOTALS = tuple(
    f"game_actions_skipped_{kind}_total"
    for kind in ("preview", "prediction", "confirmed", "unknown", "cheat")
)
_ACTION_TOTALS = (
    *(
        f"game_actions_{kind}_{label}_total"
        for kind in ("sent", "dropped")
        for label in ("preview", "prediction", "confirmed")
    ),
    *_SKIPPED_TOTALS,
)
# The ride windows need park snapshots P1 ... Pn; window 1 and window n - 2 are the two read.
_MIN_PARK_SNAPSHOTS = 4
# Plugin-issued: player in the plugin-issued values or an analytics_issued_by argument key
# (int_game_actions__labeled.sql:14, :56-62), applied before is_player_action (:105-109).
_ISSUED = (
    "coalesce(list_contains(?::BIGINT[], player), false) "
    "OR coalesce(json_exists(args_json, '$.analytics_issued_by'), false)"
)
_VIEW_COLUMNS = {
    "game_action": (
        ("session_id", "VARCHAR"),
        ("seq", "BIGINT"),
        ("hook", "VARCHAR"),
        ("action", "VARCHAR"),
        ("action_label", "VARCHAR"),
        ("player", "BIGINT"),
        ("args_json", "VARCHAR"),
        ("args_ride", "BIGINT"),
        ("result_error", "BIGINT"),
    ),
    "park_snapshot": (("session_id", "VARCHAR"), ("seq", "BIGINT")),
    "ride_snapshot": (("session_id", "VARCHAR"), ("seq", "BIGINT"), ("ride_id", "BIGINT")),
    "plugin_stats": (
        ("session_id", "VARCHAR"),
        ("seq", "BIGINT"),
        ("work_items_skipped_total", "BIGINT"),
        ("lines_dropped_total", "BIGINT"),
        ("work_items_failed_total", "BIGINT"),
        *((name, "BIGINT") for name in _SKIPPED_TOTALS),
    ),
}


class _Refused(Exception):
    """The command was refused before reading anything."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class _CheckParser(argparse.ArgumentParser):
    """Argument parser that reports invalid input as a refusal."""

    def error(self, message: str) -> Never:
        raise _Refused("usage", message)


@dataclass(frozen=True)
class _Saves:
    """The save verdict of one checkpoint."""

    save_type: str
    name: str
    outcome: str
    reason: str = ""


def _rows(
    connection: duckdb.DuckDBPyConnection, sql: str, params: list[object]
) -> list[tuple[Any, ...]]:
    return connection.execute(sql, params).fetchall()


def _session(connection: duckdb.DuckDBPyConnection, path: Path, wanted: str | None) -> str:
    if not path.exists():
        raise _Refused("no-session", f"{path} is missing; run make convert first")
    rows = _rows(
        connection,
        "SELECT session_id FROM read_parquet(?) "
        "WHERE ? IS NULL OR session_id = ? ORDER BY emitted_at DESC, seq DESC LIMIT 1",
        [str(path), wanted, wanted],
    )
    if not rows:
        raise _Refused("no-session", f"no session {wanted}" if wanted else "no session captured")
    return str(rows[0][0])


def _view(connection: duckdb.DuckDBPyConnection, name: str, folder: Path) -> None:
    """Name the rows of ``<name>.parquet`` `name`: no file is zero rows, no column is null."""
    columns = _VIEW_COLUMNS[name]
    path = folder / f"{name}.parquet"
    if not path.exists():
        empty = ", ".join(f"NULL::{kind} AS {column}" for column, kind in columns)
        connection.execute(f"CREATE VIEW {name} AS SELECT {empty} WHERE false")  # noqa: S608 - constants
        return
    present = {
        str(row[0]) for row in _rows(connection, "SELECT name FROM parquet_schema(?)", [str(path)])
    }
    chosen = ", ".join(
        column if column in present else f"NULL::{kind} AS {column}" for column, kind in columns
    )
    # DuckDB cannot bind a parameter in CREATE VIEW, so the path is a quoted literal.
    quoted = str(path).replace("'", "''")
    # Repeat deliveries of one event_id keep the first: the rule of stg_game_action.sql:45-53.
    connection.execute(
        f"CREATE VIEW {name} AS SELECT {chosen} FROM read_parquet('{quoted}') "  # noqa: S608 - quoted
        "QUALIFY row_number() OVER "
        "(PARTITION BY event_id ORDER BY received_at, _raw_file, _raw_line) = 1"
    )


@dataclass(frozen=True)
class _Rides:
    """The new rides between the start and end windows, or None and why they were refused."""

    new: tuple[int, ...] | None
    detail: str


def _window_ids(
    connection: duckdb.DuckDBPyConnection, session: str, first: int, last: int
) -> set[int]:
    rows = _rows(
        connection,
        "SELECT seq, ride_id FROM ride_snapshot WHERE session_id = ? AND seq > ? AND seq < ?",
        [session, first, last],
    )
    for seq, ride_id in rows:
        if ride_id is None:
            raise ValueError(f"ride_snapshot row seq {seq} has no ride_id")
    return {int(ride_id) for _, ride_id in rows}


def _kept_rides(connection: duckdb.DuckDBPyConnection, session: str) -> _Rides:
    """Find rides in the end window and not in the start window, from proven-complete windows."""
    parks = [
        int(row[0])
        for row in _rows(
            connection,
            "SELECT seq FROM park_snapshot WHERE session_id = ? ORDER BY seq",
            [session],
        )
    ]
    if len(parks) < _MIN_PARK_SNAPSHOTS:
        return _Rides(
            None,
            f"not enough game days: {len(parks)} park snapshots, need at least "
            f"{_MIN_PARK_SNAPSHOTS}",
        )
    # The plugin emits plugin_stats at seq m and park_snapshot at m + 1 (the contract).
    counters = {
        int(seq): (skipped, dropped, failed)
        for seq, skipped, dropped, failed in _rows(
            connection,
            "SELECT seq, work_items_skipped_total, lines_dropped_total, work_items_failed_total "
            "FROM plugin_stats WHERE session_id = ?",
            [session],
        )
    }

    def proven(index: int) -> bool:
        # Work left from window index is counted at the queueing after the next snapshot, so the
        # skipped counter before the second following snapshot is the first that holds it. Lines
        # dropped and items failed are counted when they happen, so those two counters must not
        # move from the row before the window's own snapshot to the row before the second one after.
        before = counters.get(parks[index] - 1)
        mid = counters.get(parks[index + 1] - 1)
        after = counters.get(parks[index + 2] - 1)
        if before is None or mid is None or after is None:
            return False
        if mid[0] is None or mid[0] != after[0]:
            return False
        return all(before[k] is not None and before[k] == after[k] for k in (1, 2))

    start_index, end_index = 0, len(parks) - 3
    for index in (start_index, end_index):
        if not proven(index):
            return _Rides(None, f"ride snapshot window incomplete (window {index + 1})")
    start = _window_ids(connection, session, parks[start_index], parks[start_index + 1])
    end = _window_ids(connection, session, parks[end_index], parks[end_index + 1])
    new = tuple(sorted(end - start))
    return _Rides(
        new,
        f"start set {len(start)} rides, end set {len(end)} rides; "
        f"new ride IDs: {', '.join(map(str, new)) or 'none'}",
    )


def _dropped_rows(connection: duckdb.DuckDBPyConnection, session: str) -> int:
    """Count the session's rows that break the kept-action rule."""
    rows = _rows(
        connection,
        "SELECT seq, action, action_label, coalesce(args_json, '{}') FROM game_action "
        "WHERE session_id = ?",
        [session],
    )
    for seq, action, _, args in rows:
        if action in SUBTYPE_FILTERED_ACTION_NAMES and not isinstance(json.loads(args), dict):
            raise ValueError(f"game_action row seq {seq} ({action}): args_json is not an object")
    return sum(
        dropped_action_row({"action": action, "action_label": label, "args_json": args})
        for _, action, label, args in rows
    )


def _skipped_totals(connection: duckdb.DuckDBPyConnection, session: str) -> list[int | None]:
    """Return the five skipped totals of the session's last plugin_stats row (None when absent)."""
    rows = _rows(
        connection,
        f"SELECT {', '.join(_SKIPPED_TOTALS)} FROM plugin_stats "  # noqa: S608 - constants
        "WHERE session_id = ? ORDER BY seq DESC LIMIT 1",
        [session],
    )
    return list(rows[0]) if rows else [None] * len(_SKIPPED_TOTALS)


def _checkpoint_starts(
    connection: duckdb.DuckDBPyConnection, session: str, rides: _Rides
) -> tuple[dict[str, int] | None, str]:
    """Return each checkpoint's start seq (the stall's price clicks in order), or None and why."""
    if rides.new is None:
        return None, "the ride build verdict was refused"
    if len(rides.new) != 1:
        return None, f"{len(rides.new)} new rides found, need exactly 1"
    clicks = [
        int(row[0])
        for row in _rows(
            connection,
            "SELECT seq FROM game_action WHERE session_id = ? AND hook = 'execute' "
            "AND action = 'ridesetprice' AND action_label = 'confirmed' "
            "AND coalesce(result_error, 0) = 0 AND args_ride = ? "
            f"AND NOT ({_ISSUED}) ORDER BY seq",
            [session, rides.new[0], list(PLUGIN_ISSUED_PLAYER_VALUES)],
        )
    ]
    if len(clicks) != len(CHECKPOINTS):
        return None, f"{len(clicks)} price clicks on the new stall, need {len(CHECKPOINTS)}"
    return {name: seq for (_, name, _), seq in zip(CHECKPOINTS, clicks, strict=True)}, ""


def _save_verdicts(
    connection: duckdb.DuckDBPyConnection,
    saves: Path,
    session: str,
    *,
    start: dict[str, int] | None,
    reason: str,
) -> list[_Saves]:
    save_seqs = (
        [
            int(row[0])
            for row in _rows(
                connection,
                # Repeat deliveries keep the first: the rule of stg_save_written.sql:27-30.
                "SELECT seq FROM read_parquet(?) WHERE session_id = ? "
                "QUALIFY row_number() OVER "
                "(PARTITION BY event_id ORDER BY received_at, _raw_file, _raw_line) = 1",
                [str(saves), session],
            )
        ]
        if saves.exists()
        else []
    )
    verdicts = []
    for _, name, save_type in CHECKPOINTS:
        if start is None:
            verdicts.append(_Saves(save_type, name, "cannot classify", reason))
            continue
        later = [seq for seq in start.values() if seq > start[name]]
        end = min(later, default=None)
        count = sum(1 for seq in save_seqs if seq >= start[name] and (end is None or seq < end))
        outcome = {0: "not seen", 1: "fired"}.get(count, "unknown save type")
        verdicts.append(_Saves(save_type, name, outcome))
    return verdicts


def _print_table(title: str, header: str, rows: list[tuple[Any, ...]]) -> None:
    print(f"\n{title}")
    print(header)
    for row in rows:
        print(" | ".join("null" if value is None else str(value) for value in row))
    if not rows:
        print("(no rows)")


def _supporting(connection: duckdb.DuckDBPyConnection, stats: Path, session: str) -> None:
    _print_table(
        "Rows per hook and label",
        "hook | action_label | rows",
        _rows(
            connection,
            "SELECT hook, action_label, count(*) FROM game_action WHERE session_id = ? "
            "GROUP BY ALL ORDER BY ALL",
            [session],
        ),
    )
    _print_table(
        "Distinct player values per label",
        "action_label | player values",
        _rows(
            connection,
            "SELECT action_label, string_agg(DISTINCT CAST(player AS VARCHAR), ', ' "
            "ORDER BY CAST(player AS VARCHAR)) FROM game_action WHERE session_id = ? "
            "GROUP BY ALL ORDER BY ALL",
            [session],
        ),
    )
    print("\nLast plugin_stats totals (sent, dropped and skipped beside the Parquet counts above)")
    if not stats.exists():
        print("(plugin_stats.parquet is missing)")
        return
    present = {
        str(row[0]) for row in _rows(connection, "SELECT name FROM parquet_schema(?)", [str(stats)])
    }
    wanted = [name for name in ("lines_dropped_total", *_ACTION_TOTALS) if name in present]
    last = (
        _rows(
            connection,
            f"SELECT {', '.join(wanted)} FROM read_parquet(?) "  # noqa: S608 - names are constants
            "WHERE session_id = ? ORDER BY seq DESC LIMIT 1",
            [str(stats), session],
        )
        if wanted
        else []
    )
    if not last:
        print("(no plugin_stats row with these totals)")
        return
    for name, value in zip(wanted, last[0], strict=True):
        print(f"{name}: {'null' if value is None else value}")
    for name in sorted(set(_ACTION_TOTALS) - present):
        print(f"{name}: not in this plugin_stats file")


def _run(data_set: str, wanted: str | None) -> int:
    parquet = landing_dirs(data_set).parquet / "v1"
    connection = duckdb.connect(":memory:")
    try:
        session = _session(connection, parquet / "session_start.parquet", wanted)
        for name in _VIEW_COLUMNS:
            _view(connection, name, parquet)
        print(f"Real-play check, data set {data_set}, session {session}")
        rides = _kept_rides(connection, session)
        ok_rides = rides.new is not None and len(rides.new) == 1
        if rides.new is None:
            print(f"\n1. Ride builds: FAIL ({rides.detail})")
        else:
            word = "pass" if ok_rides else "FAIL"
            print(f"\n1. Ride builds: {len(rides.new)} ({word}; pass when 1)")
            print(f"Ride snapshot windows: {rides.detail}")
        dropped = _dropped_rows(connection, session)
        skipped = _skipped_totals(connection, session)
        totals = dict(zip(_SKIPPED_TOTALS, skipped, strict=True))
        # The steps move a stall preview and then place it: both labels must show a skipped call.
        ok_actions = dropped == 0 and all(
            (totals[f"game_actions_skipped_{label}_total"] or 0) > 0
            for label in ("preview", "confirmed")
        )
        print(
            f"\n2. No build actions sent: {'pass' if ok_actions else 'FAIL'} "
            f"({dropped} dropped-action rows; pass when 0 and the preview and confirmed "
            "skipped totals are above 0)"
        )
        for name, total in totals.items():
            print(f"{name}: {'null' if total is None else total}")
        start, reason = _checkpoint_starts(connection, session, rides)
        verdicts = _save_verdicts(
            connection, parquet / "save_written.parquet", session, start=start, reason=reason
        )
        print("\n3. Save hook, per checkpoint:")
        for verdict in verdicts:
            suffix = f" ({verdict.reason})" if verdict.reason else ""
            print(f"{verdict.name} ({verdict.save_type}): {verdict.outcome}{suffix}")
        by_name = {v.name: v.outcome for v in verdicts}
        stop = by_name["check 2"] == "not seen" and by_name["check 3"] == "not seen"
        if stop:
            print(STOP_LINE)
        ok_saves = (
            by_name["check 1"] == "fired"
            and not stop
            and all(v.outcome != "cannot classify" for v in verdicts)
        )
        print(f"Save hook verdict: {'pass' if ok_saves else 'FAIL'}")
        print("\n4. Supporting tables")
        _supporting(connection, parquet / "plugin_stats.parquet", session)
    finally:
        connection.close()
    print(f"\nSession: {session}")
    if data_set == "company":
        print(f"Delete command: make delete-company-data SESSION={session}")
    return 0 if ok_rides and ok_actions and ok_saves else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Print the real-play verdicts for one data set and return the exit code."""
    parser = _CheckParser(description=__doc__)
    parser.add_argument("--data-set", choices=DATA_SETS)
    parser.add_argument("--session")
    handlers = {
        name: signal.getsignal(getattr(signal, name))
        for name in lock.SIGNAL_NAMES
        if hasattr(signal, name)
    }
    lock.set_signal_handlers(lock.raise_interrupted)
    try:
        args = parser.parse_args(argv)
        if args.data_set is None:
            raise _Refused(
                "usage", "name a data set, for example: make real-play-check DATA_SET=company"
            )
        code = _run(args.data_set, args.session)
    except _Refused as error:
        print(f"real-play-check refused: {error.reason}: {error.detail}")
        code = 2
    except ConfigError as error:
        print(f"real-play-check refused: config: {error}")
        code = 2
    except (OSError, ValueError, duckdb.Error) as error:
        print(f"real-play-check failed: io: {error}")
        code = 1
    except (lock.Interrupted, KeyboardInterrupt):
        print("real-play-check interrupted")
        code = 130
    finally:
        for name, handler in handlers.items():
            signal.signal(getattr(signal, name), handler)
    return code


if __name__ == "__main__":
    sys.exit(main())

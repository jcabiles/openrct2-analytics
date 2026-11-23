"""Print, as one JSON object, the converted play sessions the development warehouse lacks.

A session is waiting when ``session_start.parquet`` of the data set holds it and the table
``staging.stg_session_start`` of ``warehouse/dev/dev.duckdb`` does not. The warehouse is
``missing`` when the file is absent, ``building`` when a writer holds DuckDB's lock on it (every
converted session is then listed, because the warehouse cannot be read), and ``ready`` otherwise.
It writes nothing, but holds DuckDB's read-only lock on the warehouse while it reads, so a writer
(``make transform``, or ``make after-play``'s build step) that opens it then fails; run it on
demand, never on a timer while a build runs. On success standard output holds only the JSON;
refusals and failures go to standard error. Exit 0 printed, 1 failed, 2 refused, 130 interrupted.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Never

import duckdb

from openrct2_analytics.config import DATA_SETS, ConfigError
from openrct2_analytics.ingest import lock, register_parks
from openrct2_analytics.ingest.contracts import LANDING_FOLDER
from openrct2_analytics.ingest.landing_paths import landing, project_path
from openrct2_analytics.ingest.publish_audit import open_warehouse
from openrct2_analytics.ingest.registry_feed import registry_dir
from openrct2_analytics.ingest.save_files import read_records, read_save_written, save_files_dir
from openrct2_analytics.ingest.save_pairing import SavePair, cut_rows, pair_run

PROJECT_DIR = Path(__file__).resolve().parents[3]
WAREHOUSE = Path("warehouse") / "dev" / "dev.duckdb"
SESSIONS_TABLE = "staging.stg_session_start"
# DuckDB raises the same IOException for a held lock and for a damaged file; only this text tells.
LOCK_MESSAGE = "Could not set lock on file"


@dataclass(frozen=True)
class ParkStatus:
    """One park of a waiting session; ``last_save_file`` is the base name of its last save."""

    park_id: str
    park_name: str | None
    registered: bool
    last_save_file: str | None


@dataclass(frozen=True)
class SessionStatus:
    """One waiting session; ``captured_at`` is its first ``session_start`` time (plugin clock)."""

    session_id: str
    captured_at: str
    parks: tuple[ParkStatus, ...]


@dataclass(frozen=True)
class PlayStatus:
    """The warehouse state and the sessions waiting for the after-play steps."""

    data_set: str
    warehouse: str
    sessions_waiting: tuple[SessionStatus, ...]


class _Refused(Exception):
    """The command was refused before reading anything."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class _StatusParser(argparse.ArgumentParser):
    """Argument parser that reports invalid input as a refusal."""

    def error(self, message: str) -> Never:
        raise _Refused("usage", message)


def converted_starts(starts: Path) -> list[tuple[str, str, str | None, datetime]]:
    """Read the converted session starts, one row per session and park.

    Args:
        starts: Path of the converted ``session_start.parquet``; it need not exist.

    Returns:
        Session ID, park ID, park name and first start time of each session and park, oldest
        first; empty when the file does not exist.

    Raises:
        duckdb.Error: if the file exists and cannot be read.
    """
    if not starts.is_file():
        return []
    with duckdb.connect(":memory:") as connection:
        rows = connection.execute(
            """SELECT session_id, park_id, park_name, emitted_at FROM read_parquet(?)
               QUALIFY row_number() OVER (
                   PARTITION BY session_id, park_id ORDER BY emitted_at
               ) = 1
               ORDER BY emitted_at, session_id, park_id""",
            [str(starts)],
        ).fetchall()
    return [(str(sid), str(park), name, emitted) for sid, park, name, emitted in rows]


def warehouse_sessions(path: Path, project_dir: Path) -> tuple[str, set[str] | None]:
    """Read the state of a warehouse file and the sessions it holds.

    Args:
        path: Path of the DuckDB warehouse file; it need not exist.
        project_dir: Project folder the warehouse is opened under.

    Returns:
        ``("ready", session IDs)`` (an empty set when the sessions table is absent),
        ``("building", None)`` when a writer holds the file's lock, or ``("missing", None)``
        when the file does not exist.

    Raises:
        duckdb.Error: if the file cannot be read for a reason other than a held lock.
    """
    if not path.is_file():
        return "missing", None
    try:
        connection = open_warehouse(path, project_dir=project_dir, read_only=True)
    except duckdb.IOException as error:
        if LOCK_MESSAGE not in str(error):
            raise
        return "building", None
    try:
        schema, table = SESSIONS_TABLE.split(".")
        found = connection.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = ? AND table_name = ?",
            [schema, table],
        ).fetchone()
        if found is None or found[0] == 0:
            return "ready", set()
        rows = connection.execute(f"SELECT DISTINCT session_id FROM {SESSIONS_TABLE}").fetchall()
    finally:
        connection.close()
    return "ready", {str(row[0]) for row in rows}


def dim_park_numbers(project_dir: Path, park_ids: Sequence[str]) -> dict[str, tuple[int, int]]:
    """Read each listed park's company number and start year from ``marts.dim_park``.

    Args:
        project_dir: Project folder that holds ``warehouse/dev/dev.duckdb``.
        park_ids: Park IDs to look up.

    Returns:
        Park ID to (``park_number``, ``company_start_year``), for the listed parks whose row has a
        number; a park with no row or a null number is left out.

    Raises:
        FileNotFoundError: if the development warehouse does not exist.
        duckdb.Error: if it cannot be read (a writer holds its lock, the table or the column is
            missing, or the file is damaged).
    """
    path = project_dir / WAREHOUSE
    if not path.is_file():
        raise FileNotFoundError(f"{WAREHOUSE.as_posix()} does not exist")
    connection = open_warehouse(path, project_dir=project_dir, read_only=True)
    try:
        rows = connection.execute(
            "SELECT park_id, park_number, company_start_year FROM marts.dim_park "
            "WHERE park_id IN (SELECT unnest(?)) AND park_number IS NOT NULL",
            [list(park_ids)],
        ).fetchall()
    finally:
        connection.close()
    return {str(park): (int(number), int(year)) for park, number, year in rows}


def _last_save_files(
    data_set: str, parquet_dir: Path, project_dir: Path
) -> dict[tuple[str, str], str]:
    """Return the file of the latest paired save per session and park, from the save-file records.

    Each watcher run's records are paired with the ``save_written`` events received during that
    run, as the capture report pairs them. Unreadable record lines are left to the contract
    check (``make contracts``), which fails on them.
    """
    folder = project_path(save_files_dir(data_set), project_dir)
    records, _ = read_records(folder, datetime.now(UTC))
    rows = read_save_written(parquet_dir)
    starts = sorted({record.run_started_at for record in records})
    latest: dict[tuple[str, str], SavePair] = {}
    for index, start in enumerate(starts):
        following = starts[index + 1] if index + 1 < len(starts) else None
        run_records = [record for record in records if record.run_started_at == start]
        for pair in pair_run(run_records, cut_rows(rows, start, following)).pairs:
            key = (pair.row.session_id, pair.row.park_id)
            best = latest.get(key)
            if best is None or pair.row.emitted_at > best.row.emitted_at:
                latest[key] = pair
    return {key: pair.record.file_name for key, pair in latest.items()}


def registry_feed_dir(data_set: str, project_dir: Path = PROJECT_DIR) -> Path:
    """Return the ``v1`` folder of ``data_set``'s park registry feed, as an absolute path."""
    return project_path(registry_dir(data_set), project_dir) / LANDING_FOLDER


def read_status(data_set: str, project_dir: Path = PROJECT_DIR) -> PlayStatus:
    """Read the warehouse state and the waiting sessions of ``data_set``.

    It writes nothing; the warehouse is held under DuckDB's read-only lock while it is read.

    Raises:
        ConfigError: if the data set's folders are misconfigured.
        register_parks.Refused: if the registry feed fails its check.
        duckdb.Error: if the warehouse or a Parquet file cannot be read (a held lock is not an
            error; it reads as ``building``).
    """
    parquet_dir = landing(data_set, project_dir).parquet
    state, processed = warehouse_sessions(project_dir / WAREHOUSE, project_dir)
    registered = register_parks.registered_parks(registry_feed_dir(data_set, project_dir))
    saves = _last_save_files(data_set, parquet_dir, project_dir)
    sessions: dict[str, tuple[str, list[ParkStatus]]] = {}
    for session_id, park, name, emitted in converted_starts(
        parquet_dir / LANDING_FOLDER / "session_start.parquet"
    ):
        if processed is not None and session_id in processed:
            continue
        status = ParkStatus(park, name, park in registered, saves.get((session_id, park)))
        sessions.setdefault(session_id, (emitted.astimezone(UTC).isoformat(), []))[1].append(status)
    waiting = tuple(
        SessionStatus(session_id, captured_at, tuple(parks))
        for session_id, (captured_at, parks) in sessions.items()
    )
    return PlayStatus(data_set, state, waiting)


def main(argv: Sequence[str] | None = None, *, project_dir: Path = PROJECT_DIR) -> int:
    """Print the play status of one data set as one JSON object."""
    parser = _StatusParser(description=__doc__)
    parser.add_argument("--data-set", choices=DATA_SETS, required=True)
    handlers = {
        name: signal.getsignal(getattr(signal, name))
        for name in lock.SIGNAL_NAMES
        if hasattr(signal, name)
    }
    lock.set_signal_handlers(lock.raise_interrupted)
    try:
        args = parser.parse_args(argv)
        status = read_status(args.data_set, project_dir.resolve())
        print(json.dumps(asdict(status)))
        code = 0
    except _Refused as error:
        print(f"play-status refused: {error.reason}: {error.detail}", file=sys.stderr)
        code = 2
    except ConfigError as error:
        print(f"play-status refused: data-set: {error}", file=sys.stderr)
        code = 2
    except register_parks.Refused as error:
        print(f"play-status failed: {error.reason}: {error.detail}", file=sys.stderr)
        code = 1
    except (OSError, ValueError, duckdb.Error) as error:
        print(f"play-status failed: io: {error}", file=sys.stderr)
        code = 1
    except (lock.Interrupted, KeyboardInterrupt):
        print("play-status interrupted", file=sys.stderr)
        code = 130
    finally:
        for name, handler in handlers.items():
            signal.signal(getattr(signal, name), handler)
    return code


if __name__ == "__main__":
    sys.exit(main())

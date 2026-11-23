"""Planters for the autopilot-year tests: company data in temporary folders.

Each planter writes the file a real run leaves, with the contracts' column names: converted
``park_snapshot``, ``save_written`` and ``session_start`` Parquet, a save-file record paired with a
``save_written`` row, an archive copy, a registry delivery and a session-label delivery. Later
tickets import these and never edit them. Not a test module itself, like ``tests/bench_plant.py``.
Placeholder ``.park`` files hold test bytes, never game content.
"""

from __future__ import annotations

import csv
import io
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from openrct2_analytics.ingest.registry_feed import HEADER as REGISTRY_HEADER

LABEL_HEADER = (
    "session_id",
    "park_id",
    "play_mode",
    "ready_confirmation",
    "data_set",
    "delivered_on",
)
T0 = datetime(2026, 11, 12, 19, 0, 0, tzinfo=UTC)
ENVELOPE: dict[str, str] = {
    "park_id": "VARCHAR",
    "session_id": "VARCHAR",
    "seq": "BIGINT",
    "event_id": "VARCHAR",
    "game_year": "INTEGER",
    "game_month": "INTEGER",
    "game_day": "INTEGER",
    "emitted_at": "TIMESTAMP WITH TIME ZONE",
    "received_at": "TIMESTAMP WITH TIME ZONE",
    "_raw_file": "VARCHAR",
    "_raw_line": "BIGINT",
}
TYPES: dict[str, dict[str, str]] = {
    "park_snapshot": {**ENVELOPE, "cash_tenths": "BIGINT", "guests_in_park": "INTEGER"},
    "save_written": {**ENVELOPE, "save_id": "VARCHAR"},
    "session_start": {
        **ENVELOPE,
        "park_name": "VARCHAR",
        "loaded_save_id": "VARCHAR",
        "loaded_save_session_id": "VARCHAR",
        "loaded_save_seq_floor": "BIGINT",
    },
}
Row = dict[str, object]


def event_row(
    seq: int,
    *,
    park_id: str = "park-a",
    session_id: str = "sess-1",
    emitted_at: datetime = T0,
    game_date: tuple[int, int, int] = (10, 8, 1),
    event_id: str | None = None,
    **columns: object,
) -> Row:
    """One converted event: the envelope columns plus the table's own, in ``columns``.

    ``game_date`` is (game_year, game_month, game_day); ``received_at`` equals ``emitted_at``.
    """
    year, month, day = game_date
    return {
        "park_id": park_id,
        "session_id": session_id,
        "seq": seq,
        "event_id": event_id or f"{session_id}-{seq}",
        "game_year": year,
        "game_month": month,
        "game_day": day,
        "emitted_at": emitted_at,
        "received_at": emitted_at,
        "_raw_file": "events-2026-11-12.jsonl",
        "_raw_line": seq,
        **columns,
    }


def plant_events(parquet_dir: Path, table: str, rows: list[Row]) -> Path:
    """Write ``rows`` as ``<parquet_dir>/v1/<table>.parquet``; a column a row lacks is NULL."""
    columns = TYPES[table]
    path = parquet_dir / "v1" / f"{table}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"CREATE TABLE t ({', '.join(f'{name} {kind}' for name, kind in columns.items())})"
        )
        marks = ", ".join("?" for _ in columns)
        connection.executemany(
            f"INSERT INTO t VALUES ({marks})", [[row.get(name) for name in columns] for row in rows]
        )
        connection.execute(f"COPY t TO '{path}' (FORMAT PARQUET)")
    return path


def plant_park_snapshot(parquet_dir: Path, rows: list[Row]) -> Path:
    """Converted ``park_snapshot`` Parquet; rows come from ``event_row``."""
    return plant_events(parquet_dir, "park_snapshot", rows)


def plant_save_written(parquet_dir: Path, rows: list[Row]) -> Path:
    """Converted ``save_written`` Parquet; rows come from ``event_row`` with a ``save_id``."""
    return plant_events(parquet_dir, "save_written", rows)


def plant_session_start(parquet_dir: Path, rows: list[Row]) -> Path:
    """Converted ``session_start`` Parquet; rows come from ``event_row`` with a ``park_name``."""
    return plant_events(parquet_dir, "session_start", rows)


def _stamp(moment: datetime) -> str:
    return (
        moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03}Z"
    )


def plant_record(
    save_dir: Path,
    file_name: str,
    modified_at: datetime,
    size_bytes: int,
    *,
    run_started_at: datetime = T0,
    folder_kind: str = "save",
) -> None:
    """Append one watcher record to ``<save_dir>/v1/save_file_observation_<date>.jsonl``."""
    folder = save_dir / "v1"
    folder.mkdir(parents=True, exist_ok=True)
    line = {
        "run_started_at": _stamp(run_started_at),
        "observation": "modified",
        "file_name": file_name,
        "folder_kind": folder_kind,
        "modified_at": _stamp(modified_at),
        "size_bytes": size_bytes,
        "observed_at": _stamp(modified_at),
    }
    path = folder / f"save_file_observation_{run_started_at:%Y-%m-%d}.jsonl"
    with path.open("a", encoding="utf-8") as out:
        out.write(json.dumps(line) + "\n")


def plant_paired_save(save_dir: Path, row: Row, file_name: str, size_bytes: int) -> Row:
    """Write the save-file record that pairs with ``row`` (a ``save_written`` row) and return it.

    The record is modified 200 ms after ``row``'s ``emitted_at``, inside the 5 s pairing window,
    and its run starts 30 minutes before; with no other record of the file near it the pair is
    one-to-one. The caller gathers the rows and writes them with ``plant_save_written``.
    """
    emitted_at = row["emitted_at"]
    assert isinstance(emitted_at, datetime)
    plant_record(
        save_dir,
        file_name,
        emitted_at + timedelta(milliseconds=200),
        size_bytes,
        run_started_at=emitted_at - timedelta(minutes=30),
    )
    return row


def plant_archive_copy(
    archive_dir: Path,
    park_id: str,
    label: str,
    ended: datetime,
    *,
    data: bytes,
    modified_at: datetime,
) -> Path:
    """Write ``<archive_dir>/<park_id>/<label>-<YYYY-MM-DD-HHMMSS>.park`` with a set mtime."""
    path = archive_dir / park_id / f"{label}-{ended:%Y-%m-%d-%H%M%S}.park"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    modified_ns = int(modified_at.timestamp() * 1_000_000) * 1000
    os.utime(path, ns=(modified_ns, modified_ns))
    return path


def _csv_text(header: tuple[str, ...], rows: list[tuple[object, ...]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def plant_registry(
    feed_dir: Path,
    rows: list[tuple[str, int, int, str, str, str]],
    *,
    name: str = "park_registry_2026-11-12_01.csv",
) -> Path:
    """Write a registry delivery into ``feed_dir`` (a ``registry/v1`` folder).

    Each row is (park_id, company_start_year, game_year_origin, data_set, note, delivered_on),
    the order of ``registry_feed.HEADER``. A practice park's note is ``register_parks.NOTE``.
    """
    feed_dir.mkdir(parents=True, exist_ok=True)
    path = feed_dir / name
    path.write_text(_csv_text(REGISTRY_HEADER, list(rows)), encoding="utf-8")
    return path


def plant_label(
    feed_dir: Path,
    rows: list[tuple[str, str, str, str, str, str]],
    *,
    name: str = "session_play_mode_2026-11-12_01.csv",
) -> Path:
    """Write a session-label delivery as plain CSV text with the section 7 header.

    Each row is (session_id, park_id, play_mode, ready_confirmation, data_set, delivered_on).
    """
    feed_dir.mkdir(parents=True, exist_ok=True)
    path = feed_dir / name
    path.write_text(_csv_text(LABEL_HEADER, list(rows)), encoding="utf-8")
    return path

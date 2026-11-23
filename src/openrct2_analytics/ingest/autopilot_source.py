"""Find a park's last recorded save in the archive and prove it is the last one recorded.

The autopilot year starts from the newest archive copy of the park (``save_backup``), taken by the
time at the end of its name, not by the full name, which starts with the park's name. The copy
counts only when the park's latest ``save_written`` event (by ``emitted_at``, across every run)
pairs with exactly one save-file record, the copy has that record's size, and the copy was
modified at or after the record's modified time (the copy is written after the save). The time in
the copy's name is local time with no zone and is never compared with ``emitted_at``.

A refusal comes back as a ``SourceRefused`` holding the text of refusals 14, 15 and 16
(docs/ai-dlc/specs/autopilot-year.md, section 4); the command adds "Nothing was written." and
the exit code. This module only reads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb

from openrct2_analytics.ingest.contracts import LANDING_FOLDER
from openrct2_analytics.ingest.save_backup import (
    ARCHIVE_TIME_FORMAT,
    EPOCH,
    PARK_SUFFIX,
    archive_files,
    file_label,
    milliseconds,
)
from openrct2_analytics.ingest.save_files import (
    SAVE_WRITTEN_FILE,
    read_records,
    read_save_written,
)
from openrct2_analytics.ingest.save_pairing import (
    SaveFileRecord,
    SavePair,
    SaveWrittenRow,
    pair_every_run,
)

_NAME_TIME = re.compile(r"-(\d{4}-\d\d-\d\d-\d{6})" + re.escape(PARK_SUFFIX) + r"$")


@dataclass(frozen=True)
class SourceFound:
    """The proven source save and the facts of its paired ``save_written`` event."""

    file: Path
    event_id: str
    save_id: str
    session_id: str
    game_year: int
    game_month: int
    game_day: int
    seq: int


@dataclass(frozen=True)
class SourceRefused:
    """A refusal: its number in section 4 and its message text."""

    number: int
    message: str


def _name_time(path: Path) -> datetime | None:
    match = _NAME_TIME.search(path.name)
    return datetime.strptime(match.group(1), ARCHIVE_TIME_FORMAT) if match else None


def newest_copy(park_archive: Path) -> Path | None:
    """Return the archive copy with the latest time at the end of its name, or None."""
    timed = [(when, path) for path in archive_files(park_archive) if (when := _name_time(path))]
    return max(timed, default=(None, None))[1]


def _latest_row(rows: list[SaveWrittenRow], park_id: str) -> SaveWrittenRow | None:
    mine = [r for r in rows if r.park_id == park_id]
    return max(mine, key=lambda r: (r.emitted_at, r.event_id), default=None)


def _paired(
    row: SaveWrittenRow, records: list[SaveFileRecord], rows: list[SaveWrittenRow]
) -> SavePair | None:
    """The one pair of ``row`` across all runs, or None when it has none or more than one."""
    pairs = [
        pair
        for run in pair_every_run(records, rows).values()
        for pair in run.pairs
        if pair.row.event_id == row.event_id
    ]
    return pairs[0] if len(pairs) == 1 else None


def _event_facts(parquet_dir: Path, event_id: str) -> tuple[int, int, int, int]:
    """The game date and ``seq`` of one ``save_written`` event, read by ``event_id``."""
    path = parquet_dir / LANDING_FOLDER / SAVE_WRITTEN_FILE
    with duckdb.connect(":memory:") as connection:
        found = connection.execute(
            "SELECT game_year, game_month, game_day, seq FROM read_parquet(?) WHERE event_id = ?",
            [path.as_posix(), event_id],
        ).fetchall()
    return found[0]


def _modified_at_or_after(path: Path, record: SaveFileRecord) -> bool:
    return path.stat().st_mtime_ns >= milliseconds(record.modified_at) * 1_000_000


def find_source(
    park_id: str, archive_dir: Path, parquet_dir: Path, save_dir: Path
) -> SourceFound | SourceRefused:
    """Return the park's proven source save, or the refusal that stops the run.

    Args:
        park_id: The company park.
        archive_dir: The archive root; the park's copies are in ``<archive_dir>/<park folder>/``.
        parquet_dir: The converted Parquet folder holding ``v1/save_written.parquet``.
        save_dir: The save-file folder holding the watcher's ``v1/`` record files.

    Raises:
        OSError: if a file cannot be read.
        duckdb.Error: if the ``save_written`` Parquet cannot be read.
    """
    park_archive = archive_dir / file_label(None, park_id)
    copy = newest_copy(park_archive)
    if copy is None:
        return SourceRefused(
            14,
            f"Park {park_id} has no backup in {park_archive}/. Play and save it with make play "
            "DATA_SET=company, quit normally, and check that the report prints a Backup: line.",
        )
    rows = read_save_written(parquet_dir)
    latest = _latest_row(rows, park_id)
    # Unreadable record lines are not listed here: a lost record leaves its event unpaired, and an
    # unpaired latest event is refusal 15.
    records, _ = read_records(save_dir, EPOCH)  # the start only attributes unreadable lines
    pair = None if latest is None else _paired(latest, records, rows)
    if latest is None or pair is None:
        recorded = "at an unknown time" if latest is None else latest.emitted_at.isoformat()
        return SourceRefused(
            15,
            f"The last save of park {park_id} (recorded {recorded}) was not matched to exactly "
            "one save file, so its last recorded save is unknown. Play and save it once with "
            "make play DATA_SET=company.",
        )
    record = pair.record
    if copy.stat().st_size != record.size_bytes or not _modified_at_or_after(copy, record):
        return SourceRefused(
            16,
            f"The newest backup of park {park_id} ({copy}) is not its last recorded save "
            f"({record.file_name}{PARK_SUFFIX}, recorded {latest.emitted_at.isoformat()}); "
            "starting from it would drop the play recorded after it. Play and save once with "
            "make play DATA_SET=company so a new backup is made.",
        )
    year, month, day, seq = _event_facts(parquet_dir, latest.event_id)
    return SourceFound(
        copy, latest.event_id, latest.save_id, latest.session_id, year, month, day, seq
    )

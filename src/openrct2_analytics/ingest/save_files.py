"""Find, read and check the save-file observation records the capture-time watcher writes.

``save_file_observation_<YYYY-MM-DD>.jsonl`` files land under ``data/<data set>/save_files/v1/``
(``save_watch.py``). This module derives that folder from the landing folders and refuses a folder
that aliases another landing folder, reads the records and the ``save_written`` events for the
report, and checks the files against ``contracts/reference/save_file_observation.odcs.yaml``
through one throwaway DuckDB view. It never writes, moves or deletes a record file.
Requirement numbers such as R12 refer to docs/ai-dlc/specs/save-file-watcher.md.

Run it with ``python -m openrct2_analytics.ingest.save_files``, giving exactly one of
``--data-set {rehearsal,company}``, ``--data-root PATH`` (the records are in ``PATH/save_files``)
and ``--file PATH`` (one file, checked alone). Exit 0 is clean, 1 a failed check, 2 a refusal.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from openrct2_analytics.config import DATA_SETS, ConfigError, landing_dirs
from openrct2_analytics.ingest.contracts import CONTRACTS_DIR, LANDING_FOLDER, run_contract
from openrct2_analytics.ingest.registry_feed import FEED_FOLDER, absolute_path, refuse_aliases
from openrct2_analytics.ingest.save_pairing import (
    RECORD_FILE_GLOB,
    RECORD_FOLDER,
    SaveFileRecord,
    SaveWrittenRow,
    UnreadableLine,
)

SAVE_FILES_FOLDER = "save_files"
CONTRACT_PATH = CONTRACTS_DIR / "reference" / "save_file_observation.odcs.yaml"
VIEW_NAME = "save_file_observation"
SAVE_WRITTEN_FILE = "save_written.parquet"
FIELDS = (
    "run_started_at",
    "observation",
    "file_name",
    "folder_kind",
    "modified_at",
    "size_bytes",
    "observed_at",
)
_TIMESTAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z")


def save_files_dir(data_set: str) -> Path:
    """Return the folder holding the ``v1/`` record files of ``data_set``.

    The path is as configured (it may be relative to the project folder).

    Raises:
        ConfigError: if ``data_set`` is unknown or the folder equals, contains or lies inside any
            raw or Parquet folder, either registry feed (or its ``v1``) or the other data set's
            save-file folder (or its ``v1``), or if the folder or its ``v1`` resolves outside the
            data set's own folder, after resolving links.
    """
    others: list[Path] = []
    for name in DATA_SETS:
        dirs = landing_dirs(name)
        folders = [dirs.raw, dirs.parquet, dirs.raw.parent / FEED_FOLDER]
        if name != data_set:
            folders.append(dirs.raw.parent / SAVE_FILES_FOLDER)
        others += folders
        others += [folder / LANDING_FOLDER for folder in folders[2:]]
    data_folder = landing_dirs(data_set).raw.parent
    own = data_folder / SAVE_FILES_FOLDER
    refuse_aliases(f"{data_set} save-file folder", own, others)
    # A link leading out of the data set would send the watcher's writes elsewhere.
    inside = absolute_path(data_folder)
    for folder in (own, own / RECORD_FOLDER):
        if not absolute_path(folder).is_relative_to(inside):
            raise ConfigError(
                f"The {data_set} save-file folder {folder} resolves outside the data set "
                f"folder {inside}"
            )
    return own


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:  # a shape-correct but impossible date, such as month 13
        return None


def _parse_line(raw: bytes) -> SaveFileRecord | None:
    """Return the record in one line, or None when it is not JSON with the seven fields."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):  # a torn or damaged line is reported
        return None
    if not isinstance(data, dict) or any(field not in data for field in FIELDS):
        return None
    run_started = _parse_timestamp(data["run_started_at"])
    modified = _parse_timestamp(data["modified_at"])
    observed = _parse_timestamp(data["observed_at"])
    size, observation, name, kind = (
        data["size_bytes"],
        data["observation"],
        data["file_name"],
        data["folder_kind"],
    )
    if (
        run_started is None
        or modified is None
        or observed is None
        or isinstance(size, bool)
        or not isinstance(size, int)
        or not isinstance(observation, str)
        or not isinstance(name, str)
        or not isinstance(kind, str)
    ):
        return None
    return SaveFileRecord(run_started, observation, name, kind, modified, size, observed)


def _read_file(path: Path) -> tuple[list[SaveFileRecord], list[int]]:
    """Return the readable records of one file and the line numbers it could not read."""
    records: list[SaveFileRecord] = []
    unreadable: list[int] = []
    lines = path.read_bytes().split(b"\n")
    if lines[-1] == b"":  # the newline that ends the last line
        lines.pop()
    for number, raw in enumerate(lines, start=1):
        record = _parse_line(raw)
        if record is None:
            unreadable.append(number)
        else:
            records.append(record)
    return records, unreadable


def read_records(
    folder: Path, started: datetime
) -> tuple[list[SaveFileRecord], list[UnreadableLine]]:
    """Read every record file under ``folder/v1``; attribute unreadable lines by file.

    Args:
        folder: The save-file folder holding ``v1/``.
        started: This run's start, aware UTC. A file modified at or after it belongs to this run.

    Returns:
        The readable records of every file, and one ``UnreadableLine`` per line that is not JSON
        with the seven record fields (file name, line number, and whether the file is this run's).
        The rest of each file is still read. Times in the records are aware UTC.
    """
    records: list[SaveFileRecord] = []
    unreadable: list[UnreadableLine] = []
    for path in sorted((folder / RECORD_FOLDER).glob(RECORD_FILE_GLOB)):
        found, bad = _read_file(path)
        records += found
        this_run = datetime.fromtimestamp(path.stat().st_mtime, UTC) >= started
        unreadable += [UnreadableLine(path.name, number, this_run) for number in bad]
    return records, unreadable


def read_save_written(parquet_dir: Path) -> list[SaveWrittenRow]:
    """Read ``<parquet_dir>/v1/save_written.parquet``; an absent file means no rows."""
    path = parquet_dir / LANDING_FOLDER / SAVE_WRITTEN_FILE
    if not path.is_file():
        return []
    connection = duckdb.connect()
    try:
        rows = connection.execute(
            "SELECT event_id, save_id, park_id, session_id, emitted_at, received_at,"
            " _raw_file, _raw_line FROM read_parquet(?)",
            [path.as_posix()],
        ).fetchall()
    finally:
        connection.close()
    return [
        SaveWrittenRow(
            event_id,
            save_id,
            park_id,
            session_id,
            emitted.astimezone(UTC),
            received.astimezone(UTC),
            raw_file,
            raw_line,
        )
        for event_id, save_id, park_id, session_id, emitted, received, raw_file, raw_line in rows
    ]


# Every column is read as text, then the typed columns are cast only when the whole cell has the
# right shape, as in ``registry_feed``. A bad cell becomes NULL, which the contract's `required`
# check rejects, the same way alone and landed. A line DuckDB cannot read is skipped here; the
# reader reports it.
VIEW_SQL = """
CREATE VIEW {view} AS SELECT
    CASE WHEN regexp_full_match(run_started_at, '{stamp}')
        THEN TRY_CAST(run_started_at AS TIMESTAMPTZ) END AS run_started_at,
    observation,
    file_name,
    folder_kind,
    CASE WHEN regexp_full_match(modified_at, '{stamp}')
        THEN TRY_CAST(modified_at AS TIMESTAMPTZ) END AS modified_at,
    CASE WHEN regexp_full_match(size_bytes, '-?[0-9]+')
        THEN TRY_CAST(size_bytes AS BIGINT) END AS size_bytes,
    CASE WHEN regexp_full_match(observed_at, '{stamp}')
        THEN TRY_CAST(observed_at AS TIMESTAMPTZ) END AS observed_at
FROM read_json('{pattern}', format='newline_delimited', ignore_errors=true,
    columns={{{columns}}})
"""


def _check_files(files_glob: str) -> list[str]:
    """Lint the contract and test the record files matching ``files_glob`` against it."""
    pattern = files_glob.replace("'", "''")
    columns = ", ".join(f"{name}: 'VARCHAR'" for name in FIELDS)
    sql = VIEW_SQL.format(
        view=VIEW_NAME, stamp=_TIMESTAMP.pattern, pattern=pattern, columns=columns
    )

    def prepare(database: Path) -> None:
        connection = duckdb.connect(str(database))
        try:
            connection.execute(sql)
        finally:
            connection.close()

    try:
        return run_contract(
            CONTRACT_PATH.read_text(encoding="utf-8"), prepare, prefix="save-files-"
        )
    except duckdb.Error as exc:
        # A file DuckDB cannot read is a failed check with the reason.
        return [f"test cannot read the records: {exc}"]


def _unreadable_problems(path: Path) -> list[str]:
    _, unreadable = _read_file(path)
    return [f"{path.name}: line {number} is not a record" for number in unreadable]


def check_file(path: Path) -> list[str]:
    """Check one record file against the contract; return one line per problem."""
    return _unreadable_problems(path) + _check_files(path.as_posix())


def check_folder(folder: Path) -> list[str]:
    """Check every ``v1/save_file_observation_*.jsonl`` under ``folder`` against the contract.

    Returns:
        One line per problem, or an empty list when the folder passes or holds no record files.
        When the contract check fails, each file is checked alone and every failing file is
        named. An unreadable line fails the check, naming the file and line.
    """
    files = sorted((folder / RECORD_FOLDER).glob(RECORD_FILE_GLOB))
    problems = [line for path in files for line in _unreadable_problems(path)]
    if files:
        contract = _check_files((folder / RECORD_FOLDER / RECORD_FILE_GLOB).as_posix())
        if contract:
            problems += contract
            for path in files:
                problems += [f"{path.name}: {line}" for line in _check_files(path.as_posix())]
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    """Check the records; return 0 when clean, 1 on a failed check, 2 on a refusal."""
    parser = argparse.ArgumentParser(description=__doc__)
    chosen = parser.add_mutually_exclusive_group(required=True)
    chosen.add_argument("--data-set", choices=DATA_SETS, help="Data set whose records to check")
    chosen.add_argument("--data-root", type=Path, help="Folder whose save_files/ folder to check")
    chosen.add_argument("--file", type=Path, help="One record file to check alone")
    args = parser.parse_args(argv)
    if args.file is not None:
        if not args.file.is_file():
            print(f"{args.file} is not a file. Nothing was checked.")
            return 2
        problems = check_file(args.file)
    else:
        if args.data_root is not None:
            folder: Path = args.data_root / SAVE_FILES_FOLDER
        else:
            try:
                folder = absolute_path(save_files_dir(args.data_set))
            except ConfigError as exc:
                print(f"{exc}. Nothing was checked.")
                return 2
        if not any((folder / RECORD_FOLDER).glob(RECORD_FILE_GLOB)):
            print(f"No save-file records in {folder}.")
            return 0
        problems = check_folder(folder)
    for problem in problems:
        print(f"{CONTRACT_PATH.name}: {problem}")
    if problems:
        return 1
    print("The save-file record check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Find, read and check the play-mode label feed: dated CSV deliveries, one contract.

``session_play_mode_<YYYY-MM-DD>_<NN>.csv`` files land beside the park registry under
``data/<data set>/registry/v1/`` and say, per session, whether it was ``managed`` or
``autopilot``. A session with no row is managed. This module owns the file name shape, the ready
phrase, a reader of the labels for the managed-years reader and the autopilot landing, and the
checker against
``contracts/reference/session_play_mode.odcs.yaml``. The checker can take staged files, given
with their final names, and checks them together with the folder's existing deliveries. It never
writes, moves or deletes a feed file.

Run it with ``python -m openrct2_analytics.ingest.play_mode_feed``, giving exactly one of
``--data-set {rehearsal,company}`` and ``--data-root PATH`` (the feed is ``PATH/registry``).
Exit 0 is clean, 1 a failed check, 2 a refusal. A folder with no label file is clean.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import duckdb

from openrct2_analytics.config import DATA_SETS, ConfigError
from openrct2_analytics.ingest.contracts import CONTRACTS_DIR, LANDING_FOLDER, run_contract
from openrct2_analytics.ingest.registry_feed import (
    FEED_FOLDER,
    INCOMING,
    absolute_path,
    registry_dir,
)

CONTRACT_PATH = CONTRACTS_DIR / "reference" / "session_play_mode.odcs.yaml"
VIEW_NAME = "session_play_mode"
FILE_GLOB = "session_play_mode_*.csv"
HEADER = ("session_id", "park_id", "play_mode", "ready_confirmation", "data_set", "delivered_on")
# ASCII digits, whole name; sequence 01 to 99 (00 is refused below).
_NAME_SHAPE = re.compile(r"session_play_mode_([0-9]{4}-[0-9]{2}-[0-9]{2})_([0-9]{2})\.csv")
AUTOPILOT = "autopilot"
READY_SUFFIX = " is profitable and its scenario challenge is complete"


def ready_phrase(park_id: str) -> str:
    """Return the phrase a park's first autopilot row must carry in ``ready_confirmation``."""
    return f"{park_id}{READY_SUFFIX}"


def is_accepted_name(name: str) -> bool:
    """Return whether the feed reads a delivery with this base name (sequence 01 to 99)."""
    match = _NAME_SHAPE.fullmatch(name)
    return match is not None and match.group(2) != "00"


@dataclass(frozen=True)
class PlayLabel:
    """One labeled session: its park, its play mode and its ready confirmation (or None)."""

    session_id: str
    park_id: str
    play_mode: str
    ready_confirmation: str | None


def _matching_files(feed_root: Path) -> list[Path]:
    """Return every file under ``feed_root/v1`` that matches the label glob, by file name."""
    return sorted((feed_root / LANDING_FOLDER).glob(FILE_GLOB), key=lambda path: path.name)


def delivery_files(feed_root: Path) -> list[Path]:
    """Return the accepted label files under ``feed_root/v1`` in delivery order (file name)."""
    return [path for path in _matching_files(feed_root) if is_accepted_name(path.name)]


def read_labels(feed_root: Path) -> dict[str, PlayLabel]:
    """Read every label file under ``feed_root`` into a map from session to its label.

    A session in no file is managed; callers apply that default. Files are read in delivery
    order, so a repeated session (which the checker refuses) keeps its last row.
    """
    labels: dict[str, PlayLabel] = {}
    for path in delivery_files(feed_root):
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                labels[row["session_id"]] = PlayLabel(
                    session_id=row["session_id"],
                    park_id=row["park_id"],
                    play_mode=row["play_mode"],
                    ready_confirmation=row["ready_confirmation"] or None,
                )
    return labels


# Every column is read as text. row_order follows the line order of each file because DuckDB's
# window over the CSV read streams on a single thread; parallel=false is kept as an extra guard.
# The "first autopilot row" rule reads it.
VIEW_SQL = """
CREATE VIEW {view} AS SELECT
    session_id,
    park_id,
    play_mode,
    NULLIF(ready_confirmation, '') AS ready_confirmation,
    data_set,
    TRY_CAST(delivered_on AS DATE) AS delivered_on,
    park_id || '{suffix}' AS ready_phrase,
    regexp_extract(filename, '[^/]*$') AS file_name,
    TRY_CAST(regexp_extract(regexp_extract(filename, '[^/]*$'), '{date_pattern}', 1) AS DATE)
        AS file_date,
    {expected} AS expected_data_set,
    row_order
FROM (
    SELECT *, row_number() OVER () AS row_order
    FROM read_csv([{files}], header=true, union_by_name=true, all_varchar=true,
                  filename=true, parallel=false)
)
"""


def _quoted(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _check_files(files: Sequence[Path], data_set: str | None) -> list[str]:
    """Lint the contract and test the CSV ``files`` (given in any order) against it."""
    expected = _quoted(data_set) if data_set else "data_set"
    view = VIEW_SQL.format(
        view=VIEW_NAME,
        suffix=READY_SUFFIX,
        date_pattern=_NAME_SHAPE.pattern,
        expected=expected,
        files=", ".join(_quoted(path.as_posix()) for path in files),
    )

    def prepare(database: Path) -> None:
        connection = duckdb.connect(str(database))
        try:
            connection.execute(view)
        finally:
            connection.close()

    try:
        return run_contract(
            CONTRACT_PATH.read_text(encoding="utf-8"), prepare, prefix="play-mode-feed-"
        )
    except duckdb.Error as exc:
        # A file DuckDB cannot read, or one missing a column, is a failed check with the reason.
        return [f"test cannot read the CSV: {exc}"]


def _header_problems(files: Sequence[Path]) -> list[str]:
    """Report each file whose first line is not exactly ``HEADER``."""
    problems: list[str] = []
    for path in files:
        with path.open(encoding="utf-8", newline="") as stream:
            first = next(csv.reader(stream), [])
        if tuple(first) != HEADER:
            problems.append(f"{path.name}: header is not {','.join(HEADER)}")
    return problems


def _data_set_problems(files: Sequence[Path]) -> list[str]:
    """Report rows that name more than one data set (used when the folder's data set is unknown)."""
    names: set[str] = set()
    for path in files:
        with path.open(encoding="utf-8", newline="") as stream:
            names.update(row.get("data_set") or "" for row in csv.DictReader(stream))
    names.discard("")
    if len(names) > 1:
        return [f"rows name more than one data set: {', '.join(sorted(names))}"]
    return []


def check_feed(
    feed_root: Path, staged: Sequence[Path] = (), data_set: str | None = None
) -> list[str]:
    """Check the label files under ``feed_root`` and any ``staged`` files against the contract.

    ``staged`` files are given with their final names and are checked together with the
    folder's existing deliveries. ``data_set`` is the folder's data set; None checks only that
    each row names rehearsal or company.

    Returns:
        One line per problem, or an empty list when the folder passes. A folder with no label
        file is clean.
    """
    problems: list[str] = []
    files: dict[str, Path] = {}
    for path in _matching_files(feed_root):
        if is_accepted_name(path.name):
            files[path.name] = path
        else:
            problems.append(
                f"bad file name: {path.name} is not session_play_mode_YYYY-MM-DD_NN.csv"
            )
    for path in staged:
        if path.name.startswith(INCOMING):
            problems.append(f"staged file {path.name} does not have its final name")
        elif not is_accepted_name(path.name):
            problems.append(
                f"bad file name: staged {path.name} is not session_play_mode_YYYY-MM-DD_NN.csv"
            )
        elif path.name in files:
            problems.append(f"staged file {path.name} is already delivered in {feed_root}")
        else:
            files[path.name] = path
    if files:
        problems += _header_problems(list(files.values()))
        if data_set is None:
            problems += _data_set_problems(list(files.values()))
        problems += _check_files(list(files.values()), data_set)
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    """Check the feed; return 0 when clean, 1 on a failed check, 2 on a refusal."""
    parser = argparse.ArgumentParser(description=__doc__)
    chosen = parser.add_mutually_exclusive_group(required=True)
    chosen.add_argument("--data-set", choices=DATA_SETS, help="Data set whose feed to check")
    chosen.add_argument("--data-root", type=Path, help="Folder whose registry/ folder to check")
    args = parser.parse_args(argv)
    if args.data_root is not None:
        feed_root: Path = args.data_root / FEED_FOLDER
        data_set = (
            args.data_root.resolve().name if args.data_root.resolve().name in DATA_SETS else None
        )
    else:
        try:
            feed_root = absolute_path(registry_dir(args.data_set))
        except ConfigError as exc:
            print(f"{exc}. Nothing was checked.")
            return 2
        data_set = args.data_set
    problems = check_feed(feed_root, data_set=data_set)
    for problem in problems:
        print(f"{CONTRACT_PATH.name}: {problem}")
    if problems:
        return 1
    print("The play-mode feed check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

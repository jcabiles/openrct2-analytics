"""Find and check the park registry feed: dated CSV deliveries, one contract.

``park_registry_<YYYY-MM-DD>_<NN>.csv`` files land under ``data/<data set>/registry/v1/``: for
the rehearsal data set from the rehearsal capture command (ADR 0036), for company from
``make register-parks`` (ADR 0038). This module derives that folder from the landing folders,
refuses a folder that aliases
another data set's feed or any raw or Parquet folder, and checks the files against
``contracts/reference/park_registry.odcs.yaml`` through one throwaway DuckDB view.
It never writes, moves or deletes a feed file; only a pre-go-live company delete may (ADR 0033).

Run it with ``python -m openrct2_analytics.ingest.registry_feed``, giving exactly one of
``--data-set {rehearsal,company}``, ``--data-root PATH`` (the feed is ``PATH/registry``) and
``--file PATH`` (one file, checked alone before it is landed). Exit 0 is clean, 1 a failed check,
2 a refusal.
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

from openrct2_analytics.config import DATA_SETS, ConfigError, landing_dirs
from openrct2_analytics.ingest.contracts import (
    CONTRACTS_DIR,
    LANDING_FOLDER,
    run_contract,
)
from openrct2_analytics.ingest.landing_paths import project_path

# Relative landing paths (``OPENRCT2_DATA_DIR`` or the default ``data``) resolve against the project
# folder, as ``publish_snapshot.take_snapshot`` does, not against the working directory.
PROJECT_DIR = Path(__file__).resolve().parents[3]
FEED_FOLDER = "registry"
CONTRACT_PATH = CONTRACTS_DIR / "reference" / "park_registry.odcs.yaml"
VIEW_NAME = "park_registry"
FILE_GLOB = "park_registry_*.csv"
HEADER = ("park_id", "company_start_year", "game_year_origin", "data_set", "note", "delivered_on")
INCOMING = ".incoming-"
PRACTICE_NOTE = "Throwaway practice park; not company data."
# ASCII digits, whole name; mirrors the name rule in int_park_registry__history.sql.
_NAME_SHAPE = re.compile(r"park_registry_[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}\.csv")


def is_accepted_name(name: str) -> bool:
    """Return whether the warehouse reads a delivery with this base name (sequence 01 to 99)."""
    return _NAME_SHAPE.fullmatch(name) is not None and name[25:27] != "00"


@dataclass(frozen=True)
class RegistryRow:
    """One park's latest registry row."""

    company_start_year: int
    game_year_origin: int
    data_set: str
    practice: bool


def latest_rows(feed: Path) -> dict[str, RegistryRow]:
    """Return each park's latest registry row, from the deliveries in ``feed`` (a ``v1`` folder).

    Deliveries are ordered by file name (its date, then its sequence), as
    ``int_park_registry__history.sql`` orders them, and a later row replaces an earlier one. Only
    deliveries the warehouse reads by name count. The feed check is the caller's job.
    """
    latest: dict[str, RegistryRow] = {}
    for path in sorted(feed.glob(FILE_GLOB), key=lambda found: found.name):
        if not is_accepted_name(path.name):
            continue
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                latest[row["park_id"]] = RegistryRow(
                    company_start_year=int(row["company_start_year"]),
                    game_year_origin=int(row["game_year_origin"]),
                    data_set=row["data_set"],
                    practice=row["note"] == PRACTICE_NOTE,
                )
    return latest


def absolute_path(path: Path) -> Path:
    """Return ``path`` resolved, a relative one against the project folder."""
    return project_path(path, PROJECT_DIR).resolve()


def refuse_aliases(label: str, own: Path, others: Sequence[Path]) -> None:
    """Raise ConfigError when ``own`` or its ``v1`` aliases any of ``others``.

    Aliasing means equals, contains or lies inside.
    Paths are compared after resolving links, relative ones against the project folder.
    ``label`` names the folder in the message, such as "rehearsal feed folder".
    """
    mine = [absolute_path(own), absolute_path(own / LANDING_FOLDER)]
    for folder in mine:
        for other in others:
            resolved = absolute_path(other)
            if (
                folder == resolved
                or folder.is_relative_to(resolved)
                or resolved.is_relative_to(folder)
            ):
                raise ConfigError(
                    f"The {label} {own} equals, contains or lies inside {other}"
                    f" (resolving to {folder} and {resolved})"
                )


def registry_dir(data_set: str) -> Path:
    """Return the folder holding the ``v1/`` deliveries of ``data_set``.

    The path is as configured (it may be relative to the project folder).

    Raises:
        ConfigError: if ``data_set`` is unknown or the feed folder equals, contains or lies inside
            the other data set's feed folder or any raw or Parquet folder, after resolving links.
    """
    others: list[Path] = []
    for name in DATA_SETS:
        dirs = landing_dirs(name)
        others += [dirs.raw, dirs.parquet]
        if name != data_set:
            feed = dirs.raw.parent / FEED_FOLDER
            others += [feed, feed / LANDING_FOLDER]
    own = landing_dirs(data_set).raw.parent / FEED_FOLDER
    refuse_aliases(f"{data_set} feed folder", own, others)
    return own


# Every column is read as text, then the typed columns are cast only when the whole cell has the
# right shape. A cast of 1.5 or 1e3 to BIGINT rounds silently, and type detection on a header-only
# file differs from the same file among others. A bad cell becomes NULL, which the contract's
# `required` check rejects, the same way alone and landed.
VIEW_SQL = """
CREATE VIEW {view} AS SELECT
    park_id,
    CASE WHEN regexp_full_match(company_start_year, '-?[0-9]+')
        THEN CAST(company_start_year AS BIGINT) END AS company_start_year,
    CASE WHEN regexp_full_match(game_year_origin, '-?[0-9]+')
        THEN CAST(game_year_origin AS BIGINT) END AS game_year_origin,
    data_set,
    note,
    TRY_CAST(delivered_on AS DATE) AS delivered_on
FROM read_csv('{pattern}', header=true, union_by_name=true, all_varchar=true)
"""


def _check_files(files_glob: str) -> list[str]:
    """Lint the contract and test the CSV files matching ``files_glob`` against it."""
    pattern = files_glob.replace("'", "''")

    def prepare(database: Path) -> None:
        connection = duckdb.connect(str(database))
        try:
            connection.execute(VIEW_SQL.format(view=VIEW_NAME, pattern=pattern))
        finally:
            connection.close()

    try:
        return run_contract(
            CONTRACT_PATH.read_text(encoding="utf-8"), prepare, prefix="registry-feed-"
        )
    except duckdb.Error as exc:
        # A file DuckDB cannot read, or one missing a column, is a failed check with the reason.
        return [f"test cannot read the CSV: {exc}"]


def check_file(path: Path) -> list[str]:
    """Check one CSV file against the feed contract; return one line per problem."""
    return _check_files(path.as_posix())


def check_feed(feed_root: Path) -> list[str]:
    """Check every ``v1/park_registry_*.csv`` under ``feed_root`` against the feed contract.

    Returns:
        One line per problem, or an empty list when the folder passes. An empty folder fails,
        naming it. When the folder fails, each file is checked alone and every failing file is
        named.
    """
    folder = feed_root / LANDING_FOLDER
    files = sorted(folder.glob(FILE_GLOB))
    if not files:
        return [f"no delivery files matching {FILE_GLOB} in {folder}"]
    problems = _check_files((folder / FILE_GLOB).as_posix())
    if problems:
        for path in files:
            problems += [f"{path.name}: {line}" for line in check_file(path)]
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    """Check the feed; return 0 when clean, 1 on a failed check, 2 on a refusal."""
    parser = argparse.ArgumentParser(description=__doc__)
    chosen = parser.add_mutually_exclusive_group(required=True)
    chosen.add_argument("--data-set", choices=DATA_SETS, help="Data set whose feed to check")
    chosen.add_argument("--data-root", type=Path, help="Folder whose registry/ folder to check")
    chosen.add_argument("--file", type=Path, help="One CSV file to check alone")
    args = parser.parse_args(argv)
    if args.file is not None:
        problems = check_file(args.file)
    else:
        if args.data_root is not None:
            feed_root: Path = args.data_root / FEED_FOLDER
        else:
            try:
                feed_root = absolute_path(registry_dir(args.data_set))
            except ConfigError as exc:
                print(f"{exc}. Nothing was checked.")
                return 2
        problems = check_feed(feed_root)
    for problem in problems:
        print(f"{CONTRACT_PATH.name}: {problem}")
    if problems:
        return 1
    print("The registry feed check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Write or check the site's JSON exports from allowlisted mart relations.

The sample record ``sample.json`` also reads ``staging.stg_session_start``, because the session
counts and the player flag (``headless``) live there and no mart holds them.

Exit codes follow the publish module: 0 done, 1 failed (a mismatch), 2 refused, 130 interrupted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from openrct2_analytics.ingest.lock import Interrupted, raise_interrupted, set_signal_handlers

DEFAULT_ALLOWLIST = Path("site/exports.toml")
DEFAULT_SERVED_DIR = Path("site/_data")
_RELATION = re.compile(r"marts\.[a-z_][a-z0-9_]*")
_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*")
_FILE_NAME = re.compile(r"[A-Za-z0-9_.-]+")
DEFAULT_DATA_SET = "sample"
SAMPLE_SOURCES = ("marts.obt_park_year", "marts.fct_park_day", "staging.stg_session_start")


class ExportRefused(Exception):
    """The request cannot run: exit 2."""


class ExportFailed(Exception):
    """A served copy differs from the marts: exit 1."""


@dataclass(frozen=True)
class Entry:
    """One allowlist entry."""

    name: str
    relation: str
    output: str
    columns: tuple[str, ...]
    order_by: tuple[str, ...]


SAMPLE_ENTRY = Entry(
    name="sample",
    relation=", ".join(SAMPLE_SOURCES),
    output="sample.json",
    columns=("data_set", "parks", "sessions", "player_played"),
    order_by=("data_set",),
)


def load_allowlist(path: Path) -> list[Entry]:
    """Read the allowlist; refuse any entry outside the marts schema."""
    if not path.is_file():
        raise ExportRefused(f"allowlist not found: {path}")
    try:
        with path.open("rb") as handle:
            document = tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        raise ExportRefused(f"allowlist {path} is not valid TOML: {error}") from error
    stray_keys = sorted(key for key in document if key != "export")
    if stray_keys:
        raise ExportRefused(f"allowlist {path} has unknown top-level keys {stray_keys}")
    raw_entries = document.get("export")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ExportRefused(f"allowlist {path} needs a non-empty [[export]] list")
    entries = []
    for index, raw in enumerate(raw_entries):
        entry = _entry_from(raw, index)
        if not _RELATION.fullmatch(entry.relation):
            raise ExportRefused(
                f"allowlist entry {entry.name}: relation {entry.relation} is not in marts"
            )
        if not _FILE_NAME.fullmatch(entry.output) or entry.output in {".", ".."}:
            raise ExportRefused(
                f"allowlist entry {entry.name}: output {entry.output} is not a file name"
            )
        names = (*entry.columns, *entry.order_by)
        if not all(_IDENTIFIER.fullmatch(name) for name in names):
            raise ExportRefused(
                f"allowlist entry {entry.name}: a column name is not a plain identifier"
            )
        stray = [name for name in entry.order_by if name not in entry.columns]
        if stray:
            raise ExportRefused(
                f"allowlist entry {entry.name}: order_by {stray} is not in its columns"
            )
        entries.append(entry)
    return entries


def _entry_from(raw: dict[str, object], index: int) -> Entry:
    """Build one entry, refusing a missing key or a value of the wrong type."""
    label = f"allowlist entry {index + 1}"
    for key in ("name", "relation", "output", "columns", "order_by"):
        if key not in raw:
            raise ExportRefused(f"{label}: key {key} is missing")
    for key in ("name", "relation", "output"):
        if not isinstance(raw[key], str):
            raise ExportRefused(f"{label}: {key} must be a string")
    for key in ("columns", "order_by"):
        value = raw[key]
        if not (isinstance(value, list) and value and all(isinstance(item, str) for item in value)):
            raise ExportRefused(f"{label}: {key} must be a non-empty list of strings")
    return Entry(
        name=str(raw["name"]),
        relation=str(raw["relation"]),
        output=str(raw["output"]),
        columns=tuple(str(item) for item in raw["columns"]),  # type: ignore[attr-defined]
        order_by=tuple(str(item) for item in raw["order_by"]),  # type: ignore[attr-defined]
    )


def select_entries(entries: list[Entry], relation: str | None) -> list[Entry]:
    """Return every entry, or only the one whose relation is named."""
    if relation is None:
        return entries
    chosen = [entry for entry in entries if entry.relation == relation]
    if not chosen:
        raise ExportRefused(f"relation {relation} is not on the allowlist")
    return chosen


def fetch_rows(connection: duckdb.DuckDBPyConnection, entry: Entry) -> list[dict[str, object]]:
    """Run the one select the export is allowed: named columns, one ordering, no filter."""
    columns, order = ", ".join(entry.columns), ", ".join(entry.order_by)
    sql = f"select {columns} from {entry.relation} order by {order}"
    try:
        delivered = connection.execute(sql).fetchall()
    except (duckdb.CatalogException, duckdb.BinderException) as error:
        raise ExportRefused(
            f"{entry.relation} or a listed column is missing from the warehouse: {error}"
        ) from error
    return [
        {column: _plain(value) for column, value in zip(entry.columns, row, strict=True)}
        for row in delivered
    ]


def _scalar(connection: duckdb.DuckDBPyConnection, table: str, sql: str) -> object:
    """Run one single-value query on a source table, refusing when that table is missing."""
    try:
        row = connection.execute(sql).fetchone()
    except (duckdb.CatalogException, duckdb.BinderException) as error:
        raise ExportRefused(
            f"{table} or a column the sample record reads is missing: {error}"
        ) from error
    assert row is not None  # an aggregate query always returns one row
    return row[0]


def fetch_sample(connection: duckdb.DuckDBPyConnection, data_set: str) -> list[dict[str, object]]:
    """Build the one-row sample record; refuse a label the parks in dim_park do not all carry."""
    if data_set != DEFAULT_DATA_SET:
        try:
            labels = connection.execute("select distinct data_set from marts.dim_park").fetchall()
        except (duckdb.CatalogException, duckdb.BinderException) as error:
            raise ExportRefused(
                f"marts.dim_park or its data_set column is missing, so data_set {data_set} "
                f"cannot be checked: {error}"
            ) from error
        if [label for (label,) in labels] != [data_set]:
            raise ExportRefused(
                f"data_set {data_set} is not the only data_set in marts.dim_park "
                f"(found {sorted(str(label) for (label,) in labels)})"
            )
    sessions = "select distinct session_id from marts.fct_park_day"
    return [
        {
            "data_set": data_set,
            "parks": _scalar(
                connection,
                "marts.obt_park_year",
                "select count(distinct park_id) from marts.obt_park_year",
            ),
            "sessions": _scalar(
                connection,
                "marts.fct_park_day",
                "select count(distinct session_id) from marts.fct_park_day",
            ),
            "player_played": bool(
                _scalar(
                    connection,
                    "staging.stg_session_start",
                    "select coalesce(bool_or(headless = false), false) "
                    f"from staging.stg_session_start where session_id in ({sessions})",
                )
            ),
        }
    ]


def _plain(value: object) -> object:
    return value.isoformat() if isinstance(value, date) else value


def _dump(value: object, level: int = 0) -> str:
    """Write JSON in fixed key order; money keeps the exact text of its Decimal."""
    if isinstance(value, Decimal):
        return format(value, "f")
    pad, inner = "  " * level, "  " * (level + 1)
    if isinstance(value, dict):
        if not value:
            return "{}"
        body = ",\n".join(
            f"{inner}{json.dumps(key)}: {_dump(item, level + 1)}" for key, item in value.items()
        )
        return "{\n" + body + "\n" + pad + "}"
    if isinstance(value, list):
        if not value:
            return "[]"
        return (
            "[\n" + ",\n".join(inner + _dump(item, level + 1) for item in value) + "\n" + pad + "]"
        )
    return json.dumps(value)


def render(entry: Entry, rows: list[dict[str, object]]) -> str:
    """Return the file text of one export."""
    document = {
        "name": entry.name,
        "relation": entry.relation,
        "columns": list(entry.columns),
        "rows": rows,
    }
    return _dump(document) + "\n"


def _row_hash(rows: list[dict[str, object]]) -> str:
    return hashlib.sha256("\n".join(_dump(row) for row in rows).encode()).hexdigest()


def _key(entry: Entry, row: dict[str, object]) -> str:
    return ", ".join(f"{column}={row.get(column)}" for column in entry.order_by)


def _load_served(entry: Entry, served_file: Path) -> dict[str, Any]:
    """Read a served file, raising ExportFailed when it is not an object with a rows list."""
    try:
        document = json.loads(served_file.read_text(), parse_float=Decimal)
    except json.JSONDecodeError as error:
        raise ExportFailed(f"{entry.name}: served file {served_file} is not valid JSON") from error
    if not isinstance(document, dict):
        raise ExportFailed(f"{entry.name}: served file {served_file} is not a JSON object")
    if not isinstance(document.get("rows"), list):
        raise ExportFailed(f"{entry.name}: served file {served_file} has no rows list")
    return document


def compare(entry: Entry, rebuilt: list[dict[str, object]], served_file: Path) -> None:
    """Raise ExportFailed naming the first differing header key, or row key and column."""
    if not served_file.is_file():
        raise ExportFailed(f"{entry.name}: served file {served_file} is missing")
    document = _load_served(entry, served_file)
    for key, expected in (
        ("name", entry.name),
        ("relation", entry.relation),
        ("columns", list(entry.columns)),
    ):
        if document.get(key) != expected:
            raise ExportFailed(
                f"{entry.name}: header {key} differs "
                f"(allowlist {expected}, served {document.get(key)})"
            )
    served = document["rows"]
    if len(served) == len(rebuilt) and _row_hash(served) == _row_hash(rebuilt):
        return
    for mine, theirs in zip(rebuilt, served, strict=False):
        for column in entry.columns:
            if mine.get(column) != theirs.get(column):
                raise ExportFailed(
                    f"{entry.name}: row {_key(entry, mine)} "
                    f"column {column} differs "
                    f"(marts {_dump(mine.get(column))}, served {_dump(theirs.get(column))})"
                )
    for mine, theirs in zip(rebuilt, served, strict=False):
        if _dump(mine) != _dump(theirs):
            raise ExportFailed(
                f"{entry.name}: row {_key(entry, mine)} has the same values but different text "
                f"(marts {' '.join(_dump(mine).split())}, served {' '.join(_dump(theirs).split())})"
            )
    raise ExportFailed(f"{entry.name}: served has {len(served)} rows, marts have {len(rebuilt)}")


def run(
    mode: str,
    warehouse: Path,
    entries: list[Entry],
    served_dir: Path,
    *,
    data_set: str = DEFAULT_DATA_SET,
    with_record: bool = True,
) -> None:
    """Write or check every chosen entry, and the sample record when `with_record`."""
    if not warehouse.is_file():
        raise ExportRefused(f"warehouse not found: {warehouse}")
    connection = duckdb.connect(str(warehouse), read_only=True)
    try:
        fetched = [(entry, fetch_rows(connection, entry)) for entry in entries]
        if with_record:
            fetched.append((SAMPLE_ENTRY, fetch_sample(connection, data_set)))
    finally:
        connection.close()
    if mode == "write":
        served_dir.mkdir(parents=True, exist_ok=True)
        for entry, rows in fetched:
            (served_dir / entry.output).write_text(render(entry, rows))
            print(f"wrote {served_dir / entry.output}")
        return
    for entry, rows in fetched:
        compare(entry, rows, served_dir / entry.output)
        print(f"{entry.name}: matches the marts")


def main(argv: Sequence[str] | None = None) -> int:
    """Write or check the exports and return the command exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("write", "check"))
    parser.add_argument("--warehouse", type=Path, required=True)
    parser.add_argument("--relation")
    parser.add_argument("--data-set", default=DEFAULT_DATA_SET)
    parser.add_argument("--served-dir", type=Path, default=DEFAULT_SERVED_DIR)
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    args = parser.parse_args(argv)

    set_signal_handlers(raise_interrupted)
    try:
        entries = select_entries(load_allowlist(args.allowlist), args.relation)
        run(
            args.mode,
            args.warehouse,
            entries,
            args.served_dir,
            data_set=args.data_set,
            with_record=args.relation is None,
        )
    except ExportRefused as error:
        print(f"export refused: {error}")
        return 2
    except ExportFailed as error:
        print(f"export failed: {error}")
        return 1
    except Interrupted as error:
        print(f"export interrupted: {error}")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())

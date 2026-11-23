"""Convert raw ``v1`` JSON Lines events into typed Parquet, one file per event type.

Every field's name, type and required flag comes from the contracts in
``contracts/`` (read through datacontract-cli's typed model); this module keeps no
field list of its own beyond the two lineage columns, ``_raw_file`` and ``_raw_line``,
which it fills from the raw file's base name and physical line number. Run with
``python -m openrct2_analytics.ingest.convert --data-set {rehearsal,company}`` or with both
``--raw-dir PATH`` and ``--out-dir PATH``. The whole run holds the landing lock
``<out dir>.lock``, so two conversions (or a conversion and a publish) never overlap.

A schema error (unknown event type, unknown field, missing required field, wrong
JSON type) stops the run and writes nothing. A ``seq`` violation is recorded in
``audit/seq_audit.parquet``: the Parquet is still written, and the exit status is
non-zero. Malformed lines are counted, never converted. This module only reads
raw files; a pre-go-live company delete may archive, rewrite or remove them
(ADR 0033).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from openrct2_analytics.config import DATA_SETS, ConfigError, landing_dirs
from openrct2_analytics.ingest.contracts import (
    ACCEPTED_JSON_TYPES,
    CONTRACTS_DIR,
    LANDING_FOLDER,
    Field,
    load_fields,
)
from openrct2_analytics.ingest.lock import (
    Interrupted,
    LockTaken,
    hold_lock,
    raise_interrupted,
    set_signal_handlers,
)

# A timestamp must name its offset, so no instant depends on the machine's zone.
TIMESTAMP_SHAPE = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
VIOLATION_FILTER = "missing > 0 OR duplicates > 0 OR first_seq <> 1 OR park_count > 1"
OUTPUT_FOLDERS = (LANDING_FOLDER, "audit")
# Contract columns filled from the raw table's file base name and 1-based physical
# line number, never from the JSON; the plugin never sends them.
LINEAGE_SOURCES = {"_raw_file": "file", "_raw_line": "line"}


class NoInputError(Exception):
    """Raised when the raw folder holds no ``v1/events-*.jsonl`` file, or no event in them."""


class UnsafeOutputError(Exception):
    """Raised when the output folder equals, contains or lies inside the raw folder."""


@dataclass
class ConvertResult:
    """What one conversion found and did.

    Attributes:
        schema_errors: One line per schema error; when any exist nothing was written.
        seq_violations: One line per session whose ``seq`` has a gap, repeat or bad start.
        malformed_lines: Count of lines in ``malformed-*.jsonl`` (never converted).
        row_counts: Rows written per event type; a type with no events has 0 and a zero-row file.
    """

    schema_errors: list[str] = field(default_factory=list)
    seq_violations: list[str] = field(default_factory=list)
    malformed_lines: int = 0
    row_counts: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True when there was no schema error and no ``seq`` violation."""
        return not self.schema_errors and not self.seq_violations


def seq_audit(events: duckdb.DuckDBPyRelation) -> duckdb.DuckDBPyRelation:
    """Audit ``seq`` per session across all event types together.

    Within each ``session_id``, ``seq`` must start at 1 and run without a gap or a
    repeat. Works on any relation with ``park_id``, ``session_id`` and ``seq``
    columns, so the same check runs on freshly converted or committed data.

    Args:
        events: A relation holding every event, whatever its type.

    Returns:
        One row per session: ``park_id`` (the first one seen), ``session_id``,
        ``first_seq``, ``last_seq``, ``row_count``, ``missing`` (numbers absent
        from 1 to ``last_seq``), ``duplicates`` (rows beyond one per ``seq``) and
        ``park_count`` (distinct ``park_id`` values; more than 1 is a violation).
    """
    return events.query(
        "audited_events",
        """
        SELECT min(park_id) AS park_id, session_id,
               min(seq) AS first_seq,
               max(seq) AS last_seq,
               count(*) AS row_count,
               greatest(max(seq), 0) - count(DISTINCT seq) FILTER (WHERE seq >= 1) AS missing,
               count(*) - count(DISTINCT seq) AS duplicates,
               count(DISTINCT park_id) AS park_count
        FROM audited_events
        GROUP BY session_id
        ORDER BY session_id
        """,
    )


def _lines(path: Path) -> list[str]:
    # Split on "\n" only: str.splitlines() would also cut a JSON string at U+2028.
    return path.read_text(encoding="utf-8").split("\n")


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _load_raw(connection: duckdb.DuckDBPyConnection, files: Sequence[Path]) -> None:
    connection.execute("CREATE TABLE raw (file VARCHAR, line BIGINT, doc JSON)")
    rows = [
        (path.name, number, text)
        for path in files
        for number, text in enumerate(_lines(path), start=1)
        if text.strip()
    ]
    # executemany rejects an empty list; files of blank lines leave the table empty,
    # which convert() reports as NoInputError.
    if rows:
        # TRY_CAST leaves an unparseable line as NULL, reported as a schema error below.
        connection.executemany("INSERT INTO raw VALUES (?, ?, TRY_CAST(? AS JSON))", rows)
    connection.execute(
        """
        CREATE VIEW objects AS
        SELECT file, line, doc, json_extract_string(doc, '$.event_type') AS event_type
        FROM raw WHERE json_type(doc) = 'OBJECT'
        """
    )


def _row_errors(connection: duckdb.DuckDBPyConnection, fields: dict[str, list[Field]]) -> list[str]:
    errors = [
        f"{file}:{line}: not a JSON object"
        for file, line in connection.execute(
            "SELECT file, line FROM raw WHERE json_type(doc) IS DISTINCT FROM 'OBJECT'"
        ).fetchall()
    ]
    known = list(fields)
    errors += [
        f"{file}:{line}: event_type: no contract for {event_type!r}"
        for file, line, event_type in connection.execute(
            "SELECT file, line, event_type FROM objects "
            "WHERE event_type IS NULL OR NOT list_contains(?, event_type)",
            [known],
        ).fetchall()
    ]
    return errors


def _field_errors(
    connection: duckdb.DuckDBPyConnection, event_type: str, fields: list[Field]
) -> list[str]:
    sent = [f for f in fields if f.name not in LINEAGE_SOURCES]
    errors = [
        f"{file}:{line}: {key}: "
        + (
            "the converter fills this field; a raw line must not carry it"
            if key in LINEAGE_SOURCES
            else f"field is not in the {event_type} contract"
        )
        for file, line, key in connection.execute(
            """
            SELECT file, line, k FROM (
                SELECT file, line, unnest(json_keys(doc)) AS k FROM objects WHERE event_type = ?
            ) WHERE NOT list_contains(?, k)
            """,
            [event_type, [f.name for f in sent]],
        ).fetchall()
    ]
    for f in sent:
        accepted = list(ACCEPTED_JSON_TYPES[f.logical])
        shape = (
            f"regexp_full_match(txt, '{TIMESTAMP_SHAPE}')" if f.logical == "timestamp" else "true"
        )
        path = f'$."{f.name}"'
        errors += [
            f"{file}:{line}: {f.name}: {problem}"
            for file, line, problem in connection.execute(
                f"""
                SELECT file, line, CASE
                    WHEN kind IS NULL THEN 'missing required field'
                    WHEN NOT list_contains(?, kind) THEN 'expected ' || ? || ', got JSON ' || kind
                    ELSE 'value does not fit ' || ?
                END
                FROM (
                    SELECT file, line, json_type(doc, ?) AS kind,
                           json_extract_string(doc, ?) AS txt
                    FROM objects WHERE event_type = ?
                )
                WHERE (kind IS NULL AND ?)
                   OR (kind IS NOT NULL AND NOT list_contains(?, kind) AND (? OR kind <> 'NULL'))
                   OR (list_contains(?, kind)
                       AND (TRY_CAST(txt AS {f.physical}) IS NULL OR NOT {shape}))
                ORDER BY file, line
                """,
                [
                    accepted,
                    f.logical,
                    f.physical,
                    path,
                    path,
                    event_type,
                    f.required,
                    accepted,
                    f.required,
                    accepted,
                ],
            ).fetchall()
        ]
    return errors


def _schema_errors(
    connection: duckdb.DuckDBPyConnection, fields: dict[str, list[Field]]
) -> list[str]:
    errors = _row_errors(connection, fields)
    for event_type, event_fields in fields.items():
        errors += _field_errors(connection, event_type, event_fields)
    return errors


def _build_tables(
    connection: duckdb.DuckDBPyConnection, fields: dict[str, list[Field]]
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event_type, event_fields in fields.items():
        columns = ", ".join(column_projection(f) for f in event_fields)
        connection.execute(
            f"CREATE TABLE {_quote(event_type)} AS SELECT {columns} FROM objects "
            "WHERE event_type = ? ORDER BY session_id, seq",
            [event_type],
        )
        row = connection.execute(f"SELECT count(*) FROM {_quote(event_type)}").fetchone()
        counts[event_type] = int(row[0]) if row else 0
    return counts


def column_projection(f: Field) -> str:
    """The SQL select item that types one contract field as the column ``f.name``.

    It reads a relation with the raw table's columns: ``doc`` (the JSON line),
    ``file`` (the raw file's base name) and ``line`` (its physical line number). A
    lineage column (``_raw_file``, ``_raw_line``) comes from ``file`` or ``line``;
    every other field comes from ``doc``.

    Args:
        f: One contract field.

    Returns:
        A select item such as ``CAST(... AS BIGINT) AS "seq"``.
    """
    if f.name in LINEAGE_SOURCES:
        return f"CAST({LINEAGE_SOURCES[f.name]} AS {f.physical}) AS {_quote(f.name)}"
    text = f"json_extract_string(doc, '$.\"{f.name}\"')"
    if f.logical == "string":
        return f"{text} AS {_quote(f.name)}"
    return f"CAST({text} AS {f.physical}) AS {_quote(f.name)}"


def _violation_lines(audit: duckdb.DuckDBPyRelation) -> list[str]:
    return [
        f"session {session} (park {park}): first_seq={first}, last_seq={last}, "
        f"rows={rows}, missing={missing}, duplicates={duplicates}, parks={parks}"
        for park, session, first, last, rows, missing, duplicates, parks in audit.filter(
            VIOLATION_FILTER
        ).fetchall()
    ]


def _swap_in(staging: Path, out_dir: Path) -> None:
    """Replace ``out_dir/v1`` and ``out_dir/audit`` from ``staging``; touch nothing else.

    The old folders wait in ``staging/previous`` and go when the caller removes
    ``staging``. If a rename fails, the folders already swapped are put back.
    """
    previous = staging / "previous"
    previous.mkdir()
    swapped: list[str] = []
    try:
        for name in OUTPUT_FOLDERS:
            if (out_dir / name).exists():
                (out_dir / name).rename(previous / name)
            swapped.append(name)
            (staging / name).rename(out_dir / name)
    except OSError:
        for name in reversed(swapped):
            if (out_dir / name).exists():
                shutil.rmtree(out_dir / name)
            if (previous / name).exists():
                (previous / name).rename(out_dir / name)
        raise


def _check_output_is_safe(raw_dir: Path, out_dir: Path) -> None:
    raw, out = raw_dir.resolve(), out_dir.resolve()
    if out == raw or out in raw.parents or raw in out.parents:
        raise UnsafeOutputError(
            f"Refusing to write: output folder {out_dir} equals, contains or lies inside "
            f"the raw folder {raw_dir}. Nothing was written."
        )


def _count_malformed(raw_dir: Path) -> int:
    return sum(
        1
        for path in sorted(raw_dir.glob("malformed-*.jsonl"))
        for text in _lines(path)
        if text.strip()
    )


def _write_output(
    connection: duckdb.DuckDBPyConnection,
    audit: duckdb.DuckDBPyRelation,
    event_types: list[str],
    out_dir: Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".parquet-", dir=out_dir.parent))
    try:
        (staging / LANDING_FOLDER).mkdir()
        (staging / "audit").mkdir()
        for name in event_types:
            target = (staging / LANDING_FOLDER / f"{name}.parquet").as_posix().replace("'", "''")
            connection.execute(f"COPY {_quote(name)} TO '{target}' (FORMAT parquet)")
        audit.write_parquet((staging / "audit" / "seq_audit.parquet").as_posix())
        _swap_in(staging, out_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def convert(raw_dir: Path, out_dir: Path, contracts_dir: Path = CONTRACTS_DIR) -> ConvertResult:
    """Convert every ``<raw_dir>/v1/events-*.jsonl`` into ``<out_dir>``.

    Writes ``v1/<event_type>.parquet`` for every contract's event type (columns in
    contract order, rows ordered by ``session_id`` and ``seq``; a type with no events
    gets a zero-row file with the contract's columns and types) and
    ``audit/seq_audit.parquet`` into a temporary sibling of ``out_dir``, then swaps
    them in for ``out_dir/v1`` and ``out_dir/audit``. Any other file in ``out_dir``
    is left alone. Schema errors write nothing.

    Args:
        raw_dir: Folder the listener writes to.
        out_dir: Folder that receives ``v1/`` and ``audit/``; only those two are replaced.
        contracts_dir: Folder of ``*.odcs.yaml`` contracts.

    Returns:
        The schema errors, ``seq`` violations, malformed-line count and row counts.

    Raises:
        UnsafeOutputError: if ``out_dir`` equals, contains or lies inside ``raw_dir``.
        NoInputError: if there is no input file or no event.
        LockTaken: if ``<out_dir>.lock`` exists; nothing is written.
        FileNotFoundError: if ``contracts_dir`` holds no envelope contract.
        ValueError: if a contract field is unusable (see ``load_fields``).
    """
    _check_output_is_safe(raw_dir, out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with hold_lock(landing_lock_path(out_dir), f"pid {os.getpid()} started {started}"):
        return _convert_locked(raw_dir, out_dir, contracts_dir)


def landing_lock_path(out_dir: Path) -> Path:
    """The lock file of a Parquet folder: ``<out_dir>.lock``, beside the folder."""
    return out_dir.with_name(f"{out_dir.name}.lock")


def _convert_locked(raw_dir: Path, out_dir: Path, contracts_dir: Path) -> ConvertResult:
    files = sorted((raw_dir / LANDING_FOLDER).glob("events-*.jsonl"))
    if not files:
        raise NoInputError(f"No input: {raw_dir / LANDING_FOLDER} holds no events-*.jsonl file")
    fields = load_fields(contracts_dir)
    result = ConvertResult(malformed_lines=_count_malformed(raw_dir))

    connection = duckdb.connect(":memory:")
    try:
        connection.execute("SET TimeZone='UTC'")
        _load_raw(connection, files)
        result.schema_errors = _schema_errors(connection, fields)
        if result.schema_errors:
            return result
        result.row_counts = _build_tables(connection, fields)
        if not any(result.row_counts.values()):
            raise NoInputError(f"No input: {raw_dir / LANDING_FOLDER} holds no events")
        every_event = " UNION ALL ".join(
            f"SELECT park_id, session_id, seq FROM {_quote(name)}" for name in result.row_counts
        )
        audit = seq_audit(connection.sql(every_event))
        result.seq_violations = _violation_lines(audit)
        _write_output(connection, audit, list(result.row_counts), out_dir)
    finally:
        connection.close()
    return result


def report_lines(result: ConvertResult, out_dir: Path) -> list[str]:
    """The lines that report one conversion result, in the order ``main`` prints them."""
    lines: list[str] = []
    if result.malformed_lines:
        lines.append(
            f"{result.malformed_lines} malformed line(s) in malformed-*.jsonl were not converted."
        )
    lines.extend(f"schema error: {line}" for line in result.schema_errors)
    if result.schema_errors:
        lines.append("Nothing was written; the previous output is unchanged.")
        return lines
    lines.extend(f"seq violation: {line}" for line in result.seq_violations)
    counts = ", ".join(f"{name}={count}" for name, count in result.row_counts.items())
    lines.append(f"Wrote {out_dir} ({counts}).")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """Convert the raw folder.

    Returns:
        0 with no schema error and no ``seq`` violation, 1 for a failed conversion, 2 when
        refused (a taken lock, an unusable data set) and 130 when interrupted.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-set", choices=DATA_SETS, help="Data set whose folders to convert")
    parser.add_argument("--raw-dir", type=Path, help="Listener's raw folder (with --out-dir)")
    parser.add_argument("--out-dir", type=Path, help="Parquet folder (with --raw-dir)")
    args = parser.parse_args(argv)
    if args.data_set is None and (args.raw_dir is None or args.out_dir is None):
        parser.error("give --data-set, or both --raw-dir and --out-dir")
    if args.raw_dir is None or args.out_dir is None:
        try:
            folders = landing_dirs(args.data_set)
        except ConfigError as exc:
            print(f"{exc}. Nothing was written.")
            return 2
        args.raw_dir = args.raw_dir or folders.raw
        args.out_dir = args.out_dir or folders.parquet

    set_signal_handlers(raise_interrupted)
    try:
        result = convert(args.raw_dir, args.out_dir)
    except (NoInputError, UnsafeOutputError) as error:
        print(error)
        return 1
    except LockTaken as taken:
        print(
            f"Another conversion or publish holds {taken.path} ({taken.line}). Nothing was "
            "written. If no such command is running, see ARCHITECTURE.md, section "
            '"Environments and publishing" (Stale locks).'
        )
        return 2
    except Interrupted:
        print("Interrupted; the lock was removed.")
        return 130
    for line in report_lines(result, args.out_dir):
        print(line)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())

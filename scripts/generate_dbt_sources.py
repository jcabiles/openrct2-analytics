"""Write models/staging/_sources.yml from the data contracts in contracts/.

One source table per contracted event type (``plugin_stats`` included), each over
``<parquet_root>/v1/<type>.parquet``. The ``parquet_root`` default is fail-closed: the dev and ci
targets fall back to the committed sample, every other target gets a path that does not exist.
Column descriptions are the contract field descriptions, read through
``openrct2_analytics.ingest.contracts.load_fields`` (the one contract reader). Every required
envelope field gets a ``not_null`` test; no ``unique`` test is written (the envelope allows
repeated events).

A second source, ``registry`` with the tables ``park_registry`` and ``session_play_mode``, is
written from the reference contracts in ``<contracts-dir>/reference/`` (read through
``load_reference_fields``): the park registry feed and the play-mode label feed of CSV deliveries,
read all as text so staging owns the casts. The ``registry_root`` expression, fail-closed the same
way, is written once, as the source's ``config.registry_root``; each table's location names it
through dbt-duckdb's ``{registry_root}`` placeholder and its own ``file_glob``, and
``stg_session_play_mode`` reads the same two values to look for a label file.

Usage: python scripts/generate_dbt_sources.py [--check] [--contracts-dir DIR] [--output FILE]
``--check`` writes nothing and exits 1, naming the first differing line, when FILE differs from
what the contracts generate.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from openrct2_analytics.ingest.contracts import (
    CONTRACTS_DIR,
    LANDING_FOLDER,
    Field,
    load_envelope,
    load_fields,
    load_reference_fields,
)

SOURCES_FILE = Path(__file__).resolve().parent.parent / "models" / "staging" / "_sources.yml"
COMMAND = "uv run python scripts/generate_dbt_sources.py"
SOURCE_NAME = "landing"
DATA_ROOT = (
    "{{ var('parquet_root', 'data/sample/rehearsal' if target.name in ['dev', 'ci']"
    " else 'invalid-parquet-root') }}"
)
REGISTRY_SOURCE_NAME = "registry"
REFERENCE_FOLDER = "reference"
REGISTRY_ROOT = (
    "{{ var('registry_root', 'data/sample/rehearsal/registry' if target.name in"
    " ['dev', 'ci'] else 'invalid-registry-root') }}"
)
# dbt-duckdb fills {registry_root} and {file_glob} from the source and table config at run time.
REGISTRY_LOCATION = (
    "read_csv('{registry_root}/{file_glob}',"
    " header=true, filename=true, all_varchar=true, union_by_name=true)"
)
REGISTRY_TABLES = {
    "park_registry": "One row per park per delivery file; a later delivery restates the park, it"
    " does not replace the earlier row.",
    "session_play_mode": "One row per labeled session per delivery file; a session with no row is"
    " managed. A folder may hold no label file yet; stg_session_play_mode guards that case.",
}
REGISTRY_DESCRIPTION = (
    "CSV deliveries from the park registry feed and the play-mode label feed (append-only except"
    " a pre-go-live delete, ADR 0033),"
    " one file per delivery under v1/ of"
    " the registry_root variable. Every column is read as text and the file path is kept as"
    " filename, so staging owns the casts. The dev and ci targets default to the committed sample"
    " feed; rehearsal and company have no default and fail the build unless a feed folder is"
    " passed."
)
SOURCE_DESCRIPTION = (
    "Parquet files the converter writes from the raw captures, one file per event type under"
    f" {LANDING_FOLDER}/. The root folder is the parquet_root variable, so one setting switches"
    " between the committed sample data and a real capture. The dev and ci targets default to the"
    " committed sample; rehearsal and company have no default and fail the build unless a Parquet"
    " folder is passed."
)


def _quoted(text: str) -> str:
    # A JSON string is a valid double-quoted YAML scalar, so no YAML writer is needed.
    return json.dumps(text, ensure_ascii=False)


def _column_lines(event_type: str, field: Field, not_null: bool) -> list[str]:
    if not field.description:
        raise ValueError(f"{event_type}.{field.name}: the contract gives the field no description")
    lines = [
        f"          - name: {field.name}",
        f"            description: {_quoted(field.description)}",
    ]
    if not_null:
        lines += ["            data_tests:", "              - not_null"]
    return lines


def _table_lines(event_type: str, fields: list[Field], required_envelope: set[str]) -> list[str]:
    lines = [
        f"      - name: {event_type}",
        f"        description: One row per landed {event_type} delivery; "
        "a repeat delivery of one event_id is a second row.",
        "        config:",
        f'          external_location: "{DATA_ROOT}/{LANDING_FOLDER}/{event_type}.parquet"',
        "        columns:",
    ]
    for field in fields:
        lines += _column_lines(event_type, field, field.name in required_envelope)
    return lines


def _registry_lines(reference_dir: Path) -> list[str]:
    reference_fields = load_reference_fields(reference_dir)
    lines = [
        "",
        f"  - name: {REGISTRY_SOURCE_NAME}",
        f"    description: {_quoted(REGISTRY_DESCRIPTION)}",
        "    config:",
        f"      registry_root: {_quoted(REGISTRY_ROOT)}",
        "    tables:",
    ]
    for table, description in REGISTRY_TABLES.items():
        fields = reference_fields.get(table)
        if fields is None:
            raise ValueError(f"no {table} schema in the contracts in {reference_dir}")
        lines += [
            f"      - name: {table}",
            f"        description: {_quoted(description)}",
            "        config:",
            f"          external_location: {_quoted(REGISTRY_LOCATION)}",
            f"          file_glob: {_quoted(f'v1/{table}_*.csv')}",
            "        columns:",
        ]
        for field in fields:
            lines += _column_lines(table, field, False)
    return lines


def generate(contracts_dir: Path) -> str:
    """Return the text of the sources file for the contracts in ``contracts_dir``.

    Raises:
        FileNotFoundError: if there is no envelope contract in ``contracts_dir``, or no reference
            contract in its ``reference/`` folder.
        ValueError: if the contracts cannot be read, or a field has no description.
    """
    required_envelope = {f.name for f in load_envelope(contracts_dir) if f.required}
    lines = [
        f"# Generated by `{COMMAND}` from the data contracts. Do not edit by hand.",
        "version: 2",
        "",
        "sources:",
        f"  - name: {SOURCE_NAME}",
        f"    description: {_quoted(SOURCE_DESCRIPTION)}",
        "    tables:",
    ]
    for event_type, fields in load_fields(contracts_dir).items():
        lines += _table_lines(event_type, fields, required_envelope)
    lines += _registry_lines(contracts_dir / REFERENCE_FOLDER)
    return "\n".join(lines) + "\n"


def first_difference(expected: str, found: str) -> str:
    """Name the first line where ``found`` departs from ``expected``; empty when they agree."""
    expected_lines = expected.splitlines()
    found_lines = found.splitlines()
    for number in range(max(len(expected_lines), len(found_lines))):
        want = expected_lines[number] if number < len(expected_lines) else "<end of file>"
        have = found_lines[number] if number < len(found_lines) else "<end of file>"
        if want != have:
            return f"line {number + 1}: expected {want!r}, found {have!r}"
    return ""


def main(argv: Sequence[str] | None = None) -> int:
    """Write or check the sources file; return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail when the file is out of date")
    parser.add_argument("--contracts-dir", type=Path, default=CONTRACTS_DIR)
    parser.add_argument("--output", type=Path, default=SOURCES_FILE)
    args = parser.parse_args(argv)
    try:
        text = generate(args.contracts_dir)
    except (FileNotFoundError, ValueError) as error:
        print(f"generate_dbt_sources: {error}", file=sys.stderr)
        return 1
    if not args.check:
        args.output.write_text(text, encoding="utf-8")
        print(f"generate_dbt_sources: wrote {args.output}.")
        return 0
    if not args.output.exists():
        print(f"generate_dbt_sources: {args.output} is missing; run `{COMMAND}`.", file=sys.stderr)
        return 1
    difference = first_difference(text, args.output.read_text(encoding="utf-8"))
    if difference:
        print(
            f"generate_dbt_sources: {args.output} is out of date, {difference}; run `{COMMAND}`.",
            file=sys.stderr,
        )
        return 1
    print("generate_dbt_sources: the sources file matches the contracts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

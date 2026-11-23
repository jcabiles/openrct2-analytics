"""Write zero-row Parquet files for every contracted event type."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import duckdb

from openrct2_analytics.ingest.contracts import CONTRACTS_DIR, LANDING_FOLDER, load_fields
from openrct2_analytics.ingest.convert import column_projection


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _quote_path(path: Path) -> str:
    return "'" + path.as_posix().replace("'", "''") + "'"


def write_empty_extract(out_dir: Path) -> None:
    """Write one contract-typed, zero-row Parquet file per event type.

    Args:
        out_dir: Folder that receives the ``v1`` Parquet files.
    """
    fields = load_fields(CONTRACTS_DIR)
    landing = out_dir / LANDING_FOLDER
    landing.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        for event_type, event_fields in fields.items():
            columns = ", ".join(column_projection(field) for field in event_fields)
            table = _quote_identifier(event_type)
            connection.execute(
                f"CREATE TABLE {table} AS SELECT {columns} "
                "FROM (SELECT NULL::JSON AS doc, NULL::VARCHAR AS file, "
                "NULL::BIGINT AS line) AS empty_source WHERE false"
            )
            target = _quote_path(landing / f"{event_type}.parquet")
            connection.execute(f"COPY {table} TO {target} (FORMAT parquet)")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the zero-row extract command.

    Args:
        argv: Optional command-line arguments.

    Returns:
        Zero after writing the extract.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True, help="Parquet output folder")
    args = parser.parse_args(argv)
    write_empty_extract(args.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())

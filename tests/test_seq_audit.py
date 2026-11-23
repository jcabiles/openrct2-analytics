"""The converter's seq audit runs on any DuckDB relation of events."""

from __future__ import annotations

import duckdb

from openrct2_analytics.ingest.convert import seq_audit


def test_seq_audit_runs_on_any_relation_of_events() -> None:
    connection = duckdb.connect(":memory:")
    try:
        events = connection.sql(
            "SELECT * FROM (VALUES ('p', 's', 1), ('p', 's', 3)) t(park_id, session_id, seq)"
        )
        assert seq_audit(events).fetchall() == [("p", "s", 1, 3, 2, 1, 0, 1)]
    finally:
        connection.close()

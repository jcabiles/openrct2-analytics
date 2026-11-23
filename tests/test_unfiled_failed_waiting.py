"""The failed-audit list that filing uses: which waiting sessions failed their seq audit.

Every file is planted under ``tmp_path``.
"""

from __future__ import annotations

import duckdb

from openrct2_analytics.config import LandingDirs
from openrct2_analytics.ingest import unfiled
from tests.test_unfiled import _audit, _raw, _run, _start
from tests.test_unfiled import landing as landing  # noqa: F401  (pytest fixture)


def _audit_two_failing(landing: LandingDirs) -> None:
    """Plant an audit file where sessions s1 and s2 (park-a) both fail with a gap."""
    path = landing.parquet / "audit" / "seq_audit.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "COPY (SELECT 'park-a' AS park_id, session_id, 1::BIGINT AS first_seq, "
            "3::BIGINT AS last_seq, 3::BIGINT AS row_count, 1::BIGINT AS missing, "
            "0::BIGINT AS duplicates, 1::BIGINT AS park_count "
            f"FROM (VALUES ('s1'), ('s2')) AS t(session_id)) TO '{path.as_posix()}' "
            "(FORMAT PARQUET)"
        )


def test_failed_waiting_returns_a_failing_session_that_is_not_filed(
    landing: LandingDirs,
) -> None:
    _audit(landing, "s1", missing=1)
    assert unfiled.failed_waiting(landing, set()) == {"s1": ("park-a",)}


def test_failed_waiting_leaves_out_a_filed_failing_session(landing: LandingDirs) -> None:
    _audit_two_failing(landing)
    assert unfiled.failed_waiting(landing, {"s1"}) == {"s2": ("park-a",)}


def test_failed_waiting_none_means_nothing_is_filed(landing: LandingDirs) -> None:
    _audit_two_failing(landing)
    assert unfiled.failed_waiting(landing, None) == {"s1": ("park-a",), "s2": ("park-a",)}


def test_failed_waiting_skips_a_clean_audit_row(landing: LandingDirs) -> None:
    _audit(landing, "s1")
    assert unfiled.failed_waiting(landing, set()) == {}


def test_failed_waiting_with_a_missing_audit_file_is_empty(landing: LandingDirs) -> None:
    assert unfiled.failed_waiting(landing, set()) == {}


def test_failed_waiting_without_a_session_start_lists_audit_and_raw_parks(
    landing: LandingDirs,
) -> None:
    _raw(landing, [("s9", "park-b")], 600, first_seq=2)
    _audit(landing, "s9", first_seq=2)
    assert unfiled.failed_waiting(landing, set()) == {"s9": ("park-a", "park-b")}


def test_find_unfiled_lists_six_parks_in_park_id_order(landing: LandingDirs) -> None:
    ids = ["park-d", "park-f", "park-b", "park-e", "park-a", "park-c"]
    _start(landing, *((f"s-{park}", park, None) for park in ids))
    result = _run(landing, set())
    assert [park.park_id for park in result.parks] == [
        "park-a",
        "park-b",
        "park-c",
        "park-d",
        "park-e",
        "park-f",
    ]

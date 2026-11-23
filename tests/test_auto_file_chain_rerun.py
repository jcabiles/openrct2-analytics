"""Cases moved from the several-parks file: two company answers now take the chain."""

from __future__ import annotations

from pathlib import Path

import pytest

from openrct2_analytics.ingest import capture_session
from tests.auto_file_support import Asked, _before, _deliveries, _run
from tests.auto_file_support import data as data  # noqa: F401  (pytest fixture)
from tests.test_after_play import _copy
from tests.test_auto_file_answers import _plant
from tests.test_auto_file_several_parks import OPTIONS_OF_TWO, TWO_PARKS


def test_typed_input_is_discarded_before_the_first_per_park_question(
    data: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant(data, TWO_PARKS)
    _before(tmp_path, [])
    log: list[str] = []
    monkeypatch.setattr(capture_session, "discard_typed_input", lambda: log.append("discard"))
    code, _, _ = _run(tmp_path, "company", asked=Asked(["1", "2"], log))
    assert code == 0
    assert log == ["discard", "ask", "ask"]


def test_an_earlier_play_park_is_asked_its_own_question_and_ranks_only_the_new_parks(
    data: Path, tmp_path: Path
) -> None:
    # Echo has the oldest session of all, and it is in the record file: an earlier play's park.
    _plant(data, [("s0", "park-e", "Echo"), ("s1", "park-a", "Alpha"), ("s2", "park-b", "Beta")])
    _before(tmp_path, ["s0"])
    code, asked, filed = _run(tmp_path, "company", asked=Asked(["2", "1", "2"]))
    assert code == 0
    assert asked.prompts == [
        "Park Echo (first played Oct 1) from an earlier play is waiting. Where should it count?\n"
        "1. Company\n2. Sandbox\n3. Don't file now\n",
        "Park Alpha (first played Oct 2), 0 game days played, is new in this play. Which is it?\n"
        + OPTIONS_OF_TWO,
        "Park Beta (first played Oct 3), 0 game days played, is new in this play. Which is it?\n"
        + OPTIONS_OF_TWO,
    ]
    assert filed.calls == [
        ["--data-set", "company", "--parks", "park-e:practice,park-a:company,park-b:company"]
    ]
    assert filed.landed == [True]


def test_parks_with_the_same_first_emitted_at_are_ranked_by_park_id(
    data: Path, tmp_path: Path
) -> None:
    # Six parks open at the same instant, listed in reverse park ID order: park-a is first.
    parks = "fedcba"
    ties = " UNION ALL ".join(
        f"SELECT 's{n}' AS session_id, 'park-{p}' AS park_id, '{p}' AS park_name, 1 AS game_year,"
        " TIMESTAMPTZ '2026-10-01 10:00:00+00' AS emitted_at"
        for n, p in enumerate(parks, start=1)
    )
    _copy(data / "company" / "parquet" / "v1" / "session_start.parquet", ties)
    audit = " UNION ALL ".join(
        f"SELECT 'park-{p}' AS park_id, 's{n}' AS session_id, 1 AS park_count, 0 AS missing, "
        "0 AS duplicates, 1 AS first_seq, 1 AS last_seq, 1 AS row_count"
        for n, p in enumerate(parks, start=1)
    )
    _copy(data / "company" / "parquet" / "audit" / "seq_audit.parquet", audit)
    _before(tmp_path, [])
    code, _, filed = _run(tmp_path, "company", asked=Asked(["6", "5", "4", "3", "2", "1"]))
    assert code == 0
    assert filed.calls == [
        [
            "--data-set",
            "company",
            "--parks",
            "park-f:company,park-e:company,park-d:company,"
            "park-c:company,park-b:company,park-a:company",
        ]
    ]
    assert [rows[0][:2] for rows in _deliveries(data)] == [
        ("park-a", "2000"),
        ("park-b", "2001"),
        ("park-c", "2002"),
        ("park-d", "2003"),
        ("park-e", "2004"),
        ("park-f", "2005"),
    ]

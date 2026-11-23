"""auto-file refuses while a session that failed its seq audit waits unfiled (spec R4, R6, R10).

Each case plants two clean waiting sessions and fails one of them. Expected lines are literals
copied from the spec's R4 and R5.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openrct2_analytics.ingest import auto_file
from tests.auto_file_support import BEFORE, _before, _feed, _run, _sessions
from tests.auto_file_support import data as data  # noqa: F401  (pytest fixture)
from tests.test_after_play import _copy, _tree

HOW = (
    "Filing files every waiting session, so nothing is filed while one waits. To see what "
    "removing it would do, run make delete-company-data SESSION={first} "
    "(a preview; it deletes nothing)"
)


def _audit(data: Path, *rows: tuple[str, str, int]) -> None:
    """Write (park, session, missing) audit rows; every other audit column is clean."""
    values = ", ".join(f"('{park}', '{session}', {missing})" for park, session, missing in rows)
    _copy(
        data / "company" / "parquet" / "audit" / "seq_audit.parquet",
        "SELECT park_id, session_id, missing, 0 AS duplicates, 1 AS first_seq, 1 AS park_count, "
        f"1 AS last_seq, 1 AS row_count FROM (VALUES {values}) AS t(park_id, session_id, missing)",
    )


def test_a_failed_waiting_session_is_refused_before_any_question_or_registration(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _sessions(data, [("s1", "park-a", "Alpha"), ("s2", "park-b", "Beta")])
    _audit(data, ("park-a", "s1", 1), ("park-b", "s2", 0))
    _before(tmp_path, [])
    before = _tree(tmp_path)
    code, asked, filed = _run(tmp_path, "company")
    assert code == 2
    assert capsys.readouterr().out == (
        "auto-file refused: seq-failed: session s1 of park park-a failed its seq audit. "
        + HOW.format(first="s1")
        + ". Nothing was changed.\n"
    )
    assert asked.prompts == []
    assert filed.calls == []
    assert not _feed(data).exists()
    assert (tmp_path / BEFORE).read_text(encoding="utf-8") == "[]"
    assert _tree(tmp_path) == before


def test_a_failed_session_of_one_park_refuses_while_another_park_is_clean(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _sessions(data, [("s1", "park-a", "Alpha"), ("s2", "park-b", "Beta")])
    _audit(data, ("park-a", "s1", 0), ("park-b", "s2", 1))
    _before(tmp_path, [])
    code, asked, filed = _run(tmp_path, "company")
    assert code == 2
    assert capsys.readouterr().out == (
        "auto-file refused: seq-failed: session s2 of park park-b failed its seq audit. "
        + HOW.format(first="s2")
        + ". Nothing was changed.\n"
    )
    assert asked.prompts == []
    assert filed.calls == []
    assert not _feed(data).exists()


def test_a_failed_session_with_no_session_start_is_refused_not_nothing_waiting(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _audit(data, ("park-c", "s9", 1))
    _before(tmp_path, [])
    code, asked, filed = _run(tmp_path, "company")
    assert code == 2
    assert capsys.readouterr().out == (
        "auto-file refused: seq-failed: session s9 of park park-c failed its seq audit. "
        + HOW.format(first="s9")
        + ". Nothing was changed.\n"
    )
    assert asked.prompts == []
    assert filed.calls == []


def test_recording_the_before_file_is_not_refused_by_a_failed_session(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _sessions(data, [("s1", "park-a", "Alpha")])
    _audit(data, ("park-a", "s1", 1))
    code = auto_file.main(["--data-set", "company", "--record"], project_dir=tmp_path)
    assert code == 0
    assert json.loads((tmp_path / BEFORE).read_text(encoding="utf-8")) == ["s1"]


def test_a_failed_session_is_refused_before_a_bad_registry_feed_is_read(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _sessions(data, [("s1", "park-a", "Alpha"), ("s2", "park-b", "Beta")])
    _audit(data, ("park-a", "s1", 1), ("park-b", "s2", 0))
    _before(tmp_path, [])
    _feed(data).mkdir(parents=True)
    (_feed(data) / "park_registry_2026-10-18_01.csv").write_text(
        "not,a,valid,feed\n", encoding="utf-8"
    )
    code, asked, filed = _run(tmp_path, "company")
    assert code == 2
    assert capsys.readouterr().out == (
        "auto-file refused: seq-failed: session s1 of park park-a failed its seq audit. "
        + HOW.format(first="s1")
        + ". Nothing was changed.\n"
    )
    assert asked.prompts == []
    assert filed.calls == []

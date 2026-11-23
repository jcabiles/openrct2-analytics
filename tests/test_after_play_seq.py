"""after-play refuses while a session that failed its seq audit waits unfiled (spec R1-R3, R5-R8).

Each case starts from the valid fixture of ``tests/test_after_play.py`` (two clean waiting
sessions, ``s1`` of park-a and ``s2`` of park-b) and changes one thing. Expected lines are
literals copied from the spec's R5.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openrct2_analytics.ingest import after_play, lock, play_status
from openrct2_analytics.ingest.convert import landing_lock_path
from tests.test_after_play import _copy, _run, _tree
from tests.test_after_play import data as data  # noqa: F401  (pytest fixture)
from tests.test_play_status import _warehouse, _writer_holds

HOW = (
    "Filing files every waiting session, so nothing is filed while one waits. To see what "
    "removing it would do, run make delete-company-data SESSION={first} "
    "(a preview; it deletes nothing)"
)
ONE = (
    "after-play refused: seq-failed: session s1 of park park-a failed its seq audit. "
    + HOW.format(first="s1")
    + ". Nothing was changed.\n"
)
PARKS = "park-a:company,park-b:practice"


def _audit(data: Path, *rows: tuple[str, str, int, int, int]) -> None:
    """Replace the audit: (park, session, missing, duplicates, first_seq) rows, one park each."""
    values = ", ".join(f"('{park}', '{session}', {m}, {d}, {f})" for park, session, m, d, f in rows)
    _copy(
        data / "company" / "parquet" / "audit" / "seq_audit.parquet",
        "SELECT park_id, session_id, missing, duplicates, first_seq, 1 AS park_count, "
        "1 AS last_seq, 1 AS row_count FROM (VALUES "
        f"{values}) AS t(park_id, session_id, missing, duplicates, first_seq)",
    )


def _refused(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], *args: str, line: str
) -> None:
    before = _tree(tmp_path)
    assert _run(tmp_path, "--data-set", "company", *args) == 2
    assert _tree(tmp_path) == before
    assert capsys.readouterr().out == line
    assert not (data / "company" / "registry").exists()
    assert not (tmp_path / "warehouse").exists()


@pytest.mark.parametrize("args", [[], ["--parks", "park-a:company"], ["--parks", PARKS]])
def test_a_gap_refuses_with_the_exact_line_and_changes_nothing(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    _audit(data, ("park-a", "s1", 1, 0, 1), ("park-b", "s2", 0, 0, 1))
    _refused(data, tmp_path, capsys, *args, line=ONE)


def test_a_repeat_refuses(data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _audit(data, ("park-a", "s1", 0, 1, 1), ("park-b", "s2", 0, 0, 1))
    _refused(data, tmp_path, capsys, "--parks", PARKS, line=ONE)


def test_a_first_value_other_than_one_refuses(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _audit(data, ("park-a", "s1", 0, 0, 2), ("park-b", "s2", 0, 0, 1))
    _refused(data, tmp_path, capsys, "--parks", PARKS, line=ONE)


def test_two_failed_sessions_are_named_in_id_order_and_the_command_names_the_first(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _audit(data, ("park-b", "s2", 0, 0, 2), ("park-a", "s1", 1, 0, 1))
    line = (
        "after-play refused: seq-failed: session s1 of park park-a failed its seq audit; "
        "session s2 of park park-b failed its seq audit. "
        + HOW.format(first="s1")
        + ". Nothing was changed.\n"
    )
    _refused(data, tmp_path, capsys, "--parks", PARKS, line=line)


def test_a_failed_session_of_one_park_refuses_while_another_park_is_clean(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _audit(data, ("park-a", "s1", 0, 0, 1), ("park-b", "s2", 1, 0, 1))
    line = (
        "after-play refused: seq-failed: session s2 of park park-b failed its seq audit. "
        + HOW.format(first="s2")
        + ". Nothing was changed.\n"
    )
    _refused(data, tmp_path, capsys, "--parks", "park-a:company", line=line)


def test_a_failed_session_with_no_session_start_refuses_instead_of_nothing_waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "data"
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(root))
    _audit(root, ("park-c", "s9", 0, 0, 2))
    line = (
        "after-play refused: seq-failed: session s9 of park park-c failed its seq audit. "
        + HOW.format(first="s9")
        + ". Nothing was changed.\n"
    )
    _refused(root, tmp_path, capsys, line=line)


def test_a_landing_lock_is_refused_before_a_failed_session(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _audit(data, ("park-a", "s1", 1, 0, 1), ("park-b", "s2", 0, 0, 1))
    with lock.hold_lock(landing_lock_path(data / "company" / "parquet"), "test holder"):
        assert _run(tmp_path, "--data-set", "company", "--parks", PARKS) == 2
    assert "after-play refused: lock-taken:" in capsys.readouterr().out


def test_a_warehouse_being_built_is_refused_before_a_failed_session(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _audit(data, ("park-a", "s1", 1, 0, 1), ("park-b", "s2", 0, 0, 1))
    with _writer_holds(_warehouse(tmp_path, [])):
        assert _run(tmp_path, "--data-set", "company", "--parks", PARKS) == 2
    assert "after-play refused: warehouse-busy:" in capsys.readouterr().out


def test_a_failed_session_already_filed_does_not_block(
    data: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # s1 fails on a gap (missing = 2), not on park_count, and the warehouse holds it.
    _audit(data, ("park-a", "s1", 2, 0, 1), ("park-b", "s2", 0, 0, 1))
    _warehouse(tmp_path, ["s1"])
    monkeypatch.setattr(after_play, "_make", lambda target, data_set: lambda: 0)
    assert _run(tmp_path, "--data-set", "company", "--parks", "park-b:practice") == 0
    out = capsys.readouterr().out
    assert "seq-failed" not in out
    assert "after-play: transform: make transform DATA_SET=company" in out


def test_a_failed_session_of_two_parks_names_both_in_the_exact_line(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The audit names park-a; the raw file also holds a session_start of s1 under park-c.
    _audit(data, ("park-a", "s1", 1, 0, 1), ("park-b", "s2", 0, 0, 1))
    raw = data / "company" / "raw" / "v1"
    raw.mkdir(parents=True)
    (raw / "events-2026-10-01.jsonl").write_text(
        '{"session_id": "s1", "park_id": "park-c", "event_type": "session_start"}\n',
        encoding="utf-8",
    )
    line = (
        "after-play refused: seq-failed: session s1 of park park-a, park-c failed its seq audit. "
        + HOW.format(first="s1")
        + ". Nothing was changed.\n"
    )
    _refused(data, tmp_path, capsys, "--parks", PARKS, line=line)


def test_a_warehouse_that_turns_busy_after_the_first_read_is_refused_as_busy(
    data: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # No failed session: the seq-failed check now runs on the first read, before read_status reads
    # again, so only a clean fixture reaches the second read.
    real = play_status.warehouse_sessions
    calls: list[int] = []

    def second_read_is_building(path: Path, project_dir: Path) -> tuple[str, set[str] | None]:
        calls.append(1)
        return real(path, project_dir) if len(calls) == 1 else ("building", None)

    monkeypatch.setattr(play_status, "warehouse_sessions", second_read_is_building)
    before = _tree(tmp_path)
    assert _run(tmp_path, "--data-set", "company", "--parks", PARKS) == 2
    assert _tree(tmp_path) == before
    assert capsys.readouterr().out == (
        "after-play refused: warehouse-busy: Another command is writing "
        "warehouse/dev/dev.duckdb. Nothing was changed.\n"
    )
    assert len(calls) == 2


def test_a_failed_session_is_refused_before_a_bad_registry_feed_is_read(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _audit(data, ("park-a", "s1", 1, 0, 1), ("park-b", "s2", 0, 0, 1))
    feed = data / "company" / "registry" / "v1"
    feed.mkdir(parents=True)
    (feed / "park_registry_2026-10-18_01.csv").write_text("not,a,valid,feed\n", encoding="utf-8")
    assert _run(tmp_path, "--data-set", "company", "--parks", PARKS) == 2
    assert capsys.readouterr().out == ONE

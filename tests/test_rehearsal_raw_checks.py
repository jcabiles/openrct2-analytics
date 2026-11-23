"""The rehearsal capture's checks for its raw event files."""

from __future__ import annotations

from pathlib import Path

import pytest

from openrct2_analytics.ingest import rehearsal_chain
from openrct2_analytics.ingest.bench_play import play
from openrct2_analytics.ingest.bench_setup import RunFolder
from openrct2_analytics.ingest.contracts import LANDING_FOLDER
from openrct2_analytics.ingest.rehearsal_chain import raw_problems
from tests.test_rehearsal_capture import (
    START,
    RehearsalHarness,
    raw_folder,
    session,
    stats,
)


@pytest.mark.parametrize(
    "case",
    [
        ('{"schema_version": 1, "session_id": "standin-1", "seq": 99}', "lacks event_type"),
        (
            '{"schema_version": 1, "event_type": "session_start", "session_id": ["a"], "seq": 0}',
            "has non-string session_id",
        ),
        (
            '{"schema_version": 1, "event_type": {"name": "session_start"}, '
            '"session_id": "standin-1", "seq": 0}',
            "has non-string event_type",
        ),
        ("{not json", "is not valid JSON"),
    ],
    ids=["no-event-type", "list-session-id", "dict-event-type", "not-json"],
)
def test_a_line_the_listener_accepted_but_the_checks_cannot_read_fails_the_attempt(
    rh: RehearsalHarness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: tuple[str, str],
) -> None:
    bad_line, problem = case

    def play_then_add_line(
        bench: object, folder: RunFolder, *args: object, **kwargs: object
    ) -> object:
        result = play(bench, folder, *args, **kwargs)  # type: ignore[arg-type]
        landed = sorted((folder.raw / LANDING_FOLDER).glob("events-*.jsonl"))[0]
        with landed.open("a", encoding="utf-8") as handle:
            handle.write(bad_line + "\n")
        return result

    monkeypatch.setattr(rehearsal_chain, "play", play_then_add_line)
    rh.bench.plan(session(1), session(1))

    assert rh.main() == 1

    assert len(rh.bench.launch_argvs()) == 2  # one retry, then the chain stops
    out = capsys.readouterr().out
    assert out.count(problem) == 2
    assert "Step 1 (P1-1, Park 1), attempt 2, " in out
    assert "failed twice; the chain stopped. Nothing was landed." in out
    assert not (rh.data_root / "rehearsal").exists()
    rh.assert_protected()


def test_a_non_warmup_row_off_speed_8_fails_the_attempt_even_after_rows_at_speed_8(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    # Day 0 is the warm-up row and day 1 runs at 8; day 2 drops to speed 2.
    rh.bench.plan(session(1, stats=3, slow_row=2))

    assert rh.main() == 1

    assert len(rh.bench.launch_argvs()) == 2
    out = capsys.readouterr().out
    assert out.count("game_speed other than 8") == 2
    assert not (rh.data_root / "rehearsal").exists()
    rh.assert_protected()


def test_a_warmup_row_at_speed_1_before_speed_8_rows_is_valid(tmp_path: Path) -> None:
    rows = [START, stats(1, 1, warmup=True), stats(2, 8), stats(3, 8)]

    assert raw_problems(raw_folder(tmp_path, rows)) == []


def test_two_session_start_rows_are_a_problem(tmp_path: Path) -> None:
    rows = [START, {**START, "seq": 1}, stats(2, 8)]

    assert raw_problems(raw_folder(tmp_path, rows)) == ["2 session_start rows, expected 1"]


def test_two_session_ids_are_a_problem(tmp_path: Path) -> None:
    rows = [START, stats(1, 8), {**stats(2, 8), "session_id": "s2"}]

    assert raw_problems(raw_folder(tmp_path, rows)) == ["2 session_id values, expected 1"]


def test_a_non_warmup_row_at_speed_1_after_speed_8_is_a_problem(tmp_path: Path) -> None:
    rows = [START, stats(1, 1, warmup=True), stats(2, 8), stats(3, 1)]

    assert raw_problems(raw_folder(tmp_path, rows)) == [
        "plugin_stats at seq 3 has game_speed other than 8"
    ]

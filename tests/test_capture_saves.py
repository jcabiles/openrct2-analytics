"""The capture command with the save-file watcher, run as a child process on temp folders.

The test plays the game's part: it moves placeholder ``.park`` files (never game content) into
the user folder's ``save/`` folder with a chosen modified time, and sends ``save_written``
events through a real socket with a chosen ``emitted_at``.
"""

from __future__ import annotations

import json
import os
import signal
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openrct2_analytics.ingest import capture, capture_session
from openrct2_analytics.ingest.capture_session import (
    EXIT_INTERRUPTED,
    EXIT_PROBLEM,
    Cleanup,
    Options,
    convert_and_report,
)
from openrct2_analytics.ingest.game_check import GameState
from openrct2_analytics.ingest.listener import EventServer, Lander, format_received_at
from openrct2_analytics.ingest.save_pairing import WatcherError
from openrct2_analytics.ingest.save_watch import SaveWatcher, WatchStop, watch_folders
from tests.test_capture import (
    READY,
    Command,
    Folders,
    Game,
    Start,
    children_fixture,
    folders_fixture,
    free_port,
    game_fixture,
    play,
    plugin_lines,
    start_fixture,
)
from tests.test_convert import PARK, land
from tests.test_convert_event_types import typed_event

# The shared fixtures are registered under their `name=`; listing them keeps the imports used.
__all__ = ["children_fixture", "folders_fixture", "game_fixture", "start_fixture"]

GAP = timedelta(milliseconds=100)  # the measured gap from the save hook to the file is under 0.2 s


def records_dir(folders: Folders) -> Path:
    return folders.data / "rehearsal" / "save_files" / "v1"


def records(folders: Folders) -> list[dict[str, object]]:
    lines = [
        line
        for path in sorted(records_dir(folders).glob("save_file_observation_*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    return [json.loads(line) for line in lines]


def put_park(folders: Folders, name: str, modified: datetime) -> None:
    """Move a placeholder file into ``save/`` with ``modified`` as its time, in one step."""
    staged = folders.root / "staging" / f"{name}.park"
    staged.parent.mkdir(exist_ok=True)
    staged.write_bytes(b"placeholder bytes, not game content")
    stamp = modified.timestamp()
    os.utime(staged, (stamp, stamp))
    os.replace(staged, folders.user / "save" / f"{name}.park")


def save_event(session: str, seq: int, emitted: datetime) -> str:
    """One ``save_written`` line as the plugin sends it (no ``received_at``)."""
    doc = json.loads(typed_event(session, seq, "save_written", {"save_id": f"{session}-save"}))
    del doc["received_at"]
    doc["emitted_at"] = format_received_at(emitted)
    return json.dumps(doc)


def session_lines(session: str, emitted: datetime | None = None) -> list[str]:
    lines = plugin_lines(session, (1, 2))
    return lines if emitted is None else [*lines, save_event(session, 3, emitted)]


def capture_run(
    start: Start,
    game: Callable[[], Game],
    lines: Sequence[str],
    *,
    while_playing: Callable[[], None] = lambda: None,
) -> Command:
    """Start the command, open the game, run ``while_playing``, send the lines, quit the game."""
    port = free_port()
    command = start(port)
    command.wait_for(READY)
    running = game()
    command.wait_for("game seen")
    while_playing()
    play(port, lines)
    command.wait_for("events arriving")
    running.quit()
    return command


@contextmanager
def read_only(folder: Path) -> Iterator[None]:
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o500)
    try:
        yield
    finally:
        folder.chmod(0o700)


def test_start_records_exist_when_the_ready_line_prints(folders: Folders, start: Start) -> None:
    put_park(folders, "slot-main", datetime.now(UTC))

    command = start(free_port())
    command.wait_for(READY)

    [record] = records(folders)
    assert (record["observation"], record["file_name"], record["folder_kind"]) == (
        "start",
        "slot-main",
        "save",
    )
    os.kill(command.process.pid, signal.SIGTERM)
    assert command.finish() == EXIT_INTERRUPTED


def test_one_save_with_its_file_exits_0_and_prints_the_pair_line(
    folders: Folders, start: Start, game: Callable[[], Game]
) -> None:
    emitted = datetime.now(UTC)
    command = capture_run(
        start,
        game,
        session_lines("one", emitted),
        while_playing=lambda: put_park(folders, "quicksave", emitted + GAP),
    )

    assert command.finish() == 0, command.output
    assert f"quicksave (save): save_id one-save, park_id {PARK}" in command.output


def test_one_save_with_no_file_exits_1_with_the_no_file_line(
    folders: Folders, start: Start, game: Callable[[], Game]
) -> None:
    command = capture_run(start, game, session_lines("one", datetime.now(UTC)))

    assert command.finish() == EXIT_PROBLEM, command.output
    assert "no file record within 5 s" in command.output


def test_one_save_with_two_candidate_files_exits_1_with_the_window_line(
    folders: Folders, start: Start, game: Callable[[], Game]
) -> None:
    emitted = datetime.now(UTC)

    def two_files() -> None:
        put_park(folders, "first", emitted + GAP)
        put_park(folders, "second", emitted + GAP)

    command = capture_run(start, game, session_lines("one", emitted), while_playing=two_files)

    assert command.finish() == EXIT_PROBLEM, command.output
    assert "two-candidate window" in command.output
    assert "no file record" not in command.output


def test_a_main_file_changed_between_runs_is_flagged_and_keeps_the_exit_code(
    folders: Folders, start: Start, game: Callable[[], Game]
) -> None:
    emitted = datetime.now(UTC)
    first = capture_run(
        start,
        game,
        session_lines("one", emitted),
        while_playing=lambda: put_park(folders, "slot-main", emitted + GAP),
    )
    assert first.finish() == 0, first.output
    put_park(folders, "slot-main", emitted + timedelta(seconds=100))  # changed outside any run

    second = capture_run(start, game, session_lines("two"))

    assert second.finish() == 0, second.output
    assert "slot-main changed since its last paired write" in second.output


def test_a_scan_error_after_start_keeps_events_landing_and_exits_1(
    folders: Folders, start: Start, game: Callable[[], Game]
) -> None:
    with read_only(records_dir(folders)):
        port = free_port()
        command = start(port)
        command.wait_for(READY)
        running = game()
        command.wait_for("game seen")
        put_park(folders, "quicksave", datetime.now(UTC))
        command.wait_for("Save-file watcher stopped at")  # printed when it happens
        play(port, session_lines("one"))
        command.wait_for("events arriving")
        running.quit()
        code = command.finish()

    assert code == EXIT_PROBLEM, command.output
    [dated] = (folders.raw / "v1").glob("events-*.jsonl")
    assert len(dated.read_text(encoding="utf-8").splitlines()) == 2
    assert "capture failure: watcher error at" in command.output


def test_a_first_scan_failure_stops_before_the_ready_line_and_exits_1(
    folders: Folders, start: Start
) -> None:
    put_park(folders, "slot-main", datetime.now(UTC))

    with read_only(records_dir(folders)):
        command = start(free_port())
        code = command.finish()

    assert code == EXIT_PROBLEM, command.output  # not 130
    assert "The save-file watcher could not start" in command.output
    assert READY not in command.output
    assert "The plugin file was removed from" in command.output
    assert not folders.installed.exists()
    assert not folders.record.exists()


def test_an_interrupted_run_prints_the_skip_line(folders: Folders, start: Start) -> None:
    command = start(free_port())
    command.wait_for(READY)

    os.kill(command.process.pid, signal.SIGTERM)

    assert command.finish() == EXIT_INTERRUPTED, command.output
    assert "Save pairing skipped: the run was interrupted." in command.output
    assert "Watcher error at" not in command.output


def test_an_interrupt_after_a_watcher_error_exits_130_and_prints_the_error(
    folders: Folders, start: Start
) -> None:
    with read_only(records_dir(folders)):
        command = start(free_port())
        command.wait_for(READY)
        put_park(folders, "quicksave", datetime.now(UTC))
        command.wait_for("Save-file watcher stopped at")

        os.kill(command.process.pid, signal.SIGTERM)
        code = command.finish()

    assert code == EXIT_INTERRUPTED, command.output
    assert "Watcher error at" in command.output


def test_a_torn_line_in_this_runs_record_file_exits_1_naming_file_and_line(
    folders: Folders, start: Start, game: Callable[[], Game]
) -> None:
    def tear_a_record_file() -> None:
        torn = records_dir(folders) / "save_file_observation_2020-01-01.jsonl"
        torn.parent.mkdir(parents=True, exist_ok=True)
        torn.write_text("{not json\n", encoding="utf-8")

    command = capture_run(start, game, session_lines("one"), while_playing=tear_a_record_file)

    assert command.finish() == EXIT_PROBLEM, command.output
    assert (
        "capture failure: unreadable record line save_file_observation_2020-01-01.jsonl line 1"
        in command.output
    )


def land_save_events(raw: Path, count: int = 2) -> None:
    """Land events that carry ``received_at`` (2026-09-30 23:30), so conversion succeeds."""
    land(
        raw,
        *(typed_event("one", seq, "save_written", {"save_id": "s"}) for seq in range(1, count + 1)),
    )


def test_a_timed_out_stop_skips_pairing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw, parquet = tmp_path / "raw", tmp_path / "parquet"
    land_save_events(raw)
    stuck = WatchStop(WatcherError(datetime(2026, 9, 30, tzinfo=UTC), "did not stop"), False, True)

    code = convert_and_report(
        raw, parquet, tmp_path / "save_files", datetime(2026, 9, 30, 23, tzinfo=UTC), watch=stuck
    )

    out = capsys.readouterr().out
    assert code == EXIT_PROBLEM
    assert "Events landed this run" in out  # conversion worked, so the timed-out branch ran
    assert "The converter failed" not in out
    assert "Save pairing skipped: the save-file watcher did not stop in time." in out
    assert "Watcher error at 2026-09-30T00:00:00+00:00: did not stop" in out
    assert "Save files\n" not in out


def test_a_converter_failure_skips_pairing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw, parquet = tmp_path / "raw", tmp_path / "parquet"
    land(raw, *plugin_lines("one", (1, 2)))  # no received_at, so the converter reports errors
    clean = WatchStop(None, False, False)

    code = convert_and_report(
        raw, parquet, tmp_path / "save_files", datetime(2026, 9, 30, 23, tzinfo=UTC), watch=clean
    )

    out = capsys.readouterr().out
    assert code == EXIT_PROBLEM
    assert "The converter failed" in out
    assert "Save pairing skipped: the converter failed." in out


def test_an_empty_raw_folder_skips_pairing_with_the_converter_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw, parquet = tmp_path / "raw", tmp_path / "parquet"
    raw.mkdir()  # no capture file, so the converter raises NoInputError
    clean = WatchStop(None, False, False)

    code = convert_and_report(
        raw, parquet, tmp_path / "save_files", datetime(2026, 9, 30, 23, tzinfo=UTC), watch=clean
    )

    out = capsys.readouterr().out
    assert code == EXIT_PROBLEM
    assert "Save pairing skipped: the converter failed." in out


def test_a_run_with_no_event_after_conversion_skips_pairing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw, parquet = tmp_path / "raw", tmp_path / "parquet"
    land_save_events(raw)  # received 2026-09-30 23:30, before this run's start
    clean = WatchStop(None, False, False)

    code = convert_and_report(
        raw, parquet, tmp_path / "save_files", datetime(2026, 10, 1, tzinfo=UTC), watch=clean
    )

    out = capsys.readouterr().out
    assert code == EXIT_PROBLEM
    assert "No event landed in this run." in out
    assert "Save pairing skipped: no event landed in this run." in out


def test_a_seq_gap_still_prints_the_save_files_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw, parquet = tmp_path / "raw", tmp_path / "parquet"
    land(raw, typed_event("one", 1, "save_written", {"save_id": "s"}))
    land(raw, typed_event("one", 3, "save_written", {"save_id": "s"}))
    clean = WatchStop(None, False, False)

    code = convert_and_report(
        raw, parquet, tmp_path / "save_files", datetime(2026, 9, 30, 23, tzinfo=UTC), watch=clean
    )

    out = capsys.readouterr().out
    assert code == EXIT_PROBLEM
    assert "seq audit FAILED" in out
    assert out.index("Save files") < out.index("A session of this run failed the seq audit")


def test_the_watcher_is_stopped_even_when_cleanup_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_cleanup(*_args: object) -> None:
        raise RuntimeError("cleanup broke")

    (tmp_path / "user" / "save").mkdir(parents=True)
    watcher = SaveWatcher(
        watch_folders(tmp_path / "user"),
        tmp_path / "save_files",
        datetime(2026, 9, 30, tzinfo=UTC),
        0.01,
        say=lambda _line: None,
    )
    server = EventServer(("127.0.0.1", 0), Lander(tmp_path / "raw"))
    monkeypatch.setattr(capture_session, "_remove_leftover", lambda *_args: None)
    monkeypatch.setattr(capture_session, "_install", lambda *_args: None)
    monkeypatch.setattr(capture_session, "_watch", lambda *_args: None)
    monkeypatch.setattr(capture_session, "set_signal_handlers", lambda _handler: None)
    monkeypatch.setattr(capture_session, "_clean_up", broken_cleanup)
    options = Options(game_check=lambda: GameState.RUNNING, data_set="rehearsal")

    try:
        with pytest.raises(RuntimeError, match="cleanup broke"):
            capture_session.run_session(
                server,
                tmp_path / "user",
                tmp_path / "capture",
                built=tmp_path / "built",
                watcher=watcher,
                options=options,
            )
        assert not any(t.name == "save-watcher" and t.is_alive() for t in threading.enumerate())
    finally:
        server.server_close()


def _capture_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    user = tmp_path / "user"
    (user / "plugin").mkdir(parents=True)
    (user / "save").mkdir()
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENRCT2_USER_DIR", str(user))
    monkeypatch.setenv("OPENRCT2_CAPTURE_DIR", str(tmp_path / "capture"))
    monkeypatch.setattr(capture_session, "_remove_leftover", lambda *_args: None)
    monkeypatch.setattr(capture_session, "_install", lambda *_args: None)
    monkeypatch.setattr(capture_session, "set_signal_handlers", lambda _handler: None)


def test_a_stuck_connection_thread_skips_pairing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _capture_env(tmp_path, monkeypatch)
    real_clean_up = capture_session._clean_up

    def stuck(
        server: EventServer, serving: threading.Thread, user_dir: Path, capture_dir: Path
    ) -> Cleanup:
        cleanup = real_clean_up(server, serving, user_dir, capture_dir)
        return Cleanup(cleanup.removal_line, cleanup.removed, 1)

    def watch(_check: object, lander: Lander, _poll: float, _limit: float | None) -> None:
        for line in plugin_lines("one", (1, 2)):
            assert lander.land(line.encode()) is True

    monkeypatch.setattr(capture_session, "_clean_up", stuck)
    monkeypatch.setattr(capture_session, "_watch", watch)
    built = tmp_path / "built.js"
    built.write_text("x", encoding="utf-8")
    options = Options(
        game_check=lambda: GameState.NOT_RUNNING, data_set="rehearsal", port=0, poll_seconds=0.01
    )

    code = capture.run(options, lambda: built)

    out = capsys.readouterr().out
    assert code == EXIT_PROBLEM
    assert "Save pairing skipped: a connection thread was still running." in out

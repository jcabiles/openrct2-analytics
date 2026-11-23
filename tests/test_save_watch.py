"""Behavioral tests for the save-folder watcher, over real temp folders, files and threads."""

from __future__ import annotations

import json
import os
import shutil
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openrct2_analytics.ingest.save_files import read_records
from openrct2_analytics.ingest.save_watch import SaveWatcher, watch_folders

RUN_STARTED = datetime(2026, 10, 19, 8, 0, 0, tzinfo=UTC)
DAY_ONE = datetime(2026, 10, 19, 23, 59, 59, 500_000, tzinfo=UTC)
WAIT = 5.0
KINDS = ["save", "autosave", "parent"]


class Clock:
    """A steppable clock: each call returns the current time; `step` moves it."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def step(self, delta: timedelta) -> None:
        self.now += delta


class Lines:
    """The watcher's printed lines; `seen` is set once a line has been printed."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.seen = threading.Event()

    def __call__(self, text: str) -> None:
        self.lines.append(text)
        self.seen.set()


@pytest.fixture
def user_dir(tmp_path: Path) -> Path:
    (tmp_path / "user" / "save" / "autosave").mkdir(parents=True)
    return tmp_path / "user"


@pytest.fixture
def landing(tmp_path: Path) -> Path:
    return tmp_path / "landing" / "save_files"


def make_watcher(
    user_dir: Path,
    landing: Path,
    *,
    clock: Callable[[], datetime] | None = None,
    say: Lines | None = None,
    poll_seconds: float = 0.01,
) -> SaveWatcher:
    return SaveWatcher(
        watch_folders(user_dir),
        landing,
        RUN_STARTED,
        poll_seconds,
        say=say or Lines(),
        clock=clock or Clock(DAY_ONE),
    )


def put(path: Path, size: int, mtime_s: int) -> None:
    path.write_bytes(b"x" * size)
    os.utime(path, ns=(mtime_s * 1_000_000_000, mtime_s * 1_000_000_000))


def records(landing: Path) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for path in sorted((landing / "v1").glob("save_file_observation_*.jsonl")):
        out += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return out


def test_folders_derived_from_the_user_folder(tmp_path: Path) -> None:
    assert watch_folders(tmp_path) == {
        "save": tmp_path / "save",
        "autosave": tmp_path / "save" / "autosave",
        "parent": tmp_path,
    }


@pytest.mark.parametrize("kind", KINDS)
def test_created_then_modified_record_in_each_folder(
    user_dir: Path, landing: Path, kind: str
) -> None:
    folder = watch_folders(user_dir)[kind]
    watcher = make_watcher(user_dir, landing)
    watcher.scan()
    put(folder / "Alpha.park", 10, 1_700_000_000)
    watcher.scan()
    put(folder / "Alpha.park", 10, 1_700_000_005)
    watcher.scan()

    created, modified = records(landing)
    assert created == {
        "run_started_at": "2026-10-19T08:00:00.000Z",
        "observation": "created",
        "file_name": "Alpha",
        "folder_kind": kind,
        "modified_at": "2023-11-14T22:13:20.000Z",
        "size_bytes": 10,
        "observed_at": "2026-10-19T23:59:59.500Z",
    }
    assert modified["observation"] == "modified"
    assert modified["modified_at"] == "2023-11-14T22:13:25.000Z"
    for record in (created, modified):
        name = str(record["file_name"])
        assert "/" not in name and name == "Alpha.park".removesuffix(".park")


def test_modified_when_only_the_size_changes(user_dir: Path, landing: Path) -> None:
    put(user_dir / "save" / "Alpha.park", 10, 1_700_000_000)
    watcher = make_watcher(user_dir, landing)
    watcher.scan()
    put(user_dir / "save" / "Alpha.park", 25, 1_700_000_000)
    watcher.scan()

    start, record = records(landing)
    assert (start["observation"], start["size_bytes"]) == ("start", 10)
    assert record["observation"] == "modified"
    assert record["size_bytes"] == 25


def test_unchanged_files_yield_no_record(user_dir: Path, landing: Path) -> None:
    put(user_dir / "save" / "Alpha.park", 10, 1_700_000_000)
    watcher = make_watcher(user_dir, landing)
    watcher.scan()
    watcher.scan()

    assert [r["observation"] for r in records(landing)] == ["start"]


def test_ignored_entries_yield_no_record(user_dir: Path, landing: Path) -> None:
    watcher = make_watcher(user_dir, landing)
    watcher.scan()
    (user_dir / "save" / "notes.txt").write_text("x", encoding="utf-8")
    (user_dir / "save" / "other").mkdir()
    put(user_dir / "save" / "other" / "Deep.park", 5, 1_700_000_000)
    put(user_dir / "real.park", 5, 1_700_000_000)
    (user_dir / "save" / "Link.park").symlink_to(user_dir / "real.park")
    (user_dir / "save" / "Dir.park").mkdir()
    watcher.scan()

    assert [r["file_name"] for r in records(landing)] == ["real"]


def test_start_records_every_park_file_before_it_returns(user_dir: Path, landing: Path) -> None:
    put(user_dir / "save" / "Park-main.park", 5, 1_700_000_000)
    put(user_dir / "save" / "autosave" / "Auto-main.park", 6, 1_700_000_001)
    put(user_dir / "Other-main.park", 7, 1_700_000_002)
    put(user_dir / "save" / "Plain.park", 8, 1_700_000_003)
    put(user_dir / "save" / "Park-main.txt", 8, 1_700_000_003)
    watcher = make_watcher(user_dir, landing)
    watcher.start()
    try:
        written = {(r["folder_kind"], r["file_name"], r["observation"]) for r in records(landing)}
    finally:
        assert watcher.stop().error is None

    assert written == {
        ("save", "Park-main", "start"),
        ("autosave", "Auto-main", "start"),
        ("parent", "Other-main", "start"),
        ("save", "Plain", "start"),
    }


def test_records_append_to_the_dated_file_and_never_rewrite_an_earlier_day(
    user_dir: Path, landing: Path
) -> None:
    clock = Clock(DAY_ONE)
    first = make_watcher(user_dir, landing, clock=clock)
    first.scan()
    put(user_dir / "save" / "Alpha.park", 10, 1_700_000_000)
    first.scan()
    day_one_file = landing / "v1" / "save_file_observation_2026-10-19.jsonl"
    day_one_bytes = day_one_file.read_bytes()

    clock.step(timedelta(seconds=1))
    second = make_watcher(user_dir, landing, clock=clock)
    second.scan()
    put(user_dir / "save" / "Alpha.park", 11, 1_700_000_009)
    second.scan()

    assert day_one_file.read_bytes() == day_one_bytes
    next_day = landing / "v1" / "save_file_observation_2026-10-20.jsonl"
    start, record = [json.loads(line) for line in next_day.read_text(encoding="utf-8").splitlines()]
    assert start["observation"] == "start"
    assert record["observation"] == "modified"
    assert record["observed_at"] == "2026-10-20T00:00:00.500Z"


def test_a_missing_autosave_folder_is_picked_up_once_created(user_dir: Path, landing: Path) -> None:
    shutil.rmtree(user_dir / "save" / "autosave")
    said = Lines()
    watcher = make_watcher(user_dir, landing, say=said)
    watcher.scan()
    watcher.scan()
    (user_dir / "save" / "autosave").mkdir()
    put(user_dir / "save" / "autosave" / "Auto.park", 4, 1_700_000_000)
    watcher.scan()

    (record,) = records(landing)
    assert (record["observation"], record["folder_kind"]) == ("created", "autosave")
    assert said.lines == []


def test_a_vanished_folder_prints_two_lines_and_judges_files_against_the_last_scan(
    user_dir: Path, landing: Path
) -> None:
    auto = user_dir / "save" / "autosave"
    put(auto / "Kept.park", 4, 1_700_000_000)
    put(auto / "Changed.park", 4, 1_700_000_000)
    said = Lines()
    watcher = make_watcher(user_dir, landing, say=said)
    watcher.scan()
    shutil.rmtree(auto)
    watcher.scan()
    watcher.scan()
    assert said.lines == ["autosave save folder is gone; watching for it to return."]

    auto.mkdir()
    put(auto / "Kept.park", 4, 1_700_000_000)
    put(auto / "Changed.park", 9, 1_700_000_000)
    put(auto / "New.park", 4, 1_700_000_000)
    watcher.scan()
    watcher.scan()

    assert said.lines[1:] == ["autosave save folder is back."]
    assert [(r["file_name"], r["observation"]) for r in records(landing)] == [
        ("Changed", "start"),
        ("Kept", "start"),
        ("Changed", "modified"),
        ("New", "created"),
    ]


def test_building_and_stopping_an_unstarted_watcher_touch_nothing(tmp_path: Path) -> None:
    user = tmp_path / "missing-user"
    landing = tmp_path / "landing"
    watcher = make_watcher(user, landing)

    assert watcher.stop() == watcher.stop()
    assert watcher.stop().error is None
    assert not user.exists() and not landing.exists()


def test_the_landing_folder_is_created_only_on_the_first_write(
    user_dir: Path, landing: Path
) -> None:
    watcher = make_watcher(user_dir, landing)
    watcher.start()
    assert not landing.exists()
    put(user_dir / "save" / "Alpha.park", 3, 1_700_000_000)
    assert watcher.stop().error is None
    assert (landing / "v1").is_dir()


def test_the_final_scan_at_stop_records_a_late_save(user_dir: Path, landing: Path) -> None:
    watcher = make_watcher(user_dir, landing, poll_seconds=3600)
    watcher.start()
    put(user_dir / "save" / "Quit.park", 3, 1_700_000_000)

    assert watcher.stop().error is None
    assert [r["file_name"] for r in records(landing)] == ["Quit"]


def break_save_folder(user_dir: Path) -> None:
    """Make listing the save folder raise a PermissionError in one step (no poll sees it gone)."""
    (user_dir / "save").chmod(0)


def restore_save_folder(user_dir: Path) -> None:
    (user_dir / "save").chmod(0o755)


def test_the_first_scan_error_propagates_from_start(user_dir: Path, landing: Path) -> None:
    break_save_folder(user_dir)
    watcher = make_watcher(user_dir, landing)

    try:
        with pytest.raises(PermissionError):
            watcher.start()
    finally:
        restore_save_folder(user_dir)
    assert watcher.stop().error is None


def test_a_scan_error_after_start_is_stored_printed_and_stops_scanning(
    user_dir: Path, landing: Path
) -> None:
    clock = Clock(DAY_ONE)
    said = Lines()
    watcher = make_watcher(user_dir, landing, clock=clock, say=said)
    watcher.start()
    clock.step(timedelta(minutes=1))
    break_save_folder(user_dir)
    try:
        assert said.seen.wait(WAIT)
    finally:
        restore_save_folder(user_dir)
    put(user_dir / "save" / "Late.park", 3, 1_700_000_000)
    result = watcher.stop()

    assert result.error is not None
    assert result.error.at == clock.now
    assert result.error.message.startswith("PermissionError: ")
    assert not result.ended_early and not result.join_timed_out
    assert result.error.message in said.lines[0]
    assert not landing.exists()


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_thread_ended_by_another_exception_is_a_watcher_error(
    user_dir: Path, landing: Path
) -> None:
    raised = threading.Event()

    def clock() -> datetime:
        # Only the watcher's thread fails; stop() reads the clock on the calling thread.
        if threading.current_thread().name == "save-watcher":
            raised.set()
            raise RuntimeError("boom")
        return DAY_ONE

    watcher = make_watcher(user_dir, landing, clock=clock)
    watcher.start()
    assert raised.wait(WAIT)
    result = watcher.stop()

    assert result.ended_early
    assert result.error is not None and result.error.message == "watcher thread ended early"


def test_a_join_that_times_out_is_a_watcher_error(user_dir: Path, landing: Path) -> None:
    release = threading.Event()
    blocked = threading.Event()
    armed = threading.Event()

    def clock() -> datetime:
        # Only the watcher's thread blocks; stop() reads the clock on the calling thread.
        if armed.is_set() and threading.current_thread().name == "save-watcher":
            blocked.set()
            assert release.wait(WAIT)
        return DAY_ONE

    watcher = make_watcher(user_dir, landing, clock=clock)
    watcher.start()
    armed.set()
    assert blocked.wait(WAIT)
    result = watcher.stop(join_limit=0.1)
    release.set()

    assert result.join_timed_out
    assert result.error is not None and result.error.message == "watcher did not stop within 0.1 s"


class VanishingEntry:
    """A directory entry whose file is gone by the time it is read."""

    def __init__(self, name: str) -> None:
        self.name = name

    def is_file(self, *, follow_symlinks: bool) -> bool:
        return True

    def stat(self, *, follow_symlinks: bool) -> os.stat_result:
        raise FileNotFoundError(self.name)


def test_a_file_that_vanishes_between_listing_and_stat_is_skipped(
    user_dir: Path, landing: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_scandir = os.scandir
    save_dir = user_dir / "save"

    def scandir(path: Path) -> list[object]:
        if path == save_dir:
            return [VanishingEntry("Gone.park")]
        return list(real_scandir(path))

    monkeypatch.setattr(os, "scandir", scandir)
    watcher = make_watcher(user_dir, landing)
    watcher.start()

    assert watcher.stop().error is None
    assert not landing.exists()


def test_a_file_named_only_the_suffix_is_not_recorded(user_dir: Path, landing: Path) -> None:
    watcher = make_watcher(user_dir, landing)
    watcher.start()
    put(user_dir / "save" / ".park", 3, 1_700_000_000)
    put(user_dir / "save" / "Real.park", 3, 1_700_000_000)

    assert watcher.stop().error is None
    assert [r["file_name"] for r in records(landing)] == ["Real"]


def test_stop_after_a_failed_thread_start_is_a_no_op(
    user_dir: Path, landing: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def cannot_start(_thread: threading.Thread) -> None:
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", cannot_start)
    watcher = make_watcher(user_dir, landing)

    with pytest.raises(RuntimeError, match="can't start new thread"):
        watcher.start()
    result = watcher.stop()

    assert (result.error, result.ended_early, result.join_timed_out) == (None, False, False)


def test_a_torn_last_line_costs_only_itself(user_dir: Path, landing: Path) -> None:
    folder = landing / "v1"
    folder.mkdir(parents=True)
    torn = folder / "save_file_observation_2026-10-19.jsonl"
    torn.write_bytes(b'{"run_started_at": "2026-10-19T1')
    put(user_dir / "save" / "Park-main.park", 3, 1_700_000_000)

    make_watcher(user_dir, landing).scan()

    kept, unreadable = read_records(landing, RUN_STARTED)
    assert [(r.observation, r.file_name) for r in kept] == [("start", "Park-main")]
    assert [u.line_number for u in unreadable] == [1]

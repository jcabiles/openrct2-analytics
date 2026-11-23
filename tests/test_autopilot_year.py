"""The autopilot-year command end to end against the stand-in game, through ``main``.

``Full`` is the valid company world of ``test_autopilot_year_refusals.py`` with park-a's last
recorded save made a stand-in park: its archive copy carries the marker of session
``standin-7``, saved on 20 October of game year 2, so the run plays one stand-in launch to its
save on 1 March of game year 3 (12 game days, with October's statement). Each case changes one
thing: the stand-in's plan, the work folder right after the game stopped (as a game that sent
that line would have left it), or a landing step. Expected texts are copied from
docs/ai-dlc/specs/autopilot-year.md, section 4. ``test_autopilot_year_failures.py`` shares
``Full``.
"""

from __future__ import annotations

import json
import os
import re
import signal
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from openrct2_analytics.ingest import (
    autopilot_land,
    autopilot_run,
    autopilot_year,
    lock,
    save_backup,
)
from openrct2_analytics.ingest.autopilot_year import main
from openrct2_analytics.ingest.bench_play import play as real_play
from openrct2_analytics.ingest.bench_setup import RunFolder
from openrct2_analytics.ingest.capture_session import convert_and_report as real_report
from tests.autopilot_fixtures import event_row
from tests.test_autopilot_year_refusals import LAST_SAVE, READY, WORK_NAME, World
from tests.test_autopilot_year_refusals_data import earlier_autopilot_run

SOURCE = b"proven source park\n+standin-7"
STEM = "park-a-autopilot-3"
SESSION = "standin-1"  # the stand-in's first launch
IGNORED = "READY was ignored: park park-a has run on autopilot before."
OLDER_SAVES = (
    "Park park-a's older saves are now one game year behind: loading one under make play "
    "starts a newer session on the older branch, and this autopilot year leaves the kept "
    "timeline."
)
Step = Callable[[RunFolder], object]


def clean_entry(**changes: object) -> dict[str, object]:
    """A launch from 20 October of game year 2 to its save on 1 March of game year 3."""
    entry: dict[str, object] = {
        "park_id": "park-a",
        "start_date": [2, 7, 20],
        "stats": 40,
        "speed": 8,
        "save": True,
        "final_lines": 0,  # the helper pauses the game after its save: no later line
    }
    return {**entry, **changes}


class Full(World):
    """A company world whose run plays the stand-in game and lands."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__(tmp_path, monkeypatch, record_run=False)
        last = event_row(
            7,
            park_id="park-a",
            session_id="standin-7",
            game_date=(2, 7, 20),
            emitted_at=LAST_SAVE,
            save_id="save-standin-7",
        )
        self.saves[0] = (last, "Park A", len(SOURCE))
        self.copy_size = len(SOURCE)
        # The company raw folder holds only real captures; the convert after landing reads it.
        self.after_plant.append(lambda: self.raw_dir.joinpath("events-2026-11-12.jsonl").unlink())
        self.raw_sessions = []
        self.entry = clean_entry()
        self.after_game: list[Step] = []
        self.landing_steps: list[str] = []
        self.on_landing: dict[str, Callable[[], None]] = {}
        self.err: list[str] = []
        monkeypatch.setattr(autopilot_run, "play", self.play)
        monkeypatch.setattr(autopilot_land, "_land_file", self.land_file)
        monkeypatch.setattr(autopilot_year, "LANDING_LOCK_WAIT_S", 0.5)

    @property
    def raw_dir(self) -> Path:
        return self.company / "raw" / "v1"

    @property
    def work(self) -> Path:
        return self.bench.bench_dir / WORK_NAME

    @property
    def game_saves(self) -> Path:
        return self.bench.user_dir / "save"

    def plant_copy(self, archive: Path) -> Path:
        """The archive copy holds the source park; its size and modified time stay proven."""
        path = super().plant_copy(archive)
        info = path.stat()
        path.write_bytes(SOURCE)
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        return path

    def play(self, *args: object, **kwargs: object) -> str | None:
        problem = real_play(*args, **kwargs)  # type: ignore[arg-type]
        folder: RunFolder = args[1]  # type: ignore[assignment]
        date_emitted_as_save(folder)
        for step in self.after_game:
            step(folder)
        return problem

    def land_file(self, folder: Path, name: str, write: Callable[[Path], None]) -> Path:
        """Record each landing step in order, then run its seam (if any) before the real step."""
        step = folder.parent.name  # registry, save_files or raw
        self.landing_steps.append(step)
        if step in self.on_landing:
            self.on_landing.pop(step)()
        return REAL_LAND_FILE(folder, name, write)

    def go(self, capsys: pytest.CaptureFixture[str]) -> tuple[int, list[str]]:
        """Plant, run ``main`` with the stand-in game; return the code and output lines."""
        self.bench.plan(self.entry)
        self.plant()
        argv = [part for key, value in self.args.items() for part in (key, value)]
        code = main(
            argv,
            options=self.bench.options(
                clock=self.options_clock, sleep=self.sleep, load_average=lambda: self.load
            ),
            build=self.build,
            project_dir=self.project,
            game_check=lambda: self.game_state,
        )
        captured = capsys.readouterr()
        self.err = captured.err.splitlines()  # the listener's and the stand-in's own lines
        return code, captured.out.splitlines()

    def landed(self, folder: str) -> list[str]:
        path = self.company / folder / "v1"
        return sorted(p.name for p in path.iterdir()) if path.is_dir() else []


REAL_LAND_FILE = autopilot_land._land_file


def date_emitted_as_save(folder: RunFolder) -> None:
    """Date the ``save_written`` event 50 ms before the stand-in's save file was written.

    The stand-in dates ``emitted_at`` from a fixed base in the past while the file it writes
    carries the wall-clock time; the real game emits the event just before it writes the file.
    """
    save = folder.save_dir / f"{STEM}.park"
    if not save.exists():
        return  # a game that never saved: there is no file to date the event by
    written = save.stat().st_mtime - 0.05
    emitted = f"{datetime.fromtimestamp(written, UTC):%Y-%m-%dT%H:%M:%S.%f}"[:-3] + "Z"
    for path in sorted((folder.raw / "v1").glob("events-*.jsonl")):
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for index, line in enumerate(lines):
            event = json.loads(line)
            if event["event_type"] == "save_written":
                lines[index] = json.dumps({**event, "emitted_at": emitted}) + "\n"
        path.write_text("".join(lines), encoding="utf-8")


def last_line(events: int) -> str:
    return (
        "autopilot-year: park park-a played company year 2001 to 1 March of game year 3; "
        f"landed session {SESSION} ({events} events) and labeled it autopilot."
    )


def landed_raw(world: Full) -> Path:
    (path,) = world.raw_dir.glob(f"events-*-autopilot-{SESSION}.jsonl")
    return path


def label_rows(world: Full) -> list[list[str]]:
    rows = []
    for path in sorted((world.company / "registry" / "v1").glob("session_play_mode_*.csv")):
        rows += [line.split(",") for line in path.read_text(encoding="utf-8").splitlines()[1:]]
    return rows


@pytest.fixture(name="full")
def full_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Full:
    return Full(tmp_path, monkeypatch)


def daily_copy(world: Full) -> Path:
    return world.game_saves / f"Test Park-last-plugin-save-{date.today().isoformat()}.park"


def new_archive_copy(world: Full) -> Path:
    (path,) = [p for p in (world.archive / "park-a").iterdir() if p != world.copy]
    return path


def handlers() -> dict[str, object]:
    return {name: signal.getsignal(getattr(signal, name)) for name in lock.SIGNAL_NAMES}


def test_a_full_run_lands_label_records_then_one_raw_file(
    full: Full, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[tuple[bool, list[str], list[str]]] = []
    full.on_landing["raw"] = lambda: seen.append(
        (bool(label_rows(full)), full.landed("save_files"), full.landed("raw"))
    )
    code, lines = full.go(capsys)
    events = len(landed_raw(full).read_text(encoding="utf-8").splitlines())
    assert (code, lines[-1]) == (0, last_line(events))
    assert full.landing_steps == ["registry", "save_files", "raw"]
    (record,) = [n for n in full.landed("save_files") if n.endswith(f"-autopilot-{SESSION}.jsonl")]
    # When the raw step began, the label and the record had landed and no raw file had.
    assert seen == [(True, sorted([record, "save_file_observation_2026-11-12.jsonl"]), [])]
    assert full.landed("raw") == [landed_raw(full).name]
    assert label_rows(full) == [
        [SESSION, "park-a", "autopilot", READY, "company", date.today().isoformat()]
    ]
    assert IGNORED not in lines  # a first run's READY is recorded, not ignored


def test_the_report_pairs_the_end_of_year_save(
    full: Full, capsys: pytest.CaptureFixture[str]
) -> None:
    code, lines = full.go(capsys)
    assert code == 0
    assert "Save files" in lines
    assert f"  {STEM} (save): save_id save-{SESSION}, park_id park-a" in lines


def test_the_archive_and_dated_copies_hold_the_end_of_year_save(
    full: Full, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = full.go(capsys)
    assert code == 0
    end_of_year = new_archive_copy(full).read_bytes()
    assert end_of_year.startswith(SOURCE)  # the stand-in's save: the loaded park plus a marker
    assert end_of_year != SOURCE
    assert full.copy.read_bytes() == SOURCE  # the source copy is never touched
    assert daily_copy(full).read_bytes() == end_of_year


def test_a_same_day_dated_copy_is_left_alone_beside_a_timed_sibling(
    full: Full, capsys: pytest.CaptureFixture[str]
) -> None:
    # The command's own copy from earlier today: its bytes equal the park's archive copy.
    full.after_plant.append(lambda: full.game_saves.mkdir(parents=True))
    full.after_plant.append(lambda: daily_copy(full).write_bytes(SOURCE))
    code, lines = full.go(capsys)
    assert code == 0
    assert daily_copy(full).read_bytes() == SOURCE
    (sibling,) = [p for p in full.game_saves.iterdir() if p != daily_copy(full)]
    assert re.fullmatch(rf"{re.escape(daily_copy(full).stem)}-\d{{6}}\.park", sibling.name)
    assert sibling.read_bytes() == new_archive_copy(full).read_bytes()
    assert f"To refurbish the park, load save/{sibling.name}." in lines


def test_the_report_names_the_file_to_load(full: Full, capsys: pytest.CaptureFixture[str]) -> None:
    code, lines = full.go(capsys)
    assert code == 0
    assert lines[-3:] == [
        f"To refurbish the park, load save/{daily_copy(full).name}.",
        OLDER_SAVES,
        lines[-1],
    ]


def test_the_work_folder_is_removed_after_a_full_run(
    full: Full, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = full.go(capsys)
    assert code == 0
    assert full.bench.bench_dir.is_dir()
    assert not full.work.exists()


def test_kept_folders_of_earlier_failed_runs_are_listed(
    full: Full, capsys: pytest.CaptureFixture[str]
) -> None:
    older = full.bench.bench_dir / "autopilot-park-a-20261112T090000Z"
    full.after_plant.append(lambda: older.mkdir(parents=True))
    code, lines = full.go(capsys)
    assert code == 0
    assert (
        "Run folders kept from earlier failed runs of park park-a: "
        "autopilot-park-a-20261112T090000Z." in lines
    )
    assert older.is_dir()


def test_an_interrupt_during_play_lands_nothing_and_keeps_the_folder(
    full: Full, capsys: pytest.CaptureFixture[str]
) -> None:
    full.after_game.append(lambda folder: os.kill(os.getpid(), signal.SIGTERM))
    code, lines = full.go(capsys)
    assert code == 130
    # The progress lines of the run come first; the interrupt line is the last.
    assert lines[-1] == (
        f"Interrupted; company data was not touched; the run folder is kept at {full.work}."
    )
    assert all(line.startswith("autopilot: park park-a") for line in lines[:-1])
    assert full.landing_steps == []
    assert full.landed("raw") == []
    assert full.work.is_dir()


def test_an_interrupt_after_the_first_link_is_ignored_and_the_run_reports(
    full: Full, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted_report(*args: object, **kwargs: object) -> int:
        os.kill(os.getpid(), signal.SIGTERM)  # during the report, after the landing
        code: int = real_report(*args, **kwargs)  # type: ignore[arg-type]
        return code

    monkeypatch.setattr(autopilot_year, "convert_and_report", interrupted_report)
    # Right after the label's link, before the records land.
    full.on_landing["save_files"] = lambda: os.kill(os.getpid(), signal.SIGTERM)
    code, lines = full.go(capsys)
    events = len(landed_raw(full).read_text(encoding="utf-8").splitlines())
    assert (code, lines[-1]) == (0, last_line(events))
    assert not full.work.exists()


def test_a_later_run_reports_that_its_ready_was_ignored(
    full: Full, capsys: pytest.CaptureFixture[str]
) -> None:
    earlier_autopilot_run(full)
    full.args["--ready"] = "anything at all"
    code, lines = full.go(capsys)
    assert code == 0
    assert lines.count(IGNORED) == 1
    assert [SESSION, "park-a", "autopilot", "", "company", date.today().isoformat()] in (
        label_rows(full)
    )


def test_a_later_run_with_an_empty_ready_prints_no_ignored_line(
    full: Full, capsys: pytest.CaptureFixture[str]
) -> None:
    earlier_autopilot_run(full)
    full.args["--ready"] = ""
    code, lines = full.go(capsys)
    assert code == 0
    assert IGNORED not in lines
    assert lines[-1].startswith("autopilot-year: park park-a played company year 2001")


def test_a_relative_data_dir_lands_under_the_project_folder(
    full: Full, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = full.root / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "data")
    full.company = full.project / "data" / "company"
    full.parquet = full.company / "parquet"
    code, lines = full.go(capsys)
    assert code == 0
    assert full.landed("raw") == [landed_raw(full).name]
    assert full.company.is_relative_to(full.project)
    assert list(elsewhere.iterdir()) == []


def test_a_missing_dated_copy_after_the_archive_copy_is_a_backup_problem(
    full: Full, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_game_copy(*args: object, **kwargs: object) -> str:
        raise OSError("the game folder is read-only")

    monkeypatch.setattr(save_backup, "_game_copy", failing_game_copy)
    code, lines = full.go(capsys)
    assert code == 1
    assert lines[-1] == (
        f"No dated copy of the end-of-year save was found in {full.game_saves}; the backup "
        f"copy failed. The run folder is kept at {full.work}."
    )
    assert not any(line.startswith("To make the backup:") for line in lines)
    assert full.work.is_dir()
    assert new_archive_copy(full).read_bytes().startswith(SOURCE)  # the archive copy was made


def test_a_run_across_utc_midnight_lands_two_record_files_and_one_joined_raw_file(
    full: Full, capsys: pytest.CaptureFixture[str]
) -> None:
    joined: list[str] = []

    def across_midnight(folder: RunFolder) -> None:
        """Split the raw file and the record file as a run that crossed midnight leaves them."""
        for parent, prefix in (
            (folder.raw / "v1", "events-"),
            (folder.root / "save_files" / "v1", "save_file_observation_"),
        ):
            (path,) = parent.glob(f"{prefix}*.jsonl")
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            day = date.fromisoformat(path.stem[len(prefix) :])
            path.with_name(f"{prefix}{day - timedelta(days=1)}.jsonl").write_text(
                lines[0], encoding="utf-8"
            )
            path.write_text("".join(lines[1:]), encoding="utf-8")
            if prefix == "events-":
                joined.extend(lines)

    full.after_game.append(across_midnight)
    code, lines = full.go(capsys)
    events = len(joined)
    assert (code, lines[-1]) == (0, last_line(events))
    records = [n for n in full.landed("save_files") if n.endswith(f"-autopilot-{SESSION}.jsonl")]
    assert len(records) == 2
    assert landed_raw(full).read_text(encoding="utf-8") == "".join(joined)
    first = sorted((full.raw_dir).glob("events-*"))[0].name
    assert first == landed_raw(full).name


def test_signal_handlers_are_restored_after_a_full_run(
    full: Full, capsys: pytest.CaptureFixture[str]
) -> None:
    before = handlers()
    code, _ = full.go(capsys)
    assert code == 0
    assert handlers() == before

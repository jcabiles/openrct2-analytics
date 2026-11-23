"""The rehearsal capture's chain, run through ``main`` against temp folders and a stand-in game.

The stand-in game (``tests/bench_standin_game.py``) is a real child process launched in place of
the binary; the listener, converter, proof and landing are the real ones. Only the clock, the
sleep and the load average are substituted. Each stand-in launch plays one attempt, in launch
order, so a retried step consumes two plan entries. After every chain run the protected folders
are checked: the repo's ``data/sample/`` and ``plugin/src/`` trees are unchanged,
``data/company/`` and ``data/rehearsal/parquet/`` do not exist in the data folder, and the
player's autosave times are unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import threading
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest

from openrct2_analytics.ingest import rehearsal_capture
from openrct2_analytics.ingest.capture import Build, say
from openrct2_analytics.ingest.contracts import LANDING_FOLDER
from openrct2_analytics.ingest.game_check import GameState
from openrct2_analytics.ingest.lock import Interrupted
from openrct2_analytics.ingest.rehearsal_capture import RehearsalOptions, main
from openrct2_analytics.ingest.rehearsal_chain import (
    attempt_name,
    save_name,
    schedule,
)
from openrct2_analytics.ingest.rehearsal_land import SCHEDULE
from openrct2_analytics.ingest.rehearsal_land import land as real_land
from tests.test_bench_run import FIXTURE_BYTES, REPO_ROOT, BenchHarness
from tests.test_convert import query, tree

PARK2_BYTES = b"stand-in park two\n" * 64
PARK_IDS = {1: "k1791580000001-rhpark", 2: "k1791590000000-abc123"}
ORIGINS = {1: 1, 2: 4}
AUTOSAVE_TIME = 1_000_000_000.0
DATA_SET = ["--data-set", "rehearsal"]
LAUNCH_WAIT_SECONDS = 60.0


class RehearsalHarness:
    """A BenchHarness plus Park 2's source, a data folder and a recorded load reader."""

    def __init__(self, bench: BenchHarness, monkeypatch: pytest.MonkeyPatch) -> None:
        self.bench = bench
        self.park2 = bench.root / "private" / "park2" / "park2.sv6"
        self.park2.parent.mkdir()
        self.park2.write_bytes(PARK2_BYTES)
        self.data_root = bench.root / "data"
        autosaves = bench.user_dir / "save" / "autosave"
        autosaves.mkdir(parents=True)
        self.autosave = autosaves / "autosave_old.park"
        self.autosave.write_bytes(b"player autosave")
        os.utime(self.autosave, (AUTOSAVE_TIME, AUTOSAVE_TIME))
        self.loads: list[float] = []
        self.sleeps: list[float] = []
        monkeypatch.setenv("OPENRCT2_REHEARSAL_PARK2", str(self.park2))
        monkeypatch.setenv("OPENRCT2_DATA_DIR", str(self.data_root))
        self.protected = self.protected_state()

    def load_average(self) -> float:
        self.loads.append(0.5)
        return 0.5

    def options(self, **changes: object) -> RehearsalOptions:
        seams: dict[str, object] = {"load_average": self.load_average, "sleep": self.sleeps.append}
        bench_options = self.bench.options(**{**seams, **changes})
        prefix = hashlib.sha1(PARK2_BYTES).hexdigest()[:8]
        return RehearsalOptions(
            bench=bench_options,
            park2_sha1_prefix=prefix,
            game_check=lambda: GameState.NOT_RUNNING,
        )

    def main(
        self, argv: list[str] | None = None, build: Build | None = None, **changes: object
    ) -> int:
        return main(
            DATA_SET if argv is None else argv,
            options=self.options(**changes),
            build=build or (lambda: self.bench.plugin),
        )

    def protected_state(self) -> tuple[object, ...]:
        return (
            tree(REPO_ROOT / "data" / "sample"),
            tree(REPO_ROOT / "plugin" / "src"),
            self.autosave.stat().st_mtime,
            self.autosave.read_bytes(),
            self.park2.read_bytes(),
        )

    def assert_protected(self) -> None:
        assert self.protected_state() == self.protected
        assert not (self.data_root / "company").exists()
        assert not (self.data_root / "rehearsal" / "parquet").exists()

    def rehearsal_files(self) -> list[str]:
        root = self.data_root / "rehearsal"
        return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def session(step: int, **changes: object) -> dict[str, object]:
    """A stand-in launch that plays ``step`` validly: its park, speed 8, guests and a save."""
    park = SCHEDULE[step]
    played = sum(1 for earlier in range(1, step) if SCHEDULE[earlier] == park)
    entry: dict[str, object] = {
        "park_id": PARK_IDS[park],
        "start_year": ORIGINS[park] + played,
        "speed": 8,
        "guests": True,
        "save": True,
    }
    return {**entry, **changes}


def valid_chain() -> list[dict[str, object]]:
    return [session(step) for step in range(1, 10)]


def test_nine_sessions_play_in_schedule_order_and_land_a_proven_capture(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    rh.bench.plan(*valid_chain())

    assert rh.main() == 0

    rh.bench.assert_every_line_landed()
    folders = [rh.bench.folder(attempt_name(step, 1)) for step in range(1, 10)]
    copies = [folder.save_dir / "bench-park.sv6" for folder in folders]
    copies = [c if c.exists() else c.with_suffix(".park") for c in copies]
    assert [argv[1] for argv in rh.bench.launch_argvs()] == [str(c) for c in copies]  # type: ignore[index]
    # Each step loads a copy of its park's input: the fixture, Park 2's source, or the save its
    # park's previous step wrote, which stays where it was written.
    last = {1: FIXTURE_BYTES, 2: PARK2_BYTES}
    for step, (folder, copy) in enumerate(zip(folders, copies, strict=True), start=1):
        assert copy.read_bytes() == last[SCHEDULE[step]], step
        saved = folder.save_dir / f"{save_name(step)}.park"
        last[SCHEDULE[step]] = saved.read_bytes()
        plugin = folder.user_data / "plugin"
        assert f'var SAVE_FILENAME = "{save_name(step)}";' in (
            plugin / "openrct2-analytics-bench-save.js"
        ).read_text(encoding="utf-8")
        config = (folder.user_data / "config.ini").read_text(encoding="utf-8")
        assert "debugging_tools = true\n" in config and "autosave = 5\n" in config
    assert rh.bench.fixture.read_bytes() == FIXTURE_BYTES

    # The stand-in's park_id, guests, speed and start_year reach the proven Parquet.
    converted = rh.bench.bench_dir / "rehearsal-parquet" / "v1"
    stats = "SELECT DISTINCT game_speed FROM '{p}' WHERE NOT warmup"
    assert query(converted / "plugin_stats.parquet", stats) == [(8,)]
    starts = "SELECT park_id, game_year FROM '{p}' ORDER BY game_year, park_id"
    assert query(converted / "session_start.parquet", starts) == [
        (PARK_IDS[1], 1), (PARK_IDS[1], 2), (PARK_IDS[1], 3), (PARK_IDS[1], 4),
        (PARK_IDS[2], 4), (PARK_IDS[1], 5), (PARK_IDS[2], 5), (PARK_IDS[1], 6),
        (PARK_IDS[2], 6),
    ]  # fmt: skip
    for name in ("guest_arrived", "guest_boarded", "guest_left", "guest_snapshot"):
        assert query(converted / f"{name}.parquet", "SELECT count(*) > 0 FROM '{p}'") == [(True,)]

    files = rh.rehearsal_files()
    assert len([f for f in files if f.startswith("raw/v1/events-")]) == 9
    delivery = [f for f in files if f.startswith("registry/v1/park_registry_")]
    assert len(delivery) == 1 and len(files) == 10
    rows = query(
        rh.data_root / "rehearsal" / delivery[0],
        "SELECT park_id, company_start_year, game_year_origin FROM read_csv('{p}')",
    )
    assert rows == [(PARK_IDS[1], 2000, 1), (PARK_IDS[2], 2003, 4)]

    out = capsys.readouterr().out
    assert "Game version: OpenRCT2, v0.5.5 (standin on HEAD)" in out
    assert "Step 1 (P1-1, Park 1), attempt 1, " in out
    assert "Step 4 (P2-1, Park 2), attempt 1, " in out
    assert "Step 9 (P1-6, Park 1), attempt 1, " in out
    assert out.count(": valid.") == 9
    assert f"Park 1: {PARK_IDS[1]}, company start year 2000, game year origin 1." in out
    assert f"Landed rehearsal/registry/v1/{delivery[0].rsplit('/', 1)[1]}." in out
    assert out.rstrip().endswith("then make transform DATA_SET=rehearsal.")
    for private in [*rh.bench.private_texts(), str(rh.park2), str(rh.data_root)]:
        assert private not in out
    assert rh.loads == [0.5] and rh.sleeps == []  # the load wait ran once, before the chain
    rh.assert_protected()


def test_an_invalid_attempt_is_retried_once_and_a_second_failure_stops_the_chain(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    slow = {"slow_row": 2}
    rh.bench.plan(session(1, **slow), session(1), session(2, **slow), session(2, **slow))

    assert rh.main() == 1

    rh.bench.assert_every_line_landed()
    assert len(rh.bench.launch_argvs()) == 4
    retry = rh.bench.folder(attempt_name(1, 2)).save_dir / "bench-park.park"
    assert retry.read_bytes() == FIXTURE_BYTES  # a fresh copy of the same input
    assert not rh.bench.folder(attempt_name(3, 1)).root.exists()
    out = capsys.readouterr().out
    assert "Step 1 (P1-1, Park 1), attempt 2, " in out
    assert "Step 2 failed twice; the chain stopped. Nothing was landed." in out
    assert not (rh.data_root / "rehearsal").exists()
    rh.assert_protected()


def test_a_session_that_never_saves_times_out_and_stops_the_chain(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    rh.bench.plan(session(1, save=False))

    assert rh.main(seconds_per_day=0.001, startup_seconds=1.0) == 1

    assert len(rh.bench.launch_argvs()) == 2
    out = capsys.readouterr().out
    assert out.count("timed out after 1.24 s before the stop condition") == 2
    assert not (rh.data_root / "rehearsal").exists()
    rh.assert_protected()


def _input_save(rh: RehearsalHarness) -> Path:
    return rh.bench.folder(attempt_name(1, 1)).save_dir / f"{save_name(1)}.park"


Touched = Callable[[RehearsalHarness], Path]
Plan = Callable[[RehearsalHarness, str], list[dict[str, object]]]


@pytest.mark.parametrize(
    "case",
    [
        (lambda rh: rh.bench.fixture, lambda rh, t: [session(1, touch=t)], "fixture changed"),
        (lambda rh: rh.park2, lambda rh, t: [session(1, touch=t)], "Park 2 source changed"),
        (_input_save, lambda rh, t: [session(1), session(2, touch=t)], "input save changed"),
    ],
    ids=["fixture", "park2", "input-save"],
)
def test_a_changed_source_or_input_save_fails_the_attempt(
    rh: RehearsalHarness,
    capsys: pytest.CaptureFixture[str],
    case: tuple[Touched, Plan, str],
) -> None:
    touched, plan, reason = case
    target = touched(rh)
    rh.bench.plan(*plan(rh, str(target)))
    rh.protected = (*rh.protected[:4], None)  # Park 2's bytes are the thing being changed

    assert rh.main() == 1

    out = capsys.readouterr().out
    assert out.count(reason) == 2
    assert "failed twice; the chain stopped. Nothing was landed." in out
    assert not (rh.data_root / "rehearsal").exists()
    assert rh.protected_state()[:4] == rh.protected[:4]
    assert not (rh.data_root / "company").exists()


def test_an_interrupt_during_the_chain_exits_130_with_nothing_landed(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    rh.bench.plan(session(1, stats=40, day_seconds=0.1))  # about 4 s: far longer than the wait
    seen = threading.Event()

    def interrupt_once_launched() -> None:
        deadline = time.monotonic() + LAUNCH_WAIT_SECONDS
        while time.monotonic() < deadline:
            if rh.bench.launch_argvs():
                seen.set()
                os.kill(os.getpid(), signal.SIGINT)
                return
            time.sleep(0.01)

    watcher = threading.Thread(target=interrupt_once_launched)
    watcher.start()
    try:
        assert rh.main() == 130
    finally:
        watcher.join()
    assert seen.is_set(), f"the stand-in game was not launched within {LAUNCH_WAIT_SECONDS} s"

    assert len(rh.bench.launch_argvs()) == 1
    assert "Interrupted before landing began. Nothing was landed." in capsys.readouterr().out
    assert not (rh.data_root / "rehearsal").exists()
    rh.assert_protected()


def test_a_signal_between_the_renames_exits_130_and_says_to_read_what_landed(
    rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def interrupt(stage: str) -> None:
        if stage == "between-renames":
            os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(rehearsal_capture, "land", partial(real_land, hook=interrupt))
    rh.bench.plan(*valid_chain())

    assert rh.main() == 130

    files = rh.rehearsal_files()
    assert len([f for f in files if f.startswith("raw/v1/")]) == 9
    assert len([f for f in files if f.startswith("registry/v1/park_registry_")]) == 1
    out = capsys.readouterr().out
    assert "both finished, so the capture is landed" in out
    assert "Interrupted while landing; the lines above say whether the capture landed." in out
    assert "Nothing was landed" not in out and "Next:" not in out
    rh.assert_protected()


def test_a_link_made_during_the_chain_is_refused_under_the_lock_and_the_capture_is_kept(
    rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = rh.bench.root / "repo"
    stash = repo / "data" / "company" / "stash"
    stash.mkdir(parents=True)

    def link_raw_folder(stage: str) -> None:
        if stage == "locked":  # every refusal passed long ago; the link appears now
            (rh.data_root / "rehearsal" / "raw").symlink_to(stash)

    monkeypatch.setattr(rehearsal_capture, "land", partial(real_land, hook=link_raw_folder))
    rh.bench.plan(*valid_chain())

    code = main(
        DATA_SET,
        options=rh.options(),
        build=lambda: rh.bench.plugin,
        project_dir=repo,
    )

    assert code == 1
    out = capsys.readouterr().out
    assert "data/rehearsal/raw/ equals or lies inside data/company/." in out
    assert "Nothing was written" not in out and "Next:" not in out
    assert "The captured files stay in rehearsal-raw/ and rehearsal-parquet/" in out
    assert list(stash.iterdir()) == []
    assert rh.rehearsal_files() == []
    assert not (rh.data_root / "rehearsal" / "parquet.lock").exists()
    assert (rh.bench.bench_dir / "rehearsal-raw").is_dir()
    assert (rh.bench.bench_dir / "rehearsal-parquet").is_dir()
    rh.assert_protected()


def test_an_error_inside_land_is_never_reported_as_success(
    rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken_land(*args: object, **kwargs: object) -> int:
        raise PermissionError("cannot write")

    monkeypatch.setattr(rehearsal_capture, "land", broken_land)
    rh.bench.plan(*valid_chain())

    with pytest.raises(PermissionError):
        rh.main()

    assert "Next:" not in capsys.readouterr().out
    rh.assert_protected()


@pytest.mark.parametrize(
    ("argv", "line"),
    [
        ([], "Name a data set ("),
        (["--data-set", "company"], "make capture-rehearsal writes only rehearsal data"),
    ],
)
def test_a_missing_or_company_data_set_exits_2_and_changes_nothing(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str], argv: list[str], line: str
) -> None:
    assert rh.main(argv) == 2

    err = capsys.readouterr().err
    assert err.startswith(line) and err.rstrip().endswith("Nothing was changed.")
    assert not rh.bench.bench_dir.exists() and not rh.data_root.exists()
    assert rh.bench.launches() == []
    rh.assert_protected()


def test_a_signal_after_land_returns_says_to_read_what_landed_not_that_nothing_landed(
    rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def landed(*args: object, **kwargs: object) -> int:
        return 0

    real_say = say

    def interrupted_say(line: str) -> None:
        if line == rehearsal_capture.NEXT_STEPS:
            raise Interrupted
        real_say(line)

    monkeypatch.setattr(rehearsal_capture, "land", landed)
    monkeypatch.setattr(rehearsal_capture, "say", interrupted_say)
    rh.bench.plan(*valid_chain())

    assert rh.main() == 130

    out = capsys.readouterr().out
    assert rehearsal_capture.INTERRUPTED_LANDING in out and "Nothing was landed" not in out
    rh.assert_protected()


def test_a_retried_step_carries_the_second_attempt_forward(rh: RehearsalHarness) -> None:
    rh.bench.plan(session(1, slow_row=2), session(1), *[session(step) for step in range(2, 10)])

    assert rh.main() == 0

    first = rh.bench.folder(attempt_name(1, 1)).save_dir / f"{save_name(1)}.park"
    second = rh.bench.folder(attempt_name(1, 2)).save_dir / f"{save_name(1)}.park"
    assert first.read_bytes() != second.read_bytes()
    step_2_input = rh.bench.folder(attempt_name(2, 1)).save_dir / "bench-park.park"
    assert step_2_input.read_bytes() == second.read_bytes()
    landed = (rh.data_root / "rehearsal" / "raw" / LANDING_FOLDER).glob("events-*.jsonl")
    sessions = {
        json.loads(line)["session_id"]
        for path in landed
        for line in path.read_text(encoding="utf-8").splitlines()
    }
    assert "standin-2" in sessions and "standin-1" not in sessions
    rh.assert_protected()


def test_the_default_timeout_and_planned_days_follow_the_spec() -> None:
    assert RehearsalOptions().bench.timeout_seconds(245) == 1035.0  # 3.0 s a day plus 300 s
    assert [step.days for step in schedule()] == [240, *[245] * 8]


def raw_folder(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    landing = tmp_path / "raw" / LANDING_FOLDER
    landing.mkdir(parents=True)
    lines = [json.dumps({"session_id": "s1", **row}) for row in rows]
    (landing / "events-2026-10-01.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path / "raw"


def stats(seq: int, speed: int, *, warmup: bool = False) -> dict[str, object]:
    return {"event_type": "plugin_stats", "seq": seq, "warmup": warmup, "game_speed": speed}


START: dict[str, object] = {"event_type": "session_start", "seq": 0}

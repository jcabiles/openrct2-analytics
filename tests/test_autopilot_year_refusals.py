"""The autopilot-year command's refusals 1 to 11, their order, and the run they lead to.

Every case runs ``main`` against temporary folders: a valid company world (two registered parks,
converted Parquet, paired saves and a proven archive copy) that passes every refusal, changed in
exactly one way. Each refusal must print its section 4 text, exit 2 and write nothing: the
listing of every temporary folder (bar the stand-in game's own log folder) is compared before
and after. Expected texts are copied from docs/ai-dlc/specs/autopilot-year.md, section 4.
A world that passes every refusal reaches the run, which ``World`` replaces with a recorder that
stops there as an interrupt would, so no game starts. ``World`` and ``BREAKERS`` are shared with
``test_autopilot_year_refusals_data.py``; the full run is in ``test_autopilot_year.py``.
"""

# WEAKENED-OK: one placeholder replaced by a stronger run assertion and three tests moved to test_autopilot_year_refusals_data.py (AY-10 review)  # noqa: E501
from __future__ import annotations

import errno
import os
import socket
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openrct2_analytics.ingest import autopilot_year
from openrct2_analytics.ingest import plugin_install as pi
from openrct2_analytics.ingest.autopilot_year import main
from openrct2_analytics.ingest.bench_setup import BenchSettings
from openrct2_analytics.ingest.game_check import GameState
from openrct2_analytics.ingest.lock import Interrupted
from tests.autopilot_fixtures import (
    T0,
    Row,
    event_row,
    plant_archive_copy,
    plant_label,
    plant_paired_save,
    plant_park_snapshot,
    plant_registry,
    plant_save_written,
    plant_session_start,
)
from tests.test_bench_run import BenchHarness

NOW = datetime(2026, 11, 13, 10, 0, 0, tzinfo=UTC)
WORK_NAME = "autopilot-park-a-20261113T100000Z"
LAST_SAVE = T0 + timedelta(hours=1)
READY = "park-a is profitable and its scenario challenge is complete"
TAIL = " Nothing was written."
IN_USE = os.strerror(errno.EADDRINUSE)  # the system's words; the rest of the text is the spec's
FIRST_RUN = (
    "This is park park-a's first autopilot run. Confirm it is ready with "
    'READY="park-a is profitable and its scenario challenge is complete".' + TAIL
)
NO_CONVERTED = "No converted data; run make convert DATA_SET=company first." + TAIL
COMPANY_ROW = ("park-a", 2000, 1, "company", "", "2026-11-12")


class World:
    """A company world that passes every refusal; tests change one thing, then call ``run``."""

    def __init__(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, record_run: bool = True
    ) -> None:
        self.root = tmp_path
        self.monkeypatch = monkeypatch
        self.bench = BenchHarness(tmp_path)
        self.project = tmp_path / "project"
        self.project.mkdir()
        self.company = tmp_path / "data" / "company"
        self.parquet = self.company / "parquet"
        self.archive = tmp_path / "archive"
        for name, value in self.bench.environment().items():
            monkeypatch.setenv(name, value)
        monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("OPENRCT2_BACKUP_DIR", str(self.archive))
        self.args = {"--data-set": "company", "--park": "park-a", "--ready": READY}
        self.now = NOW.timestamp()
        self.load = 0.5
        self.game_state = GameState.NOT_RUNNING
        self.build: Callable[[], Path] = lambda: self.bench.plugin
        self.registry: list[tuple[str, int, int, str, str, str]] = [
            COMPANY_ROW,
            ("park-b", 2001, 1, "company", "", "2026-11-12"),
        ]
        self.snapshots: list[Row] = [
            event_row(10, park_id="park-a", session_id="sess-a1", game_date=(1, 5, 1)),
            event_row(900, park_id="park-a", session_id="sess-a1", game_date=(2, 0, 1)),
            event_row(1, park_id="park-b", session_id="sess-b1", game_date=(1, 0, 5)),
        ]
        # (row, paired save-file name or None for an unpaired save, its size)
        self.saves: list[tuple[Row, str | None, int]] = [
            (self.save("park-a", "sess-a1", 905, date=(2, 0, 1), emitted=LAST_SAVE), "Park A", 7),
            (self.save("park-b", "sess-b1", 5, date=(1, 0, 5), emitted=T0), "Park B", 5),
        ]
        self.starts: list[Row] = [
            self.start("park-a", "sess-a1", (1, 4, 1), "Park A"),
            self.start("park-b", "sess-b1", (1, 0, 1), "Park B"),
        ]
        self.labels: list[tuple[str, str, str, str, str, str]] = []
        self.copy_size: int | None = 7  # None: no archive copy
        self.raw_sessions = ["sess-a1", "sess-b1"]
        self.audit = True
        self.session_start = True  # False: no session_start.parquet
        self.after_plant: list[Callable[[], object]] = []
        self.held: list[socket.socket] = []
        self.interrupt = False  # True: the load wait's sleep raises the interrupt
        self.runs: list[tuple[BenchSettings, dict[str, object]]] = []
        if record_run:
            monkeypatch.setattr(autopilot_year, "run_autopilot", self.stop_at_the_run)

    def stop_at_the_run(self, settings: BenchSettings, **inputs: object) -> None:
        """Record the run's inputs and stop as an interrupt would; nothing is written."""
        self.runs.append((settings, inputs))
        raise Interrupted

    @staticmethod
    def save(
        park: str, session: str, seq: int, *, date: tuple[int, int, int], emitted: datetime
    ) -> Row:
        return event_row(
            seq,
            park_id=park,
            session_id=session,
            game_date=date,
            emitted_at=emitted,
            save_id=f"save-{session}-{seq}",
        )

    @staticmethod
    def start(park: str, session: str, date: tuple[int, int, int], name: str) -> Row:
        return event_row(0, park_id=park, session_id=session, game_date=date, park_name=name)

    def options_clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        if self.interrupt:
            raise Interrupted
        self.now += seconds

    def plant(self) -> None:
        """Write the world's files; the archive copy is modified a minute after park-a's save."""
        plant_park_snapshot(self.parquet, self.snapshots)
        if self.session_start:
            plant_session_start(self.parquet, self.starts)
        saves = self.company / "save_files"
        for row, name, size in self.saves:
            if name is not None:
                plant_paired_save(saves, row, name, size)
        plant_save_written(self.parquet, [row for row, _, _ in self.saves])
        if self.audit:
            (self.parquet / "audit").mkdir(parents=True)
            (self.parquet / "audit" / "seq_audit.parquet").write_bytes(b"test audit")
        raw = self.company / "raw" / "v1"
        raw.mkdir(parents=True)
        (raw / "events-2026-11-12.jsonl").write_text(
            "".join(f'{{"session_id": "{s}"}}\n' for s in self.raw_sessions), encoding="utf-8"
        )
        plant_registry(self.company / "registry" / "v1", self.registry)
        if self.labels:
            plant_label(self.company / "registry" / "v1", self.labels)
        if self.copy_size is not None:
            self.copy = self.plant_copy(self.archive)
        for step in self.after_plant:
            step()

    def plant_copy(self, archive: Path) -> Path:
        times = [row["emitted_at"] for row, _, _ in self.saves if row["park_id"] == "park-a"]
        latest = max(time for time in times if isinstance(time, datetime))
        return plant_archive_copy(
            archive,
            "park-a",
            "Park A",
            datetime(2026, 11, 12, 21, 0, 0),
            data=b"x" * (self.copy_size or 0),
            modified_at=latest + timedelta(minutes=1),
        )

    def listing(self) -> dict[str, int | None]:
        return {
            str(path.relative_to(self.root)): path.stat().st_size if path.is_file() else None
            for path in self.root.rglob("*")
            if path.relative_to(self.root).parts[0] != "standin"  # the stand-in game's own log
        }

    def run(self, capsys: pytest.CaptureFixture[str]) -> tuple[int, list[str]]:
        """Plant, run ``main``, assert nothing was written; return the code and output lines."""
        self.plant()
        before = self.listing()
        argv = [part for key, value in self.args.items() for part in (key, value)]
        try:
            code = main(
                argv,
                options=self.bench.options(
                    clock=self.options_clock, sleep=self.sleep, load_average=lambda: self.load
                ),
                build=self.build,
                project_dir=self.project,
                game_check=lambda: self.game_state,
            )
        finally:
            for held in self.held:
                held.close()
        assert self.listing() == before
        captured = capsys.readouterr()
        return code, (captured.out + captured.err).splitlines()


@pytest.fixture(name="world")
def world_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return World(tmp_path, monkeypatch)


def assert_refused(world: World, capsys: pytest.CaptureFixture[str], text: str) -> None:
    code, lines = world.run(capsys)
    assert (code, lines) == (2, text.splitlines())


def hold_port(world: World, host: str, port: int) -> None:
    probe = socket.socket()
    probe.bind((host, port))
    probe.listen()
    world.held.append(probe)


def recent_autosave(world: World) -> None:
    autosaves = world.bench.user_dir / "save" / "autosave"
    autosaves.mkdir(parents=True)
    autosave = autosaves / "autosave.park"
    autosave.write_bytes(b"test autosave")
    os.utime(autosave, (world.now - 60, world.now - 60))


def broken_binary(world: World) -> None:
    world.bench.binary.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")


def failing_build() -> Path:
    raise pi.BuildError("The plugin build failed (test).")


Breaker = tuple[Callable[[World], object], Callable[[World], str]]

# One change per refusal of section 4, and the text it must print. Refusal 12 here is its missing
# Parquet cause; the data file covers its other two.
BREAKERS: dict[str, Breaker] = {
    "1": (
        lambda w: w.args.update({"--data-set": "rehearsal"}),
        lambda w: "autopilot-year runs only on the company data set; give DATA_SET=company." + TAIL,
    ),
    "2": (lambda w: w.args.update({"--park": ""}), lambda w: "Give PARK=<park id>." + TAIL),
    "3": (
        lambda w: w.monkeypatch.delenv("OPENRCT2_GAME_PATH"),
        lambda w: (
            "OPENRCT2_GAME_PATH is not set and was not found in OpenRCT2's own settings. Add a "
            "line OPENRCT2_GAME_PATH=<path to the RollerCoaster Tycoon 2 folder> to "
            "local/game-settings.env, or export it." + TAIL
        ),
    ),
    "4": (
        lambda w: w.monkeypatch.setenv("OPENRCT2_BENCH_DIR", str(w.archive / "bench")),
        lambda w: "The work folder equals, contains or lies inside the archive folder." + TAIL,
    ),
    "5": (
        lambda w: w.after_plant.append(
            lambda: (w.company / "raw" / "v1" / ".incoming-events.jsonl").write_bytes(b"x")
        ),
        lambda w: (
            "Staged file .incoming-events.jsonl already exists in data/company/raw/v1; "
            "a killed landing left it." + TAIL
        ),
    ),
    "6": (
        lambda w: w.after_plant.append(lambda: (w.bench.bench_dir / WORK_NAME).mkdir(parents=True)),
        lambda w: (
            f"The work folder (OPENRCT2_BENCH_DIR) already holds {WORK_NAME} from an "
            "earlier run; move them away first." + TAIL
        ),
    ),
    "7": (
        lambda w: w.after_plant.append(lambda: broken_binary(w)),
        lambda w: "OPENRCT2_BINARY did not answer --version." + TAIL,
    ),
    "8": (
        lambda w: setattr(w, "game_state", GameState.RUNNING),
        lambda w: "OpenRCT2 is running. Quit it, then run this command." + TAIL,
    ),
    "9": (
        lambda w: w.after_plant.append(lambda: recent_autosave(w)),
        lambda w: (
            "The newest real OpenRCT2 autosave is 1.0 minutes old, so the game is probably "
            "running and would share the CPU. Quit it and retry once no autosave has appeared for "
            "10 minutes." + TAIL
        ),
    ),
    "10": (
        lambda w: w.after_plant.append(lambda: hold_port(w, "127.0.0.1", w.bench.listener_port)),
        lambda w: (
            f"Cannot listen on 127.0.0.1:{w.bench.listener_port} ({IN_USE}); "
            "a capture or `make listen` may be running." + TAIL
        ),
    ),
    "11": (
        lambda w: w.after_plant.append(lambda: (w.company / "parquet.lock").write_bytes(b"")),
        lambda w: (
            "data/company/parquet.lock is present: a convert, landing or delete is "
            "running, or a killed run left it." + TAIL
        ),
    ),
    "12": (lambda w: setattr(w, "session_start", False), lambda w: NO_CONVERTED),
    "13": (
        lambda w: w.registry.remove(COMPANY_ROW),
        lambda w: (
            "Park park-a is not a registered company park; register it with make "
            "register-parks DATA_SET=company first." + TAIL
        ),
    ),
    "14": (
        lambda w: setattr(w, "copy_size", None),
        lambda w: (
            f"Park park-a has no backup in {w.archive}/park-a/. Play and save it with make "
            "play DATA_SET=company, quit normally, and check that the report prints a Backup: line."
            + TAIL
        ),
    ),
    "15": (
        lambda w: w.saves.__setitem__(0, (w.saves[0][0], None, 7)),
        lambda w: (
            "The last save of park park-a (recorded 2026-11-12T20:00:00+00:00) was not "
            "matched to exactly one save file, so its last recorded save is unknown. Play and save "
            "it once with make play DATA_SET=company." + TAIL
        ),
    ),
    "16": (
        lambda w: setattr(w, "copy_size", 8),
        lambda w: (
            f"The newest backup of park park-a ({w.copy}) is not its last recorded save "
            "(Park A.park, recorded 2026-11-12T20:00:00+00:00); starting from it would drop the "
            "play recorded after it. Play and save once with make play DATA_SET=company so a new "
            "backup is made." + TAIL
        ),
    ),
    "17a": (
        lambda w: w.snapshots.pop(),  # park-b's only managed day, in company year 2001
        lambda w: (
            "Park park-a would play company year 2001, but no other registered company "
            "park has a managed day in 2001 yet. An autopilot park runs only a company year the "
            "managed park runs; play the managed park into 2001 first." + TAIL
        ),
    ),
    "17b": (
        lambda w: w.snapshots.append(
            event_row(904, park_id="park-a", session_id="sess-a1", game_date=(2, 0, 2))
        ),
        lambda w: (
            "Park park-a is itself the managed park of company year 2001. Play it by hand "
            "to 1 March of the next game year, save, and quit, with make play DATA_SET=company."
            + TAIL
        ),
    ),
    "18": (lambda w: w.args.update({"--ready": ""}), lambda w: FIRST_RUN),
    "19": (
        lambda w: setattr(w, "load", 5.0),
        # 300 s of waiting at 15 s per check: 20 progress lines, then the refusal.
        lambda w: (
            "The one-minute load average is 5.00; checking again.\n" * 20
            + "The one-minute load average stayed at or above 3 for 5 minutes (now 5.00)."
            + TAIL
        ),
    ),
    "20": (
        lambda w: setattr(w, "build", failing_build),
        lambda w: "The plugin build failed (test).\nThe plugin did not build." + TAIL,
    ),
}


def reached_the_run(world: World) -> tuple[int, list[str]]:
    """What ``main`` prints when the recorder stops it at the run (spec section 4, exit 130)."""
    kept = world.bench.bench_dir / WORK_NAME
    return 130, [f"Interrupted; company data was not touched; the run folder is kept at {kept}."]


def refused_by(world: World, capsys: pytest.CaptureFixture[str], *numbers: str) -> None:
    """Apply each named breaker, then assert the first one's text is the only output."""
    for number in numbers:
        BREAKERS[number][0](world)
    code, lines = world.run(capsys)
    assert (code, lines) == (2, BREAKERS[numbers[0]][1](world).splitlines())


def test_the_valid_world_passes_every_refusal_and_reaches_the_run(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    assert world.run(capsys) == reached_the_run(world)
    assert len(world.runs) == 1


@pytest.mark.parametrize("number", [str(n) for n in range(1, 12)])
def test_each_refusal_1_to_11_prints_its_text_exits_2_and_writes_nothing(
    world: World, capsys: pytest.CaptureFixture[str], number: str
) -> None:
    refused_by(world, capsys, number)


def test_a_missing_data_set_is_refusal_1(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    del world.args["--data-set"]
    assert_refused(world, capsys, BREAKERS["1"][1](world))


@pytest.mark.parametrize("folder", ["raw/v1", "save_files/v1", "registry/v1"])
def test_a_staged_leftover_in_any_landing_folder_is_refusal_5(
    world: World, capsys: pytest.CaptureFixture[str], folder: str
) -> None:
    staged = world.company / folder / ".incoming-x.csv"
    world.after_plant.append(lambda: staged.parent.mkdir(parents=True, exist_ok=True))
    world.after_plant.append(lambda: staged.write_bytes(b"x"))
    assert_refused(
        world,
        capsys,
        f"Staged file .incoming-x.csv already exists in data/company/{folder}; a killed landing "
        "left it." + TAIL,
    )


def test_refusal_3_a_work_folder_inside_the_players_folder(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.monkeypatch.setenv("OPENRCT2_BENCH_DIR", str(world.bench.user_dir / "bench"))
    assert_refused(
        world,
        capsys,
        "OPENRCT2_BENCH_DIR and the player's OpenRCT2 folder (OPENRCT2_USER_DIR) must not be "
        "the same folder or inside one another." + TAIL,
    )


def test_refusal_8_a_game_check_that_cannot_tell(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.game_state = GameState.UNKNOWN
    assert_refused(world, capsys, "Cannot tell whether OpenRCT2 is running." + TAIL)


def test_refusal_10_a_busy_game_port(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.after_plant.append(lambda: hold_port(world, "", world.bench.game_port))
    assert_refused(
        world,
        capsys,
        f"Port {world.bench.game_port} cannot be bound ({IN_USE}), so the game cannot host on "
        "it." + TAIL,
    )


def test_an_interrupt_during_the_load_wait_exits_130_and_writes_nothing(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.load = 5.0
    world.interrupt = True
    assert world.run(capsys) == (
        130,
        ["The one-minute load average is 5.00; checking again.", "Interrupted." + TAIL],
    )


ORDER = [str(n) for n in range(1, 17)] + ["17a", "18", "19", "20"]


@pytest.mark.parametrize(
    ("earlier", "later"), [*zip(ORDER, ORDER[1:], strict=False), ("17b", "18")]
)
def test_a_command_failing_two_refusals_shows_only_the_earlier(
    world: World, capsys: pytest.CaptureFixture[str], earlier: str, later: str
) -> None:
    refused_by(world, capsys, earlier, later)


def test_a_park_failing_17a_and_17b_shows_17b(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    # 17a first: its breaker drops the last snapshot, which 17b's breaker would add.
    BREAKERS["17a"][0](world)
    BREAKERS["17b"][0](world)
    assert_refused(world, capsys, BREAKERS["17b"][1](world))

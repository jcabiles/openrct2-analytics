"""The benchmark's refusals and setup helpers: nothing is written and no game is launched."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path

import pytest

from openrct2_analytics.ingest import bench_run
from openrct2_analytics.ingest import plugin_install as pi
from openrct2_analytics.ingest.bench_setup import (
    AUTOSAVE_EVERY_5_MINUTES,
    AUTOSAVE_NEVER,
    BENCH_PARK_SHA1_PREFIX,
    check_no_live_game,
    config_ini,
    load_settings,
    save_helper,
    wait_for_low_load,
)
from openrct2_analytics.ingest.capture import Refused
from tests.test_bench_run import REPO_ROOT, BenchHarness, make_bench

NOTHING = "Nothing was written."


@pytest.fixture(name="bench")
def bench_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BenchHarness:
    return make_bench(tmp_path, monkeypatch)


class FakeTime:
    """A clock that only the fake sleep moves."""

    def __init__(self) -> None:
        self.now = 1_000_000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def assert_refused_before_anything(bench: BenchHarness, match: str, **changes: object) -> None:
    with pytest.raises(Refused, match=match) as refusal:
        bench_run.run(bench.options(**changes), lambda: bench.plugin)
    assert str(refusal.value).endswith(NOTHING)
    assert all(private not in str(refusal.value) for private in bench.private_texts())
    assert not bench.bench_dir.exists()
    assert bench.launches() == []  # the stand-in only ever answered --version
    assert bench.fixture.read_bytes().startswith(b"stand-in park")


# ---- settings ----


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("OPENRCT2_BENCH_PARK", "OPENRCT2_BENCH_PARK is not set"),
        ("OPENRCT2_GAME_PATH", "OPENRCT2_GAME_PATH is not set"),
    ],
)
def test_a_missing_setting_refuses(
    bench: BenchHarness, monkeypatch: pytest.MonkeyPatch, name: str, message: str
) -> None:
    monkeypatch.delenv(name)
    assert_refused_before_anything(bench, message)


@pytest.mark.parametrize(
    ("setting", "message"),
    [
        (("OPENRCT2_BINARY", "missing/OpenRCT2"), "OPENRCT2_BINARY does not name an executable"),
        (("OPENRCT2_BENCH_PARK", "missing.park"), "OPENRCT2_BENCH_PARK does not name a file"),
        (("OPENRCT2_GAME_PATH", "missing-rct2"), "OPENRCT2_GAME_PATH does not name a folder"),
        (("OPENRCT2_BENCH_DIR", " "), "OPENRCT2_BENCH_DIR must not be empty"),
    ],
)
def test_an_invalid_setting_refuses(
    bench: BenchHarness, monkeypatch: pytest.MonkeyPatch, setting: tuple[str, str], message: str
) -> None:
    name, value = setting
    monkeypatch.setenv(name, value if value.isspace() else str(bench.root / value))
    assert_refused_before_anything(bench, message)


@pytest.mark.parametrize(
    "name", ["OPENRCT2_BINARY", "OPENRCT2_BENCH_PARK", "OPENRCT2_GAME_PATH", "OPENRCT2_BENCH_DIR"]
)
def test_an_empty_setting_refuses(
    bench: BenchHarness, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv(name, " ")
    assert_refused_before_anything(bench, f"{name} must not be empty")


def test_a_binary_that_is_not_executable_refuses(bench: BenchHarness) -> None:
    bench.binary.chmod(0o644)
    assert_refused_before_anything(bench, "OPENRCT2_BINARY does not name an executable")


def test_a_binary_that_does_not_answer_version_refuses(bench: BenchHarness) -> None:
    bench.binary.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    assert_refused_before_anything(bench, "OPENRCT2_BINARY did not answer --version")


def test_leftovers_in_the_work_folder_refuse(bench: BenchHarness) -> None:
    (bench.bench_dir / "run-2-attempt-1").mkdir(parents=True)

    with pytest.raises(Refused, match="already holds run-2-attempt-1 from an earlier run"):
        bench.run()
    assert [path.name for path in bench.bench_dir.iterdir()] == ["run-2-attempt-1"]
    assert bench.launches() == []


def test_a_relative_work_folder_is_under_the_repo_from_any_current_folder(
    bench: BenchHarness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENRCT2_BENCH_DIR", "data/bench")
    assert load_settings("Darwin").bench_dir == REPO_ROOT / "data" / "bench"

    monkeypatch.setenv("OPENRCT2_BENCH_DIR", str(bench.bench_dir))
    assert load_settings("Darwin").bench_dir == bench.bench_dir


def test_a_given_park_replaces_the_unset_bench_park_setting(
    bench: BenchHarness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENRCT2_BENCH_PARK")
    given = tmp_path / "not-created-yet.park"
    assert load_settings("Darwin", park=given).park == given
    with pytest.raises(Refused, match="OPENRCT2_BENCH_PARK is not set"):
        load_settings("Darwin")


def test_without_a_given_park_the_bench_park_setting_is_used(bench: BenchHarness) -> None:
    assert load_settings("Darwin", park=None).park == bench.fixture


@pytest.mark.parametrize("where", ["same", "inside", "contains"])
def test_a_work_folder_that_overlaps_the_players_folder_refuses(
    bench: BenchHarness, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    work = {
        "same": bench.user_dir,
        "inside": bench.user_dir / "bench",
        "contains": bench.user_dir.parent,
    }[where]
    monkeypatch.setenv("OPENRCT2_BENCH_DIR", str(work))

    with pytest.raises(
        Refused, match="must not be the same folder or inside one another"
    ) as refusal:
        bench_run.run(bench.options(), lambda: bench.plugin)

    assert str(refusal.value).endswith(NOTHING)
    assert all(private not in str(refusal.value) for private in bench.private_texts())
    assert not (bench.user_dir / "bench").exists()
    assert bench.launches() == []


def test_any_park_with_sample_refuses_before_anything(bench: BenchHarness) -> None:
    with pytest.raises(Refused, match="--sample cannot be combined with --any-park") as refusal:
        bench_run.run(bench.options(), lambda: bench.plugin, any_park=True, sample=True)

    assert str(refusal.value).endswith(NOTHING)
    assert not bench.bench_dir.exists()
    assert not (bench.script.parent / "versions.jsonl").exists()  # the game was never asked
    assert bench.launches() == []


def test_dry_run_with_sample_refuses_before_anything(bench: BenchHarness) -> None:
    with pytest.raises(Refused, match="--sample cannot be combined with --dry-run") as refusal:
        bench_run.run(bench.options(), lambda: bench.plugin, sample=True, dry_run=True)

    assert str(refusal.value).endswith(NOTHING)
    assert not bench.bench_dir.exists()
    assert not (bench.script.parent / "versions.jsonl").exists()
    assert bench.launches() == []


def test_the_version_check_runs_the_game_on_a_throwaway_user_data_folder(
    bench: BenchHarness,
) -> None:
    with socket.socket() as other:
        other.bind(("", bench.game_port))
        other.listen()
        assert_refused_before_anything(bench, f"Port {bench.game_port} cannot be bound")

    versions = (bench.script.parent / "versions.jsonl").read_text(encoding="utf-8").splitlines()
    [argv] = [json.loads(line)["argv"] for line in versions]
    assert argv[:2] == ["--version", "--user-data-path"]
    throwaway = Path(argv[2])
    assert not throwaway.exists()  # removed after the call
    for kept in (REPO_ROOT, bench.user_dir, bench.bench_dir, bench.root):
        assert not throwaway.resolve().is_relative_to(kept.resolve())


# ---- the fixture ----


def test_a_park_that_is_not_the_benchmark_park_refuses_without_any_park(
    bench: BenchHarness,
) -> None:
    assert_refused_before_anything(
        bench, "not the benchmark park.*--any-park", fixture_sha1_prefix=BENCH_PARK_SHA1_PREFIX
    )


# ---- ports, a live game, load ----


def test_a_busy_listener_port_refuses(bench: BenchHarness) -> None:
    with socket.socket() as other:
        other.bind(("127.0.0.1", bench.listener_port))
        other.listen()
        assert_refused_before_anything(bench, f"Cannot listen on 127.0.0.1:{bench.listener_port}")


def test_a_busy_game_port_refuses(bench: BenchHarness) -> None:
    with socket.socket() as other:
        other.bind(("", bench.game_port))
        other.listen()
        assert_refused_before_anything(bench, f"Port {bench.game_port} cannot be bound")


def test_a_fresh_real_autosave_refuses(bench: BenchHarness) -> None:
    autosaves = bench.user_dir / "save" / "autosave"
    autosaves.mkdir(parents=True)
    (autosaves / "autosave.park").write_bytes(b"live")
    before = {path: path.stat().st_mtime_ns for path in bench.user_dir.rglob("*")}

    assert_refused_before_anything(bench, "autosave is 0.0 minutes old")
    assert {path: path.stat().st_mtime_ns for path in bench.user_dir.rglob("*")} == before


def test_only_an_autosave_under_ten_minutes_old_counts(tmp_path: Path) -> None:
    check_no_live_game(tmp_path, time.time())  # no autosave folder: no live game
    autosaves = tmp_path / "save" / "autosave"
    autosaves.mkdir(parents=True)
    old = autosaves / "old.park"
    old.write_bytes(b"old")
    os.utime(old, (time.time() - 601, time.time() - 601))
    check_no_live_game(tmp_path, time.time())

    (autosaves / "new.park").write_bytes(b"new")
    with pytest.raises(Refused, match="autosave"):
        check_no_live_game(tmp_path, time.time())


def test_a_load_average_that_stays_high_for_five_minutes_refuses(bench: BenchHarness) -> None:
    fake = FakeTime()

    assert_refused_before_anything(
        bench,
        "load average stayed at or above 3 for 5 minutes",
        clock=fake.clock,
        sleep=fake.sleep,
        load_average=lambda: 3.0,
    )
    assert sum(fake.sleeps) >= 300
    assert sum(fake.sleeps[:-1]) < 300  # it re-checks up to the end of the wait, no further


def test_a_load_average_that_drops_within_five_minutes_lets_the_run_start() -> None:
    fake = FakeTime()
    readings = iter([3.5, 3.0, 4.0, 2.9])

    wait_for_low_load(lambda: next(readings), fake.clock, fake.sleep)

    assert len(fake.sleeps) == 3 and next(readings, None) is None


def test_a_failed_build_refuses(bench: BenchHarness) -> None:
    def failing_build() -> Path:
        raise pi.BuildError("tsc: error")

    with pytest.raises(Refused, match="tsc: error\nThe plugin did not build"):
        bench_run.run(bench.options(), failing_build)
    assert not bench.bench_dir.exists()


def test_main_prints_the_refusal_and_exits_2(
    bench: BenchHarness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OPENRCT2_GAME_PATH")

    assert bench_run.main([]) == 2

    assert capsys.readouterr().out == (
        "OPENRCT2_GAME_PATH is not set and was not found in OpenRCT2's own settings. Add a line "
        "OPENRCT2_GAME_PATH=<path to the RollerCoaster Tycoon 2 folder> to "
        f"local/game-settings.env, or export it. {NOTHING}\n"
    )


# ---- what a run's folder holds, and git ----


def test_config_ini_sets_the_game_data_path_and_the_autosave_per_mode(tmp_path: Path) -> None:
    rest = "\n[network]\npause_server_if_no_clients = false\nadvertise = false\n"
    head = f'[general]\ngame_path = "{tmp_path}"\n'
    assert config_ini(tmp_path, AUTOSAVE_EVERY_5_MINUTES) == f"{head}autosave = 1\n{rest}"
    assert config_ini(tmp_path, AUTOSAVE_NEVER) == f"{head}autosave = 5\n{rest}"


def test_the_save_helper_registers_its_own_name_with_the_plugins_metadata() -> None:
    helper = save_helper("bench-sample-session-2", 36)

    assert 'var SAVE_FILENAME = "bench-sample-session-2";' in helper
    assert "var SAVE_AFTER_DAYS = 36;" in helper
    assert 'name: "openrct2-analytics-bench-save",' in helper
    assert helper.count("context.") == 2  # subscribe to the day, then save; nothing else
    main_ts = (REPO_ROOT / "plugin" / "src" / "main.ts").read_text(encoding="utf-8")
    for key in ("authors", "type", "targetApiVersion"):
        found = re.search(rf"^\s*({key}: .*)$", main_ts, re.MULTILINE)
        assert found is not None and found.group(1) in helper


def test_the_work_folder_is_ignored_by_git() -> None:
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "data/bench/run-1-attempt-1/user-data/config.ini"],
        cwd=REPO_ROOT,
        check=False,
    )
    assert ignored.returncode == 0

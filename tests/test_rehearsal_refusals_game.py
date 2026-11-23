"""The rehearsal capture's refusals for items 7 to 11 (spec R3) and the Makefile check.

Each returns 2 from ``main`` and writes nothing.
"""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path

import pytest

from openrct2_analytics.ingest import plugin_install as pi
from openrct2_analytics.ingest.game_check import GameState
from openrct2_analytics.ingest.rehearsal_capture import main
from tests.test_bench_run import REPO_ROOT
from tests.test_rehearsal_capture import AUTOSAVE_TIME, RehearsalHarness
from tests.test_rehearsal_refusals import (
    NOTHING,
    FakeTime,
    assert_refused,
    held,
    refuse_unchanged,
)

# ---- item 7: the source saves ----


def test_item_7_a_wrong_fixture_sha1_refuses_without_an_any_park_hint(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    rh.bench.fixture.write_bytes(b"another park")

    refuse_unchanged(rh, capsys, "OPENRCT2_BENCH_PARK is not the benchmark park")


def test_item_7_a_wrong_park2_sha1_refuses_naming_its_setting(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    rh.park2.write_bytes(b"another park two")
    rh.protected = rh.protected_state()  # the test changed the source on purpose

    refuse_unchanged(rh, capsys, "OPENRCT2_REHEARSAL_PARK2 is not Park 2's save")


# ---- item 8: the game answers --version ----


def test_item_8_a_binary_that_does_not_answer_version_refuses(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    rh.bench.binary.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")

    refuse_unchanged(rh, capsys, "OPENRCT2_BINARY did not answer --version")


# ---- item 9: a live game or a busy port ----


@pytest.mark.parametrize("state", [GameState.RUNNING, GameState.UNKNOWN])
def test_item_9_a_running_or_unknowable_game_process_refuses(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str], state: GameState
) -> None:
    match = "OpenRCT2 is running" if state is GameState.RUNNING else "Cannot tell whether"

    refuse_unchanged(rh, capsys, match, game_check=lambda: state)


def test_item_9_a_fresh_autosave_refuses(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    refuse_unchanged(rh, capsys, "autosave is 1.0 minutes old", clock=lambda: AUTOSAVE_TIME + 60)


def test_skip_process_check_still_refuses_a_fresh_autosave(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    def unexpected_process_check() -> GameState:
        raise AssertionError("the process check should be skipped")

    def unexpected_build() -> Path:
        raise AssertionError("build reached")

    options = dataclasses.replace(
        rh.options(clock=lambda: AUTOSAVE_TIME + 60), game_check=unexpected_process_check
    )
    assert (
        main(
            ["--data-set", "rehearsal", "--skip-process-check"],
            options=options,
            build=unexpected_build,
        )
        == 2
    )
    assert "autosave is 1.0 minutes old" in capsys.readouterr().out
    assert not rh.bench.bench_dir.exists()
    assert rh.bench.launches() == []


def test_skip_process_check_still_refuses_a_busy_listener_port(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    def unexpected_build() -> Path:
        raise AssertionError("build reached")

    with held(rh.bench.listener_port, "127.0.0.1"):
        assert (
            main(
                ["--data-set", "rehearsal", "--skip-process-check"],
                options=rh.options(),
                build=unexpected_build,
            )
            == 2
        )

    out = capsys.readouterr().out
    assert "Cannot listen on" in out and out.endswith(f"{NOTHING}\n")
    assert not rh.bench.bench_dir.exists()
    assert not (rh.data_root / "rehearsal").exists()
    assert rh.bench.launches() == []
    rh.assert_protected()


def test_skip_process_check_still_refuses_a_load_average_that_stays_high(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeTime()
    readings: list[float] = []

    def high_load() -> float:
        readings.append(3.0)
        return 3.0

    def unexpected_build() -> Path:
        raise AssertionError("build reached")

    assert (
        main(
            ["--data-set", "rehearsal", "--skip-process-check"],
            options=rh.options(load_average=high_load, clock=fake.clock, sleep=fake.sleep),
            build=unexpected_build,
        )
        == 2
    )

    out = capsys.readouterr().out
    assert "load average stayed at or above 3 for 5 minutes" in out
    assert out.endswith(f"{NOTHING}\n")
    assert sum(fake.sleeps) >= 300 and len(readings) == len(fake.sleeps) + 1
    assert not rh.bench.bench_dir.exists()
    assert not (rh.data_root / "rehearsal").exists()
    assert rh.bench.launches() == []
    rh.assert_protected()


def test_skip_process_check_documents_the_open_game_gap(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing_build() -> Path:
        raise pi.BuildError("tsc: error")

    options = dataclasses.replace(rh.options(), game_check=lambda: GameState.UNKNOWN)
    assert (
        main(
            ["--data-set", "rehearsal", "--skip-process-check"],
            options=options,
            build=failing_build,
        )
        == 2
    )
    out = capsys.readouterr().out
    assert "tsc: error" in out
    assert "The plugin did not build" in out


def test_skip_process_check_does_not_skip_the_data_set_refusal(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--skip-process-check"], options=rh.options(), build=lambda: rh.bench.plugin) == 2
    assert "Name a data set (rehearsal and company)" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("which", "host", "match"),
    [("listener_port", "127.0.0.1", "Cannot listen on"), ("game_port", "", "cannot be bound")],
)
def test_item_9_a_busy_port_refuses(
    rh: RehearsalHarness,
    capsys: pytest.CaptureFixture[str],
    *,
    which: str,
    host: str,
    match: str,
) -> None:
    with held(getattr(rh.bench, which), host):
        refuse_unchanged(rh, capsys, match)


# ---- the Makefile ----


def test_the_makefile_refuses_an_exported_data_set_for_capture_rehearsal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATA_SET", "rehearsal")

    done = subprocess.run(  # noqa: S603  # fixed argument list, no shell
        ["make", "-n", "capture-rehearsal"],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert done.returncode != 0
    assert "DATA_SET must be given on the command line" in done.stderr


# ---- item 10: the load average ----


def test_item_10_a_load_average_that_stays_high_for_five_minutes_refuses(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeTime()
    readings: list[float] = []

    def high_load() -> float:
        readings.append(3.0)
        return 3.0

    assert_refused(
        rh,
        capsys,
        "load average stayed at or above 3 for 5 minutes",
        load_average=high_load,
        clock=fake.clock,
        sleep=fake.sleep,
    )
    assert sum(fake.sleeps) >= 300 and len(readings) == len(fake.sleeps) + 1


# ---- item 11: the plugin build ----


def test_item_11_a_failed_build_refuses(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing_build() -> Path:
        raise pi.BuildError("tsc: error")

    assert rh.main(["--data-set", "rehearsal"], build=failing_build) == 2

    out = capsys.readouterr().out
    assert out == f"tsc: error\nThe plugin did not build. {NOTHING}\n"
    assert not rh.bench.bench_dir.exists()
    assert not (rh.data_root / "rehearsal").exists()
    assert rh.bench.launches() == []
    rh.assert_protected()

"""The game check adapter: pgrep's exit-code contract and the Windows tasklist parse."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from openrct2_analytics.ingest.capture import Refused, refuse_unless_closed
from openrct2_analytics.ingest.capture_session import NOTHING_CHANGED
from openrct2_analytics.ingest.game_check import (
    DEFAULT_PROCESS,
    GameState,
    check_command,
    command_check,
    platform_game_check,
    state_from_exit_code,
    tasklist_state,
)
from openrct2_analytics.ingest.rehearsal_capture import RehearsalOptions


@pytest.mark.parametrize(
    ("code", "state"),
    [
        (0, GameState.RUNNING),
        (1, GameState.NOT_RUNNING),
        (2, GameState.UNKNOWN),
        (3, GameState.UNKNOWN),
        (None, GameState.UNKNOWN),
    ],
)
def test_exit_codes_map_by_pgreps_contract(code: int | None, state: GameState) -> None:
    assert state_from_exit_code(code) is state


@pytest.mark.parametrize(
    ("code", "output", "state"),
    [
        (0, '"openrct2.exe","4242","Console","1","812,004 K"\r\n', GameState.RUNNING),
        (0, '"OpenRCT2.EXE","4242","Console","1","812,004 K"\n', GameState.RUNNING),
        (
            0,
            "INFO: No tasks are running which match the specified criteria.\r\n",
            GameState.NOT_RUNNING,
        ),
        (0, '"openrct2-helper.exe","1","Console","1","1 K"\n', GameState.NOT_RUNNING),
        (1, '"openrct2.exe","4242","Console","1","812,004 K"\n', GameState.UNKNOWN),
        (None, "", GameState.UNKNOWN),
    ],
)
def test_tasklist_output_is_parsed(code: int | None, output: str, state: GameState) -> None:
    assert tasklist_state(code, output, "openrct2.exe") is state


def test_a_check_that_cannot_run_cannot_tell(tmp_path: Path) -> None:
    assert command_check([str(tmp_path / "no-such-tool")])() is GameState.UNKNOWN
    exit_1 = [sys.executable, "-c", "raise SystemExit(1)"]
    assert command_check(exit_1)() is GameState.NOT_RUNNING


@pytest.mark.parametrize(
    ("system", "command"),
    [
        ("Darwin", ["pgrep", "-x", "OpenRCT2"]),  # the macOS app's process name is capitalized
        ("Linux", ["pgrep", "-x", "openrct2"]),
        ("Windows", ["tasklist", "/FI", "IMAGENAME eq openrct2.exe", "/FO", "CSV", "/NH"]),
    ],
)
def test_the_default_check_command_names_each_platforms_process(
    system: str, command: list[str]
) -> None:
    assert check_command(system, DEFAULT_PROCESS[system]) == command


def test_the_rehearsal_default_check_cannot_tell_on_an_unknown_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("platform.system", lambda: "Plan9")

    assert RehearsalOptions().game_check() is GameState.UNKNOWN


def test_the_rehearsal_default_check_runs_pgrep_on_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert RehearsalOptions().game_check() is GameState.RUNNING
    assert commands == [["pgrep", "-x", "OpenRCT2"]]


def test_the_shared_refusal_keeps_capture_datas_text_by_default() -> None:
    with pytest.raises(Refused) as running:
        refuse_unless_closed(lambda: GameState.RUNNING)
    with pytest.raises(Refused) as unknown:
        refuse_unless_closed(lambda: GameState.UNKNOWN)

    assert str(running.value) == (
        f"OpenRCT2 is running. Quit it, run this command, then open the game. {NOTHING_CHANGED}"
    )
    assert str(unknown.value) == f"Cannot tell whether OpenRCT2 is running. {NOTHING_CHANGED}"
    refuse_unless_closed(lambda: GameState.NOT_RUNNING)


def test_a_platform_with_no_known_process_cannot_tell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Plan9")

    assert platform_game_check()() is GameState.UNKNOWN

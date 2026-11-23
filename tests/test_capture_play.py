"""``make play``: the capture command opens the game, backs up the last recorded save, and warns.

Run as a child process on temp folders, like the other capture tests. The stand-in open command
starts the stand-in game; placeholder ``.park`` files hold test bytes, never game content.
"""

from __future__ import annotations

import contextlib
import os
import shlex
import signal
import subprocess
import sys
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openrct2_analytics.ingest import capture, capture_session
from openrct2_analytics.ingest.capture_session import EXIT_PROBLEM, LATE_START, GameDidNotStart
from openrct2_analytics.ingest.game_check import GameState
from openrct2_analytics.ingest.listener import Lander
from tests.test_capture import (
    READY,
    Command,
    Folders,
    Game,
    children_fixture,
    command_argv,
    folders_fixture,
    free_port,
    game_fixture,
    play,
    plugin_lines,
)
from tests.test_capture_saves import GAP, put_park, save_event, session_lines
from tests.test_convert import PARK

__all__ = ["children_fixture", "folders_fixture", "game_fixture"]

# Starts the stand-in game and notes whether the plugin was installed when the open ran.
OPEN_CODE = """
import subprocess, sys
from pathlib import Path
pid_file, installed, marker = (Path(arg) for arg in sys.argv[1:4])
marker.write_text(str(installed.exists()))
game = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
pid_file.write_text(str(game.pid))
"""

PlayStart = Callable[..., Command]


def open_args(folders: Folders) -> list[str]:
    marker = folders.root / "opened"
    return [
        sys.executable,
        "-c",
        OPEN_CODE,
        str(folders.pid_file),
        str(folders.installed),
        str(marker),
    ]


def argv(folders: Folders, port: int, data_set: str, open_command: list[str] | None) -> list[str]:
    args = command_argv(folders, port)
    args[args.index("rehearsal")] = data_set
    if open_command is not None:
        args += ["--open-game", "--open-game-command", shlex.join(open_command)]
        args += ["--open-game-seconds", "2"]
    return args


@pytest.fixture(name="opened_games")
def opened_games_fixture(folders: Folders) -> Iterator[None]:
    """Kill a stand-in game the open command started, which no test fixture owns."""
    yield
    if folders.pid_file.exists():
        with contextlib.suppress(ProcessLookupError):  # the test already quit it
            os.kill(int(folders.pid_file.read_text()), signal.SIGKILL)


@pytest.fixture(name="run_play")
def run_play_fixture(
    folders: Folders, children: list[subprocess.Popen[str]], opened_games: None
) -> PlayStart:
    def start(
        data_set: str = "company", open_command: list[str] | None = None, port: int | None = None
    ) -> Command:
        process = subprocess.Popen(
            argv(folders, port or free_port(), data_set, open_command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=folders.env(),
        )
        children.append(process)
        return Command(process)

    return start


def company_run(
    folders: Folders,
    game: Callable[[], Game],
    run_play: PlayStart,
    session: str,
    *,
    save: str | None = "Crazy Castle",
) -> Command:
    """One company capture with the player's game: one save of ``save`` (or none), then quit."""
    port = free_port()
    command = run_play(port=port)
    command.wait_for(READY)
    running = game()
    command.wait_for("game seen")
    emitted = datetime.now(UTC)
    if save is not None:
        put_park(folders, save, emitted + GAP)
    play(port, session_lines(session, emitted if save is not None else None))
    command.wait_for("events arriving")
    running.quit()
    return command


def test_open_game_runs_after_the_install_and_the_ready_line(
    folders: Folders, run_play: PlayStart
) -> None:
    port = free_port()
    command = run_play("rehearsal", open_args(folders), port)
    command.wait_for("game seen")
    play(port, session_lines("one"))
    command.wait_for("events arriving")
    os.kill(int(folders.pid_file.read_text()), signal.SIGTERM)

    assert command.finish() == 0, command.output
    assert (folders.root / "opened").read_text() == "True"
    ready = next(i for i, line in enumerate(command.lines) if READY in line)
    assert command.lines.index("Opening OpenRCT2.") > ready


def test_a_failing_open_command_cleans_up_and_exits_1(
    folders: Folders, run_play: PlayStart
) -> None:
    command = run_play("rehearsal", [sys.executable, "-c", "import sys; sys.exit(3)"])

    assert command.finish() == EXIT_PROBLEM, command.output
    assert (
        "OpenRCT2 did not start; nothing was recorded. Open the launcher again." in command.output
    )
    assert "The plugin file was removed from" in command.output
    assert not folders.installed.exists()


def test_the_bounded_wait_raises_when_the_game_never_appears(tmp_path: Path) -> None:
    answers = iter([GameState.NOT_RUNNING] * 10_000)  # runs out, so a missing limit fails fast

    with pytest.raises(GameDidNotStart, match="OpenRCT2 did not start"):
        capture_session._watch(lambda: next(answers), Lander(tmp_path), 0.001, 0.05)


def test_the_bounded_wait_ends_normally_once_the_game_ran_and_quit(tmp_path: Path) -> None:
    answers = iter([GameState.NOT_RUNNING, GameState.RUNNING, GameState.NOT_RUNNING])

    capture_session._watch(lambda: next(answers), Lander(tmp_path), 0, 30)


def test_a_company_run_backs_up_the_last_recorded_save(
    folders: Folders, game: Callable[[], Game], run_play: PlayStart
) -> None:
    command = company_run(folders, game, run_play, "one")

    assert command.finish() == 0, command.output
    day = datetime.now().astimezone().strftime("%Y-%m-%d")
    game_copy = folders.user / "save" / f"Test Park-last-plugin-save-{day}.park"
    assert game_copy.read_bytes() == (folders.user / "save" / "Crazy Castle.park").read_bytes()
    (archive,) = (folders.root / "backups" / PARK).iterdir()
    assert archive.name.startswith(f"Test Park-{day}-")
    assert (
        f"Backup: Test Park's last recorded save (Crazy Castle) copied to "
        f"save/Test Park-last-plugin-save-{day}.park; archive copy" in command.output
    )


def test_a_company_run_with_a_capture_problem_makes_no_backup(
    folders: Folders, game: Callable[[], Game], run_play: PlayStart
) -> None:
    port = free_port()
    command = run_play(port=port)
    command.wait_for(READY)
    running = game()
    command.wait_for("game seen")
    play(port, session_lines("one", datetime.now(UTC)))  # a save event with no file
    command.wait_for("events arriving")
    running.quit()

    assert command.finish() == EXIT_PROBLEM, command.output
    assert "No backup made: this run had a capture problem (above)" in command.output
    assert not (folders.root / "backups").exists()


def test_a_company_run_without_a_save_notes_it_and_exits_0(
    folders: Folders, game: Callable[[], Game], run_play: PlayStart
) -> None:
    command = company_run(folders, game, run_play, "one", save=None)

    assert command.finish() == 0, command.output
    assert "Backup: no recorded save in this run, so no backup was made." in command.output


def test_a_rehearsal_run_makes_no_backup(
    folders: Folders, game: Callable[[], Game], run_play: PlayStart
) -> None:
    port = free_port()
    command = run_play("rehearsal", port=port)
    command.wait_for(READY)
    running = game()
    command.wait_for("game seen")
    emitted = datetime.now(UTC)
    put_park(folders, "Crazy Castle", emitted + GAP)
    play(port, session_lines("one", emitted))
    command.wait_for("events arriving")
    running.quit()

    assert command.finish() == 0, command.output
    assert "Backup" not in command.output
    assert [p.name for p in (folders.user / "save").iterdir()] == ["Crazy Castle.park"]


def test_a_save_changed_while_nothing_recorded_warns_before_play(
    folders: Folders, game: Callable[[], Game], run_play: PlayStart
) -> None:
    first = company_run(folders, game, run_play, "one")
    assert first.finish() == 0, first.output
    put_park(folders, "Crazy Castle", datetime.now(UTC) + timedelta(seconds=100))  # unrecorded

    second = run_play()
    second.wait_for(READY)

    day = datetime.now().astimezone().strftime("%Y-%m-%d")
    warning = (
        "Warning: Crazy Castle.park changed after the last recorded save; load "
        f"Test Park-last-plugin-save-{day}.park instead."
    )
    assert warning in second.lines
    assert second.lines.index(warning) < next(
        i for i, line in enumerate(second.lines) if READY in line
    )
    os.kill(second.process.pid, signal.SIGTERM)
    second.finish()


def test_an_unchanged_save_prints_no_warning(
    folders: Folders, game: Callable[[], Game], run_play: PlayStart
) -> None:
    first = company_run(folders, game, run_play, "one")
    assert first.finish() == 0, first.output

    second = run_play()
    second.wait_for(READY)

    assert "Warning:" not in second.output
    os.kill(second.process.pid, signal.SIGTERM)
    second.finish()


def test_a_company_play_run_opens_the_game_and_backs_up(
    folders: Folders, run_play: PlayStart
) -> None:
    port = free_port()
    command = run_play("company", open_args(folders), port)
    command.wait_for("game seen")
    emitted = datetime.now(UTC)
    put_park(folders, "Crazy Castle", emitted + GAP)
    play(port, session_lines("one", emitted))
    command.wait_for("events arriving")
    os.kill(int(folders.pid_file.read_text()), signal.SIGTERM)

    assert command.finish() == 0, command.output
    day = datetime.now().astimezone().strftime("%Y-%m-%d")
    assert (folders.user / "save" / f"Test Park-last-plugin-save-{day}.park").is_file()
    assert "Backup: Test Park's last recorded save (Crazy Castle)" in command.output


def test_an_opened_game_that_never_appears_times_out_and_cleans_up(
    folders: Folders, run_play: PlayStart
) -> None:
    command = run_play("rehearsal", [sys.executable, "-c", "pass"])

    assert command.finish(timeout=60) == EXIT_PROBLEM, command.output
    assert "OpenRCT2 did not start; nothing was recorded." in command.output
    assert not folders.installed.exists()
    assert "NOT recording" not in command.output


def test_a_game_seen_only_after_the_limit_gets_the_loud_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    failure = GameDidNotStart("OpenRCT2 did not start; nothing was recorded.")

    assert capture._start_failed(failure, lambda: GameState.RUNNING) == EXIT_PROBLEM

    assert capsys.readouterr().out.splitlines()[-1] == LATE_START


def test_the_wait_never_times_out_once_events_have_landed(tmp_path: Path) -> None:
    lander = Lander(tmp_path)
    assert lander.land(session_lines("one")[0].encode()) is True
    answers = iter([GameState.NOT_RUNNING] * 50 + [GameState.RUNNING, GameState.NOT_RUNNING])

    capture_session._watch(lambda: next(answers), lander, 0.001, 0.0)


def test_the_wait_never_times_out_while_the_check_cannot_tell(tmp_path: Path) -> None:
    answers = iter([GameState.UNKNOWN] * 50 + [GameState.RUNNING, GameState.NOT_RUNNING])

    capture_session._watch(lambda: next(answers), Lander(tmp_path), 0.001, 0.0)


def test_a_company_run_with_a_seq_gap_makes_no_backup(
    folders: Folders, game: Callable[[], Game], run_play: PlayStart
) -> None:
    port = free_port()
    command = run_play(port=port)
    command.wait_for(READY)
    running = game()
    command.wait_for("game seen")
    emitted = datetime.now(UTC)
    put_park(folders, "Crazy Castle", emitted + GAP)
    play(port, [*plugin_lines("one", (1, 3)), save_event("one", 4, emitted)])  # seq 2 missing
    command.wait_for("events arriving")
    running.quit()

    assert command.finish() == EXIT_PROBLEM, command.output
    assert "failed the seq audit" in command.output
    assert "No backup made: this run had a capture problem (above)" in command.output
    assert not (folders.root / "backups").exists()


def test_a_failed_copy_makes_a_healthy_run_exit_1(
    folders: Folders, game: Callable[[], Game], run_play: PlayStart
) -> None:
    (folders.root / "backups").write_text("a file where the archive folder should be")

    command = company_run(folders, game, run_play, "one")

    assert command.finish() == EXIT_PROBLEM, command.output
    assert "The recorded data is fine; only the backup copy failed." in command.output


def test_an_open_command_that_hangs_is_stopped_and_counts_as_not_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(capture_session, "OPEN_COMMAND_SECONDS", 0.2)

    with pytest.raises(GameDidNotStart, match="The open command failed"):
        capture_session._open_game([sys.executable, "-c", "import time; time.sleep(30)"])


def test_play_without_a_data_set_names_make_play(folders: Folders) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "openrct2_analytics.ingest.capture", "--open-game"],
        capture_output=True,
        text=True,
        env=folders.env(),
        check=False,
    )

    assert result.returncode == 2
    assert "make play" in result.stderr

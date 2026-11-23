"""The capture command's refusals, signals, leftovers and foreign files, on temp folders.

Refusals that happen before the build run the command as a child process; the build-time
cases (a failed build, a file that appears after the checks) call ``capture.run`` in this
process with the build step injected, because the build is the step after every check. An
in-process run whose refusal breaks meets a game that opens and quits, so it ends instead
of waiting for a game that never starts.
"""

from __future__ import annotations

import errno
import hashlib
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from functools import partial
from pathlib import Path

import pytest

from openrct2_analytics.ingest import capture, capture_session, lock
from openrct2_analytics.ingest import plugin_install as pi
from openrct2_analytics.ingest.capture_session import EXIT_INTERRUPTED, Options
from openrct2_analytics.ingest.game_check import GameCheck, GameState, command_check
from tests.test_capture import (
    PLUGIN_BYTES,
    READY,
    Folders,
    Game,
    Start,
    # Shared fixtures, registered under their `name=`, so nothing shadows these imports.
    children_fixture,  # noqa: F401
    command_argv,
    folders_fixture,  # noqa: F401
    free_port,
    game_fixture,  # noqa: F401
    play,
    plugin_lines,
    start_fixture,  # noqa: F401
)
from tests.test_convert import tree

REPO_ROOT = Path(__file__).resolve().parents[1]
REFUSED = "Nothing was changed."
HANDLED_SIGNALS = [signal.SIGINT, signal.SIGTERM, *([signal.SIGHUP] if os.name == "posix" else [])]


def refuse(start: Start, folders: Folders, *, port: int | None = None, **kw: list[str]) -> str:
    """Run the command to its end; assert it refused with exit 2 and changed no file."""
    before = tree(folders.root)
    command = start(port or free_port(), **kw)
    assert command.finish() == capture.EXIT_REFUSED, command.output
    assert REFUSED in command.output
    assert tree(folders.root) == before
    return command.output


def opens_then_quits() -> GameCheck:
    """A game check: not running at the start check, then running once, then quit."""
    answers = iter([GameState.NOT_RUNNING, GameState.RUNNING])
    return lambda: next(answers, GameState.NOT_RUNNING)


@pytest.fixture
def in_process(folders: Folders, monkeypatch: pytest.MonkeyPatch) -> Iterator[Options]:
    """Settings pointed at the temp folders, and this process's signal handlers kept."""
    for name, value in folders.env().items():
        if name.startswith("OPENRCT2_"):
            monkeypatch.setenv(name, value)
    saved = {number: signal.getsignal(number) for number in HANDLED_SIGNALS}
    yield Options(command_check(folders.check_args()), "rehearsal", free_port(), 0.05)
    for number, handler in saved.items():
        signal.signal(number, handler)


# ---- signals ----


@pytest.mark.parametrize("number", HANDLED_SIGNALS, ids=lambda number: number.name)
def test_4_a_signal_removes_the_plugin_and_exits_130_without_converting(
    folders: Folders, start: Start, game: Callable[[], Game], number: signal.Signals
) -> None:
    port = free_port()
    command = start(port)
    command.wait_for(READY)
    game()
    command.wait_for("game seen")
    play(port, plugin_lines("signalled"))
    command.wait_for("events arriving")

    os.kill(command.process.pid, number)

    assert command.finish() == EXIT_INTERRUPTED, command.output
    assert not folders.installed.exists()
    assert not folders.record.exists()
    assert "The plugin file was removed from" in command.output
    assert "Stopped without converting" in command.output
    assert not folders.parquet.exists()
    [dated] = (folders.raw / "v1").glob("events-*.jsonl")
    assert len(dated.read_text(encoding="utf-8").splitlines()) == 3  # raw capture kept


# ---- a second signal, and a connection still open ----


def test_10_two_signals_back_to_back_still_remove_the_plugin(
    folders: Folders, start: Start, game: Callable[[], Game]
) -> None:
    command = start(free_port())
    command.wait_for(READY)
    game()
    command.wait_for("game seen")

    os.kill(command.process.pid, signal.SIGINT)
    os.kill(command.process.pid, signal.SIGTERM)

    assert command.finish() == EXIT_INTERRUPTED, command.output
    assert not folders.installed.exists()
    assert not folders.record.exists()
    assert "The plugin file was removed from" in command.output


def test_11_a_signal_with_a_connection_still_open_ends_within_seconds(
    folders: Folders, start: Start, game: Callable[[], Game]
) -> None:
    port = free_port()
    command = start(port)
    command.wait_for(READY)
    game()
    command.wait_for("game seen")
    with socket.create_connection(("127.0.0.1", port)) as still_open:
        still_open.sendall("".join(line + "\n" for line in plugin_lines("open")).encode())
        command.wait_for("events arriving")

        signalled = time.monotonic()
        os.kill(command.process.pid, signal.SIGINT)
        still_open.settimeout(10)
        assert still_open.recv(1) == b""  # the command shut the connection down
        gone_when_closed = not folders.installed.exists()
        code = command.finish()
        elapsed = time.monotonic() - signalled

    assert gone_when_closed, "the listener stopped before the plugin file was removed"
    assert code == EXIT_INTERRUPTED, command.output
    assert elapsed < 5, f"took {elapsed:.1f} s"
    assert "still running" not in command.output
    assert not folders.installed.exists()
    assert not folders.record.exists()


# ---- refusals when the game runs or the port is busy ----


def test_6_refuses_when_the_game_already_runs(
    folders: Folders, start: Start, game: Callable[[], Game]
) -> None:
    game()
    assert "OpenRCT2 is running" in refuse(start, folders)
    assert not folders.capture.exists()


def test_6_refuses_when_the_port_is_busy_on_loopback(folders: Folders, start: Start) -> None:
    with socket.socket() as other:
        other.bind(("127.0.0.1", 0))
        other.listen()
        port = int(other.getsockname()[1])
        assert f"Cannot listen on 127.0.0.1:{port}" in refuse(start, folders, port=port)


def test_refuses_when_the_check_cannot_tell(folders: Folders, start: Start) -> None:
    cannot_tell = [sys.executable, "-c", "raise SystemExit(3)"]
    assert "Cannot tell whether OpenRCT2 is running" in refuse(start, folders, check=cannot_tell)


# ---- a leftover from a killed run ----


def test_7_a_leftover_from_a_sigkilled_run_is_removed_at_the_next_start(
    folders: Folders, start: Start
) -> None:
    killed = start(free_port())
    killed.wait_for(READY)
    killed.process.kill()
    killed.finish()
    assert folders.installed.read_bytes() == PLUGIN_BYTES
    assert folders.record.exists()

    command = start(free_port())
    command.wait_for(READY)
    assert "Removed the plugin file left by an earlier session" in command.output
    assert folders.installed.read_bytes() == PLUGIN_BYTES  # this run's own install

    os.kill(command.process.pid, signal.SIGTERM)
    assert command.finish() == EXIT_INTERRUPTED
    assert not folders.installed.exists()
    assert not folders.record.exists()


# ---- a file the command did not install ----


def test_8_a_file_at_the_install_path_is_never_overwritten(folders: Folders, start: Start) -> None:
    folders.installed.write_bytes(b"the player's own file")

    assert "holds a file this command did not install" in refuse(start, folders)
    assert folders.installed.read_bytes() == b"the player's own file"


def test_8_a_file_at_the_temporary_name_refuses_before_the_build(
    folders: Folders, start: Start
) -> None:
    temp = pi.temp_path(folders.user)
    temp.write_bytes(b"a file this command did not write")

    assert f"{temp} holds a file this command did not install" in refuse(start, folders)
    assert temp.read_bytes() == b"a file this command did not write"
    assert not folders.capture.exists()  # no install record was written


def test_8_a_file_that_appears_after_the_checks_is_left_alone(
    folders: Folders, in_process: Options
) -> None:
    def build_while_a_file_appears() -> Path:
        folders.installed.write_bytes(b"appeared during the build")
        return folders.plugin_file

    with pytest.raises(capture.Refused, match="was left alone"):
        capture.run(in_process, build_while_a_file_appears)

    assert folders.installed.read_bytes() == b"appeared during the build"
    assert not pi.temp_path(folders.user).exists()
    assert not folders.record.exists()


# ---- a failed build ----


def test_9_a_failed_build_deletes_its_output_and_refuses(
    folders: Folders, in_process: Options
) -> None:
    root = folders.root / "repo-copy"
    shutil.copytree(REPO_ROOT / "plugin", root / "plugin", ignore=shutil.ignore_patterns("dist"))
    shutil.copy(REPO_ROOT / "package.json", root / "package.json")
    (root / "node_modules").symlink_to(REPO_ROOT / "node_modules")
    (root / "plugin" / "src" / "broken.ts").write_text('const wrong: number = "text";\n')
    stale = root / pi.BUILT_PLUGIN
    stale.parent.mkdir(parents=True)
    stale.write_text("output of an earlier build")
    user_before = tree(folders.user)

    options = replace(in_process, game_check=opens_then_quits())
    with pytest.raises(capture.Refused, match="The plugin did not build; nothing was installed."):
        capture.run(options, partial(pi.build_plugin, root))

    assert not stale.exists()
    assert tree(folders.user) == user_before
    assert not folders.capture.exists()
    assert not folders.raw.exists()


# ---- the game starting during the build, and a signal during the install ----


def test_refuses_when_the_game_starts_while_the_plugin_builds(
    folders: Folders, in_process: Options
) -> None:
    before = tree(folders.root)
    options = replace(in_process, game_check=opens_then_quits())

    with pytest.raises(capture.Refused, match=f"started while the plugin was building.*{REFUSED}"):
        capture.run(options, lambda: folders.plugin_file)

    assert tree(folders.root) == before


def test_a_signal_during_the_install_step_waits_until_the_step_ends() -> None:
    saved = {number: signal.getsignal(number) for number in HANDLED_SIGNALS}
    steps: list[str] = []
    try:
        lock.set_signal_handlers(lock.raise_interrupted)  # as main() sets them
        with pytest.raises(lock.Interrupted, match="SIGTERM"), capture_session._signals_deferred():
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(0.05)  # the handler runs here, inside the block
            steps.append("the install step finished")
    finally:
        for number, handler in saved.items():
            signal.signal(number, handler)

    assert steps == ["the install step finished"]


# ---- the other refusals, before any change ----


def test_refuses_without_the_user_folder_or_its_plugin_folder(
    folders: Folders, in_process: Options
) -> None:
    (folders.user / "plugin").rmdir()
    with pytest.raises(capture.Refused, match=f"plugin does not exist. .*{REFUSED}"):
        capture.run(in_process, lambda: folders.plugin_file)
    (folders.user / "save").rmdir()
    folders.user.rmdir()
    with pytest.raises(capture.Refused, match=f"user does not exist. .*{REFUSED}"):
        capture.run(in_process, lambda: folders.plugin_file)


def test_a_missing_save_folder_refuses_and_changes_nothing(folders: Folders, start: Start) -> None:
    (folders.user / "save").rmdir()

    output = refuse(start, folders)

    assert f"{folders.user / 'save'} does not exist. Open OpenRCT2 once" in output


def test_a_refused_leftover_removal_leaves_no_save_files_folder(
    folders: Folders, in_process: Options
) -> None:
    folders.installed.write_bytes(PLUGIN_BYTES)
    digest = hashlib.sha256(PLUGIN_BYTES).hexdigest()
    pi.write_record(folders.capture, pi.InstallRecord(folders.installed, digest, "2026-09-30"))

    def build_while_the_leftover_changes() -> Path:
        folders.installed.write_bytes(b"changed during the build")
        return folders.plugin_file

    with pytest.raises(capture.Refused, match="changed after the checks"):
        capture.run(in_process, build_while_the_leftover_changes)

    assert not (folders.data / "rehearsal" / "save_files").exists()


def test_a_save_files_folder_aliasing_the_raw_folder_refuses_and_changes_nothing(
    folders: Folders, start: Start
) -> None:
    folders.raw.mkdir(parents=True)
    (folders.data / "rehearsal" / "save_files").symlink_to(folders.raw)

    assert "save-file folder" in refuse(start, folders)


def test_refuses_a_record_naming_another_install_path(
    folders: Folders, in_process: Options
) -> None:
    elsewhere = folders.root / "old-user" / "plugin" / pi.PLUGIN_FILE_NAME
    pi.write_record(folders.capture, pi.InstallRecord(elsewhere, "ab" * 32, "2026-09-30"))
    before = tree(folders.root)

    with pytest.raises(capture.Refused, match=f"names {elsewhere}, not"):
        capture.run(in_process, lambda: folders.plugin_file)

    assert tree(folders.root) == before


def test_refuses_a_corrupt_record(folders: Folders, in_process: Options) -> None:
    folders.capture.mkdir()
    folders.record.write_text("{not json")

    with pytest.raises(capture.Refused, match="is not valid"):
        capture.run(in_process, lambda: folders.plugin_file)

    assert folders.record.read_text() == "{not json"


def test_refuses_a_symlink_at_the_install_path(folders: Folders, in_process: Options) -> None:
    folders.installed.symlink_to(folders.plugin_file)

    with pytest.raises(capture.Refused, match="is a symlink"):
        capture.run(in_process, lambda: folders.plugin_file)

    assert folders.installed.is_symlink()
    assert folders.plugin_file.read_bytes() == PLUGIN_BYTES


def test_refuses_another_plugin_file_registering_the_name(
    folders: Folders, in_process: Options
) -> None:
    other = folders.user / "plugin" / "old" / "copy.js"
    other.parent.mkdir()
    other.write_text('registerPlugin({name: "openrct2-analytics"});')
    before = tree(folders.root)

    options = replace(in_process, game_check=opens_then_quits())
    with pytest.raises(capture.Refused, match=f"registers openrct2-analytics: {other}"):
        capture.run(options, lambda: folders.plugin_file)

    assert tree(folders.root) == before


def test_the_port_is_8765_without_port_even_when_the_listener_port_is_set(
    in_process: Options, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_LISTENER_PORT", str(free_port()))
    bound: list[tuple[str, int]] = []

    def busy(host: str, port: int, raw_dir: Path) -> None:
        bound.append((host, port))  # the network is the external: no real bind of 8765
        raise OSError(errno.EADDRINUSE, "Address already in use")

    monkeypatch.setattr(capture, "create_server", busy)
    not_running = shlex.join([sys.executable, "-c", "raise SystemExit(1)"])

    assert (
        capture.main(["--data-set", "rehearsal", "--game-check-command", not_running])
        == capture.EXIT_REFUSED
    )

    assert bound == [("127.0.0.1", 8765)]
    assert "Test run on port" not in capsys.readouterr().out


def test_a_bad_setting_refuses_without_a_traceback(
    folders: Folders,
    in_process: Options,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("OPENRCT2_LISTENER_PORT", "abc")
    before = tree(folders.root)
    not_running = shlex.join([sys.executable, "-c", "raise SystemExit(1)"])

    assert (
        capture.main(["--data-set", "rehearsal", "--game-check-command", not_running])
        == capture.EXIT_REFUSED
    )

    out = capsys.readouterr().out
    assert "OPENRCT2_LISTENER_PORT must be an integer, got: 'abc'" in out
    assert REFUSED in out
    assert tree(folders.root) == before


def test_a_print_failing_after_the_terminal_closes_never_stops_cleanup(
    folders: Folders, children: list[subprocess.Popen[str]]
) -> None:
    process = subprocess.Popen(
        command_argv(folders, free_port()),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=folders.env(),
    )
    children.append(process)
    assert process.stdout is not None
    assert any(READY in line for line in process.stdout), "the command never got ready"
    process.stdout.close()  # every later print fails, as after the Terminal closes

    os.kill(process.pid, signal.SIGHUP)

    assert process.wait(timeout=30) == EXIT_INTERRUPTED
    assert not folders.installed.exists()
    assert not folders.record.exists()

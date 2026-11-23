"""The capture session: install the plugin, serve and watch, clean up, then convert and report.

Split from ``capture`` so that module holds the refusals and the command line. Nothing here
imports ``capture``; ``capture`` re-exports the names the benchmark modules use.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import FrameType

from openrct2_analytics.ingest import plugin_install as pi
from openrct2_analytics.ingest.capture_report import render, summarize
from openrct2_analytics.ingest.convert import NoInputError, UnsafeOutputError, convert
from openrct2_analytics.ingest.game_check import GameCheck, GameState
from openrct2_analytics.ingest.listener import EventServer, Lander
from openrct2_analytics.ingest.lock import (
    Interrupted,
    LockTaken,
    raise_interrupted,
    set_signal_handlers,
)
from openrct2_analytics.ingest.save_backup import BackupPlan, back_up
from openrct2_analytics.ingest.save_files import read_records, read_save_written
from openrct2_analytics.ingest.save_pairing import (
    SaveJudgment,
    judge_saves,
    render_saves,
    render_skipped,
)
from openrct2_analytics.ingest.save_watch import SaveWatcher, WatchStop

if sys.platform != "win32":
    import termios

HANDLER_WAIT_SECONDS = 10.0
SERVE_POLL_SECONDS = 0.1
POLL_SECONDS = 1.0
GAME_START_SECONDS = 60.0
OPEN_COMMAND_SECONDS = 30.0
GAME_DID_NOT_START = "OpenRCT2 did not start; nothing was recorded. Open the launcher again."
LATE_START = (
    "WARNING: OpenRCT2 is running now, but NOT recording: the plugin was already removed. "
    "Quit the game, then open the launcher again."
)
EXIT_OK, EXIT_PROBLEM, EXIT_REFUSED, EXIT_INTERRUPTED = 0, 1, 2, 130
NOTHING_CHANGED = "Nothing was changed."
PLUGIN_PORT = 8765  # plugin/src/transport.ts sends here and nowhere else

Build = Callable[[], Path]


class Refused(Exception):
    """Raised when the command refuses; the message says why and what was left unchanged."""


class WatcherStartFailed(Exception):
    """Raised when the save-file watcher's first scan fails; the run stops before the game opens."""


class GameDidNotStart(Exception):
    """Raised when the opened game was not seen running in time; cleanup has already run."""


@dataclass(frozen=True)
class Options:
    """How one run checks for the game and listens.

    Attributes:
        game_check: Answers whether the game is running.
        data_set: The data set whose landing folders this run writes.
        port: Listener port on ``127.0.0.1``; only 8765 reaches the real plugin.
        poll_seconds: Seconds between game checks.
        open_game: The command that opens the game once the plugin is installed; None leaves
            opening the game to the player.
        start_seconds: With ``open_game``, how long to wait for the game to be seen running.
        before_play: Returns the warning lines printed after the first save-folder scan.
    """

    game_check: GameCheck
    data_set: str
    port: int = PLUGIN_PORT
    poll_seconds: float = POLL_SECONDS
    open_game: tuple[str, ...] | None = None
    start_seconds: float = GAME_START_SECONDS
    before_play: Callable[[], Sequence[str]] = tuple


@dataclass(frozen=True)
class Cleanup:
    """What cleanup did.

    Attributes:
        removal_line: One line saying what happened to the installed plugin file.
        removed: False when the plugin file or its record could not be cleared.
        handlers_running: Connection threads still running after the wait.
    """

    removal_line: str
    removed: bool
    handlers_running: int


def _silence_output() -> None:
    devnull = os.open(os.devnull, os.O_WRONLY)
    for stream in (sys.stdout, sys.stderr):
        os.dup2(devnull, stream.fileno())
    os.close(devnull)


def say(text: str) -> None:
    """Print a line; once the Terminal is gone, later output goes to the null device."""
    try:
        print(text, flush=True)
    except OSError:
        # The Terminal closed (SIGHUP), so nobody can read this line, and a failed print
        # must never stop cleanup: send this and all later output to the null device.
        _silence_output()


@contextmanager
def _signals_deferred() -> Iterator[None]:
    """Hold Ctrl-C, SIGHUP and SIGTERM until the block ends, then raise ``Interrupted``.

    A signal that lands between creating the temporary file and writing its bytes would
    otherwise leave a file that cleanup cannot prove is ours.
    """
    caught: list[int] = []

    def record(signum: int, frame: FrameType | None) -> None:
        caught.append(signum)

    set_signal_handlers(record)
    try:
        yield
    finally:
        set_signal_handlers(raise_interrupted)
    if caught:
        raise_interrupted(caught[0], None)


def _remove_leftover(user_dir: Path, capture_dir: Path) -> None:
    try:
        outcome = pi.remove_installed(user_dir, capture_dir)
    except pi.RemovalError as exc:
        raise Refused(f"{exc} The plugin was not installed.") from exc
    if outcome is pi.RemovalOutcome.NOT_OURS:
        raise Refused(
            f"{pi.install_path(user_dir)} changed after the checks; it was left alone. "
            "The plugin was not installed."
        )
    if outcome is pi.RemovalOutcome.REMOVED:
        say("Removed the plugin file left by an earlier session that did not finish.")
    elif outcome is pi.RemovalOutcome.RECORD_CLEARED:
        say("Cleared the install record of an earlier session; its plugin file was gone.")


def _install(user_dir: Path, capture_dir: Path, built: Path) -> None:
    try:
        pi.install(user_dir, capture_dir, built)
    except pi.InstallRaceError as exc:
        raise Refused(f"{exc} The plugin was not installed.") from exc


def _watch(
    check: GameCheck, lander: Lander, poll_seconds: float, start_seconds: float | None = None
) -> None:
    """Poll the game check until the game has run and quit; never reads input.

    Raises:
        GameDidNotStart: if ``start_seconds`` is set and the game is not seen running within it.
    """
    seen = arriving = unsure = False
    deadline = None if start_seconds is None else time.monotonic() + start_seconds
    while True:
        state = check()
        if state is GameState.UNKNOWN and not unsure:
            say("Cannot tell whether the game is running; checking again.")
        unsure = state is GameState.UNKNOWN
        if state is GameState.RUNNING and not seen:
            say("game seen")
            seen = True
        if state is GameState.NOT_RUNNING and seen:
            say("The game has quit.")
            return
        # Only a clear "not running" with no event landed can time out: a check that cannot
        # tell, or events arriving, means the game may be up, so the session keeps recording.
        if (
            not seen
            and deadline is not None
            and state is GameState.NOT_RUNNING
            and not lander.events_landed
            and time.monotonic() > deadline
        ):
            raise GameDidNotStart(GAME_DID_NOT_START)
        if not arriving and lander.events_landed:
            say("events arriving")
            arriving = True
        time.sleep(poll_seconds)


def _remove_plugin(user_dir: Path, capture_dir: Path) -> tuple[str, bool]:
    target = pi.install_path(user_dir)
    try:
        outcome = pi.remove_installed(user_dir, capture_dir)
    except (pi.RemovalError, pi.RecordError) as exc:
        return f"The plugin file was NOT removed: {exc}", False
    if outcome is pi.RemovalOutcome.NOT_OURS:
        return (
            f"The plugin file was NOT removed: {target} is no longer the file this command "
            "installed, so it was left alone and the install record was kept.",
            False,
        )
    lines = {
        pi.RemovalOutcome.REMOVED: f"The plugin file was removed from {target}.",
        pi.RemovalOutcome.RECORD_CLEARED: (
            f"The plugin file was already gone from {target}; its install record was cleared."
        ),
        pi.RemovalOutcome.NO_RECORD: "No plugin file was installed, so none was removed.",
    }
    return lines[outcome], True


def stop_listener(server: EventServer, serving: threading.Thread) -> int:
    """Stop serving, close open connections, wait for their threads; return how many still run."""
    if serving.ident is not None:  # shutdown() waits forever for a loop that never started
        server.shutdown()
    server.close_connections()
    running = server.wait_for_handlers(HANDLER_WAIT_SECONDS)
    server.server_close()
    if running:
        say(f"{running} connection thread(s) still running after {HANDLER_WAIT_SECONDS:g} s.")
    return running


def discard_typed_input() -> None:
    """Flush input typed during the session, so it never runs as shell commands afterwards."""
    if sys.platform == "win32" or sys.stdin is None or not sys.stdin.isatty():
        return
    try:
        termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    except termios.error:
        # The Terminal is gone (SIGHUP), so no typed input can reach a shell either.
        return


def _clean_up(
    server: EventServer, serving: threading.Thread, user_dir: Path, capture_dir: Path
) -> Cleanup:
    """Remove the plugin, then stop the listener and wait for its threads, then flush input."""
    try:
        removal_line, removed = _remove_plugin(user_dir, capture_dir)
    finally:
        running = stop_listener(server, serving)
        discard_typed_input()
    return Cleanup(removal_line, removed, running)


def _start_watcher(watcher: SaveWatcher) -> None:
    try:
        watcher.start()
    except OSError as exc:
        raise WatcherStartFailed(
            f"The save-file watcher could not start: {type(exc).__name__}: {exc}"
        ) from exc


def _open_game(command: Sequence[str]) -> None:
    """Run the open command; a failure to run it is a game that did not start."""
    say("Opening OpenRCT2.")
    # A file, not a pipe: a program the open command leaves running would hold a pipe open.
    with tempfile.TemporaryFile() as errors:
        try:
            result = subprocess.run(
                list(command),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=errors,
                timeout=OPEN_COMMAND_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GameDidNotStart(f"The open command failed ({exc}). {GAME_DID_NOT_START}") from exc
        errors.seek(0)
        detail = errors.read().decode("utf-8", "replace").strip()
    if result.returncode != 0:
        detail = detail or f"exit {result.returncode}"
        raise GameDidNotStart(f"The open command failed ({detail}). {GAME_DID_NOT_START}")


def run_session(
    server: EventServer,
    user_dir: Path,
    capture_dir: Path,
    *,
    built: Path,
    watcher: SaveWatcher,
    options: Options,
) -> tuple[bool, Cleanup, WatchStop]:
    """Install, serve and watch; clean up on every way out. True when the game quit.

    Raises:
        WatcherStartFailed: if the watcher's first scan fails; cleanup has already run.
        GameDidNotStart: if ``options.open_game`` is set and the game did not start; cleanup has
            already run.
    """
    game_quit = interrupted = False
    serving = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": SERVE_POLL_SECONDS}, daemon=True
    )
    try:
        _remove_leftover(user_dir, capture_dir)
        with _signals_deferred():
            _install(user_dir, capture_dir, built)
        serving.start()
        _start_watcher(watcher)
        for line in options.before_play():
            say(line)
        host, port = server.address
        say(
            f"Plugin installed at {pi.install_path(user_dir)}; listening on {host}:{port}.\n"
            "Open OpenRCT2 now and play. Quit the game when you are done; nothing typed "
            "here is read."
        )
        start_seconds = None
        if options.open_game is not None:
            _open_game(options.open_game)
            start_seconds = options.start_seconds
        _watch(options.game_check, server.lander, options.poll_seconds, start_seconds)
        game_quit = True
        set_signal_handlers(signal.SIG_IGN)  # a signal now must not undo the quit
    except Interrupted:
        interrupted = True  # cleanup runs below; run() then stops without converting
    finally:
        set_signal_handlers(signal.SIG_IGN)  # nothing may cut cleanup short
        try:
            cleanup = _clean_up(server, serving, user_dir, capture_dir)
        finally:
            watch = watcher.stop()  # a no-op when the watcher never started
        if interrupted or not game_quit:  # after a quit, the line follows the report
            say(cleanup.removal_line)
    return game_quit, cleanup, watch


def _report_saves(
    save_dir: Path, parquet_dir: Path, started: datetime, watch: WatchStop
) -> SaveJudgment | None:
    """Print the "Save files" section (or the skip line); None when pairing was skipped.

    A skipped pairing is a capture failure: a timed-out join is a watcher error.
    """
    if watch.join_timed_out:
        say(render_skipped("the save-file watcher did not stop in time", watch.error))
        return None
    records, unreadable = read_records(save_dir, started)
    judgment = judge_saves(
        records,
        read_save_written(parquet_dir),
        started,
        unreadable=unreadable,
        watcher_error=watch.error,
    )
    say(render_saves(judgment))
    return judgment


def _report_backup(judgment: SaveJudgment | None, seq_failed: bool, plan: BackupPlan) -> bool:
    """Print the backup lines; False when a copy failed."""
    if judgment is None or judgment.failed or seq_failed:
        say("No backup made: this run had a capture problem (above); the previous backup was kept.")
        return True
    lines, ok = back_up(judgment, plan, datetime.now().astimezone())
    for line in lines:
        say(line)
    return ok


def convert_and_report(
    raw_dir: Path,
    parquet_dir: Path,
    save_dir: Path,
    started: datetime,
    *,
    watch: WatchStop,
    backup: BackupPlan | None = None,
) -> int:
    """Convert the raw folder and print the report of this run; return the exit code.

    With ``backup``, a healthy run then copies each park's last recorded save.
    """
    try:
        result = convert(raw_dir, parquet_dir)
    except (NoInputError, UnsafeOutputError, LockTaken, FileNotFoundError, ValueError) as exc:
        say(f"The converter failed: {exc}")
        say(render_skipped("the converter failed", watch.error))
        return EXIT_PROBLEM
    if result.schema_errors:
        say("The converter failed; no report was built from older Parquet.")
        for line in result.schema_errors:
            say(f"  schema error: {line}")
        say(render_skipped("the converter failed", watch.error))
        return EXIT_PROBLEM
    summary = summarize(parquet_dir, started)
    say(render(summary, result.malformed_lines))
    if summary.total_events == 0:
        say("No event landed in this run.")
        say(render_skipped("no event landed in this run", watch.error))
        return EXIT_PROBLEM
    judgment = _report_saves(save_dir, parquet_dir, started, watch)
    seq_failed = any(session.seq_problem for session in summary.sessions)
    if seq_failed:
        say("A session of this run failed the seq audit; the raw capture was kept.")
    backup_ok = backup is None or _report_backup(judgment, seq_failed, backup)
    if seq_failed or judgment is None or judgment.failed or not backup_ok:
        return EXIT_PROBLEM
    return EXIT_OK

"""Capture one play session: install the plugin, listen until the game quits, then report.

Run with ``python -m openrct2_analytics.ingest.capture`` (``make capture-data``). The
command refuses before changing anything when it is unsafe to start, builds and installs
the repo's plugin into the player's OpenRCT2 plugin folder, lands events through the
listener on ``127.0.0.1:8765`` (the only address the plugin sends to), and removes the
plugin however the session ends. After the game quits it converts the raw folder and
prints a report of this run. It never reads Terminal input.

With ``--open-game`` (``make play``) it opens the game itself once the plugin is installed and
waits up to 60 seconds to see it running. After a healthy company capture it copies each park's
last recorded save to the game's save folder and to an archive (``save_backup``).

Exit codes: 0 a clean capture, 1 a capture problem (no event, a ``seq`` violation in this
run, the converter failed, the save-file watcher failed, or the "Save files" section found a
capture failure (a save with no matching file, an unpaired event, a two-candidate window or an
unreadable record line of this run), the plugin could not be removed, the opened game did not
start, or a backup copy failed), 2 refused, 130 stopped by Ctrl-C, a closed Terminal or SIGTERM.
"""

from __future__ import annotations

import argparse
import platform
import shlex
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from openrct2_analytics.config import (
    CAPTURE_DEFAULT_DATA_SET,
    DATA_SETS,
    Config,
    ConfigError,
    landing_dirs,
)
from openrct2_analytics.ingest import plugin_install as pi
from openrct2_analytics.ingest.capture_session import (
    EXIT_INTERRUPTED,
    EXIT_OK,
    EXIT_PROBLEM,
    EXIT_REFUSED,
    GAME_START_SECONDS,
    HANDLER_WAIT_SECONDS,
    LATE_START,
    NOTHING_CHANGED,
    PLUGIN_PORT,
    POLL_SECONDS,
    SERVE_POLL_SECONDS,
    Build,
    GameDidNotStart,
    Options,
    Refused,
    WatcherStartFailed,
    convert_and_report,
    run_session,
    say,
    stop_listener,
)
from openrct2_analytics.ingest.game_check import (
    DEFAULT_OPEN_GAME,
    DEFAULT_PROCESS,
    GameCheck,
    GameState,
    command_check,
    default_check,
)
from openrct2_analytics.ingest.listener import EventServer, create_server, no_data_set_line
from openrct2_analytics.ingest.lock import Interrupted, raise_interrupted, set_signal_handlers
from openrct2_analytics.ingest.save_backup import BACKUP_DATA_SET, BackupPlan, warn_before_play
from openrct2_analytics.ingest.save_files import save_files_dir
from openrct2_analytics.ingest.save_pairing import render_skipped
from openrct2_analytics.ingest.save_watch import (
    REMEMBERED_KIND,
    SaveWatcher,
    remembered_folder,
    watch_folders,
)

# The benchmark modules import these names from here.
__all__ = [
    "EXIT_OK",
    "EXIT_PROBLEM",
    "EXIT_REFUSED",
    "HANDLER_WAIT_SECONDS",
    "PLUGIN_HOST",
    "PLUGIN_PORT",
    "REPO_ROOT",
    "SERVE_POLL_SECONDS",
    "Build",
    "Refused",
    "say",
    "stop_listener",
]

PLUGIN_HOST = "127.0.0.1"  # plugin/src/transport.ts sends here and nowhere else
REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_PATH_REFUSALS = {
    pi.InstallState.FOREIGN: "holds a file this command did not install",
    pi.InstallState.UNSAFE: "is a symlink, not a regular file, or has more than one hard link",
}


def _check_folders(user_dir: Path) -> None:
    for folder in (user_dir, user_dir / "plugin", user_dir / "save"):
        if not folder.is_dir():
            raise Refused(
                f"{folder} does not exist. Open OpenRCT2 once so it creates its folders, or "
                f"set OPENRCT2_USER_DIR. {NOTHING_CHANGED}"
            )


def _check_game_still_closed(check: GameCheck) -> None:
    if check() is not GameState.NOT_RUNNING:
        raise Refused(
            "The game started while the plugin was building; quit it and run again. "
            f"{NOTHING_CHANGED}"
        )


def refuse_unless_closed(
    check: GameCheck,
    *,
    advice: str = "Quit it, run this command, then open the game.",
    tail: str = NOTHING_CHANGED,
) -> None:
    """Refuse when the game runs or the check cannot tell; the callers word the advice and tail."""
    state = check()
    if state is GameState.RUNNING:
        raise Refused(f"OpenRCT2 is running. {advice} {tail}")
    if state is GameState.UNKNOWN:
        raise Refused(f"Cannot tell whether OpenRCT2 is running. {tail}")


def _bind(port: int, raw_dir: Path) -> EventServer:
    try:
        return create_server(PLUGIN_HOST, port, raw_dir)
    except OSError as exc:
        raise Refused(
            f"Cannot listen on {PLUGIN_HOST}:{port} ({exc}); another capture or "
            f"`make listen` may be running. {NOTHING_CHANGED}"
        ) from exc


def _check_install_path(user_dir: Path, capture_dir: Path) -> None:
    try:
        record = pi.read_record(capture_dir)
    except pi.RecordError as exc:
        raise Refused(f"{exc} {NOTHING_CHANGED}") from exc
    if pi.classify_temp(user_dir, record) is pi.TempState.OTHER:
        raise Refused(
            f"{pi.temp_path(user_dir)} holds a file this command did not install; it was left "
            f"alone. {NOTHING_CHANGED}"
        )
    target = pi.install_path(user_dir)
    state = pi.classify_install_path(user_dir, record)
    if record is not None and state is pi.InstallState.RECORD_ELSEWHERE:
        raise Refused(
            f"The install record {pi.record_path(capture_dir)} names {record.path}, not "
            f"{target} (did OPENRCT2_USER_DIR change?). Both were left alone. {NOTHING_CHANGED}"
        )
    reason = INSTALL_PATH_REFUSALS.get(state)
    if reason is not None:
        raise Refused(f"{target} {reason}; it was left alone. {NOTHING_CHANGED}")
    others = pi.find_other_plugin_files(user_dir)
    if others:
        names = ", ".join(str(path) for path in others)
        raise Refused(
            f"Another plugin file registers openrct2-analytics: {names}. Move it out of the "
            f"plugin folder first. {NOTHING_CHANGED}"
        )


def _build(build: Build) -> Path:
    try:
        return build()
    except pi.BuildError as exc:
        raise Refused(f"{exc}\nThe plugin did not build; nothing was installed.") from exc


def start_time() -> datetime:
    """Now, cut to whole milliseconds like ``received_at``, so no event of this run is earlier."""
    now = datetime.now(UTC)
    return now.replace(microsecond=now.microsecond // 1000 * 1000)


def _start_failed(failure: Exception, check: GameCheck) -> int:
    """Report a session that stopped before play; warn when the game opened after the limit."""
    say(str(failure))
    if isinstance(failure, GameDidNotStart) and check() is GameState.RUNNING:
        say(LATE_START)
    return EXIT_PROBLEM


def run(options: Options, build: Build) -> int:
    """Refuse or capture one session, then convert and report after a normal game quit.

    Args:
        options: The game check and listener settings.
        build: Returns the built plugin file; raises ``BuildError`` when the build fails.

    Returns:
        The exit code: 0, 1 or 130.

    Raises:
        Refused: before any change (or, for an install race, before the plugin is
            installed); the message says why.
        Interrupted: if a signal arrives before the session starts.
    """
    started = start_time()
    try:
        folders = landing_dirs(options.data_set)  # first: nothing else may happen without it
        save_dir = save_files_dir(options.data_set)
        config = Config.from_env()
    except ConfigError as exc:
        raise Refused(f"{exc}. {NOTHING_CHANGED}") from exc
    user_dir = pi.resolve_user_dir(config, platform.system())
    _check_folders(user_dir)
    refuse_unless_closed(options.game_check)
    with _bind(options.port, folders.raw) as server:
        _check_install_path(user_dir, config.capture_dir)
        built = _build(build)
        _check_game_still_closed(options.game_check)
        watched = watch_folders(user_dir)
        remembered, remembered_line = remembered_folder(user_dir)
        if remembered is not None:
            watched[REMEMBERED_KIND] = remembered
        if remembered_line is not None:
            say(remembered_line)
        watcher = SaveWatcher(watched, save_dir, started, options.poll_seconds, say=say)
        try:
            game_quit, cleanup, watch = run_session(
                server,
                user_dir,
                config.capture_dir,
                built=built,
                watcher=watcher,
                options=replace(
                    options,
                    before_play=partial(
                        warn_before_play,
                        save_dir,
                        folders.parquet,
                        started,
                        game_save_dir=watched["save"],
                        archive_dir=config.backup_dir,
                    ),
                ),
            )
        except (WatcherStartFailed, GameDidNotStart) as failure:
            return _start_failed(failure, options.game_check)
    if not game_quit:
        say("Stopped without converting; the raw capture was kept.")
        say(render_skipped("the run was interrupted", watch.error))
        return EXIT_INTERRUPTED
    if cleanup.handlers_running:
        say("Conversion skipped: a connection may still be writing to the raw files.")
        say(render_skipped("a connection thread was still running", watch.error))
        say(cleanup.removal_line)
        return EXIT_PROBLEM
    if server.lander.events_landed == 0:
        say("No event landed in this run.")
        say(render_skipped("no event landed in this run", watch.error))
        say(cleanup.removal_line)
        return EXIT_PROBLEM
    backup = None
    if options.data_set == BACKUP_DATA_SET:
        backup = BackupPlan(watched, watched["save"], config.backup_dir, folders.parquet)
    try:
        code = convert_and_report(
            folders.raw, folders.parquet, save_dir, started, watch=watch, backup=backup
        )
    finally:
        say(cleanup.removal_line)
    return code if cleanup.removed else EXIT_PROBLEM


def main(argv: Sequence[str] | None = None) -> int:
    """Capture one session; return 0, 1 (capture problem), 2 (refused) or 130 (interrupted)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-set",
        choices=DATA_SETS,
        default=CAPTURE_DEFAULT_DATA_SET,
        help="Data set whose landing folders receive the capture",
    )
    parser.add_argument("--game-process", help="Game process name (default: per platform)")
    parser.add_argument(
        "--game-check-command",
        help="Replace the game check with this command (exit 0 running, 1 not); a test seam",
    )
    parser.add_argument("--port", type=int, default=PLUGIN_PORT, help="Listener port; a test seam")
    parser.add_argument(
        "--plugin-file", type=Path, help="Install this built file instead of building; a test seam"
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=POLL_SECONDS,
        help="Between game checks; also between save-folder scans",
    )
    parser.add_argument(
        "--open-game",
        action="store_true",
        help="Open the game once the plugin is installed; wait up to 60 s to see it running",
    )
    parser.add_argument(
        "--open-game-command",
        help="With --open-game, replace the open command (default: per platform); a test seam",
    )
    parser.add_argument(
        "--open-game-seconds",
        type=float,
        default=GAME_START_SECONDS,
        help="With --open-game, how long to wait for the game; a test seam",
    )
    args = parser.parse_args(argv)
    if args.data_set is None:
        print(no_data_set_line("play" if args.open_game else "capture-data"), file=sys.stderr)
        return EXIT_REFUSED
    system = platform.system()
    if args.game_check_command:
        check = command_check(shlex.split(args.game_check_command))
    else:
        process = args.game_process or DEFAULT_PROCESS.get(system)
        if process is None:
            parser.error(f"no default game process for {system}; pass --game-process")
        check = default_check(system, process)
    open_game: tuple[str, ...] | None = None
    if args.open_game:
        open_game = (
            tuple(shlex.split(args.open_game_command))
            if args.open_game_command
            else DEFAULT_OPEN_GAME.get(system)
        )
        if open_game is None:
            parser.error(f"no default open command for {system}; pass --open-game-command")
    plugin_file: Path | None = args.plugin_file
    build: Build = partial(pi.build_plugin, REPO_ROOT)
    if plugin_file is not None:
        build = partial(Path, plugin_file)
    if args.port != PLUGIN_PORT:
        say(f"Test run on port {args.port}: the real plugin sends only to {PLUGIN_PORT}.")

    set_signal_handlers(raise_interrupted)
    try:
        options = Options(
            check, args.data_set, args.port, args.poll_seconds, open_game, args.open_game_seconds
        )
        return run(options, build)
    except Refused as refusal:
        say(str(refusal))
        return EXIT_REFUSED
    except Interrupted:
        say(f"Interrupted before the plugin was installed. {NOTHING_CHANGED}")
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())

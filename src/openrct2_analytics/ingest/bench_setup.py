"""Benchmark setup: settings and fixture checks, refusals, and each run's isolated folder.

``bench_run`` calls the checks here before anything is written, then builds one isolated
OpenRCT2 user-data folder per run: the built plugin, a copy of the park, a fresh
``config.ini`` and, in sample mode, the save helper. The player's real OpenRCT2 folder is
never written; the only thing read there is the modification time of the newest autosave.
The fixture park is only read and copied. Refusal messages name settings, never their
values, because the values are private paths.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from openrct2_analytics.config import BenchConfig, Config, ConfigError
from openrct2_analytics.ingest import plugin_install as pi
from openrct2_analytics.ingest.bench_actions import ACTION_HELPER_FILE
from openrct2_analytics.ingest.capture import PLUGIN_HOST, REPO_ROOT, Refused, say
from openrct2_analytics.ingest.game_settings import (
    NOTHING_WRITTEN,
    SETTINGS_FILE_LABEL,
    game_path_from_openrct2,
    read_settings_file,
)
from openrct2_analytics.ingest.listener import create_server

# Dusty Greens, the benchmark park; the full 40-character hash would trip the secret scan.
BENCH_PARK_SHA1_PREFIX = "a65dba74"
SHA1_PREFIX_LENGTH = len(BENCH_PARK_SHA1_PREFIX)
AUTOSAVE_QUIET_SECONDS = 600.0  # a newer real autosave means the player's game is live
MAX_LOAD = 3.0
LOAD_WAIT_SECONDS = 300.0
LOAD_POLL_SECONDS = 15.0
VERSION_TIMEOUT_SECONDS = 30.0
# OpenRCT2's AutosaveFrequency values for config.ini.
AUTOSAVE_EVERY_5_MINUTES = 1
AUTOSAVE_EVERY_5_MINUTES_LABEL = "every 5 minutes"  # how the verdict conditions name that setting
AUTOSAVE_NEVER = 5
PARK_COPY_STEM = "bench-park"
SAVE_HELPER_FILE = "openrct2-analytics-bench-save.js"
# Game settings found without exports: the git-ignored file at the repo root (read, never written).
SETTINGS_FILE = REPO_ROOT / "local" / "game-settings.env"
SETTING_HINTS = {
    "OPENRCT2_BINARY": "the OpenRCT2 executable",
    "OPENRCT2_GAME_PATH": "the RollerCoaster Tycoon 2 folder",
    "OPENRCT2_BENCH_PARK": "the benchmark .park file",
}
SAVE_HELPER = """// Benchmark save helper, written only into one benchmark run's own plugin folder.
// It saves the park once, on its SAVE_AFTER_DAYS-th day callback, and does nothing else.
var SAVE_FILENAME = __SAVE_FILENAME__;
var SAVE_AFTER_DAYS = __SAVE_AFTER_DAYS__;

function main() {
  var daysSeen = 0;
  context.subscribe("interval.day", function () {
    daysSeen += 1;
    if (daysSeen === SAVE_AFTER_DAYS) {
      context.saveGame({ filename: SAVE_FILENAME });
    }
  });
}

registerPlugin({
  name: "openrct2-analytics-bench-save",
  version: "0.1.0",
  authors: ["John Cabiles"],
  type: "local",
  licence: "MIT",
  targetApiVersion: 122,
  main: main
});
"""

Clock = Callable[[], float]
Sleep = Callable[[float], None]
LoadAverage = Callable[[], float]


@dataclass(frozen=True)
class BenchSettings:
    """The benchmark's settings, checked to exist.

    Attributes:
        binary: The OpenRCT2 executable (``OPENRCT2_BINARY``).
        park: The fixture park file (``OPENRCT2_BENCH_PARK``); only ever read.
        game_path: The RollerCoaster Tycoon 2 data folder (``OPENRCT2_GAME_PATH``).
        user_dir: The player's real OpenRCT2 folder; only its newest autosave's age is read.
        bench_dir: The work folder (``OPENRCT2_BENCH_DIR``; a relative value is under the repo).
    """

    binary: Path
    park: Path
    game_path: Path
    user_dir: Path
    bench_dir: Path


@dataclass(frozen=True)
class RunFolder:
    """One run's folder under the work folder, kept after the run.

    Attributes:
        root: The folder; it holds ``user-data/``, ``raw/``, ``parquet/`` and the game's log.
    """

    root: Path

    @property
    def user_data(self) -> Path:
        """The isolated OpenRCT2 user-data folder the game runs with."""
        return self.root / "user-data"

    @property
    def save_dir(self) -> Path:
        """Where the park copy goes and where the game writes its saves."""
        return self.user_data / "save"

    @property
    def raw(self) -> Path:
        """The listener's raw folder for this run."""
        return self.root / "raw"

    @property
    def parquet(self) -> Path:
        """The converter's output folder for this run."""
        return self.root / "parquet"

    @property
    def game_log(self) -> Path:
        """The game's own output, kept out of the command's output (it names private paths)."""
        return self.root / "game.log"


def _required(value: Path | None, name: str, *, also: str = "") -> Path:
    if value is None:
        raise Refused(
            f"{name} is not set{also}. Add a line {name}=<path to {SETTING_HINTS[name]}> to "
            f"{SETTINGS_FILE_LABEL}, or export it. {NOTHING_WRITTEN}"
        )
    return value


def _pick(
    name: str,
    from_env: Path | None,
    saved: dict[str, tuple[Path, str]],
    *,
    default: Path | None,
    default_source: str,
) -> tuple[Path | None, str]:
    """Exported value first, then the settings file, then the automatic default, with its source."""
    if name in os.environ:
        return from_env, "exported"
    if name in saved:
        return saved[name]
    return default, default_source


def load_settings(system: str, *, park: Path | None = None) -> BenchSettings:
    """Read and check the benchmark settings.

    Each of ``OPENRCT2_BINARY``, ``OPENRCT2_GAME_PATH`` and ``OPENRCT2_BENCH_PARK`` comes from
    the first source that has it: the exported environment, then ``local/game-settings.env``,
    then the automatic default (the macOS app location; the ``game_path`` in the game's own
    ``config.ini``; the benchmark park has none).

    Args:
        system: ``platform.system()``, for the player's default OpenRCT2 folder.
        park: a park file that replaces ``OPENRCT2_BENCH_PARK``; it is not checked here.

    Returns:
        The settings, each checked to name an existing file or folder, except a given ``park``.

    Raises:
        Refused: if a setting is missing, invalid, or names nothing usable.
    """
    try:
        config = Config.from_env()
        bench = BenchConfig.from_env()
    except ConfigError as exc:
        raise Refused(f"{exc}. {NOTHING_WRITTEN}") from exc
    user_dir = pi.resolve_user_dir(config, system)
    saved = read_settings_file(SETTINGS_FILE)
    binary_value, binary_source = _pick(
        "OPENRCT2_BINARY",
        bench.binary,
        saved,
        default=bench.binary,
        default_source="the default location",
    )
    binary = _required(binary_value, "OPENRCT2_BINARY")
    park_source = ""
    if park is None:
        park_value, park_source = _pick(
            "OPENRCT2_BENCH_PARK", bench.park, saved, default=None, default_source=""
        )
        park_file = _required(park_value, "OPENRCT2_BENCH_PARK")
    else:
        park_file = park
    game_path_value, game_source = _pick(
        "OPENRCT2_GAME_PATH", bench.game_path, saved, default=None, default_source=""
    )
    if game_path_value is None:  # an exported value is never None: an empty one is a ConfigError
        game_path_value = game_path_from_openrct2(user_dir)
        game_source = "OpenRCT2's own settings"
    game_path = _required(
        game_path_value,
        "OPENRCT2_GAME_PATH",
        also=" and was not found in OpenRCT2's own settings",
    )
    if not (binary.is_file() and os.access(binary, os.X_OK)):
        raise Refused(
            f"OPENRCT2_BINARY does not name an executable file (from {binary_source}). "
            f"{NOTHING_WRITTEN}"
        )
    if park is None and not park_file.is_file():
        raise Refused(
            f"OPENRCT2_BENCH_PARK does not name a file (from {park_source}). {NOTHING_WRITTEN}"
        )
    if not game_path.is_dir():
        raise Refused(
            f"OPENRCT2_GAME_PATH does not name a folder (from {game_source}). {NOTHING_WRITTEN}"
        )
    # A relative work folder is the repo's, so the git-ignore rule covers it from any folder.
    bench_dir = REPO_ROOT / bench.work_dir
    if bench_dir.resolve().is_relative_to(user_dir.resolve()) or user_dir.resolve().is_relative_to(
        bench_dir.resolve()
    ):
        raise Refused(
            "OPENRCT2_BENCH_DIR and the player's OpenRCT2 folder (OPENRCT2_USER_DIR) must not "
            f"be the same folder or inside one another. {NOTHING_WRITTEN}"
        )
    return BenchSettings(binary, park_file, game_path, user_dir, bench_dir)


def game_version(binary: Path) -> str:
    """Return the first line of ``<binary> --version``.

    The game is pointed at a throwaway user-data folder outside the repo, so asking for its
    version can never create or touch the player's real OpenRCT2 folder or the work folder.

    Raises:
        Refused: if the binary does not answer within the timeout.
    """
    try:
        with tempfile.TemporaryDirectory(prefix="openrct2-version-") as throwaway:
            result = subprocess.run(  # noqa: S603  # an argument list, no shell
                [str(binary), "--version", "--user-data-path", throwaway],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=VERSION_TIMEOUT_SECONDS,
                check=False,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Refused(
            f"OPENRCT2_BINARY did not answer --version ({type(exc).__name__}). {NOTHING_WRITTEN}"
        ) from exc
    lines = result.stdout.strip().splitlines()
    if result.returncode != 0 or not lines:
        raise Refused(f"OPENRCT2_BINARY did not answer --version. {NOTHING_WRITTEN}")
    return lines[0]


def file_sha1(path: Path) -> str:
    """Return the SHA-1 hex digest of a file; callers record only its prefix."""
    return hashlib.sha1(path.read_bytes(), usedforsecurity=False).hexdigest()


def check_fixture(
    park: Path,
    expected_prefix: str | None,
    *,
    setting: str = "OPENRCT2_BENCH_PARK",
    hint: str = "pass --any-park to measure another park.",
    park_name: str = "the benchmark park",
) -> str:
    """Return the fixture's SHA-1, refusing a park whose SHA-1 lacks the expected prefix.

    Args:
        park: The fixture park file.
        expected_prefix: The required SHA-1 prefix, or None to accept any park (``--any-park``).
        setting: The name of the setting that points at the park, shown in the refusal.
        hint: A sentence telling the user how to proceed; left out of the refusal when empty.
        park_name: What the refusal calls the park, after "is not".

    Raises:
        Refused: if the prefix is required and does not match.
    """
    digest = file_sha1(park)
    if expected_prefix is not None and not digest.startswith(expected_prefix):
        tail = f"; {hint} {NOTHING_WRITTEN}" if hint else f". {NOTHING_WRITTEN}"
        raise Refused(
            f"{setting} is not {park_name} (SHA-1 {digest[:SHA1_PREFIX_LENGTH]}, "
            f"expected {expected_prefix})" + tail
        )
    return digest


def check_work_folder(bench_dir: Path, names: Sequence[str]) -> None:
    """Refuse when the work folder already holds a folder or file this run would write.

    Raises:
        Refused: naming the leftovers relative to the work folder.
    """
    taken = [name for name in names if (bench_dir / name).exists()]
    if taken:
        raise Refused(
            f"The work folder (OPENRCT2_BENCH_DIR) already holds {', '.join(taken)} from an "
            f"earlier run; move them away first. {NOTHING_WRITTEN}"
        )


def check_ports(listener_port: int, game_port: int, bench_dir: Path) -> None:
    """Refuse when the listener's port or the game's port cannot be bound.

    The listener port is checked by binding the listener itself on ``127.0.0.1`` (it writes
    nothing until a line arrives); the game's port by binding a socket on all interfaces.

    Raises:
        Refused: naming the busy port.
    """
    try:
        with create_server(PLUGIN_HOST, listener_port, bench_dir):
            pass
    except OSError as exc:
        raise Refused(
            f"Cannot listen on {PLUGIN_HOST}:{listener_port} ({exc.strerror}); a capture or "
            f"`make listen` may be running. {NOTHING_WRITTEN}"
        ) from exc
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("", game_port))
    except OSError as exc:
        raise Refused(
            f"Port {game_port} cannot be bound ({exc.strerror}), so the game cannot host on it. "
            f"{NOTHING_WRITTEN}"
        ) from exc


def check_no_live_game(user_dir: Path, now: float) -> None:
    """Refuse while the newest autosave in the player's real folder is under 10 minutes old.

    Only the modification times in ``<user_dir>/save/autosave/`` are read; a missing folder
    means no recent autosave. ``pgrep`` cannot see the game from inside the agent sandbox.

    Raises:
        Refused: if a live game would share the CPU.
    """
    autosaves = user_dir / "save" / "autosave"
    if not autosaves.is_dir():
        return
    times = [entry.stat().st_mtime for entry in autosaves.iterdir() if entry.is_file()]
    if times and now - max(times) < AUTOSAVE_QUIET_SECONDS:
        raise Refused(
            f"The newest real OpenRCT2 autosave is {(now - max(times)) / 60:.1f} minutes old, so "
            "the game is probably running and would share the CPU. Quit it and retry once no "
            f"autosave has appeared for {AUTOSAVE_QUIET_SECONDS / 60:g} minutes. {NOTHING_WRITTEN}"
        )


def one_minute_load() -> float:
    """Return the operating system's one-minute load average."""
    return os.getloadavg()[0]


def wait_for_low_load(load: LoadAverage, clock: Clock, sleep: Sleep) -> None:
    """Wait up to 5 minutes for the one-minute load average to drop below 3.0.

    Raises:
        Refused: if it stays at or above 3.0 for the whole wait.
    """
    deadline = clock() + LOAD_WAIT_SECONDS
    while (current := load()) >= MAX_LOAD:
        if clock() >= deadline:
            raise Refused(
                f"The one-minute load average stayed at or above {MAX_LOAD:g} for "
                f"{LOAD_WAIT_SECONDS / 60:g} minutes (now {current:.2f}). {NOTHING_WRITTEN}"
            )
        say(f"The one-minute load average is {current:.2f}; checking again.")
        sleep(LOAD_POLL_SECONDS)


def config_ini(game_path: Path, autosave: int, *, debugging_tools: bool = False) -> str:
    """Return a run's ``config.ini``; the game fills in every other setting.

    ``debugging_tools`` adds one ``debugging_tools = true`` line under ``[general]``.
    """
    debugging = "debugging_tools = true\n" if debugging_tools else ""
    return (
        "[general]\n"
        f'game_path = "{game_path}"\n'
        f"autosave = {autosave}\n"
        f"{debugging}"
        "\n[network]\n"
        "pause_server_if_no_clients = false\n"
        "advertise = false\n"
    )


def save_helper(filename: str, days: int) -> str:
    """Return the save helper's plugin text, saving as ``filename`` on day callback ``days``."""
    return SAVE_HELPER.replace("__SAVE_FILENAME__", json.dumps(filename)).replace(
        "__SAVE_AFTER_DAYS__", str(days)
    )


@dataclass(frozen=True)
class RunInputs:
    """What one run's isolated folder is built from.

    Attributes:
        park: The park file to copy into ``save/`` (the fixture, or the previous session's save).
        built: The built repo plugin.
        game_path: The RollerCoaster Tycoon 2 data folder for ``config.ini``.
        autosave: OpenRCT2's autosave setting for this mode.
        helper: The save helper's text, or None when the run does not save.
        action_helper: The action workload plugin, or None for sample runs.
        debugging_tools: Whether ``config.ini`` turns on the game's debugging tools.
    """

    park: Path
    built: Path
    game_path: Path
    autosave: int
    helper: str | None = None
    debugging_tools: bool = False
    action_helper: str | None = None


def make_run_folder(folder: RunFolder, inputs: RunInputs) -> Path:
    """Create a run's isolated user-data folder and return the park copy the game loads.

    Raises:
        FileExistsError: if the run's folder already exists; a run never reuses one.
    """
    folder.root.mkdir(parents=True)
    plugin_dir = folder.user_data / "plugin"
    plugin_dir.mkdir(parents=True)
    folder.save_dir.mkdir()
    shutil.copyfile(inputs.built, plugin_dir / pi.PLUGIN_FILE_NAME)
    if inputs.helper is not None:
        (plugin_dir / SAVE_HELPER_FILE).write_text(inputs.helper, encoding="utf-8")
    if inputs.action_helper is not None:
        (plugin_dir / ACTION_HELPER_FILE).write_text(inputs.action_helper, encoding="utf-8")
    (folder.user_data / "config.ini").write_text(
        config_ini(inputs.game_path, inputs.autosave, debugging_tools=inputs.debugging_tools),
        encoding="utf-8",
    )
    park_copy = folder.save_dir / f"{PARK_COPY_STEM}{inputs.park.suffix}"
    shutil.copyfile(inputs.park, park_copy)
    return park_copy

"""Answer whether the game is running, by ``pgrep``'s exit-code contract.

A check exits 0 when the game runs, 1 when it does not, and anything else (or fails to
run) when it cannot tell. The default check is ``pgrep -x <process>`` on macOS and Linux
and a parse of ``tasklist``'s CSV output on Windows; any command that follows the same
contract can replace it.
"""

from __future__ import annotations

import csv
import platform
import subprocess
from collections.abc import Callable, Sequence
from enum import Enum

DEFAULT_PROCESS = {"Darwin": "OpenRCT2", "Linux": "openrct2", "Windows": "openrct2.exe"}
DEFAULT_OPEN_GAME = {"Darwin": ("open", "-a", "OpenRCT2")}  # make play opens the game this way
WINDOWS = "Windows"
PGREP_RUNNING, PGREP_NOT_RUNNING = 0, 1
CHECK_TIMEOUT_SECONDS = 10.0


class GameState(Enum):
    """What the game check answered."""

    RUNNING = "running"
    NOT_RUNNING = "not running"
    UNKNOWN = "cannot tell"


GameCheck = Callable[[], GameState]


def state_from_exit_code(code: int | None) -> GameState:
    """Map a process check's exit code by ``pgrep``'s contract; None means it did not run."""
    if code == PGREP_RUNNING:
        return GameState.RUNNING
    if code == PGREP_NOT_RUNNING:
        return GameState.NOT_RUNNING
    return GameState.UNKNOWN


def tasklist_state(code: int | None, output: str, image: str) -> GameState:
    """Read ``tasklist /FO CSV /NH`` output: running when a row's image name is ``image``.

    With no match, tasklist prints an ``INFO:`` line and exits 0, so only the rows decide.
    """
    if code != 0:
        return GameState.UNKNOWN
    rows = csv.reader(output.splitlines())
    if any(row and row[0].lower() == image.lower() for row in rows):
        return GameState.RUNNING
    return GameState.NOT_RUNNING


def _run_check(command: Sequence[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(  # noqa: S603  # an argument list, no shell
            command,
            stdin=subprocess.DEVNULL,  # never hand the Terminal's input to a child
            capture_output=True,
            text=True,
            timeout=CHECK_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        # A check that cannot run or hangs answers "cannot tell", which callers report.
        return None


def command_check(command: Sequence[str], tasklist_image: str | None = None) -> GameCheck:
    """Return a game check that runs ``command`` and reads its exit code like ``pgrep``'s.

    With ``tasklist_image``, the output is read as ``tasklist``'s instead.
    """

    def check() -> GameState:
        result = _run_check(command)
        if result is None or tasklist_image is None:
            return state_from_exit_code(None if result is None else result.returncode)
        return tasklist_state(result.returncode, result.stdout, tasklist_image)

    return check


def check_command(system: str, process: str) -> list[str]:
    """Return the platform's game check command: ``tasklist`` on Windows, else ``pgrep -x``."""
    if system == WINDOWS:
        return ["tasklist", "/FI", f"IMAGENAME eq {process}", "/FO", "CSV", "/NH"]
    return ["pgrep", "-x", process]


def default_check(system: str, process: str) -> GameCheck:
    """Return the platform's game check; ``tasklist``'s output is read, not its exit code."""
    image = process if system == WINDOWS else None
    return command_check(check_command(system, process), tasklist_image=image)


def _cannot_tell() -> GameState:
    return GameState.UNKNOWN


def platform_game_check() -> GameCheck:
    """Return this platform's game check; a platform with no known process name cannot tell."""
    system = platform.system()
    process = DEFAULT_PROCESS.get(system)
    return _cannot_tell if process is None else default_check(system, process)

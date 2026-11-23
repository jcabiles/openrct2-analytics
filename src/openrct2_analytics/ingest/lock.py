"""The landing lock and the signal handling every long-running ingest command shares.

``hold_lock`` is the one lock helper the converter and the publisher use: a file created
exclusively, removed when the block ends however it ends. ``Interrupted`` and the handler
installer turn Ctrl-C, a closed Terminal (SIGHUP) and SIGTERM into an exception, so every
``finally`` runs and no lock outlives the command.
"""

from __future__ import annotations

import os
import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import FrameType

SIGNAL_NAMES = ("SIGINT", "SIGHUP", "SIGTERM")  # Windows has no SIGHUP

SignalHandler = Callable[[int, FrameType | None], None] | signal.Handlers


class LockTaken(Exception):
    """Raised when the lock file already exists.

    Attributes:
        path: The lock file.
        line: The line found in it (the holder's process ID and start time).
    """

    def __init__(self, path: Path, line: str) -> None:
        super().__init__(f"{path} is held ({line!r})")
        self.path = path
        self.line = line


class Interrupted(Exception):
    """Raised by the signal handler on Ctrl-C, a closed Terminal (SIGHUP) or SIGTERM."""


def set_signal_handlers(handler: SignalHandler) -> None:
    """Install ``handler`` for SIGINT, SIGHUP and SIGTERM (SIGHUP where the platform has it)."""
    for name in SIGNAL_NAMES:
        number = getattr(signal, name, None)
        if number is not None:
            signal.signal(number, handler)


def raise_interrupted(signum: int, frame: FrameType | None) -> None:
    """Signal handler: raise ``Interrupted`` once, ignoring any repeat of the signal."""
    # `uv run` forwards SIGHUP and SIGTERM, so a closed Terminal delivers the signal twice.
    set_signal_handlers(signal.SIG_IGN)
    raise Interrupted(signal.Signals(signum).name)


def _cleanup(step: Callable[[], object], failure: BaseException | None) -> None:
    """Run a cleanup step; its error replaces nothing, so it becomes a note on ``failure``."""
    try:
        step()
    except OSError as error:
        if failure is None:
            raise
        failure.add_note(f"lock cleanup also failed: {error}")


@contextmanager
def hold_lock(path: Path, line: str) -> Iterator[None]:
    """Hold the lock file ``path``, holding ``line``, for the length of the block.

    The file is created with ``O_CREAT | O_EXCL``, so two holders never both succeed. It is
    removed however the block ends, even when writing the line fails.

    Args:
        path: The lock file; its folder must exist.
        line: The text written to it, for whoever finds the lock taken.

    Raises:
        LockTaken: if ``path`` already exists, carrying the line found in it.
    """
    failure: BaseException | None = None
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as exc:
        try:
            holder = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            # Another process can remove the lock after creation fails but before this read.
            holder = ""
        raise LockTaken(path, holder) from exc
    try:
        try:
            os.write(descriptor, f"{line}\n".encode())
            yield
        except BaseException as error:
            failure = error
            raise
        finally:
            _cleanup(lambda: os.close(descriptor), failure)
    finally:
        _cleanup(lambda: path.unlink(missing_ok=True), failure)

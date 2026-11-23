"""Landing step of ``site_company``: re-check the published file, rename the staged folders in.

The command stages its exports and its built site in one folder under ``local/``. Landing only
renames folders: an existing target is renamed into the stage folder, the staged folder is
renamed onto the target, and the old folders are then removed. A file is never written into an
existing output folder, so a link inside one is never followed.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import signal
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

from openrct2_analytics.ingest import lock

BUILD_STAMP = ".site-company-build"
STAMP_LINE = "built from warehouse/company.duckdb by make site-company"
_HASH_PREFIX = "index.html sha256 "
PUBLISHED = Path("warehouse") / "company.duckdb"
LOCK = Path("warehouse") / "company.lock"
EXPORTS_STAGE = "site-data"
SITE_STAGE = "site"
# Temporary folders the command makes under ``local/``; ``delete_data`` removes a killed run's.
STAGE_PREFIX = ".site-company-stage-"
INPUT_PREFIX = ".site-company-input-"


class LandRefused(Exception):
    """The run must not land: ``site_company`` maps it to exit 2."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class LandStuck(Exception):
    """A landing rename failed and a restoring rename failed too: the stage must be kept."""

    def __init__(self, stage: Path, detail: str) -> None:
        super().__init__(detail)
        self.stage = stage
        self.detail = detail


@dataclass(frozen=True)
class PublishedStamp:
    """Identity of the published file when the run started: inode and modified time."""

    inode: int
    mtime_ns: int


def snapshot(project_dir: Path) -> PublishedStamp:
    """Record the published file's inode and modified time."""
    info = os.stat(project_dir / PUBLISHED)
    return PublishedStamp(info.st_ino, info.st_mtime_ns)


def recheck(project_dir: Path, start: PublishedStamp) -> None:
    """Refuse when a lock exists or the published file is not the one the run started with."""
    changed = LandRefused(
        "published-file",
        f"{PUBLISHED.as_posix()} changed during the run; run the command again",
    )
    if (project_dir / LOCK).exists():
        raise changed
    try:
        now = snapshot(project_dir)
    except FileNotFoundError as error:
        raise changed from error
    if now != start:
        raise changed


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_stamp(site_dir: Path) -> None:
    """Write the build stamp into a staged site: the source line and the page's SHA-256."""
    lines = [STAMP_LINE, f"{_HASH_PREFIX}{_sha256(site_dir / 'index.html')}"]
    (site_dir / BUILD_STAMP).write_text("\n".join(lines) + "\n")


def is_company_build(path: Path) -> bool:
    """Return whether ``path`` is a real folder whose stamp still matches its ``index.html``."""
    if path.is_symlink() or not path.is_dir():
        return False
    stamp, page = path / BUILD_STAMP, path / "index.html"
    if not stamp.is_file() or not page.is_file():
        return False
    lines = stamp.read_text().splitlines()
    return lines == [STAMP_LINE, f"{_HASH_PREFIX}{_sha256(page)}"]


def _put_back(
    landed: list[tuple[Path, Path]], parked: list[tuple[Path, Path]], stage: Path
) -> None:
    """Undo the renames made so far; stop at the first failure and raise ``LandStuck``."""
    try:
        for target, staged in reversed(landed):
            os.replace(target, staged)
        for old, target in reversed(parked):
            os.replace(old, target)
    except OSError as error:
        raise LandStuck(
            stage, f"a rename that puts the earlier outputs back failed ({error})"
        ) from error


def _swap(moves: tuple[tuple[Path, Path], ...], stage: Path) -> None:
    """Rename each old target into the stage and each staged folder onto its target.

    When a rename fails, every folder moved so far goes back, so the two targets stay a pair.
    """
    parked: list[tuple[Path, Path]] = []
    landed: list[tuple[Path, Path]] = []
    try:
        for staged, target in moves:
            if target.exists() or target.is_symlink():
                old = stage / f"old-{staged.name}"
                os.replace(target, old)
                parked.append((old, target))
            os.replace(staged, target)
            landed.append((target, staged))
    except OSError:
        _put_back(landed, parked, stage)
        raise


def land(project_dir: Path, stage: Path, start: PublishedStamp) -> None:
    """Re-check the published file, then rename the staged folders onto the output folders.

    Termination signals are recorded, not acted on, until the renames and the removal of the old
    folders end (a handler, because a blocked signal mask does not stop another thread from
    taking the signal). A signal recorded during the landing does not change the exit code once
    it completes (exit 0); the handlers are then restored, so a later signal ends the command with
    exit 130.

    Raises:
        LandRefused: A lock exists or the published file changed; nothing was landed.
        LandStuck: A rename failed and putting the earlier outputs back failed too; the stage
            folder still holds them and must be kept.
        OSError: A rename failed; the folders moved so far were put back.
        lock.Interrupted: A signal arrived and the landing failed and was put back.
    """
    recheck(project_dir, start)
    moves = (
        (stage / EXPORTS_STAGE, project_dir / "local" / "site-data"),
        (stage / SITE_STAGE, project_dir / "site" / "_site"),
    )
    received: list[int] = []

    def record(signum: int, _frame: FrameType | None) -> None:
        received.append(signum)

    numbers = [getattr(signal, name) for name in lock.SIGNAL_NAMES if hasattr(signal, name)]
    previous = {number: signal.getsignal(number) for number in numbers}
    for number in numbers:
        signal.signal(number, record)
    try:
        try:
            _swap(moves, stage)
        except OSError as error:
            if received:
                raise lock.Interrupted(signal.Signals(received[0]).name) from error
            raise
        for old in stage.glob("old-*"):
            shutil.rmtree(old)
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)

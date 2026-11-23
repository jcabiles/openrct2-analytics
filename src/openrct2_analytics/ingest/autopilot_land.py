"""Land a checked autopilot capture into company data, under the company landing lock.

``land`` appends one session in a fixed order: the play-mode label delivery, then the work
folder's save-file records, then one raw file joining the work folder's raw files. A raw session
never lands without its label; a label or record file may land without its session when a later
step fails. Each file is written into an ``.incoming-`` folder inside its target folder and
placed with a hard link, which fails when the name exists, so no landed file is ever replaced.
Signals are ignored from the first link and stay ignored when ``land`` returns or raises, so the
caller can keep them ignored to the end of its report.

The work folder holds ``raw/v1/events-*.jsonl`` and ``save_files/v1/save_file_observation_*.jsonl``
(the listener's and the save watcher's own names). Nothing is written outside the three landing
folders under ``data_root`` apart from the lock file beside its Parquet folder.
"""

from __future__ import annotations

import csv
import functools
import io
import os
import shutil
import signal
import time
from collections.abc import Callable
from contextlib import ExitStack
from datetime import date
from pathlib import Path

from openrct2_analytics.ingest import lock, play_mode_feed
from openrct2_analytics.ingest.contracts import LANDING_FOLDER
from openrct2_analytics.ingest.convert import landing_lock_path
from openrct2_analytics.ingest.registry_feed import INCOMING
from openrct2_analytics.ingest.save_pairing import RECORD_FILE_GLOB, RECORD_FILE_SUFFIX

DATA_SET = "company"
RAW_GLOB = "events-*.jsonl"
LOCK_RETRY_S = 1.0


class LandingLockHeld(Exception):
    """The landing lock stayed taken for the whole wait; nothing landed.

    Attributes:
        holder_line: The line in the lock file (the holder's process ID and start time).
    """

    def __init__(self, holder_line: str) -> None:
        super().__init__(f"the landing lock is held ({holder_line!r})")
        self.holder_line = holder_line


class StagedLabelFailed(Exception):
    """The staged label delivery failed the play-mode feed check; nothing landed.

    Attributes:
        problems: One line per problem the checker found.
    """

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class LandingStepFailed(Exception):
    """A landing step failed; the files of the earlier steps stay landed.

    Signals may be left ignored even when ``landed`` is empty: they are set to ignored just
    before the label link, so a failed label link raises with them ignored. The caller restores
    its signal handlers on every exit.

    Attributes:
        step: ``label``, ``records`` or ``raw``.
        landed: The files already landed, in landing order.
        cause: The error that stopped the step.
    """

    def __init__(self, step: str, landed: list[Path], cause: BaseException) -> None:
        super().__init__(f"landing failed at {step}: {cause}")
        self.step = step
        self.landed = landed
        self.cause = cause


def _local_today() -> date:
    """The local date that names and dates the label delivery (a seam for tests)."""
    return date.today()


def _label_text(session_id: str, park_id: str, ready_confirmation: str, today: date) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(play_mode_feed.HEADER)
    writer.writerow(
        (
            session_id,
            park_id,
            play_mode_feed.AUTOPILOT,
            ready_confirmation,
            DATA_SET,
            today.isoformat(),
        )
    )
    return buffer.getvalue()


def _label_name(feed: Path, today: date) -> str:
    """The next free delivery name of ``today``, numbered as ``register_parks`` numbers them."""
    for number in range(1, 100):
        name = f"session_play_mode_{today.isoformat()}_{number:02}.csv"
        if not (feed / name).exists():
            return name
    raise FileExistsError(f"All 99 label delivery names for {today} are used in {feed}")


def _land_file(folder: Path, name: str, write: Callable[[Path], None]) -> Path:
    """Write ``folder/.incoming-<name>/<name>`` with ``write``, then hard-link it to ``name``.

    The link fails when ``folder/name`` exists, so a landed file is never replaced. The
    ``.incoming-`` folder is removed however the step ends.
    """
    incoming = folder / f"{INCOMING}{name}"
    incoming.mkdir()
    try:
        write(incoming / name)
        os.link(incoming / name, folder / name)
    finally:
        shutil.rmtree(incoming)
    return folder / name


def _join_raw(parts: list[Path], staged: Path) -> None:
    """Write ``parts`` end to end into ``staged``; a part not ending in a newline is refused."""
    with staged.open("wb") as joined:
        for source in parts:
            with source.open("rb") as part:
                shutil.copyfileobj(part, joined)
                if part.tell() > 0:
                    part.seek(-1, os.SEEK_END)
                    if part.read(1) != b"\n":  # joining it would merge two events into one line
                        raise OSError(f"{source} does not end in a newline")


def _refuse_leftovers(targets: list[Path]) -> None:
    """Raise ``FileExistsError`` naming the first ``.incoming-<target>`` entry present."""
    for target in targets:
        leftover = target.parent / f"{INCOMING}{target.name}"
        if os.path.lexists(leftover):
            raise FileExistsError(f"{leftover} is left from an earlier landing")


def _refuse_taken(targets: list[Path]) -> None:
    """Raise ``FileExistsError`` naming the first target name present.

    ``lexists`` also counts a link whose target is gone, since a hard link to its name fails.
    """
    for target in targets:
        if os.path.lexists(target):
            raise FileExistsError(f"{target} already exists; a landed file is never replaced")


def _hold(stack: ExitStack, path: Path, wait_s: float) -> None:
    """Take the lock ``path``, retrying every second for up to ``wait_s`` seconds."""
    deadline = time.monotonic() + wait_s
    line = f"pid {os.getpid()} started {time.strftime('%Y-%m-%dT%H:%M:%S%z')}"
    while True:
        try:
            stack.enter_context(lock.hold_lock(path, line))
            return
        except lock.LockTaken as taken:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LandingLockHeld(taken.line) from taken
            time.sleep(min(LOCK_RETRY_S, remaining))


def land(  # noqa: PLR0913  # the inputs are fixed by the autopilot-year spec and its review
    work_dir: Path,
    *,
    park_id: str,
    session_id: str,
    ready_confirmation: str,
    data_root: Path,
    guard: Callable[[], None],
    lock_wait_s: float = 120.0,
) -> list[Path]:
    """Append the checked capture in ``work_dir`` to the company data under ``data_root``.

    Args:
        work_dir: The run's work folder (``raw/v1/`` and ``save_files/v1/`` inside).
        park_id: The park the session played.
        session_id: The session to land.
        ready_confirmation: Empty, or the park's ready phrase on its first autopilot run.
        data_root: The company data folder (``data/company``).
        guard: Raises when a landing folder is unsafe to write through (for example a link);
            called once the lock is held, before anything is created.
        lock_wait_s: How long to wait for the landing lock.

    Returns:
        The landed files in landing order: the label delivery, the record files, the raw file.
        Signals are still ignored.

    Raises:
        LandingLockHeld: the lock stayed taken; nothing landed.
        StagedLabelFailed: the staged label failed its check; nothing landed.
        LandingStepFailed: a step failed; ``landed`` lists what the earlier steps placed. A
            target name or ``.incoming-`` entry that already exists fails ``label`` before any
            link, so nothing lands.
        Exception: whatever ``guard`` raises, unchanged; nothing landed.
    """
    raw_files = sorted((work_dir / "raw" / LANDING_FOLDER).glob(RAW_GLOB), key=lambda p: p.name)
    if not raw_files:
        raise FileNotFoundError(f"No {RAW_GLOB} file in {work_dir / 'raw' / LANDING_FOLDER}")
    record_files = sorted(
        (work_dir / "save_files" / LANDING_FOLDER).glob(RECORD_FILE_GLOB), key=lambda p: p.name
    )
    feed = data_root / "registry" / LANDING_FOLDER
    records = data_root / "save_files" / LANDING_FOLDER
    raw = data_root / "raw" / LANDING_FOLDER
    suffix = f"-{play_mode_feed.AUTOPILOT}-{session_id}"
    # events-<UTC date of the first file>-autopilot-<session id>.jsonl
    raw_name = f"{raw_files[0].name[: len('events-YYYY-MM-DD')]}{suffix}.jsonl"
    today = _local_today()
    with ExitStack() as stack:
        _hold(stack, landing_lock_path(data_root / "parquet"), lock_wait_s)
        guard()  # under the lock: a link made during the run or the lock wait is caught too
        text = _label_text(session_id, park_id, ready_confirmation, today)

        def write_label(staged: Path) -> None:
            staged.write_text(text, encoding="utf-8")
            problems = play_mode_feed.check_feed(feed.parent, staged=[staged], data_set=DATA_SET)
            if problems:
                raise StagedLabelFailed(problems)
            # After the checker, so a session landed before is reported as such.
            _refuse_taken(targets)
            # From the first link on, an interrupt would only cut the landing short.
            lock.set_signal_handlers(signal.SIG_IGN)

        landed: list[Path] = []
        step = "label"
        try:
            for folder in (feed, records, raw):
                folder.mkdir(parents=True, exist_ok=True)
            label = feed / _label_name(feed, today)
            record_targets = [
                (records / f"{source.name.removesuffix(RECORD_FILE_SUFFIX)}{suffix}.jsonl", source)
                for source in record_files
            ]
            # The checker already refuses a taken label name, so only the leftover is checked.
            targets = [*(target for target, _ in record_targets), raw / raw_name]
            _refuse_leftovers([label, *targets])
            landed.append(_land_file(feed, label.name, write_label))
            step = "records"
            for target, source in record_targets:
                copy = functools.partial(shutil.copyfile, source)
                landed.append(_land_file(records, target.name, copy))
            step = "raw"
            landed.append(_land_file(raw, raw_name, functools.partial(_join_raw, raw_files)))
        except OSError as error:
            raise LandingStepFailed(step, list(landed), error) from error
    return landed

"""Prove a captured two-park chain in the work folder, then land it into ``data/rehearsal/``.

This is the only module that writes into ``data/rehearsal/``. The capture command
(``rehearsal_capture``) is its one caller and calls it once, after the ninth valid session::

    land(attempts: Sequence[Attempt], *, combined: Path, converted: Path,
         guard: Callable[[], None], hook: Hook = no_hook) -> int

``attempts`` holds the nine accepted attempts, one per schedule step (1 to 9), each naming its
park as ``SCHEDULE`` fixes it and its raw folder; list order does not matter. ``combined`` and
``converted`` are two of the command's reserved work-folder names; neither may exist yet.
``guard`` is the write-boundary check (``rehearsal_capture.check_write_boundary``); it is called
under the landing lock and raises ``Refused`` when a landing folder now resolves into a folder that
must not be written. ``hook`` is a test seam called with a stage name at fixed points of the
landing. The result is an exit code: 0 landed, 1 a proof, landing or write-boundary problem
(nothing landed), 130 interrupted. The caller installs ``set_signal_handlers(raise_interrupted)``
before calling, so a signal raises ``Interrupted``.

The proof: ``combine_raw`` copies the raw folders into ``combined`` in step order; ``convert``
writes Parquet and the ``seq`` audit into ``converted``; then every check below must pass, read
from the converted Parquet. Each attempt holds one ``session_id`` and one ``session_start``; the
nine attempts hold nine distinct ``session_id`` values; the chain holds exactly two ``park_id``
values, one shared by every Park 1 step and the other by every Park 2 step. The calendar takes
each attempt's step and park from the caller, never from file order or ``emitted_at``: a park's
origin Y0 is the ``game_year`` of its first step's ``session_start``; its k-th step must start in
Y0 + k - 1 and its last event (highest ``seq``) must fall in Y0 + k. No event of a park may fall
before its origin, and each of the four guest event types needs at least one row.

The landing, under the landing lock of ``data/rehearsal/parquet``: run ``guard``, then re-check
that ``raw/`` and ``registry/v1/`` are empty; copy the raw files into ``raw/.incoming-v1/``;
write the registry delivery, built in memory, as ``.incoming-<name>`` in ``registry/v1/`` and check
it with ``registry_feed.check_file``; then rename the raw folder to ``raw/v1/`` and, straight
after, the delivery into place. SIGINT, SIGHUP and SIGTERM are only recorded during the two
renames and raise ``Interrupted`` once both are done. A failure or signal before the first
rename succeeds removes the ``.incoming-`` entries this run created. A failure of the second
rename leaves a half landing (raw landed, delivery still ``.incoming-``): nothing is removed, and
the next run refuses it with the half-landed text.
"""

from __future__ import annotations

import csv
import io
import os
import shutil
import signal
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from types import FrameType

import duckdb

from openrct2_analytics.config import landing_dirs
from openrct2_analytics.ingest.bench_sample import combine_raw
from openrct2_analytics.ingest.capture import Refused
from openrct2_analytics.ingest.capture_session import (
    EXIT_INTERRUPTED,
    EXIT_OK,
    EXIT_PROBLEM,
    say,
)
from openrct2_analytics.ingest.contracts import LANDING_FOLDER
from openrct2_analytics.ingest.convert import (
    ConvertResult,
    NoInputError,
    convert,
    landing_lock_path,
)
from openrct2_analytics.ingest.lock import (
    SIGNAL_NAMES,
    Interrupted,
    LockTaken,
    hold_lock,
    set_signal_handlers,
)
from openrct2_analytics.ingest.registry_feed import HEADER, INCOMING, check_file, registry_dir

DATA_SET = "rehearsal"
STEPS = 9
PARK_COUNT = 2
# The registry values the project owner set (ruling 1, Q8): Park 1 starts in 2000, Park 2 in 2003.
COMPANY_START_YEARS = {1: 2000, 2: 2003}
# The fixed schedule (spec R7): step -> park. Park 2 joins at step 4 and plays steps 4, 6 and 8.
SCHEDULE = {1: 1, 2: 1, 3: 1, 4: 2, 5: 1, 6: 2, 7: 1, 8: 2, 9: 1}
NOTE = "Rehearsal values; not company data."
GUEST_TYPES = ("guest_arrived", "guest_boarded", "guest_left", "guest_snapshot")
RECOVERY = (
    "If an earlier run stopped between its two renames, the data set is half landed; "
    "move data/rehearsal/ aside by hand and capture again."
)

Hook = Callable[[str], None]


def no_hook(stage: str) -> None:
    """The default hook: does nothing at any stage."""


@dataclass(frozen=True)
class Attempt:
    """One accepted attempt, as the chain played it.

    Attributes:
        step: Its schedule step, 1 to 9.
        park: The park the schedule plays at that step, 1 or 2 (``SCHEDULE``).
        raw: Its raw folder, laid out as the listener writes it (``v1/events-*.jsonl``).
    """

    step: int
    park: int
    raw: Path


@dataclass(frozen=True)
class StepFacts:
    """What the converted Parquet says about one attempt."""

    sessions: list[str]
    starts: int
    parks: list[str]
    start_year: int | None
    end_year: int
    first_year: int


class LandingFailed(Exception):
    """Raised when the proof or the landing fails; nothing was landed.

    Attributes:
        lines: One line per problem, for the operator.
    """

    def __init__(self, lines: list[str]) -> None:
        super().__init__("; ".join(lines))
        self.lines = lines


def land(
    attempts: Sequence[Attempt],
    *,
    combined: Path,
    converted: Path,
    guard: Callable[[], None],
    hook: Hook = no_hook,
) -> int:
    """Prove the nine attempts in the work folder and land them; return the exit code.

    Args:
        attempts: The nine accepted attempts, one per step.
        combined: Work-folder folder for the combined raw files; must not exist.
        converted: Work-folder folder for the Parquet and the ``seq`` audit.
        guard: The write-boundary check, run under the landing lock.
        hook: Test seam, called with ``"locked"``, ``"copying"`` (after each raw file),
            ``"delivery-written"``, ``"checked"`` and ``"between-renames"``.

    Returns:
        0 landed, 1 a proof or landing problem with nothing landed, 130 interrupted.

    Raises:
        ValueError: if ``attempts`` is not one attempt per step 1 to 9, each with the park
            ``SCHEDULE`` fixes for its step.
    """
    if (
        sorted(a.step for a in attempts) != list(range(1, STEPS + 1))
        or {a.step: a.park for a in attempts} != SCHEDULE
    ):
        raise ValueError("land needs one attempt per step 1 to 9, each with its scheduled park")
    try:
        origins = prove(attempts, combined, converted)
        name, text = render_delivery(origins, datetime.now(UTC).date())
        landed = _land_locked(combined, name, text, guard=guard, hook=hook)
    except LandingFailed as failure:
        for line in failure.lines:
            say(line)
        say("Nothing was landed.")
        return EXIT_PROBLEM
    except (
        Refused
    ) as refusal:  # the guard, under the lock; the capture already sits in the work folder
        say(str(refusal))
        return EXIT_PROBLEM
    except LockTaken as taken:
        say(
            f"Another conversion or publish holds {taken.path.name} ({taken.line}). "
            "Nothing was landed."
        )
        return EXIT_PROBLEM
    except Interrupted:
        say("Interrupted.")
        return EXIT_INTERRUPTED
    for park, (park_id, origin) in sorted(origins.items()):
        say(
            f"Park {park}: {park_id}, company start year {COMPANY_START_YEARS[park]}, "
            f"game year origin {origin}."
        )
    for path in landed:
        say(f"Landed {path}.")
    return EXIT_OK


def prove(
    attempts: Sequence[Attempt], combined: Path, converted: Path
) -> dict[int, tuple[str, int]]:
    """Combine and convert the attempts in the work folder and run every proof check.

    Returns:
        Each park's ``park_id`` and game year origin, by park number.

    Raises:
        LandingFailed: when any check fails.
    """
    ordered = sorted(attempts, key=lambda a: a.step)
    # combine_raw numbers each attempt's files by position, which is its step.
    combine_raw([a.raw for a in ordered], combined)
    try:
        result = convert(combined, converted)
    except NoInputError as error:
        raise LandingFailed(["The converter found no event in the nine attempts."]) from error
    _raise_if(_conversion_problems(result))
    facts = _step_facts(converted)
    parks = {a.step: a.park for a in attempts}
    _raise_if(_attempt_problems(facts))
    _raise_if(_park_problems(facts, parks))
    origins = {
        park: (facts[first].parks[0], _start(facts[first]))
        for park, first in _first_steps(parks).items()
    }
    _raise_if(_calendar_problems(facts, parks, origins))
    return origins


def _raise_if(problems: list[str]) -> None:
    if problems:
        raise LandingFailed(problems)


def _conversion_problems(result: ConvertResult) -> list[str]:
    problems = [f"Schema error: {line}" for line in result.schema_errors]
    problems += [f"seq audit: {line}" for line in result.seq_violations]
    if result.malformed_lines:
        problems.append(f"{result.malformed_lines} malformed line(s) in the attempts.")
    problems += [
        f"No {name} row; a capture must hold every guest event type."
        for name in GUEST_TYPES
        if not result.row_counts.get(name)
    ]
    return problems


STEP_FACTS_SQL = """
WITH events AS (
    SELECT park_id, session_id, seq, game_year,
           CAST(regexp_extract(_raw_file, '-session-([0-9]+)\\.jsonl$', 1) AS INTEGER) AS step,
           regexp_extract(filename, '([^/]+)\\.parquet$', 1) AS event_type
    FROM read_parquet('{pattern}', union_by_name = true, filename = true)
)
SELECT step,
       list(DISTINCT session_id ORDER BY session_id),
       count(*) FILTER (WHERE event_type = 'session_start'),
       list(DISTINCT park_id ORDER BY park_id),
       min(game_year) FILTER (WHERE event_type = 'session_start'),
       arg_max(game_year, seq),
       min(game_year)
FROM events GROUP BY step ORDER BY step
"""


def _step_facts(converted: Path) -> dict[int, StepFacts]:
    pattern = (converted / LANDING_FOLDER / "*.parquet").as_posix().replace("'", "''")
    connection = duckdb.connect(":memory:")
    try:
        rows = connection.execute(STEP_FACTS_SQL.format(pattern=pattern)).fetchall()
    finally:
        connection.close()
    return {int(row[0]): StepFacts(*row[1:]) for row in rows}


def _attempt_problems(facts: dict[int, StepFacts]) -> list[str]:
    problems: list[str] = []
    for step in range(1, STEPS + 1):
        found = facts.get(step)
        if found is None:
            problems.append(f"Step {step} holds no event.")
            continue
        if len(found.sessions) != 1:
            problems.append(f"Step {step} holds {len(found.sessions)} session_id values, not 1.")
        if found.starts != 1:
            problems.append(f"Step {step} holds {found.starts} session_start rows, not 1.")
    if not problems:
        distinct = {found.sessions[0] for found in facts.values()}
        if len(distinct) != STEPS:
            problems.append(f"The nine steps hold {len(distinct)} distinct session_id values.")
    return problems


def _park_problems(facts: dict[int, StepFacts], parks: dict[int, int]) -> list[str]:
    every = {park_id for found in facts.values() for park_id in found.parks}
    if len(every) != PARK_COUNT:
        return [f"The chain holds {len(every)} park_id values, not {PARK_COUNT}."]
    problems: list[str] = []
    for park in sorted(COMPANY_START_YEARS):
        ids = {park_id for step, p in parks.items() if p == park for park_id in facts[step].parks}
        if len(ids) != 1:
            steps = sorted(step for step, p in parks.items() if p == park)
            problems.append(f"The Park {park} steps {steps} do not share one park_id.")
    return problems


def _first_steps(parks: dict[int, int]) -> dict[int, int]:
    return {park: min(s for s, p in parks.items() if p == park) for park in set(parks.values())}


def _start(found: StepFacts) -> int:
    # _attempt_problems has passed, so every step holds exactly one session_start.
    assert found.start_year is not None
    return found.start_year


def _calendar_problems(
    facts: dict[int, StepFacts], parks: dict[int, int], origins: dict[int, tuple[str, int]]
) -> list[str]:
    problems: list[str] = []
    for park, (_, origin) in sorted(origins.items()):
        steps = sorted(step for step, p in parks.items() if p == park)
        for k, step in enumerate(steps, start=1):
            found = facts[step]
            planned = origin + k - 1
            if (_start(found), found.end_year) != (planned, planned + 1):
                problems.append(
                    f"Step {step} (Park {park}, session {k}) plays game years {_start(found)} to"
                    f" {found.end_year}; the plan is {planned} to {planned + 1}."
                )
            if found.first_year < origin:
                problems.append(
                    f"Step {step} has an event in game year {found.first_year}, before Park "
                    f"{park}'s origin {origin}."
                )
    return problems


def render_delivery(origins: dict[int, tuple[str, int]], delivered_on: date) -> tuple[str, str]:
    """Build the registry delivery in memory: its file name and its CSV text.

    Args:
        origins: Each park's ``park_id`` and game year origin, by park number.
        delivered_on: The UTC date of the delivery; it names the file.

    Returns:
        ``park_registry_<date>_01.csv`` and the CSV text, Park 1's row before Park 2's.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(HEADER)
    for park, (park_id, origin) in sorted(origins.items()):
        writer.writerow(
            (park_id, COMPANY_START_YEARS[park], origin, DATA_SET, NOTE, delivered_on.isoformat())
        )
    return f"park_registry_{delivered_on.isoformat()}_01.csv", buffer.getvalue()


def _land_locked(
    combined: Path, name: str, text: str, *, guard: Callable[[], None], hook: Hook
) -> list[str]:
    """Land the combined raw files and the delivery under the landing lock (R9 order)."""
    guard()  # first: nothing, not even the lock file's folder, is created through a new link
    folders = landing_dirs(DATA_SET)
    feed = registry_dir(DATA_SET) / LANDING_FOLDER
    folders.parquet.parent.mkdir(parents=True, exist_ok=True)  # the lock file's folder
    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with hold_lock(landing_lock_path(folders.parquet), f"pid {os.getpid()} started {started}"):
        hook("locked")
        guard()  # again under the lock: a link made while waiting for it is caught too
        folders.raw.mkdir(parents=True, exist_ok=True)
        feed.mkdir(parents=True, exist_ok=True)
        _check_empty(folders.raw, feed)
        incoming_raw = folders.raw / f"{INCOMING}{LANDING_FOLDER}"
        incoming_csv = feed / f"{INCOMING}{name}"
        files = _stage_and_rename(
            combined,
            (incoming_raw, folders.raw / LANDING_FOLDER),
            (incoming_csv, feed / name),
            text=text,
            hook=hook,
        )
    raw = [f"{DATA_SET}/raw/{LANDING_FOLDER}/{file}" for file in files]
    return [*raw, f"{DATA_SET}/registry/{LANDING_FOLDER}/{name}"]


def _check_empty(raw: Path, feed: Path) -> None:
    for folder, shown in ((raw, "raw/"), (feed, f"registry/{LANDING_FOLDER}/")):
        if any(folder.iterdir()):
            raise LandingFailed(
                [f"data/{DATA_SET}/{shown} is not empty; a rehearsal data set holds one chain."]
                + [RECOVERY]
            )


@contextmanager
def _deferred_signals() -> Iterator[list[int]]:
    """Record SIGINT, SIGHUP and SIGTERM instead of raising; restore the old handlers on exit."""
    received: list[int] = []

    def record(signum: int, frame: FrameType | None) -> None:
        received.append(signum)

    numbers = [getattr(signal, n) for n in SIGNAL_NAMES if hasattr(signal, n)]
    previous = {number: signal.getsignal(number) for number in numbers}
    try:
        set_signal_handlers(record)
        yield received
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def _stage_and_rename(
    combined: Path,
    raw: tuple[Path, Path],
    delivery: tuple[Path, Path],
    *,
    text: str,
    hook: Hook,
) -> list[str]:
    """Stage the raw files and the delivery under ``.incoming-`` names, then rename both.

    Any failure or signal before the first rename removes the ``.incoming-`` entries this call
    created; the recording handlers are installed before that cleanup stops, so no signal can
    fall between the two. A signal during the renames is raised once both are done.
    """
    incoming_raw, incoming_csv = raw[0], delivery[0]
    files = sorted((combined / LANDING_FOLDER).glob("events-*.jsonl"))
    created: list[Path] = []
    renaming = False
    received: list[int] = []
    try:
        incoming_raw.mkdir()
        created.append(incoming_raw)
        for path in files:
            shutil.copyfile(path, incoming_raw / path.name)
            hook("copying")
        created.append(incoming_csv)
        incoming_csv.write_text(text, encoding="utf-8")
        hook("delivery-written")
        problems = check_file(incoming_csv)
        if problems:
            raise LandingFailed([f"The registry delivery fails its check: {p}" for p in problems])
        hook("checked")
        with _deferred_signals() as received:
            raw[0].rename(raw[1])
            renaming = True  # the raw folder landed: the delivery rename is the half landing's
            hook("between-renames")
            delivery[0].rename(delivery[1])
    finally:
        if not renaming:
            for entry in created:
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink(missing_ok=True)
    if received:
        say("A signal arrived during the two renames; both finished, so the capture is landed.")
        # The old handlers are back: this disarms them and raises Interrupted, as a new signal would
        signal.raise_signal(received[0])
    return [path.name for path in files]

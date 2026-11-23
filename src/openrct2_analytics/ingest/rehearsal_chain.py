"""The rehearsal capture's nine-session chain across two parks (spec R4, R5, D7).

``rehearsal_capture`` refuses or prepares the invocation, then calls ``run_chain`` once. Each
step loads a copy of its park's input: step 1 the fixture, step 4 the Park 2 source, every other
step the save its park's previous step wrote (the file is copied, never moved). Each attempt
runs in its own reserved work-folder folder with autosave off, the built plugin, the speed
helper (``rehearsal_helper``) and the game's debugging tools on, and stops once its save has
landed (``SaveLanded``) or its timeout passes.

An attempt is valid only when ``play`` reported no problem; the fixture's and the Park 2
source's SHA-1 still equal the ones checked before the chain, and the attempt's input save
still has the SHA-1 it had before the attempt; its raw files hold exactly one
``session_start`` and one distinct ``session_id``; and every ``plugin_stats`` row with
``warmup`` false reports ``game_speed`` 8. An invalid attempt is repeated once from a fresh copy
of the same input; a second invalid attempt stops the chain.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from openrct2_analytics.ingest.bench_judge import FIXTURE_CHANGED
from openrct2_analytics.ingest.bench_play import Bench, play
from openrct2_analytics.ingest.bench_sample import SAVE_SUFFIX, SaveLanded
from openrct2_analytics.ingest.bench_setup import (
    AUTOSAVE_NEVER,
    RunFolder,
    RunInputs,
    file_sha1,
    make_run_folder,
)
from openrct2_analytics.ingest.capture import say
from openrct2_analytics.ingest.contracts import LANDING_FOLDER
from openrct2_analytics.ingest.rehearsal_helper import rehearsal_helper
from openrct2_analytics.ingest.rehearsal_land import SCHEDULE, STEPS, Attempt

MAX_ATTEMPTS = 2  # D7: an invalid attempt is repeated once
FIRST_STEP_DAYS = 240  # planned game days, used only for the timeout (R4)
LATER_STEP_DAYS = 245
SECONDS_PER_DAY = 3.0  # R5's timeout: 3.0 s per planned day plus 300 s
STARTUP_SECONDS = 300.0
SESSION_SPEED = 8
RAW_KEYS = ("event_type", "session_id", "seq")  # the keys raw_problems indexes
COMBINED = "rehearsal-raw"
CONVERTED = "rehearsal-parquet"
PARK2_CHANGED = "Park 2 source changed during the run"
INPUT_CHANGED = "input save changed during the run"


@dataclass(frozen=True)
class Step:
    """One step of the schedule (R4).

    Attributes:
        number: The step, 1 to 9.
        park: The park it plays, 1 or 2.
        label: The session's name, for example ``P2-1`` (Park 2's first session).
        days: The planned game days, used only for the timeout.
    """

    number: int
    park: int
    label: str
    days: int


def schedule() -> list[Step]:
    """The nine steps in R4's order, built from ``rehearsal_land.SCHEDULE``."""
    played = {1: 0, 2: 0}
    steps = []
    for number in range(1, STEPS + 1):
        park = SCHEDULE[number]
        played[park] += 1
        days = FIRST_STEP_DAYS if number == 1 else LATER_STEP_DAYS
        steps.append(Step(number, park, f"P{park}-{played[park]}", days))
    return steps


def attempt_name(step: int, attempt: int) -> str:
    """The folder of one attempt, relative to the work folder."""
    return f"rehearsal-step-{step}-attempt-{attempt}"


def save_name(step: int) -> str:
    """The save file stem a step's helper writes."""
    return f"rehearsal-step-{step}"


def reserved_names() -> list[str]:
    """Every work-folder name this command writes; a leftover of any of them refuses (R3 6)."""
    attempts = range(1, MAX_ATTEMPTS + 1)
    folders = [attempt_name(s, a) for s in range(1, STEPS + 1) for a in attempts]
    return [*folders, COMBINED, CONVERTED]


@dataclass(frozen=True)
class Sources:
    """The two parks' starting files and the SHA-1 each had when the refusals checked it.

    Attributes:
        fixture: Park 1's starting save (``OPENRCT2_BENCH_PARK``); only ever read.
        fixture_sha1: Its SHA-1 at the refusal check.
        park2: Park 2's starting save (``OPENRCT2_REHEARSAL_PARK2``); only ever read.
        park2_sha1: Its SHA-1 at the refusal check.
    """

    fixture: Path
    fixture_sha1: str
    park2: Path
    park2_sha1: str


def raw_problems(raw: Path) -> list[str]:
    """R5's checks on one attempt's raw files: one session, one start, speed 8 throughout.

    A line that is not valid JSON, or lacks a key these checks read, is itself a problem: the
    listener accepts any object with a schema version, so the attempt fails and is retried.
    """
    events: list[dict[str, object]] = []
    problems: list[str] = []
    for path in sorted((raw / LANDING_FOLDER).glob("events-*.jsonl")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            where = f"{path.name} line {number}"
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                problems.append(f"{where} is not valid JSON ({error.msg})")
                continue
            missing = [key for key in RAW_KEYS if key not in event]
            if missing:
                problems.append(f"{where} lacks {', '.join(missing)}")
                continue
            non_strings = [
                key for key in ("event_type", "session_id") if not isinstance(event[key], str)
            ]
            if non_strings:
                problems.append(f"{where} has non-string {', '.join(non_strings)}")
                continue
            events.append(event)
    starts = sum(event["event_type"] == "session_start" for event in events)
    if starts != 1:
        problems.append(f"{starts} session_start rows, expected 1")
    sessions = {event["session_id"] for event in events}
    if len(sessions) != 1:
        problems.append(f"{len(sessions)} session_id values, expected 1")
    slow = [
        event["seq"]
        for event in events
        if event["event_type"] == "plugin_stats"
        and event.get("warmup") is False
        and event.get("game_speed") != SESSION_SPEED
    ]
    if slow:
        problems.append(f"plugin_stats at seq {slow[0]} has game_speed other than {SESSION_SPEED}")
    return problems


def _attempt(
    bench: Bench, sources: Sources, step: Step, *, attempt: int, park_in: Path
) -> tuple[Path, list[str]]:
    """Run one attempt; return its save file and its problems (empty when valid)."""
    input_sha1 = file_sha1(park_in)
    folder = RunFolder(bench.settings.bench_dir / attempt_name(step.number, attempt))
    name = save_name(step.number)
    inputs = RunInputs(
        park_in,
        bench.built,
        bench.settings.game_path,
        AUTOSAVE_NEVER,
        rehearsal_helper(name),
        debugging_tools=True,
    )
    park_copy = make_run_folder(folder, inputs)
    save_file = folder.save_dir / f"{name}{SAVE_SUFFIX}"
    problem = play(bench, folder, park_copy, stop=SaveLanded(save_file), days=step.days)
    problems = [] if problem is None else [problem]
    if file_sha1(sources.fixture) != sources.fixture_sha1:
        problems.append(FIXTURE_CHANGED)
    if file_sha1(sources.park2) != sources.park2_sha1:
        problems.append(PARK2_CHANGED)
    if file_sha1(park_in) != input_sha1:
        problems.append(INPUT_CHANGED)
    problems += raw_problems(folder.raw)
    return save_file, problems


def run_chain(bench: Bench, sources: Sources) -> list[Attempt] | None:
    """Play the nine steps in order; return the accepted attempts, or None if the chain stopped.

    Prints one line per attempt: step, session, park, attempt, wall seconds and verdict.

    Raises:
        Interrupted: from the caller's signal handler; the attempt in progress is abandoned.
    """
    inputs = {1: sources.fixture, 2: sources.park2}
    accepted: list[Attempt] = []
    for step in schedule():
        for attempt in range(1, MAX_ATTEMPTS + 1):
            started = time.monotonic()
            save_file, problems = _attempt(
                bench, sources, step, attempt=attempt, park_in=inputs[step.park]
            )
            seconds = time.monotonic() - started
            verdict = "valid" if not problems else "invalid: " + "; ".join(problems)
            say(
                f"Step {step.number} ({step.label}, Park {step.park}), attempt {attempt}, "
                f"{seconds:.0f} s: {verdict}."
            )
            if not problems:
                break
        else:
            say(f"Step {step.number} failed twice; the chain stopped. Nothing was landed.")
            return None
        folder = RunFolder(bench.settings.bench_dir / attempt_name(step.number, attempt))
        accepted.append(Attempt(step=step.number, park=step.park, raw=folder.raw))
        inputs[step.park] = save_file
    return accepted

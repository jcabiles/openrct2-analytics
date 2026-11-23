"""File the parks of one company play as company or sandbox (``practice``), then run after-play.

The game launcher runs ``--record`` before a play: it writes the sorted IDs of every converted
session to ``local/auto-file/converted-before.json``. After the play, ``--count-as
<company|practice>`` classifies each waiting park once. A park with a waiting session missing from
that file is this play's park and takes ``--count-as``; a registered park keeps its registration,
and is asked about when it is this play's park and registered with the other choice; any other
park is asked about. When two or more parks are new in this play, each is asked which it is
(``several_parks``), whatever ``--count-as`` is, and the answers must match the order of the
parks' first sessions. It prints one line per park about to be registered, then runs after-play with
``--parks`` (and ``--start-year`` for a later company park) and returns its exit code, except that
after a landed registration a failure exits 1 (``several_parks.end_lines``).
With two or more company parks to register, it plans every year and runs every check first, then
registers the parks one at a time itself (``several_parks``) before one after-play call.
The record file is removed only after exit 0. Exit 0 filed or nothing waiting, 1 a step failed,
2 refused (including "Don't file now", a question with no terminal and an order answer that
does not match), 130 interrupted.

The answer to each question a run asked (never a ``--count-as`` choice or a kept registration) is
stored in ``local/auto-file/answers.json`` before the first registration, or before after-play for
one park. A run that ends with no registration landed removes the file, so its rerun asks again;
one that landed a park keeps it, so the rerun asks nothing twice. When a failure ends a run after a
park was registered, the run names the parks it filed and the rerun command instead of "Nothing was
changed" (``several_parks.filed_report``); it learns what landed by reading the registry again.
"""

from __future__ import annotations

import argparse
import csv
import signal
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Never, Protocol

import duckdb

from openrct2_analytics.config import DATA_SETS, ConfigError, LandingDirs
from openrct2_analytics.ingest import (
    after_play,
    auto_file_state,
    capture_session,
    landing_paths,
    lock,
    managed_years,
    park_label,
    play_status,
    previous_park,
    register_parks,
    several_parks,
)
from openrct2_analytics.ingest.auto_file_state import write_json
from openrct2_analytics.ingest.start_year import next_start_year

PROJECT_DIR = Path(__file__).resolve().parents[3]
DATA_SET = "company"
ANSWERS_FILE = several_parks.ANSWERS_FILE
# The word the player sees for each practice flag; the stored value stays ``practice``.
SHOWN = {False: "Company", True: "Sandbox"}
CHOICE_NAMES = {practice: name for name, practice in register_parks.CHOICES.items()}
# Answer to the question about a park from an earlier play: its practice flag, or None (not now).
EARLIER_ANSWERS: dict[str, bool | None] = {"1": False, "2": True, "3": None}
# Answer to the question about a park saved with the other choice: keep it, or not now.
CONFLICT_ANSWERS = {"1": True, "2": False}
# What each waiting park needs, decided without input or output (see ``_plan``).
KEEP, CONFLICT, EARLIER, COUNT_AS, NEW, STORED = (
    "keep",
    "conflict",
    "earlier",
    "count-as",
    "new",
    "stored",
)
ASKED = {CONFLICT, EARLIER, NEW}
INTERRUPTED = several_parks.INTERRUPTED
# This many new parks in one play are each asked which they are.
SEVERAL = 2


class FileWith(Protocol):
    """How the chosen parks are filed: the call shape of ``after_play.main``."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        project_dir: Path,
        registrations_landed: bool = False,
        registered: list[str] | None = None,
    ) -> int:
        """File the parks in ``argv`` for the project at ``project_dir``; return the exit code.

        ``registered`` receives the ID of each park this call wrote to a registry delivery.
        """
        ...


class _Refused(Exception):
    """The command was refused before anything was filed."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class _NotFiled(_Refused):
    """Nothing was filed, and the player can file later with the rerun line."""


class _AutoFileParser(argparse.ArgumentParser):
    """Argument parser that reports invalid input as a refusal."""

    def error(self, message: str) -> Never:
        raise _Refused("usage", message)


@dataclass(frozen=True)
class _Park:
    """One waiting park, classified once; ``this_play`` is true when any session is new."""

    park_id: str
    name: str | None
    label: str
    this_play: bool


def _stdin_is_terminal() -> bool:
    return sys.stdin is not None and sys.stdin.isatty()


def _skip() -> None:
    """Write no answers file: this run asked no per-park question."""


def _classify(
    status: play_status.PlayStatus, before: set[str] | None, landing: LandingDirs
) -> list[_Park]:
    """Return each waiting park once, in ``play_status`` order (spec R3), with its label."""
    facts = park_label.park_facts(landing)
    labels = park_label.labels(facts)
    new: dict[str, bool] = {}
    for session in status.sessions_waiting:
        this_play = before is not None and session.session_id not in before
        for park in session.parks:
            new[park.park_id] = new.get(park.park_id, False) or this_play
    return [
        _Park(
            p,
            facts[p].converted_name if p in facts else None,
            park_label.label_of(labels, p),
            flag,
        )
        for p, flag in new.items()
    ]


def _plan(
    parks: list[_Park],
    registered: dict[str, tuple[str, bool]],
    practice: bool,
    stored: dict[str, bool],
    *,
    unreadable: bool,
) -> dict[str, str]:
    """Return what each waiting park needs; this is the one home of "is a question needed".

    With two or more new parks each is asked which it is; one new park takes ``practice``. A park
    with a stored answer takes it, and a registered park whose stored answer equals its
    registration is not asked about the conflict. When the answers file cannot be read, one new
    park is asked too, because its stored answer is lost.
    """
    new = sum(
        1
        for park in parks
        if park.park_id not in registered and park.this_play and park.park_id not in stored
    )
    plan: dict[str, str] = {}
    for park in parks:
        entry = registered.get(park.park_id)
        if entry is not None:
            conflict = (
                park.this_play and entry[1] != practice and stored.get(park.park_id) != entry[1]
            )
            plan[park.park_id] = CONFLICT if conflict else KEEP
        elif park.park_id in stored:
            plan[park.park_id] = STORED
        elif not park.this_play:
            plan[park.park_id] = EARLIER
        else:
            plan[park.park_id] = NEW if new >= SEVERAL else (EARLIER if unreadable else COUNT_AS)
    return plan


def _ask_earlier(park: _Park, ask: Callable[[str], str]) -> bool:
    question = (
        f"Park {park.label} from an earlier play is waiting. Where should it count?\n"
        "1. Company\n2. Sandbox\n3. Don't file now"
    )
    practice = EARLIER_ANSWERS[several_parks.answer(ask, question, list(EARLIER_ANSWERS))]
    if practice is None:
        raise _NotFiled("not-now", f"Don't file now was chosen for park {park.label}")
    return practice


def _ask_conflict(park: _Park, saved: bool, ask: Callable[[str], str]) -> None:
    question = (
        f"Park {park.label} is saved as {SHOWN[saved]}, but this play was started as "
        f"{SHOWN[not saved]}.\n1. File it as {SHOWN[saved]}\n2. Don't file now"
    )
    if not CONFLICT_ANSWERS[several_parks.answer(ask, question, list(CONFLICT_ANSWERS))]:
        raise _NotFiled("not-now", f"Don't file now was chosen for park {park.label}")


def _choose(
    parks: list[_Park],
    plan: dict[str, str],
    *,
    saved: dict[str, bool],
    practice: bool,
    days: dict[str, int],
    ask: Callable[[str], str],
) -> tuple[dict[str, bool], dict[str, int | None]]:
    """Return every park's practice flag and each new park's answered rank, asking as planned.

    ``saved`` holds the flag each registered or stored park already has.
    """
    choices: dict[str, bool] = {}
    ranks: dict[str, int | None] = {}
    count = list(plan.values()).count(NEW)
    for park in parks:
        kind = plan[park.park_id]
        if kind in (KEEP, CONFLICT, STORED):
            if kind == CONFLICT:
                _ask_conflict(park, saved[park.park_id], ask)
            choices[park.park_id] = saved[park.park_id]
        elif kind == COUNT_AS:
            choices[park.park_id] = practice
        elif kind == EARLIER:
            choices[park.park_id] = _ask_earlier(park, ask)
        else:
            rank = several_parks.ask_new_park(park.label, days.get(park.park_id, 0), count, ask)
            ranks[park.park_id] = rank
            choices[park.park_id] = rank is None
    return choices, ranks


def _start_year(to_register: dict[str, bool], project_dir: Path) -> int | None:
    """Return the one accepted start year when a company park registers after the first."""
    if all(to_register.values()):
        return None
    folders = landing_paths.landing(DATA_SET, project_dir)
    return next_start_year(
        play_status.registry_feed_dir(DATA_SET, project_dir),
        folders.parquet,
        folders.raw,
    )


@dataclass(frozen=True)
class _Seams:
    ask: Callable[[str], str]
    file_with: FileWith
    is_terminal: Callable[[], bool]
    register_with: several_parks.RegisterWith


def _announce(
    parks: list[_Park], to_register: dict[str, bool], year: int | None, shown: dict[str, str]
) -> None:
    """Print one line per park about to be registered and note how it is registered in ``shown``."""
    for park in parks:
        how = several_parks.how(to_register[park.park_id], year or register_parks.FIRST_START_YEAR)
        several_parks.announce(park.park_id, park.label, how, shown)


def _file(practice: bool, project_dir: Path, seams: _Seams, shown: dict[str, str]) -> int:
    """File the waiting parks; ``shown`` collects how each park to register is registered."""
    status = after_play.check_can_start(DATA_SET, project_dir)
    if not status.sessions_waiting:
        print("auto-file: nothing is waiting to be filed.")
        auto_file_state.clear(project_dir)
        return 0
    registered = register_parks.registered_parks(
        play_status.registry_feed_dir(DATA_SET, project_dir)
    )
    landing = landing_paths.landing(DATA_SET, project_dir)
    parks = _classify(status, auto_file_state.read_before(project_dir), landing)
    read = several_parks.read_answers(project_dir)
    stored = read or {}
    plan = _plan(parks, registered, practice, stored, unreadable=read is None)
    asked = bool(ASKED & set(plan.values()))
    if asked:
        if not seams.is_terminal():
            raise _NotFiled(
                "no-terminal", "A question is needed, but standard input is not a terminal"
            )
        capture_session.discard_typed_input()
    parquet = landing.parquet
    days = managed_years.played_game_days(parquet) if NEW in plan.values() else {}
    choices, ranks = _choose(
        parks,
        plan,
        saved={**stored, **{park: entry[1] for park, entry in registered.items()}},
        practice=practice,
        days=days,
        ask=seams.ask,
    )
    if ranks:
        try:
            several_parks.check_order(parquet, ranks, {park.park_id: park.label for park in parks})
        except several_parks.OrderMismatch as error:
            raise _NotFiled("order", str(error)) from error
    to_register = {park: flag for park, flag in choices.items() if park not in registered}
    listed = ",".join(f"{park}:{CHOICE_NAMES[flag]}" for park, flag in choices.items())
    argv = ["--data-set", DATA_SET, "--parks", listed]
    answers = {park: CHOICE_NAMES[flag] for park, flag in choices.items() if plan[park] in ASKED}
    write_answers = partial(write_json, project_dir / ANSWERS_FILE, answers) if asked else _skip
    landed: list[str] = []
    years: Mapping[str, int | None] = {}
    if list(to_register.values()).count(False) >= SEVERAL:
        landed, years = several_parks.file_chain(
            project_dir,
            to_register,
            {park.park_id: park.label for park in parks},
            seams.register_with,
            shown=shown,
            write_answers=write_answers,
        )
        code = seams.file_with(
            argv, project_dir=project_dir, registrations_landed=True, registered=landed
        )
    else:
        year = _start_year(to_register, project_dir) if to_register else None
        years = {park: year for park, flag in to_register.items() if not flag}
        _announce([park for park in parks if park.park_id in to_register], to_register, year, shown)
        if year is not None:
            argv += ["--start-year", str(year)]
        write_answers()
        code = seams.file_with(argv, project_dir=project_dir, registered=landed)
    if code == 0:
        # Only parks this run wrote: another run may have registered one after the snapshot above.
        companies = {
            p.park_id: p.name or p.park_id
            for p in parks
            if p.park_id in landed and not to_register[p.park_id]
        }
        lines = several_parks.joins(project_dir, companies)
        auto_file_state.clear(project_dir)
        # The notes are read after the filing; say() covers an interrupt during the read.
        wanted = {park: years[park] for park in companies}
        notes = partial(previous_park.note_lines, project_dir, companies, wanted)
        return several_parks.say(lines, notes if companies else list)
    return _end(shown, project_dir, CHOICE_NAMES[practice], first=None, plain=None, code=code)


def _end(
    shown: dict[str, str],
    project_dir: Path,
    count_as: str,
    *,
    first: str | None,
    plain: str | None,
    code: int,
) -> int:
    """End a failed run with the lines ``several_parks.end_lines`` gives; return the exit code."""
    try:
        lines, code = several_parks.end_lines(
            shown, project_dir, count_as, first=first, plain=plain, code=code
        )
        if lines:
            print("\n".join(lines))
    except (lock.Interrupted, KeyboardInterrupt):
        # A second interrupt while these lines print; parks already landed stay landed.
        return INTERRUPTED
    return code


def _run(args: argparse.Namespace, project_dir: Path, seams: _Seams, shown: dict[str, str]) -> int:
    if args.data_set != DATA_SET:
        raise _Refused("data-set", f"auto-file files {DATA_SET} plays only; got {args.data_set}")
    try:
        if args.record:
            auto_file_state.record(project_dir, DATA_SET)
            return 0
        return _file(register_parks.CHOICES[args.count_as], project_dir, seams, shown)
    except ConfigError as error:
        # After a landed registration the paths are read again, so this can come late.
        raise _Refused("data-set", str(error)) from error


def main(
    argv: Sequence[str] | None = None,
    *,
    project_dir: Path = PROJECT_DIR,
    ask: Callable[[str], str] = input,
    file_with: FileWith = after_play.main,
    is_terminal: Callable[[], bool] = _stdin_is_terminal,
    register_with: several_parks.RegisterWith = register_parks.register,
) -> int:
    """Record or file one company play and map each outcome to its documented exit code."""
    parser = _AutoFileParser(description=__doc__)
    parser.add_argument("--data-set", choices=DATA_SETS, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--record", action="store_true", help="Record the converted sessions")
    mode.add_argument("--count-as", choices=sorted(register_parks.CHOICES), help="This play's")
    handlers = {
        name: signal.getsignal(getattr(signal, name))
        for name in lock.SIGNAL_NAMES
        if hasattr(signal, name)
    }
    lock.set_signal_handlers(lock.raise_interrupted)
    count_as = ""
    root = project_dir.resolve()
    shown: dict[str, str] = {}

    def end(first: str, plain: str, code: int) -> int:
        return _end(shown, root, count_as, first=first, plain=plain, code=code)

    def refuse(why: str) -> int:
        return end(
            f"auto-file failed: {why}.", f"auto-file refused: {why}. Nothing was changed.", 2
        )

    try:
        args = parser.parse_args(argv)
        count_as = args.count_as or ""
        code = _run(args, root, _Seams(ask, file_with, is_terminal, register_with), shown)
    except _NotFiled as error:
        print(f"auto-file refused: {error.reason}: {error.detail}. Nothing was changed.")
        print(f"To file it, run: make auto-file DATA_SET={DATA_SET} COUNT_AS={count_as}")
        code = 2
    # check_can_start and next_start_year raise their owners' refusals; the reason and detail are
    # theirs, under auto-file's prefix.
    except (_Refused, after_play.Refused, register_parks.Refused) as error:
        code = refuse(f"{error.reason}: {error.detail}")
    except lock.LockTaken as error:
        code = refuse(f'lock-taken: {error}; see ARCHITECTURE.md "Stale locks"')
    except register_parks.CheckFailed as error:
        code = end(
            f"auto-file failed: check-failed: {error}.",
            f"auto-file failed: check-failed: {error}",
            1,
        )
    except (OSError, ValueError, csv.Error, duckdb.Error) as error:
        code = end(f"auto-file failed: io: {error}.", f"auto-file failed: io: {error}", 1)
    except (lock.Interrupted, KeyboardInterrupt, EOFError):
        code = end(
            "auto-file interrupted.", "auto-file interrupted. Nothing was changed.", INTERRUPTED
        )
    finally:
        for name, handler in handlers.items():
            signal.signal(getattr(signal, name), handler)
    return code


if __name__ == "__main__":
    sys.exit(main())

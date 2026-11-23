"""Ask about each new park of a play that opened several, and check the order answers.

``auto_file`` calls this when two or more parks are new in one play. Each park is asked which one
it is: "Opened first", "Opened second", ... or "Sandbox". Every answer is collected first. Then
each "Opened n" answer must match the order of the parks' first recorded ``session_start`` rows
(earliest ``emitted_at``, ties by park ID), Sandbox parks counted in the ranking, because that is
the order in which the parks were opened.

With two or more company parks to register, ``plan_chain`` plans every park's start year and runs
every refusal check before any write, and ``file_chain`` then registers the parks one at a
time, each re-checking its year under the landing lock. It also words what auto-file says when a
failure ends a run after a park was registered.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

import duckdb

from openrct2_analytics.config import ConfigError
from openrct2_analytics.domain.start_year_plan import Planned
from openrct2_analytics.ingest import (
    after_play,
    lock,
    managed_years,
    play_status,
    register_parks,
    start_year,
)
from openrct2_analytics.ingest.landing_paths import landing
from openrct2_analytics.ingest.query_interrupt import interrupt_as_signal

INTERRUPTED = 130
ANSWERS_FILE = Path("local") / "auto-file" / "answers.json"

ORDINALS = (
    "first",
    "second",
    "third",
    "fourth",
    "fifth",
    "sixth",
    "seventh",
    "eighth",
    "ninth",
    "tenth",
)


class RegisterWith(Protocol):
    """How one park is registered: the call shape of ``register_parks.register``."""

    def __call__(
        self,
        project_dir: Path,
        today: date,
        practice: bool,
        *,
        parks: dict[str, bool] | None = None,
        start_year: int | None = None,
    ) -> str:
        """Register ``parks`` in one delivery and return its file name."""
        ...


class OrderMismatch(Exception):
    """An "Opened n" answer does not match the order of the parks' first recorded sessions."""


def ordinal(number: int) -> str:
    """Return the English word for ``number``, or its numeral with an ordinal suffix past ten."""
    if number <= len(ORDINALS):
        return ORDINALS[number - 1]
    teens = number % 100 in (11, 12, 13)
    suffix = "th" if teens else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def answer(ask: Callable[[str], str], question: str, answers: Sequence[str]) -> str:
    """Ask ``question`` until the answer is one of ``answers``."""
    while True:
        reply = ask(f"{question}\n").strip()
        if reply in answers:
            return reply


def question(label: str, days: int, count: int) -> str:
    """Return the question about one of ``count`` new parks, with its numbered options."""
    options = [f"{rank}. Opened {ordinal(rank)}" for rank in range(1, count + 1)]
    options.append(f"{count + 1}. Sandbox")
    unit = "game day" if days == 1 else "game days"
    head = f"Park {label}, {days} {unit} played, is new in this play. Which is it?"
    return "\n".join([head, *options])


def ask_new_park(label: str, days: int, count: int, ask: Callable[[str], str]) -> int | None:
    """Ask about one new park; return the rank it was opened in, or None for Sandbox."""
    options = [str(number) for number in range(1, count + 2)]
    chosen = int(answer(ask, question(label, days, count), options))
    return None if chosen == count + 1 else chosen


def check_order(
    parquet_dir: Path, given: Mapping[str, int | None], labels: Mapping[str, str]
) -> None:
    """Raise OrderMismatch for the first park whose "Opened n" answer is not its real rank.

    ``given`` holds each asked park's answered rank (None for Sandbox), in the order asked.

    Raises:
        ValueError: an asked park has no ``session_start`` row.
    """
    starts = managed_years.table(parquet_dir, "session_start")
    ranked = [park for park, _, _ in start_year.first_sessions(starts) if park in given]
    for park in given:
        if park not in ranked:
            raise ValueError(f"Park {labels[park]} has no session_start row to order it by")
    actual = {park: rank for rank, park in enumerate(ranked, start=1)}
    for park, rank in given.items():
        if rank is not None and rank != actual[park]:
            raise OrderMismatch(
                f"Park {labels[park]} was answered as opened {ordinal(rank)}, but its first "
                f"recorded session is the {ordinal(actual[park])} of this play's new parks"
            )


def read_answers(project_dir: Path) -> dict[str, bool] | None:
    """Return each stored park's practice flag; None, with one line, when the file is unusable."""
    try:
        stored = json.loads((project_dir / ANSWERS_FILE).read_text(encoding="utf-8"))
        if not isinstance(stored, dict) or not all(
            isinstance(choice, str) and choice in register_parks.CHOICES
            for choice in stored.values()
        ):
            raise ValueError("it is not a map of park IDs to company or practice")
        return {park: register_parks.CHOICES[choice] for park, choice in stored.items()}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        print("auto-file: answers.json could not be read; asking again.")
        return None


AFTER_PLAY_STOPPED = "auto-file: after-play stopped, and these parks are already registered."


def rerun_line(count_as: str) -> str:
    """Return the line that tells the player how to file the parks that are left."""
    return (
        f"To file the rest, run: make auto-file DATA_SET=company COUNT_AS={count_as} "
        "(run it here; the launcher starts a new play)"
    )


def filed_report(first: str | None, filed: Sequence[str], count_as: str) -> list[str]:
    """Return the lines for a run that registered ``filed`` ("park <label> as <how>") then failed.

    ``first`` is the failure line; None after an after-play failure, which printed its own.
    """
    return [
        first or AFTER_PLAY_STOPPED,
        f"auto-file: already registered by this run: {'; '.join(filed)}.",
        rerun_line(count_as),
    ]


def unread_report(first: str | None, known: Sequence[str], count_as: str) -> list[str]:
    """Return the lines for a failed run whose registry cannot be read again to see what landed."""
    lines = [first] if first else []
    lines.append(
        "auto-file: could not read the registry; "
        f"run make auto-file DATA_SET=company COUNT_AS={count_as} "
        "and it will report what is registered"
    )
    if known:
        lines.append(f"auto-file: it was registering: {'; '.join(known)}.")
    return lines


def end_lines(
    shown: Mapping[str, str],
    project_dir: Path,
    count_as: str,
    *,
    first: str | None,
    plain: str | None,
    code: int,
) -> tuple[list[str], int]:
    """Return the lines and exit code that end a failed run: ``plain`` when no park landed.

    ``shown`` holds the parks the run set out to register; the registry, read again, says which
    landed. ``first`` is the failure line for the filed report, None after an after-play failure.
    Once a park landed the code is 1, or 130 for an interrupt. When none landed, the stored
    ``ANSWERS_FILE`` is removed, so the rerun asks again; it stays when a park landed or the
    registry cannot be read.
    """
    landed_code = INTERRUPTED if code == INTERRUPTED else 1
    try:
        feed = play_status.registry_feed_dir("company", project_dir) if shown else None
        registry = register_parks.registered_parks(feed) if feed else {}
    except (register_parks.Refused, ConfigError, OSError, csv.Error, ValueError):
        return unread_report(first, list(shown.values()), count_as), landed_code
    filed = [text for park, text in shown.items() if park in registry]
    if not filed:
        (project_dir / ANSWERS_FILE).unlink(missing_ok=True)
        return ([plain] if plain else []), code
    return filed_report(first, filed, count_as), landed_code


def how(practice: bool, year: int) -> str:
    """Return how a park is registered, as the "is new" line and the filed report word it."""
    return "a sandbox park" if practice else f"company park, start year {year}"


def announce(park: str, label: str, how: str, shown: dict[str, str]) -> None:
    """Print the "is new" line of one park about to be registered and note it in ``shown``."""
    shown[park] = f"park {label} as {how}"
    print(f"auto-file: park {label} is new; registering it as {how}.", flush=True)


def joins_line(name: str, number: int, year: int) -> str:
    """Return the line that tells a newly registered company park's number and start year."""
    return f"{name} joins the company as Park {number}, starting in company year {year}"


def unread_reason(error: Exception) -> str:
    """Return a short fixed reason for a failed read of the park numbers.

    The reason is chosen from the kind of the error and never carries the error's own text, which
    can hold SQL, a machine path, a process ID and the user name.
    """
    if isinstance(error, FileNotFoundError):
        return "no warehouse file"
    if isinstance(error, duckdb.IOException) and "Could not set lock" in str(error):
        return "the warehouse is locked by another program"
    if isinstance(error, duckdb.BinderException | duckdb.CatalogException):
        return "the warehouse was built before park numbers"
    return "the warehouse could not be read"


def unread_line(error: Exception) -> str:
    """Return the one line for a filed play whose park numbers could not be read."""
    reason = unread_reason(error)
    return f"auto-file: the play is filed, but the park number could not be shown ({reason})."


def say(lines: list[str], notes: Callable[[], list[str]] = list) -> int:
    """Print the lines and the ``notes`` after filing; return 0, or 130 on an interrupt."""
    try:
        lines = [*lines, *notes()]
        if lines:
            print("\n".join(lines))
            sys.stdout.flush()
    except (lock.Interrupted, KeyboardInterrupt):
        # The record and answers files are already cleared and parks already landed stay landed.
        return INTERRUPTED
    except OSError:
        # The filing is done and the record files are gone, so a closed or broken output (a
        # BrokenPipeError, say) must not become a failure report; tell standard error if it works.
        # Standard output now points at the null device so that the flush Python runs at exit
        # cannot fail again and turn the exit code into 120.
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115  (kept open for the process lifetime)
        with suppress(OSError):
            print(
                "auto-file: the play is filed, but its last lines could not be written.",
                file=sys.stderr,
            )
    return 0


def no_number_line(names: list[str]) -> str:
    """Return the line for newly registered company parks that have no number."""
    shown = ", ".join(names)
    return f"auto-file: the play is filed, but the park number could not be shown for {shown}."


def joins_lines(names: Mapping[str, str], found: Mapping[str, tuple[int, int]]) -> list[str]:
    """Return one joins line per park in ``found``, in order of n, then the line for the rest.

    ``names`` maps each looked-up park ID to its shown name; ``found`` maps the IDs the warehouse
    numbered to (number, start year).
    """
    lines = [
        joins_line(names[park], number, year)
        for park, (number, year) in sorted(found.items(), key=lambda item: item[1][0])
    ]
    missing = [name for park, name in names.items() if park not in found]
    return [*lines, no_number_line(missing)] if missing else lines


def joins(project_dir: Path, names: dict[str, str]) -> list[str]:
    """Return the lines that tell each newly registered company park's number, in order of n."""
    if not names:
        return []
    try:
        with interrupt_as_signal():
            found = play_status.dim_park_numbers(project_dir, list(names))
    except (OSError, duckdb.Error) as error:
        # Filing already succeeded (after-play returned 0); a warehouse that cannot be read now
        # (absent, locked, built before park_number, damaged) must not turn it into a failure.
        return [unread_line(error)]
    return joins_lines(names, found)


def _ids(parks: set[str]) -> str:
    return ", ".join(sorted(parks)) or "none"


def plan_chain(
    project_dir: Path, to_register: Mapping[str, bool], answered: set[str], today: date
) -> list[Planned]:
    """Plan each park of ``to_register`` (park ID to practice flag) and run every check first.

    The parks are planned in the order of their first recorded sessions, each earlier park counted
    as registered. ``answered`` holds every waiting park the player answered for.

    Raises:
        register_parks.Refused: a year refusal, a registration refusal for any park, or a waiting
            list that changed while the player was answering; nothing was written.
        after_play.Refused: a landing lock or a warehouse build that started meanwhile.
        ValueError: a park to register has no ``session_start`` row.
    """
    starts = managed_years.table(landing("company", project_dir).parquet, "session_start")
    ranked = [park for park, _, _ in start_year.first_sessions(starts) if park in to_register]
    for park in to_register:
        if park not in ranked:
            raise ValueError(f"Park {park} has no session_start row to order it by")
    planned = start_year.plan_start_years(project_dir, [(p, to_register[p]) for p in ranked])
    register_parks.check_registrations(project_dir, today, len(planned))
    status = after_play.check_can_start("company", project_dir)
    waiting = {park.park_id for session in status.sessions_waiting for park in session.parks}
    if waiting != answered:
        raise register_parks.Refused(
            "waiting-list",
            "the waiting parks changed while you were answering "
            f"(added: {_ids(waiting - answered)}; removed: {_ids(answered - waiting)})",
        )
    return planned


def file_chain(
    project_dir: Path,
    to_register: Mapping[str, bool],
    labels: Mapping[str, str],
    register_with: RegisterWith,
    *,
    shown: dict[str, str],
    write_answers: Callable[[], None],
) -> tuple[list[str], dict[str, int]]:
    """Plan and check every park of ``to_register``, then register each in its own delivery.

    Returns the IDs of the parks that wrote a delivery, in order, and each company park's year.

    ``labels`` holds every waiting park the player answered for. After the checks, one "is new"
    line is printed per park and ``write_answers`` runs, before the first registration. Each later
    company park passes its planned year, which ``register`` checks again under the landing lock.
    """
    today = datetime.now(UTC).date()
    planned = plan_chain(project_dir, to_register, set(labels), today)
    for park in planned:
        announce(
            park.park_id, labels[park.park_id], how(park.practice, park.company_start_year), shown
        )
    write_answers()
    # A company park takes START_YEAR (its planned year) when a company park is registered or
    # planned before it; the first company park of the company takes none, whatever its year.
    feed = play_status.registry_feed_dir("company", project_dir)
    later = bool(start_year.registered_company_parks(feed))
    written: list[str] = []
    for park in planned:
        year = park.company_start_year if later and not park.practice else None
        name = register_with(
            project_dir, today, False, parks={park.park_id: park.practice}, start_year=year
        )
        if name:
            written.append(park.park_id)
        later = later or not park.practice
    return written, {p.park_id: p.company_start_year for p in planned if not p.practice}

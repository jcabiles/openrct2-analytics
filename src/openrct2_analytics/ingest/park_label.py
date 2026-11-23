"""The one rule for naming a park: ``<name> (first played <Mon D>)``.

This module is the only home of a park's display name, its first-played time and the label text.
It reads the converted ``session_start`` Parquet and the raw ``events-*.jsonl`` files of one data
set and writes nothing. ``to_local`` is the only place a time becomes local time.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb

from openrct2_analytics.config import LandingDirs
from openrct2_analytics.ingest import managed_years, start_year

NOON = 12
MIN_TWINS = 2
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class ParkFacts:
    """What the landing files say about one park: its name and its first-played instant."""

    name: str | None
    first_played: datetime | None
    converted_name: str | None = None


def to_local(moment: datetime) -> datetime:
    """Return the instant in the local zone, applying the offset in force at that instant."""
    return moment.astimezone()


def park_names(parquet_dir: Path) -> dict[str, str | None]:
    """The latest ``park_name`` of each park in the converted ``session_start`` events.

    The latest is by ``emitted_at``, then ``session_id``, both descending; a NULL name counts
    only when the park has no other name.
    """
    path = managed_years.table(parquet_dir, "session_start")
    if not path.is_file():
        return {}
    with duckdb.connect(":memory:") as connection:
        rows = connection.execute(
            """SELECT park_id, park_name FROM read_parquet(?)
               QUALIFY row_number() OVER (
                   PARTITION BY park_id
                   ORDER BY park_name IS NULL, emitted_at DESC, session_id DESC
               ) = 1""",
            [path.as_posix()],
        ).fetchall()
    return {str(park): name for park, name in rows}


def park_facts(landing: LandingDirs) -> dict[str, ParkFacts]:
    """Each park the data set holds, with its name and first-played instant.

    The clock is wall-clock: the plugin's ``emitted_at`` of the park's earliest ``session_start``
    (ties by ``session_id``), taken over the converted Parquet and the raw files together; the
    game date, the company date and file times are never read. The instants stay as stored
    (UTC); ``labels`` converts them to the local zone through ``to_local``. The name is the latest
    converted ``session_start`` name, or the latest raw one for a park with no converted start; a
    null, empty or all-space name is missing. A missing ``session_start.parquet`` gives no
    converted facts. ``converted_name`` is that converted name as stored, so a caller needs no
    second read of the Parquet. A converted row with no ``game_year`` or no ``emitted_at`` gives
    no first-played instant.
    """
    starts = managed_years.table(landing.parquet, "session_start")
    converted_names: dict[str, str | None] = {}
    first: dict[str, datetime] = {}
    if starts.is_file():
        converted_names = park_names(landing.parquet)
        first = {park: emitted for park, _, emitted in start_year.first_sessions(starts)}
    raw_names: dict[str, str | None] = {}
    seen: set[str] = set(converted_names) | set(first)
    timed: dict[str, list[tuple[datetime, str]]] = {}
    untimed: dict[str, list[str]] = {}
    index = managed_years.raw_session_index(landing.raw)
    for session, record in index.items():
        seen |= record.park_ids
        for park, moment in record.start_times.items():
            if moment is None:
                untimed.setdefault(park, []).append(session)
            else:
                timed.setdefault(park, []).append((moment, session))
    for park in set(timed) | set(untimed):
        # Ascending order puts a start with no time after every timed one; the latest is last.
        latest = max(untimed[park]) if park in untimed else max(timed[park])[1]
        raw_names[park] = index[latest].park_names.get(park)
        if park in timed:
            earliest = min(timed[park])[0]
            first[park] = min(first[park], earliest) if park in first else earliest
    facts: dict[str, ParkFacts] = {}
    for park in seen:
        name = converted_names[park] if park in converted_names else raw_names.get(park)
        facts[park] = ParkFacts(
            name if name and name.strip() else None, first.get(park), converted_names.get(park)
        )
    return facts


def _clock(moment: datetime) -> str:
    """The 12-hour time, ``3:42 pm``; ``12`` for noon and midnight."""
    return (
        f"{moment.hour % NOON or NOON}:{moment.minute:02} {'pm' if moment.hour >= NOON else 'am'}"
    )


def _shown(name: str) -> str:
    """The name as a player sees it: whitespace runs are one space, the ends are trimmed."""
    return " ".join(name.split())


def labels(facts: dict[str, ParkFacts]) -> dict[str, str]:
    """The display label of every park in ``facts``, one rule for all of them.

    Two names are the same when they show the same: whitespace runs count as one space and the
    ends are trimmed, as the autopilot menu and the dashboard show them.

    ``<name> (first played <Mon D>)``; ``<name> (<Mon D>, <h:mm am|pm>)`` for parks that share a
    name and a shown day; the park ID added for those that also share the minute; ``<name>
    (<park ID>)`` with no time; the park ID in place of a missing name.
    """
    local = {park: to_local(f.first_played) for park, f in facts.items() if f.first_played}
    days = {park: f"{MONTHS[moment.month - 1]} {moment.day}" for park, moment in local.items()}
    shown = {park: _shown(f.name) for park, f in facts.items() if f.name}
    twin_days = Counter((shown[park], days[park]) for park in shown if park in days)
    twin_minutes = Counter(
        (shown[park], days[park], _clock(local[park])) for park in shown if park in days
    )
    result: dict[str, str] = {}
    for park, f in facts.items():
        name = f.name or park
        if park not in local:
            result[park] = f"{name} ({park})" if f.name else park
        elif not f.name or twin_days[(shown[park], days[park])] < MIN_TWINS:
            result[park] = f"{name} (first played {days[park]})"
        elif twin_minutes[(shown[park], days[park], _clock(local[park]))] < MIN_TWINS:
            result[park] = f"{name} ({days[park]}, {_clock(local[park])})"
        else:
            result[park] = f"{name} ({days[park]}, {_clock(local[park])}, {park})"
    return result


def label_of(label_map: dict[str, str], park_id: str) -> str:
    """The park's label, or the bare park ID for a park the helper has no facts about."""
    return label_map.get(park_id, park_id)

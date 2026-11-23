"""Read the year rule's inputs from converted Parquet, before ``make transform``.

The rule itself is ``domain/company_years.py``. This module reads the converted ``park_snapshot``,
``save_written`` and ``session_start`` Parquet, the park registry and the session-label feed
(``registry_dir`` is the registry root that holds ``v1/``) and hands plain values to it. It also
scans the raw folder for a session the converted Parquet lacks (refusal 12), lists the converted
parks the registry does not list yet, and lists a park's landed ``autopilot`` sessions. It also
holds the raw session index with its per-file cache, which ``unfiled.py`` and the dashboard read.
It writes nothing and refuses nothing: each caller raises its own refusal.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType

import duckdb

from openrct2_analytics.domain.company_years import (
    Registration,
    SnapshotDay,
    managed_years_by_park,
)
from openrct2_analytics.ingest import play_mode_feed, registry_feed
from openrct2_analytics.ingest.contracts import LANDING_FOLDER


def table(parquet_dir: Path, name: str) -> Path:
    """The converted Parquet file of one event type."""
    return parquet_dir / LANDING_FOLDER / f"{name}.parquet"


def unconverted_raw_file(raw_dir: Path, parquet_dir: Path) -> Path | None:
    """Return the first ``raw/v1/events-*.jsonl`` (by name) holding a session the Parquet lacks.

    A session is converted when ``session_start.parquet`` lists it. A missing raw folder counts as
    clean (None). A line that cannot be parsed, or has no session ID, makes its file unconverted;
    the refusal sends the player to ``make convert``, which reports the bad line itself. A missing
    ``session_start.parquet`` is the caller's check, made before this call.
    """
    files = raw_files(raw_dir)
    if not files:
        return None
    converted = converted_sessions(parquet_dir)
    for path in files:
        content = _cached_read(path)
        if content.has_unreadable_line or not content.sessions <= converted:
            return path
    return None


def unreadable_raw_files(raw_dir: Path) -> list[Path]:
    """The raw files, by name, whose cached read has ``has_unreadable_line`` set."""
    return [path for path in raw_files(raw_dir) if _cached_read(path).has_unreadable_line]


@dataclass(frozen=True)
class RawFile:
    """What one raw file holds: its session IDs, whether a line had none, and per-session facts.

    ``start_times`` holds the ``emitted_at`` of each (session, park) ``session_start`` line, named
    or not; None when the value is not an ISO 8601 string with a UTC offset.
    """

    sessions: frozenset[str]
    has_unreadable_line: bool
    park_ids: Mapping[str, frozenset[str]]
    park_names: Mapping[tuple[str, str], str]
    start_times: Mapping[tuple[str, str], datetime | None]


@dataclass(frozen=True)
class RawSession:
    """One raw session: its park IDs, the ``session_start`` name and time of each park, its files.

    ``start_times`` has a key for each park with a ``session_start`` line, None when it has no time.
    """

    park_ids: frozenset[str]
    park_names: Mapping[str, str]
    files: tuple[Path, ...]
    start_times: Mapping[str, datetime | None]


_RAW_CACHE: dict[Path, tuple[tuple[int, int], RawFile]] = {}


def read_raw_file(path: Path) -> RawFile:
    """Parse one raw file. A line that cannot be parsed or has no string session ID adds none."""
    sessions: set[str] = set()
    parks: dict[str, set[str]] = {}
    names: dict[tuple[str, str], str] = {}
    times: dict[tuple[str, str], datetime | None] = {}
    unreadable = False
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            event = _event_of(line)
            session = event.get("session_id") if event else None
            if not event or not isinstance(session, str):
                unreadable = True
                continue
            sessions.add(session)
            park = event.get("park_id")
            if isinstance(park, str):
                parks.setdefault(session, set()).add(park)
            name = event.get("park_name")
            is_start = event.get("event_type") == "session_start"
            if is_start and isinstance(park, str):
                key = (session, park)
                moment = _start_time(event.get("emitted_at"))
                earlier = _is_earlier(moment, key in times, times.get(key))
                if earlier:
                    times[key] = moment
                if isinstance(name, str) and (earlier or key not in names):
                    names[key] = name
    return RawFile(
        sessions=frozenset(sessions),
        has_unreadable_line=unreadable,
        park_ids=MappingProxyType({session: frozenset(found) for session, found in parks.items()}),
        park_names=MappingProxyType(names),
        start_times=MappingProxyType(times),
    )


def _is_earlier(moment: datetime | None, held: bool, current: datetime | None) -> bool:
    """Whether a start at ``moment`` replaces the held one: the earliest valid time wins.

    A start with no time is kept only when nothing is held; any valid time beats it. Equal times
    keep the first start.
    """
    if not held:
        return True
    return moment is not None and (current is None or moment < current)


def _start_time(value: object) -> datetime | None:
    """The ``emitted_at`` as an aware time; None when it is not a string, unparsable or naive."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def raw_session_index(raw_dir: Path) -> dict[str, RawSession]:
    """Every session in ``raw/v1/events-*.jsonl``, with its parks, park name and files.

    Each file is parsed once per ``(mtime_ns, size)``; an unchanged file is read from the cache.
    """
    parks: dict[str, set[str]] = {}
    names: dict[str, dict[str, str]] = {}
    times: dict[str, dict[str, datetime | None]] = {}
    files: dict[str, list[Path]] = {}
    for path in raw_files(raw_dir):
        content = _cached_read(path)
        for session in content.sessions:
            files.setdefault(session, []).append(path)
            parks.setdefault(session, set()).update(content.park_ids.get(session, ()))
        for (session, park), name in content.park_names.items():
            names.setdefault(session, {}).setdefault(park, name)
        for (session, park), moment in content.start_times.items():
            slot = times.setdefault(session, {})
            if _is_earlier(moment, park in slot, slot.get(park)):
                slot[park] = moment
                if (session, park) in content.park_names:
                    names.setdefault(session, {})[park] = content.park_names[(session, park)]
    return {
        session: RawSession(
            frozenset(parks[session]),
            MappingProxyType(names.get(session, {})),
            tuple(held),
            MappingProxyType(times.get(session, {})),
        )
        for session, held in files.items()
    }


def raw_sessions(raw_dir: Path) -> set[str]:
    """The session IDs in ``raw/v1/events-*.jsonl``; a line that cannot be parsed adds none."""
    return set(raw_session_index(raw_dir))


def raw_files(raw_dir: Path) -> list[Path]:
    """The ``raw/v1/events-*.jsonl`` files, sorted by name: the one raw-file list."""
    return sorted((raw_dir / LANDING_FOLDER).glob("events-*.jsonl"))


def file_key(path: Path) -> tuple[int, int] | None:
    """``(mtime_ns, size)`` of one file from one ``stat``; None when it is missing."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _cached_read(path: Path) -> RawFile:
    key = file_key(path)
    if key is None:
        raise FileNotFoundError(path)
    cached = _RAW_CACHE.get(path)
    if cached is not None and cached[0] == key:
        return cached[1]
    content = read_raw_file(path)
    _RAW_CACHE[path] = (key, content)
    return content


def _event_of(line: str) -> dict[str, object] | None:
    """The line's event; a line that cannot be parsed has none."""
    try:
        event = json.loads(line)
    except (ValueError, RecursionError):
        # Deeply nested JSON overflows the parser's stack: an unreadable line, as in delete_plan.
        return None
    return event if isinstance(event, dict) else None


def converted_sessions(parquet_dir: Path) -> set[str]:
    """The IDs of every session in the converted ``session_start`` table."""
    starts = table(parquet_dir, "session_start")
    with duckdb.connect(":memory:") as connection:
        rows = connection.execute(
            "SELECT DISTINCT session_id FROM read_parquet(?)", [str(starts)]
        ).fetchall()
    return {str(session) for (session,) in rows}


def company_registrations(registry_dir: Path) -> dict[str, Registration]:
    """Each park's latest registry row of the company data set, a practice park included.

    The one home of the registered-company rule: ``start_year`` builds its company park list from
    this, and the year rule ignores a practice park's days. A row of another data set is left out.
    """
    rows = registry_feed.latest_rows(registry_dir / LANDING_FOLDER)
    return {
        park: Registration(row.company_start_year, row.game_year_origin, row.practice)
        for park, row in sorted(rows.items())
        if row.data_set == "company"
    }


@dataclass(frozen=True)
class ManagedInputs:
    """The plain values the year rule needs, read once from converted Parquet and the feeds."""

    days: list[SnapshotDay]
    registrations: dict[str, Registration]
    last_save_seq: dict[str, int]
    session_start_year: dict[str, int]
    autopilot_sessions: frozenset[str]


def read_managed_inputs(parquet_dir: Path, registry_dir: Path) -> ManagedInputs:
    """Read the year rule's inputs (spec section 5).

    A missing ``park_snapshot.parquet`` or ``save_written.parquet`` gives no managed days, but
    the registrations are still read. A missing ``session_start.parquet`` gives no session start
    years.
    """
    snapshots = table(parquet_dir, "park_snapshot")
    saves = table(parquet_dir, "save_written")
    starts = table(parquet_dir, "session_start")
    registrations = company_registrations(registry_dir)
    if not snapshots.is_file() or not saves.is_file():
        return ManagedInputs([], registrations, {}, {}, frozenset())
    labels = play_mode_feed.read_labels(registry_dir)
    autopilot = frozenset(
        session for session, label in labels.items() if label.play_mode == play_mode_feed.AUTOPILOT
    )
    with duckdb.connect(":memory:") as connection:
        days = [
            SnapshotDay(str(park), str(session), int(seq), int(year), int(month), int(number))
            for park, session, seq, year, month, number in connection.execute(
                "SELECT park_id, session_id, seq, game_year, game_month, game_day"
                " FROM read_parquet(?)",
                [str(snapshots)],
            ).fetchall()
        ]
        last_save_seq = {
            str(session): int(seq)
            for session, seq in connection.execute(
                "SELECT session_id, max(seq) FROM read_parquet(?) GROUP BY session_id",
                [str(saves)],
            ).fetchall()
        }
        start_year = (
            {
                str(session): int(year)
                for session, year in connection.execute(
                    "SELECT session_id, game_year FROM read_parquet(?)", [str(starts)]
                ).fetchall()
            }
            if starts.is_file()
            else {}
        )
    return ManagedInputs(days, registrations, last_save_seq, start_year, autopilot)


def company_managed_years(parquet_dir: Path, registry_dir: Path) -> dict[str, frozenset[int]]:
    """Return each park's managed company years (spec section 5); parks with none are absent."""
    inputs = read_managed_inputs(parquet_dir, registry_dir)
    return managed_years_by_park(
        inputs.days,
        inputs.registrations,
        inputs.last_save_seq,
        inputs.session_start_year,
        autopilot_sessions=inputs.autopilot_sessions,
    )


def played_game_days(parquet_dir: Path) -> dict[str, int]:
    """Return each park's played game days: distinct game dates in its ``park_snapshot`` rows.

    Counts over all the park's converted sessions. A park with no row, or no
    ``park_snapshot.parquet`` file, is absent: read it with ``.get(park, 0)``.
    """
    snapshots = table(parquet_dir, "park_snapshot")
    if not snapshots.is_file():
        return {}
    with duckdb.connect(":memory:") as connection:
        rows = connection.execute(
            "SELECT park_id, count(DISTINCT (game_year, game_month, game_day))"
            " FROM read_parquet(?) GROUP BY park_id",
            [str(snapshots)],
        ).fetchall()
    return {str(park): int(count) for park, count in rows}


def waiting_parks(parquet_dir: Path, registry_dir: Path) -> list[tuple[str, str]]:
    """Return (park ID, park name) of each converted park the registry does not list, by ID.

    The name is the park's latest ``session_start`` name (ties by session ID).
    """
    registered = registry_feed.latest_rows(registry_dir / LANDING_FOLDER)
    with duckdb.connect(":memory:") as connection:
        rows = connection.execute(
            "SELECT park_id, park_name FROM read_parquet(?) QUALIFY row_number() OVER ("
            " PARTITION BY park_id ORDER BY emitted_at DESC, session_id DESC) = 1"
            " ORDER BY park_id",
            [str(table(parquet_dir, "session_start"))],
        ).fetchall()
    return [(str(park), str(name)) for park, name in rows if park not in registered]


def landed_autopilot_sessions(parquet_dir: Path, registry_dir: Path, park_id: str) -> list[str]:
    """Return the park's ``autopilot`` sessions whose ``session_start`` is converted, sorted.

    A label row whose session is not in ``session_start.parquet`` is not a landed session.
    """
    converted = converted_sessions(parquet_dir)
    labels = play_mode_feed.read_labels(registry_dir)
    return sorted(
        session
        for session, label in labels.items()
        if label.park_id == park_id
        and label.play_mode == play_mode_feed.AUTOPILOT
        and session in converted
    )

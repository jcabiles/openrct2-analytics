"""Company years and the autopilot year rule: pure logic over plain values.

A park's company year is its ``company_start_year`` plus the game years played since its
``game_year_origin``. A managed day is a ``park_snapshot`` of a registered company park that the
player played and saved; a 1 March managed day closes the year before when its session was
already playing in that year. The verdict decides whether one park may run a company year that
another park has played by hand. The callers read the inputs from converted Parquet and the
registry and pass them in; nothing here reads a file.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from enum import StrEnum

# In the game's date, month 0 is March, so 1 March is month 0, day 1.
YEAR_END_MONTH = 0
YEAR_END_DAY = 1


class Verdict(StrEnum):
    """Whether a park may run a company year; the refusals carry the spec's numbers."""

    ALLOWED = "allowed"
    REFUSAL_17A = "17a"
    REFUSAL_17B = "17b"


@dataclass(frozen=True)
class Registration:
    """A park's latest registry row, as the year rules need it."""

    company_start_year: int
    game_year_origin: int
    practice: bool = False


@dataclass(frozen=True)
class SnapshotDay:
    """One ``park_snapshot``: the park and session it belongs to, its ``seq`` and game date."""

    park_id: str
    session_id: str
    seq: int
    game_year: int
    game_month: int
    game_day: int


def company_year(game_year: int, company_start_year: int, game_year_origin: int) -> int:
    """Return the company year of ``game_year`` for a park with this start year and origin."""
    return company_start_year + (game_year - game_year_origin)


def managed_years_by_park(
    days: Iterable[SnapshotDay],
    registrations: Mapping[str, Registration],
    last_save_seq: Mapping[str, int],
    session_start_year: Mapping[str, int],
    *,
    autopilot_sessions: AbstractSet[str] = frozenset(),
) -> dict[str, frozenset[int]]:
    """Return each registered company park's company years that hold a managed day.

    A day counts when its park is registered and not a practice park, its session is not an
    ``autopilot`` session, and its ``seq`` is at or below the session's last ``save_written``
    ``seq`` (``last_save_seq``; a session with no save has no managed day). A 1 March day of game
    year g counts toward g - 1 when its session also has a managed day in g - 1 or its
    ``session_start`` is dated in g - 1 (``session_start_year`` holds that game year); a session
    loaded from a late-October save emits no ``park_snapshot`` before 1 March. Every other day
    counts toward its own game year. Parks with no managed day are absent.
    """
    managed = [
        day
        for day in days
        if day.park_id in registrations
        and not registrations[day.park_id].practice
        and day.session_id not in autopilot_sessions
        and day.session_id in last_save_seq
        and day.seq <= last_save_seq[day.session_id]
    ]
    played_years: dict[str, set[int]] = {}
    for day in managed:
        played_years.setdefault(day.session_id, set()).add(day.game_year)
    years: dict[str, set[int]] = {}
    for day in managed:
        game_year = day.game_year
        if (day.game_month, day.game_day) == (YEAR_END_MONTH, YEAR_END_DAY) and (
            game_year - 1 in played_years[day.session_id]
            or session_start_year.get(day.session_id) == game_year - 1
        ):
            game_year -= 1
        registration = registrations[day.park_id]
        years.setdefault(day.park_id, set()).add(
            company_year(game_year, registration.company_start_year, registration.game_year_origin)
        )
    return {park: frozenset(found) for park, found in years.items()}


def latest_company_year(managed_years: AbstractSet[int]) -> int | None:
    """Return the latest of a park's managed company years, or None when it has none."""
    return max(managed_years, default=None)


def autopilot_verdict(
    park_id: str, target_year: int, managed_years: Mapping[str, AbstractSet[int]]
) -> Verdict:
    """Return whether ``park_id`` may run company year ``target_year``.

    ``managed_years`` is the result of ``managed_years_by_park``. The park may run when it has no
    managed day in the year (else 17b) and some other park has one (else 17a).
    """
    if target_year in managed_years.get(park_id, frozenset()):
        return Verdict.REFUSAL_17B
    others = (years for park, years in managed_years.items() if park != park_id)
    if any(target_year in years for years in others):
        return Verdict.ALLOWED
    return Verdict.REFUSAL_17A

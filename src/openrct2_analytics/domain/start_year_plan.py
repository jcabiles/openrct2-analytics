"""The company start-year plan: pure logic over plain values.

A company park's start year is the year after the floor F, where F is the largest, over the
registered company parks, of a park's start year and its latest managed company year. Managed
days count only for registered parks, so park n's year cannot be read before parks 1 to n-1 are
registered. ``plan_years`` therefore adds each earlier park's planned registration to the
registrations it passes on. The callers read the inputs and pass them in; nothing here reads a
file.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass

from openrct2_analytics.domain.company_years import (
    Registration,
    SnapshotDay,
    latest_company_year,
    managed_years_by_park,
)

FIRST_START_YEAR = 2000


@dataclass(frozen=True)
class Planned:
    """One park's planned registration: its start year, game year origin and Sandbox flag.

    A Sandbox park (``practice``) takes no year; its year is ``FIRST_START_YEAR``, as registration
    writes it.
    """

    park_id: str
    company_start_year: int
    game_year_origin: int
    practice: bool = False


def floor_year(
    start_years: Mapping[str, int], managed: Mapping[str, frozenset[int]]
) -> tuple[int, str]:
    """Return F and the park that sets it (the lowest park ID on a tie).

    A park's year is the larger of its start year and its latest managed company year.
    ``start_years`` holds the registered company parks and must not be empty.
    """
    years = {
        park: max(start, latest_company_year(managed.get(park, frozenset())) or start)
        for park, start in start_years.items()
    }
    floor = max(years.values())
    return floor, min(park for park in years if years[park] == floor)


def plan_years(
    order: Sequence[tuple[str, int, bool]],
    registrations: Mapping[str, Registration],
    *,
    days: Iterable[SnapshotDay],
    last_save_seq: Mapping[str, int],
    session_start_year: Mapping[str, int],
    autopilot_sessions: AbstractSet[str] = frozenset(),
) -> list[Planned]:
    """Return the planned registration of each park in ``order``.

    ``order`` holds (park, game year origin, practice flag). The first company park gets
    ``FIRST_START_YEAR``; every later one gets F + 1, with each earlier park of ``order`` counted
    as registered, built as the registry row is written (company data set). A Sandbox park (practice
    flag true) takes no year (``FIRST_START_YEAR``) and counts as a practice park, so its days never
    move F. ``days``, ``last_save_seq``, ``session_start_year`` and ``autopilot_sessions`` are the
    year rule's inputs, as ``managed_years.ManagedInputs`` holds.
    """
    registered = dict(registrations)
    days = list(days)
    planned: list[Planned] = []
    for park, origin, practice in order:
        company = {
            found: row.company_start_year for found, row in registered.items() if not row.practice
        }
        if company:
            managed = managed_years_by_park(
                days,
                registered,
                last_save_seq,
                session_start_year,
                autopilot_sessions=autopilot_sessions,
            )
            year = floor_year(company, managed)[0] + 1
        else:
            year = FIRST_START_YEAR
        if practice:
            year = FIRST_START_YEAR
        planned.append(Planned(park, year, origin, practice))
        registered[park] = Registration(year, origin, practice)
    return planned

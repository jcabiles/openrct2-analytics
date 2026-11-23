"""Tests for the company-year rules and the autopilot year verdict, on plain values.

Park 1 has origin 1 and start year 2000 (Y); Park 2 has origin 1 and start year 2001 (Y + 1).
Game months count from March = 0, so 1 March is month 0, day 1 and 31 October is month 7, day 31.
Every expected year is a literal from the spec's year-rules table (section 5).
"""

from __future__ import annotations

from openrct2_analytics.domain.company_years import (
    Registration,
    SnapshotDay,
    Verdict,
    autopilot_verdict,
    company_year,
    latest_company_year,
    managed_years_by_park,
)

MARCH, JULY, OCTOBER = 0, 4, 7
PARK_1 = Registration(company_start_year=2000, game_year_origin=1)
PARK_2 = Registration(company_start_year=2001, game_year_origin=1)
REGISTRY = {"park-1": PARK_1, "park-2": PARK_2}


def day(
    seq: int, year: int, month: int, number: int, *, park: str = "park-1", session: str = "s1"
) -> SnapshotDay:
    return SnapshotDay(park, session, seq, year, month, number)


def first_session() -> list[SnapshotDay]:
    """Park 1 plays game year 1 and reaches 1 March of game year 2 (seq 900); save 905 follows."""
    return [day(100, 1, JULY, 1), day(900, 2, MARCH, 1)]


def test_company_year_adds_the_years_played_since_the_origin() -> None:
    assert company_year(2, 2000, 1) == 2001
    assert company_year(5, 2020, 3) == 2022


def test_a_day_after_the_sessions_last_save_never_counts() -> None:
    days = [*first_session(), day(910, 2, MARCH, 2)]

    years = managed_years_by_park(days, REGISTRY, {"s1": 905}, {"s1": 1})

    assert years == {"park-1": frozenset({2000})}
    assert latest_company_year(years["park-1"]) == 2000


def test_a_day_after_the_last_save_counts_when_the_save_is_later() -> None:
    days = [*first_session(), day(910, 2, MARCH, 2)]

    years = managed_years_by_park(days, REGISTRY, {"s1": 915}, {"s1": 1})

    assert years == {"park-1": frozenset({2000, 2001})}


def test_a_session_with_no_save_has_no_managed_day() -> None:
    assert managed_years_by_park(first_session(), REGISTRY, {}, {"s1": 1}) == {}


def test_a_session_that_ends_on_1_march_closes_the_year_before() -> None:
    years = managed_years_by_park(first_session(), REGISTRY, {"s1": 905}, {"s1": 1})

    assert years == {"park-1": frozenset({2000})}
    assert latest_company_year(years["park-1"]) == 2000


def test_a_session_that_starts_on_1_march_counts_that_day_toward_its_own_year() -> None:
    second = [day(1, 2, MARCH, 1, session="s2"), day(200, 2, MARCH, 20, session="s2")]

    years = managed_years_by_park(
        [*first_session(), *second], REGISTRY, {"s1": 905, "s2": 210}, {"s1": 1, "s2": 2}
    )

    assert years == {"park-1": frozenset({2000, 2001})}
    assert latest_company_year(years["park-1"]) == 2001


def test_a_session_that_starts_and_ends_on_1_march_counts_toward_its_own_year() -> None:
    days = [day(1, 2, MARCH, 1)]

    years = managed_years_by_park(days, REGISTRY, {"s1": 5}, {"s1": 2})

    assert years == {"park-1": frozenset({2001})}


def test_a_session_resumed_from_31_october_closes_the_year_before() -> None:
    days = [day(40, 2, MARCH, 1)]

    years = managed_years_by_park(days, REGISTRY, {"s1": 45}, {"s1": 1})

    assert years == {"park-1": frozenset({2000})}
    assert latest_company_year(years["park-1"]) == 2000


def test_the_same_session_started_on_1_march_of_the_year_counts_it_toward_that_year() -> None:
    days = [day(40, 2, MARCH, 1)]

    years = managed_years_by_park(days, REGISTRY, {"s1": 45}, {"s1": 2})

    assert years == {"park-1": frozenset({2001})}


def test_a_session_resumed_from_31_october_without_a_session_start_row_counts_toward_its_year() -> (
    None
):
    days = [day(40, 2, MARCH, 1)]

    assert managed_years_by_park(days, REGISTRY, {"s1": 45}, {}) == {"park-1": frozenset({2001})}


def test_park_2_first_session_from_1_march_of_game_year_1_counts_toward_company_year_y_plus_1() -> (
    None
):
    days = [day(1, 1, MARCH, 1, park="park-2"), day(90, 1, MARCH, 10, park="park-2")]

    years = managed_years_by_park(days, REGISTRY, {"s1": 95}, {"s1": 1})

    assert years == {"park-2": frozenset({2001})}


def test_a_park_that_plays_several_years_closes_each_year_on_the_next_1_march() -> None:
    days = [
        day(1, 1, MARCH, 1),
        day(50, 1, JULY, 1),
        day(100, 2, MARCH, 1),
        day(150, 2, JULY, 1),
        day(200, 3, MARCH, 1),
        day(250, 3, JULY, 1),
        day(300, 4, MARCH, 1),
    ]

    years = managed_years_by_park(days, REGISTRY, {"s1": 305}, {"s1": 1})

    assert years == {"park-1": frozenset({2000, 2001, 2002})}
    assert latest_company_year(years["park-1"]) == 2002


def test_a_session_that_skips_a_year_counts_a_1_march_toward_its_own_year() -> None:
    # No day in game year 2 and a session_start in game year 1: the 1 March of year 3 stays in 3.
    days = [day(100, 1, JULY, 1), day(200, 3, MARCH, 1)]

    years = managed_years_by_park(days, REGISTRY, {"s1": 205}, {"s1": 1})

    assert years == {"park-1": frozenset({2000, 2002})}


def test_an_autopilot_session_never_counts_as_managed() -> None:
    managed = [*first_session()]
    autopilot = [day(1, 2, JULY, 1, session="auto"), day(50, 2, JULY, 2, session="auto")]
    saves = {"s1": 905, "auto": 60}

    both = managed_years_by_park(
        [*managed, *autopilot],
        REGISTRY,
        saves,
        {"s1": 1, "auto": 2},
        autopilot_sessions=frozenset(),
    )
    labeled = managed_years_by_park(
        [*managed, *autopilot],
        REGISTRY,
        saves,
        {"s1": 1, "auto": 2},
        autopilot_sessions=frozenset({"auto"}),
    )

    assert both == {"park-1": frozenset({2000, 2001})}
    assert labeled == {"park-1": frozenset({2000})}


def test_a_practice_park_is_never_a_managed_park() -> None:
    registry = {"park-1": PARK_1, "park-2": Registration(2001, 1, practice=True)}
    days = [*first_session(), day(5, 1, JULY, 1, park="park-2", session="s2")]

    years = managed_years_by_park(days, registry, {"s1": 905, "s2": 9}, {"s1": 1, "s2": 1})

    assert years == {"park-1": frozenset({2000})}


def test_an_unregistered_park_is_never_a_managed_park() -> None:
    days = [*first_session(), day(5, 1, JULY, 1, park="park-2", session="s2")]

    years = managed_years_by_park(days, {"park-1": PARK_1}, {"s1": 905, "s2": 9}, {"s1": 1})

    assert years == {"park-1": frozenset({2000})}


def test_latest_company_year_is_none_without_a_managed_day() -> None:
    assert latest_company_year(frozenset()) is None


def roadmap_1() -> dict[str, frozenset[int]]:
    """Park 1 managed to its save on 1 March of game year 2; Park 2 is registered, no session."""
    return managed_years_by_park(first_session(), REGISTRY, {"s1": 905}, {"s1": 1})


def test_roadmap_1_park_1_is_refused_y_plus_1_until_park_2_has_a_managed_day() -> None:
    assert autopilot_verdict("park-1", 2001, roadmap_1()) is Verdict.REFUSAL_17A


def test_roadmap_2_park_1_may_run_y_plus_1_once_park_2_has_a_managed_day_in_it() -> None:
    days = [*first_session(), day(5, 1, JULY, 1, park="park-2", session="s2")]

    years = managed_years_by_park(days, REGISTRY, {"s1": 905, "s2": 9}, {"s1": 1, "s2": 1})

    assert years == {"park-1": frozenset({2000}), "park-2": frozenset({2001})}
    assert autopilot_verdict("park-1", 2001, years) is Verdict.ALLOWED


def test_roadmap_3_park_1_is_refused_y_plus_2_while_park_2_has_managed_days_only_in_y_plus_1() -> (
    None
):
    autopilot = [
        day(1, 2, JULY, 1, session="auto"),
        day(80, 3, MARCH, 1, session="auto"),
    ]
    park_2 = [day(5, 1, JULY, 1, park="park-2", session="s2")]

    years = managed_years_by_park(
        [*first_session(), *autopilot, *park_2],
        REGISTRY,
        {"s1": 905, "auto": 85, "s2": 9},
        {"s1": 1, "auto": 2, "s2": 1},
        autopilot_sessions=frozenset({"auto"}),
    )

    assert years == {"park-1": frozenset({2000}), "park-2": frozenset({2001})}
    assert autopilot_verdict("park-1", 2002, years) is Verdict.REFUSAL_17A


def test_a_park_that_is_itself_the_managed_park_of_the_year_is_refused_17b() -> None:
    days = [
        *first_session(),
        day(920, 2, JULY, 1),
        day(5, 1, JULY, 1, park="park-2", session="s2"),
    ]

    years = managed_years_by_park(days, REGISTRY, {"s1": 925, "s2": 9}, {"s1": 1, "s2": 1})

    assert years == {"park-1": frozenset({2000, 2001}), "park-2": frozenset({2001})}
    assert autopilot_verdict("park-1", 2001, years) is Verdict.REFUSAL_17B


def test_a_parks_own_managed_days_never_let_it_run() -> None:
    days = [*first_session(), day(920, 2, JULY, 1)]

    years = managed_years_by_park(days, REGISTRY, {"s1": 925}, {"s1": 1})

    assert autopilot_verdict("park-1", 2001, years) is Verdict.REFUSAL_17B


def test_a_practice_park_never_counts_as_the_other_park() -> None:
    registry = {"park-1": PARK_1, "park-2": Registration(2001, 1, practice=True)}
    days = [*first_session(), day(5, 1, JULY, 1, park="park-2", session="s2")]

    years = managed_years_by_park(days, registry, {"s1": 905, "s2": 9}, {"s1": 1, "s2": 1})

    assert autopilot_verdict("park-1", 2001, years) is Verdict.REFUSAL_17A


def test_an_unregistered_park_never_counts_as_the_other_park() -> None:
    days = [*first_session(), day(5, 1, JULY, 1, park="park-2", session="s2")]

    years = managed_years_by_park(days, {"park-1": PARK_1}, {"s1": 905, "s2": 9}, {"s1": 1})

    assert autopilot_verdict("park-1", 2001, years) is Verdict.REFUSAL_17A


def test_an_autopilot_session_never_counts_as_the_other_parks_managed_day() -> None:
    park_2 = [day(5, 1, JULY, 1, park="park-2", session="auto")]

    years = managed_years_by_park(
        [*first_session(), *park_2],
        REGISTRY,
        {"s1": 905, "auto": 9},
        {"s1": 1, "auto": 1},
        autopilot_sessions=frozenset({"auto"}),
    )

    assert autopilot_verdict("park-1", 2001, years) is Verdict.REFUSAL_17A

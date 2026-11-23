"""The company start-year plan: the pure rules, then ``plan_start_years`` on planted files.

Expected years are literals: the first company park starts in 2000, and each later park in the
year after the floor F. Game months count from March = 0.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openrct2_analytics.domain.company_years import Registration, SnapshotDay
from openrct2_analytics.domain.start_year_plan import Planned, floor_year, plan_years
from openrct2_analytics.ingest import register_parks
from openrct2_analytics.ingest.registry_feed import PRACTICE_NOTE
from openrct2_analytics.ingest.start_year import Refused, next_start_year, plan_start_years
from tests.test_register_parks_start_year import (
    TODAY,
    World,
    _first_park,
    later_year,
    park_one,
    plant,
)


def _days(park: str, session: str, *dates: tuple[int, int, int]) -> list[SnapshotDay]:
    return [SnapshotDay(park, session, seq, *date) for seq, date in enumerate(dates, start=2)]


def test_plan_gives_each_later_company_park_the_year_after_the_previous() -> None:
    # Park 1 is registered (2000), played through 1 March of game year 2 and saved: F = 2000.
    # Park 2 has a managed day in game year 1.
    days = _days("park-1", "s1", (1, 0, 2), (1, 7, 31), (2, 0, 1)) + _days(
        "park-2", "s2", (1, 3, 1)
    )
    plan = plan_years(
        [("park-2", 1, False), ("park-3", 1, False)],
        {"park-1": Registration(2000, 1)},
        days=days,
        last_save_seq={"s1": 5, "s2": 3},
        session_start_year={},
    )
    # Park 3 counts park 2 (planned 2001, with a managed day in 2001) as registered: F = 2001.
    assert plan == [Planned("park-2", 2001, 1), Planned("park-3", 2002, 1)]


def test_plan_starts_the_first_company_park_in_2000() -> None:
    plan = plan_years(
        [("park-1", 1, False), ("park-2", 1, False)],
        {},
        days=[],
        last_save_seq={},
        session_start_year={},
    )
    assert plan == [Planned("park-1", 2000, 1), Planned("park-2", 2001, 1)]


@pytest.mark.parametrize(
    ("start_years", "managed", "expected"),
    [
        pytest.param(
            {"park-1": 2000, "park-2": 2001},
            {"park-1": frozenset({2000, 2002})},
            (2002, "park-1"),
            id="managed-year-beats-a-later-start",
        ),
        pytest.param(
            {"park-1": 2000, "park-2": 2003},
            {"park-1": frozenset({2000})},
            (2003, "park-2"),
            id="start-year-sets-the-floor",
        ),
        pytest.param(
            {"park-1": 2001, "park-2": 2001},
            {},
            (2001, "park-1"),
            id="tie-goes-to-the-lowest-park-id",
        ),
    ],
)
def test_floor_year_names_the_park_that_sets_the_floor(
    start_years: dict[str, int], managed: dict[str, frozenset[int]], expected: tuple[int, str]
) -> None:
    assert floor_year(start_years, managed) == expected


def _unconverted(root: Path) -> None:
    raw = root / "company" / "raw" / "v1" / "events-2026-11-13.jsonl"
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps({"session_id": "s9", "park_id": "park-2"}) + "\n")


def test_plan_start_years_plans_from_files(tmp_path: Path) -> None:
    plant(tmp_path / "data", park_one())
    assert plan_start_years(tmp_path, [("park-2", False)]) == [Planned("park-2", 2001, 1)]


@pytest.mark.parametrize("registered", [False, True], ids=["empty-registry", "registered-park"])
def test_plan_start_years_refuses_an_unconverted_raw_session_with_an_empty_registry(
    tmp_path: Path, registered: bool
) -> None:
    plant(tmp_path / "data", park_one() if registered else _first_park(1))
    assert plan_start_years(
        tmp_path, [("park-2", False)]
    )  # the valid input: no raw file, no refusal
    _unconverted(tmp_path / "data")
    with pytest.raises(Refused) as caught:
        plan_start_years(tmp_path, [("park-2", False)])
    assert caught.value.reason == "not-converted"
    assert caught.value.detail == (
        "events-2026-11-13.jsonl holds a session that was never converted, so the latest "
        "managed year is unknown; run make convert DATA_SET=company first"
    )


def test_plan_start_years_refuses_a_later_park_not_from_game_year_1(tmp_path: Path) -> None:
    world = _first_park(1)
    world["sessions"].append(("park-3", "s3", (1, 0, 1), 4))
    plant(tmp_path / "data", world)
    assert plan_start_years(tmp_path, [("park-2", False), ("park-3", False)]) == [
        Planned("park-2", 2000, 1),
        Planned("park-3", 2001, 1),
    ]
    world["sessions"][1] = ("park-3", "s3", (9, 0, 1), 4)
    plant(tmp_path / "data", world)
    with pytest.raises(Refused) as caught:
        plan_start_years(tmp_path, [("park-2", False), ("park-3", False)])
    assert caught.value.reason == "start-year-origin"
    assert caught.value.detail == (
        "Park park-3 has game-year origin 9; a company start year needs a park that began in "
        "game year 1, so capture the park from a new game before registering it"
    )


def test_plan_start_years_lets_the_first_company_park_start_from_another_origin(
    tmp_path: Path,
) -> None:
    plant(tmp_path / "data", _first_park(9))
    assert plan_start_years(tmp_path, [("park-2", False)]) == [Planned("park-2", 2000, 9)]


def _real_next_year(root: Path) -> int | None:
    """The year ``next_start_year`` gives for the registry and Parquet planted under ``root``."""
    folder = root / "data" / "company"
    return next_start_year(folder / "registry" / "v1", folder / "parquet", folder / "raw")


def _plan_park_2(root: Path, world: World) -> int:
    """Plant ``world`` and return park 2's planned year, which must be the real next year."""
    plant(root / "data", world)
    planned = plan_start_years(root, [("park-2", False)])[0].company_start_year
    assert planned == _real_next_year(root)
    return planned


@pytest.mark.parametrize("missing", ["park_snapshot", "save_written"])
def test_plan_start_years_counts_a_registered_park_when_a_managed_day_file_is_missing(
    tmp_path: Path, missing: str
) -> None:
    world = park_one()
    assert _plan_park_2(tmp_path, world) == 2001  # both files present
    if missing == "save_written":
        world["saves"] = []
    else:
        world["days"] = []
    assert _plan_park_2(tmp_path, world) == 2001  # park 1 is still registered


def test_plan_counts_a_simulated_parks_managed_year_toward_the_next_park() -> None:
    # Park 2 plans 2001 and is managed on a day in its game year 2, which is company year 2002.
    plan = plan_years(
        [("park-2", 1, False), ("park-3", 1, False)],
        {"park-1": Registration(2000, 1)},
        days=_days("park-2", "s2", (2, 3, 1)),
        last_save_seq={"s2": 3},
        session_start_year={},
    )
    assert plan == [Planned("park-2", 2001, 1), Planned("park-3", 2003, 1)]


def test_plan_start_years_gives_a_first_park_from_game_year_9_its_own_origin_for_the_next_park(
    tmp_path: Path,
) -> None:
    # Park 1 starts in game year 9 (company year 2000) and is managed there; park 2 begins in 1.
    world = _first_park(9)
    world["sessions"] = [("park-1", "s1", (9, 0, 1), 0), ("park-2", "s2", (1, 0, 1), 2)]
    world["days"] = [("park-1", "s1", 2, (9, 3, 1))]
    world["saves"] = [("park-1", "s1", 3, (9, 3, 1))]
    plant(tmp_path / "data", world)
    assert plan_start_years(tmp_path, [("park-1", False), ("park-2", False)]) == [
        Planned("park-1", 2000, 9),
        Planned("park-2", 2001, 1),
    ]


def test_plan_start_years_leaves_out_an_autopilot_session(tmp_path: Path) -> None:
    world = later_year(park_one())  # a second session of park 1 is managed in 2001
    assert _plan_park_2(tmp_path, world) == 2002
    world["labels"] = [("s1b", "park-1", "autopilot", "", "company", "2026-11-12")]
    assert _plan_park_2(tmp_path, world) == 2001


def test_plan_start_years_leaves_out_an_unsaved_tail(tmp_path: Path) -> None:
    world = later_year(park_one())  # park 1 is saved in company year 2001
    world["days"].append(("park-1", "s1b", 5, (3, 0, 5)))
    world["saves"].append(("park-1", "s1b", 6, (3, 0, 5)))
    assert _plan_park_2(tmp_path, world) == 2003  # the day in game year 3 is saved
    world["saves"].pop()
    assert _plan_park_2(tmp_path, world) == 2002  # the day after the last save does not count


def test_plan_start_years_closes_the_year_before_for_a_session_resumed_from_october(
    tmp_path: Path,
) -> None:
    # The session starts on 31 October of game year 1; its only day is 1 March of game year 2.
    world = park_one()
    world["sessions"][0] = ("park-1", "s1", (1, 7, 31), 0)
    world["days"] = [("park-1", "s1", 2, (2, 0, 1))]
    world["saves"] = [("park-1", "s1", 3, (2, 0, 1))]
    assert _plan_park_2(tmp_path, world) == 2001


def test_plan_start_years_does_not_count_a_practice_registration(tmp_path: Path) -> None:
    world = park_one()
    world["registry"].append(("park-3", 2005, 1, "company", "", "2026-11-12"))
    assert _plan_park_2(tmp_path, world) == 2006  # a company park starting in 2005 sets F
    world["registry"][1] = ("park-3", 2005, 1, "company", PRACTICE_NOTE, "2026-11-12")
    assert _plan_park_2(tmp_path, world) == 2001


def test_plan_start_years_does_not_count_a_row_of_another_data_set(tmp_path: Path) -> None:
    world = park_one()
    world["registry"].append(("park-3", 2005, 1, "company", "", "2026-11-12"))
    assert _plan_park_2(tmp_path, world) == 2006
    world["registry"][1] = ("park-3", 2005, 1, "rehearsal", "", "2026-11-12")
    assert _plan_park_2(tmp_path, world) == 2001


def _sandbox_world(origin: int, saved_in_game_year: int) -> World:
    """Park 2 and park 4 wait as company parks; park 3 waits and is saved once."""
    world = park_one()
    world["sessions"] += [("park-3", "s3", (origin, 0, 1), 4), ("park-4", "s4", (1, 0, 1), 6)]
    world["days"].append(("park-3", "s3", 2, (saved_in_game_year, 3, 1)))
    world["saves"].append(("park-3", "s3", 3, (saved_in_game_year, 3, 1)))
    return world


def test_plan_start_years_takes_a_sandbox_park_from_game_year_9_without_an_origin_check(
    tmp_path: Path,
) -> None:
    plant(tmp_path / "data", _sandbox_world(9, 9))
    order = [("park-2", False), ("park-3", False)]
    with pytest.raises(Refused) as caught:
        plan_start_years(tmp_path, order)
    assert caught.value.reason == "start-year-origin"  # as a company park it is refused
    assert plan_start_years(tmp_path, [("park-2", False), ("park-3", True)]) == [
        Planned("park-2", 2001, 1),
        Planned("park-3", 2000, 9, True),
    ]


def test_plan_start_years_does_not_move_the_next_company_park_for_a_sandbox_park(
    tmp_path: Path,
) -> None:
    # Park 3 is saved in its game year 3; as a company park it would set F to 2002.
    plant(tmp_path / "data", _sandbox_world(1, 3))
    plan = plan_start_years(tmp_path, [("park-2", False), ("park-3", True), ("park-4", False)])
    assert plan == [
        Planned("park-2", 2001, 1),
        Planned("park-3", 2000, 1, True),
        Planned("park-4", 2002, 1),
    ]


def test_plan_start_years_gives_a_bad_registry_row_the_registration_refusal(
    tmp_path: Path,
) -> None:
    plant(tmp_path / "data", park_one())
    assert plan_start_years(tmp_path, [("park-2", False)])  # the valid input
    delivery = tmp_path / "data" / "company" / "registry" / "v1" / "park_registry_2026-11-12_01.csv"
    delivery.write_text(delivery.read_text().replace("park-1,2000,", "park-1,,"))
    with pytest.raises(Refused) as caught:
        register_parks.check_registrations(tmp_path, TODAY, 1)
    expected = caught.value.detail
    with pytest.raises(Refused) as planned:
        plan_start_years(tmp_path, [("park-2", False)])
    assert planned.value.reason == "registry-check"
    assert planned.value.detail == expected
    assert planned.value.detail == (
        "test overall result: failed; test Check that field company_start_year has no missing "
        "values: failed (Actual missing_count(company_start_year) was 1, expected = 0); "
        "park_registry_2026-11-12_01.csv: test overall result: failed; "
        "park_registry_2026-11-12_01.csv: test Check that field company_start_year has no "
        "missing values: failed (Actual missing_count(company_start_year) was 1, expected = 0)"
    )

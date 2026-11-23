"""Tests for the managed-years reader, on planted Parquet, registry and label files.

Park A has origin 1 and start year 2000. Game months count from March = 0. Expected years are
literals: company year = 2000 + (game year - 1).
"""

from __future__ import annotations

from pathlib import Path

from openrct2_analytics.domain.company_years import Registration, latest_company_year
from openrct2_analytics.ingest import managed_years
from openrct2_analytics.ingest.registry_feed import PRACTICE_NOTE
from tests.autopilot_fixtures import (
    Row,
    event_row,
    plant_label,
    plant_park_snapshot,
    plant_registry,
    plant_save_written,
    plant_session_start,
)

JULY, MARCH, OCTOBER = 4, 0, 7
COMPANY = ("park-a", 2000, 1, "company", "", "2026-11-12")


def folders(tmp_path: Path) -> tuple[Path, Path]:
    """Return the Parquet folder and the registry root; ``plant_*`` add the ``v1`` folders."""
    return tmp_path / "parquet", tmp_path / "registry"


def latest_year(parquet: Path, registry: Path, park: str) -> int | None:
    """The park's latest managed company year, from ``company_managed_years``; None if none."""
    years = managed_years.company_managed_years(parquet, registry)
    return latest_company_year(years.get(park, frozenset()))


def snapshot(
    seq: int, date: tuple[int, int, int], *, park: str = "park-a", session: str = "s1"
) -> Row:
    return event_row(seq, park_id=park, session_id=session, game_date=date)


def save(seq: int, *, park: str = "park-a", session: str = "s1") -> Row:
    return event_row(seq, park_id=park, session_id=session, save_id=f"{session}-{seq}")


def start(
    session: str, date: tuple[int, int, int], *, park: str = "park-a", name: str = "Park A"
) -> Row:
    return event_row(
        1, park_id=park, session_id=session, game_date=date, park_name=name, event_id=f"{session}-0"
    )


def plant(
    tmp_path: Path,
    snapshots: list[Row],
    saves: list[Row],
    starts: list[Row],
    *,
    registry: list[tuple[str, int, int, str, str, str]] | None = None,
) -> tuple[Path, Path]:
    parquet, registry_root = folders(tmp_path)
    plant_park_snapshot(parquet, snapshots)
    plant_save_written(parquet, saves)
    plant_session_start(parquet, starts)
    plant_registry(registry_root / "v1", registry if registry is not None else [COMPANY])
    return parquet, registry_root


def test_a_practice_park_and_an_unregistered_park_are_not_managed(tmp_path: Path) -> None:
    parquet, registry = plant(
        tmp_path,
        [
            snapshot(10, (1, JULY, 1)),
            snapshot(10, (1, JULY, 1), park="park-b", session="s2"),
            snapshot(10, (1, JULY, 1), park="park-c", session="s3"),
        ],
        [save(20), save(20, park="park-b", session="s2"), save(20, park="park-c", session="s3")],
        [start("s1", (1, JULY, 1))],
        registry=[COMPANY, ("park-b", 2000, 1, "company", PRACTICE_NOTE, "2026-11-12")],
    )

    assert managed_years.company_managed_years(parquet, registry) == {"park-a": frozenset({2000})}


def test_a_registered_park_with_a_plain_note_is_managed(tmp_path: Path) -> None:
    parquet, registry = plant(
        tmp_path,
        [snapshot(10, (1, JULY, 1), park="park-b", session="s2")],
        [save(20, park="park-b", session="s2")],
        [start("s2", (1, JULY, 1), park="park-b")],
        registry=[("park-b", 2000, 1, "company", "", "2026-11-12")],
    )

    assert managed_years.company_managed_years(parquet, registry) == {"park-b": frozenset({2000})}


def plant_with_autopilot(tmp_path: Path) -> tuple[Path, Path]:
    return plant(
        tmp_path,
        [snapshot(10, (1, JULY, 1)), snapshot(10, (2, JULY, 1), session="auto")],
        [save(20), save(20, session="auto")],
        [start("s1", (1, JULY, 1)), start("auto", (2, JULY, 1))],
    )


def test_an_autopilot_session_is_not_managed(tmp_path: Path) -> None:
    parquet, registry = plant_with_autopilot(tmp_path)
    plant_label(registry / "v1", [("auto", "park-a", "autopilot", "", "company", "2026-11-12")])

    assert managed_years.company_managed_years(parquet, registry) == {"park-a": frozenset({2000})}


def test_with_no_label_file_every_session_is_managed(tmp_path: Path) -> None:
    parquet, registry = plant_with_autopilot(tmp_path)

    assert managed_years.company_managed_years(parquet, registry) == {
        "park-a": frozenset({2000, 2001})
    }


def test_a_managed_label_leaves_the_session_managed(tmp_path: Path) -> None:
    parquet, registry = plant_with_autopilot(tmp_path)
    plant_label(registry / "v1", [("auto", "park-a", "managed", "", "company", "2026-11-12")])

    assert managed_years.company_managed_years(parquet, registry) == {
        "park-a": frozenset({2000, 2001})
    }


def days_after_save(tmp_path: Path, last_save: int) -> tuple[Path, Path]:
    return plant(
        tmp_path,
        [snapshot(10, (1, JULY, 1)), snapshot(30, (2, JULY, 1))],
        [save(last_save)],
        [start("s1", (1, JULY, 1))],
    )


def test_a_day_after_the_sessions_last_save_is_not_managed(tmp_path: Path) -> None:
    parquet, registry = days_after_save(tmp_path, 20)

    assert latest_year(parquet, registry, "park-a") == 2000


def test_a_day_at_or_before_the_sessions_last_save_is_managed(tmp_path: Path) -> None:
    parquet, registry = days_after_save(tmp_path, 30)

    assert latest_year(parquet, registry, "park-a") == 2001


def test_the_last_save_is_taken_per_session(tmp_path: Path) -> None:
    # s2's day (seq 25) is after s1's save (20) but before s2's own save (40).
    parquet, registry = plant(
        tmp_path,
        [snapshot(10, (1, JULY, 1)), snapshot(25, (2, JULY, 1), session="s2")],
        [save(20), save(40, session="s2")],
        [start("s1", (1, JULY, 1)), start("s2", (2, JULY, 1))],
    )

    assert latest_year(parquet, registry, "park-a") == 2001


def test_the_latest_registry_row_wins(tmp_path: Path) -> None:
    parquet, registry = plant(
        tmp_path,
        [snapshot(10, (1, JULY, 1))],
        [save(20)],
        [start("s1", (1, JULY, 1))],
        registry=[COMPANY],
    )
    plant_registry(
        registry / "v1",
        [("park-a", 2010, 1, "company", "", "2026-11-13")],
        name="park_registry_2026-11-13_01.csv",
    )

    assert latest_year(parquet, registry, "park-a") == 2010


def resumed(tmp_path: Path, start_date: tuple[int, int, int]) -> tuple[Path, Path]:
    """A session whose only day is 1 March of game year 2 (seq 40), saved there (seq 45)."""
    return plant(
        tmp_path,
        [snapshot(40, (2, MARCH, 1))],
        [save(45)],
        [start("s1", start_date)],
    )


def test_a_session_resumed_from_a_31_october_save_counts_its_1_march_toward_the_year_before(
    tmp_path: Path,
) -> None:
    parquet, registry = resumed(tmp_path, (1, OCTOBER, 31))

    assert latest_year(parquet, registry, "park-a") == 2000


def test_a_session_started_on_1_march_counts_that_day_toward_its_own_year(tmp_path: Path) -> None:
    parquet, registry = resumed(tmp_path, (2, MARCH, 1))

    assert latest_year(parquet, registry, "park-a") == 2001


def test_a_session_with_a_day_in_the_year_before_closes_it_on_1_march(tmp_path: Path) -> None:
    # Its session_start is dated in game year 1, so only the day in game year 2 closes year 2.
    parquet, registry = plant(
        tmp_path,
        [
            snapshot(10, (1, JULY, 1)),
            snapshot(20, (2, JULY, 1)),
            snapshot(40, (3, MARCH, 1)),
        ],
        [save(45)],
        [start("s1", (1, MARCH, 1))],
    )

    assert latest_year(parquet, registry, "park-a") == 2001


def test_the_latest_managed_year_is_none_for_a_park_without_a_managed_day(tmp_path: Path) -> None:
    parquet, registry = plant(
        tmp_path,
        [snapshot(10, (1, JULY, 1))],
        [save(20)],
        [start("s1", (1, JULY, 1))],
    )

    assert latest_year(parquet, registry, "park-b") is None


def test_the_latest_managed_year_is_none_without_park_snapshot_parquet(tmp_path: Path) -> None:
    parquet, registry = plant(
        tmp_path, [snapshot(10, (1, JULY, 1))], [save(20)], [start("s1", (1, JULY, 1))]
    )
    (parquet / "v1" / "park_snapshot.parquet").unlink()

    assert latest_year(parquet, registry, "park-a") is None


def test_the_latest_managed_year_is_none_without_save_written_parquet(tmp_path: Path) -> None:
    parquet, registry = plant(
        tmp_path, [snapshot(10, (1, JULY, 1))], [save(20)], [start("s1", (1, JULY, 1))]
    )
    (parquet / "v1" / "save_written.parquet").unlink()

    assert latest_year(parquet, registry, "park-a") is None


def test_the_registrations_are_read_when_a_managed_day_file_is_missing(tmp_path: Path) -> None:
    parquet, registry = plant(
        tmp_path, [snapshot(10, (1, JULY, 1))], [save(20)], [start("s1", (1, JULY, 1))]
    )
    registered = {"park-a": Registration(2000, 1, False)}
    assert managed_years.read_managed_inputs(parquet, registry).registrations == registered
    (parquet / "v1" / "save_written.parquet").unlink()
    inputs = managed_years.read_managed_inputs(parquet, registry)
    assert inputs.registrations == registered
    assert inputs.days == []


def test_a_row_of_another_data_set_is_not_a_company_registration(tmp_path: Path) -> None:
    parquet, registry = plant(
        tmp_path,
        [snapshot(10, (1, JULY, 1))],
        [save(20)],
        [start("s1", (1, JULY, 1))],
        registry=[COMPANY, ("park-b", 2000, 1, "rehearsal", "", "2026-11-12")],
    )
    assert set(managed_years.read_managed_inputs(parquet, registry).registrations) == {"park-a"}


def test_a_missing_session_start_parquet_means_no_start_years(tmp_path: Path) -> None:
    parquet, registry = plant(
        tmp_path, [snapshot(10, (1, JULY, 1))], [save(20)], [start("s1", (1, JULY, 1))]
    )
    managed_years.table(parquet, "session_start").unlink()

    assert managed_years.company_managed_years(parquet, registry) == {"park-a": frozenset({2000})}


def test_waiting_parks_lists_converted_parks_the_registry_does_not_list(tmp_path: Path) -> None:
    parquet, registry = plant(
        tmp_path,
        [snapshot(10, (1, JULY, 1))],
        [save(20)],
        [start("s1", (1, JULY, 1)), start("s2", (1, JULY, 1), park="park-b", name="Park B")],
    )

    assert managed_years.waiting_parks(parquet, registry) == [("park-b", "Park B")]


def test_an_orphan_label_row_is_not_a_landed_autopilot_session(tmp_path: Path) -> None:
    parquet, registry = plant(
        tmp_path,
        [snapshot(10, (1, JULY, 1))],
        [save(20)],
        [start("auto-1", (1, JULY, 1))],
    )
    plant_label(
        registry / "v1",
        [
            ("auto-1", "park-a", "autopilot", "", "company", "2026-11-12"),
            ("ghost", "park-a", "autopilot", "", "company", "2026-11-12"),
            ("auto-b", "park-b", "autopilot", "", "company", "2026-11-12"),
        ],
    )

    assert managed_years.landed_autopilot_sessions(parquet, registry, "park-a") == ["auto-1"]


def test_played_game_days_counts_distinct_game_dates(tmp_path: Path) -> None:
    parquet, _ = folders(tmp_path)
    assert managed_years.played_game_days(parquet) == {}  # no park_snapshot file
    plant_park_snapshot(
        parquet,
        [
            snapshot(1, (1, MARCH, 1)),
            snapshot(2, (1, MARCH, 1)),  # the same date again: once
            snapshot(3, (1, JULY, 5)),
            snapshot(1, (1, MARCH, 1), session="s2"),  # a second session on a counted date: once
            snapshot(2, (1, JULY, 6), session="s2"),
            snapshot(1, (1, MARCH, 1), park="park-b", session="s3"),
        ],
    )
    days = managed_years.played_game_days(parquet)
    assert days == {"park-a": 3, "park-b": 1}
    assert days.get("park-c", 0) == 0  # a park with no snapshot row

"""The autopilot source save: newest archive copy by name time, proved against the last record.

Real files in temporary folders. Expected texts are copied from
docs/ai-dlc/specs/autopilot-year.md, section 4, refusals 14 to 16.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest.autopilot_source import SourceFound, SourceRefused, find_source
from openrct2_analytics.ingest.register_parks import NOTE, registered_parks
from openrct2_analytics.ingest.save_backup import park_names
from tests.autopilot_fixtures import (
    event_row,
    plant_archive_copy,
    plant_label,
    plant_paired_save,
    plant_park_snapshot,
    plant_record,
    plant_registry,
    plant_save_written,
    plant_session_start,
)

OLD_SAVE = datetime(2026, 11, 12, 19, 0, 0, tzinfo=UTC)
LAST_SAVE = datetime(2026, 11, 12, 20, 0, 0, tzinfo=UTC)
LAST_RECORDED = LAST_SAVE + timedelta(milliseconds=200)
LAST_SIZE = 7


class World:
    """One company park with two recorded saves and three archive copies."""

    def __init__(self, tmp_path: Path) -> None:
        self.archive = tmp_path / "archive"
        self.parquet = tmp_path / "parquet"
        self.saves = tmp_path / "save_files"
        old = event_row(7, emitted_at=OLD_SAVE, save_id="save-7")
        last = event_row(42, emitted_at=LAST_SAVE, game_date=(10, 9, 14), save_id="save-42")
        self.rows = [
            plant_paired_save(self.saves, old, "Old", 5),
            plant_paired_save(self.saves, last, "Latest", LAST_SIZE),
        ]
        plant_save_written(self.parquet, self.rows)

    def copy(self, label: str, ended: datetime, *, size: int = LAST_SIZE, late: int = 60) -> Path:
        return plant_archive_copy(
            self.archive,
            "park-a",
            label,
            ended,
            data=b"x" * size,
            modified_at=LAST_RECORDED + timedelta(seconds=late),
        )

    def find(self) -> SourceFound | SourceRefused:
        return find_source("park-a", self.archive, self.parquet, self.saves)


@pytest.fixture(name="world")
def world_fixture(tmp_path: Path) -> World:
    return World(tmp_path)


def renamed_copies(world: World) -> Path:
    """Three copies whose full-name order differs from their end-of-name time order."""
    world.copy("Zulu", datetime(2026, 11, 10, 10, 0, 0))
    newest = world.copy("Beta", datetime(2026, 11, 12, 21, 0, 0))
    world.copy("Alpha", datetime(2026, 11, 11, 9, 0, 0))
    return newest


def test_chosen_copy_is_the_newest_by_the_time_at_the_end_of_the_name(world: World) -> None:
    world.copy("Park", datetime(2026, 11, 10, 10, 0, 0))
    newest = world.copy("Park", datetime(2026, 11, 12, 21, 0, 0))
    world.copy("Park", datetime(2026, 11, 11, 9, 0, 0))

    found = world.find()

    assert isinstance(found, SourceFound)
    assert found.file == newest


def test_chosen_copy_after_a_park_rename_is_not_the_last_full_name(world: World) -> None:
    newest = renamed_copies(world)

    found = world.find()

    assert isinstance(found, SourceFound)
    assert found.file == newest


def test_a_matching_copy_returns_the_paired_events_facts(world: World) -> None:
    newest = renamed_copies(world)

    found = world.find()

    assert found == SourceFound(
        file=newest,
        event_id="sess-1-42",
        save_id="save-42",
        session_id="sess-1",
        game_year=10,
        game_month=9,
        game_day=14,
        seq=42,
    )


def test_a_copy_modified_exactly_at_the_record_passes(world: World) -> None:
    world.copy("Beta", datetime(2026, 11, 12, 21, 0, 0), late=0)

    assert isinstance(world.find(), SourceFound)


def test_a_wrong_size_fails_with_refusal_16(world: World) -> None:
    copy = world.copy("Beta", datetime(2026, 11, 12, 21, 0, 0), size=LAST_SIZE + 1)

    assert world.find() == SourceRefused(
        16,
        f"The newest backup of park park-a ({copy}) is not its last recorded save "
        "(Latest.park, recorded 2026-11-12T20:00:00+00:00); starting from it would drop the "
        "play recorded after it. Play and save once with make play DATA_SET=company so a new "
        "backup is made.",
    )


def test_a_matching_size_with_an_older_modified_time_fails_with_refusal_16(world: World) -> None:
    copy = world.copy("Beta", datetime(2026, 11, 12, 21, 0, 0), late=-1)

    assert world.find() == SourceRefused(
        16,
        f"The newest backup of park park-a ({copy}) is not its last recorded save "
        "(Latest.park, recorded 2026-11-12T20:00:00+00:00); starting from it would drop the "
        "play recorded after it. Play and save once with make play DATA_SET=company so a new "
        "backup is made.",
    )


def test_the_proof_ignores_the_time_in_the_copys_name(world: World) -> None:
    """A name time before the recorded save still passes: only size and modified time count."""
    world.copy("Beta", datetime(2026, 11, 12, 1, 0, 0))

    assert isinstance(world.find(), SourceFound)


def test_no_archive_copy_is_refusal_14(world: World, tmp_path: Path) -> None:
    assert world.find() == SourceRefused(
        14,
        f"Park park-a has no backup in {tmp_path}/archive/park-a/. Play and save it with make "
        "play DATA_SET=company, quit normally, and check that the report prints a Backup: line.",
    )


def test_a_non_copy_file_in_the_archive_folder_is_not_a_copy(world: World) -> None:
    (world.archive / "park-a").mkdir(parents=True)
    (world.archive / "park-a" / "notes.txt").write_text("not a save")
    (world.archive / "park-a" / "Beta.park").write_bytes(b"x" * LAST_SIZE)

    refused = world.find()

    assert isinstance(refused, SourceRefused)
    assert refused.number == 14


def test_a_latest_save_with_two_candidate_files_is_refusal_15(world: World) -> None:
    world.copy("Beta", datetime(2026, 11, 12, 21, 0, 0))
    plant_record(
        world.saves,
        "Other",
        LAST_SAVE + timedelta(seconds=1),
        3,
        run_started_at=LAST_SAVE - timedelta(minutes=30),
    )

    assert world.find() == SourceRefused(
        15,
        "The last save of park park-a (recorded 2026-11-12T20:00:00+00:00) was not matched to "
        "exactly one save file, so its last recorded save is unknown. Play and save it once "
        "with make play DATA_SET=company.",
    )


def test_a_latest_save_paired_in_two_runs_is_refusal_15(world: World) -> None:
    world.copy("Beta", datetime(2026, 11, 12, 21, 0, 0))
    again = event_row(42, emitted_at=LAST_SAVE, game_date=(10, 9, 14), save_id="save-42")
    again["received_at"] = LAST_SAVE + timedelta(minutes=10)  # the same event, delivered again
    plant_save_written(world.parquet, [*world.rows, again])
    plant_record(
        world.saves,
        "Latest",
        LAST_SAVE + timedelta(milliseconds=300),
        LAST_SIZE,
        run_started_at=LAST_SAVE + timedelta(minutes=5),
    )

    assert world.find() == SourceRefused(
        15,
        "The last save of park park-a (recorded 2026-11-12T20:00:00+00:00) was not matched to "
        "exactly one save file, so its last recorded save is unknown. Play and save it once "
        "with make play DATA_SET=company.",
    )


def test_a_park_with_no_save_event_is_refusal_15(world: World) -> None:
    world.copy("Beta", datetime(2026, 11, 12, 21, 0, 0))
    plant_save_written(world.parquet, [event_row(1, park_id="park-b", save_id="s")])

    assert world.find() == SourceRefused(
        15,
        "The last save of park park-a (recorded at an unknown time) was not matched to exactly "
        "one save file, so its last recorded save is unknown. Play and save it once with make "
        "play DATA_SET=company.",
    )


def test_the_shared_planters_write_files_the_readers_accept(tmp_path: Path) -> None:
    plant_session_start(tmp_path, [event_row(1, park_name="Crazy Castle")])
    snapshot = plant_park_snapshot(tmp_path, [event_row(2, cash_tenths=500, guests_in_park=3)])
    feed = tmp_path / "registry" / "v1"
    plant_registry(
        feed,
        [
            ("park-a", 2000, 9, "company", "", "2026-11-12"),
            ("park-b", 2000, 9, "company", NOTE, "2026-11-12"),
        ],
    )
    label = plant_label(feed, [("sess-1", "park-a", "autopilot", "", "company", "2026-11-12")])

    assert park_names(tmp_path) == {"park-a": "Crazy Castle"}
    with duckdb.connect(":memory:") as connection:
        found = connection.execute(
            "SELECT cash_tenths FROM read_parquet(?)", [snapshot.as_posix()]
        ).fetchall()
    assert found == [(500,)]
    assert registered_parks(feed) == {"park-a": ("company", False), "park-b": ("company", True)}
    assert label.read_text() == (
        "session_id,park_id,play_mode,ready_confirmation,data_set,delivered_on\n"
        "sess-1,park-a,autopilot,,company,2026-11-12\n"
    )

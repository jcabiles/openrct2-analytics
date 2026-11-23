"""The warning before play: which saves warn, and which backup copy each warning names."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from openrct2_analytics.ingest import save_backup
from openrct2_analytics.ingest.save_backup import warning_lines
from openrct2_analytics.ingest.save_pairing import SaveFileRecord, StartCheck
from tests.test_save_backup import T0, pair, user_fixture, write_park

__all__ = ["user_fixture"]


def start_check(name: str, outcome: str, park: str = "kpark1") -> StartCheck:
    record = SaveFileRecord(T0, "start", name, "save", T0, 1, T0)
    paired_at = T0 - timedelta(minutes=5) if outcome == "changed" else T0
    paired = SaveFileRecord(T0, "created", name, "save", paired_at, 1, T0)
    last = pair(paired, park, 0) if outcome in ("changed", "same") else None
    return StartCheck(record, outcome, last)


def test_warning_names_the_newest_own_copy_of_the_park(user: Path, tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    write_park(archive / "kpark1" / "Crazy Castle-2026-11-08-101010.park", b"own", 1)
    for day, data in (("2026-11-07", b"own"), ("2026-11-08", b"own"), ("2026-11-09", b"played")):
        write_park(user / "save" / f"Crazy Castle-last-plugin-save-{day}.park", data, 1)

    lines = warning_lines(
        [start_check("Crazy Castle", "changed")],
        {"kpark1": "Crazy Castle"},
        user / "save",
        archive,
    )

    assert lines == [
        "Warning: Crazy Castle.park changed after the last recorded save; load "
        "Crazy Castle-last-plugin-save-2026-11-08.park instead."
    ]


def test_warning_names_the_archive_copy_when_no_game_copy_is_its_own(
    user: Path, tmp_path: Path
) -> None:
    archived = tmp_path / "archive" / "kpark1" / "kpark1-2026-11-08-101010.park"
    write_park(archived, b"own", 1)

    lines = warning_lines([start_check("slot", "changed")], {}, user / "save", tmp_path / "archive")

    assert lines == [
        "Warning: slot.park changed after the last recorded save; copy "
        f"{archived} into the game's save folder and load it."
    ]


def test_warning_without_a_backup_says_none_exists(user: Path, tmp_path: Path) -> None:
    lines = warning_lines([start_check("slot", "changed")], {}, user / "save", tmp_path)

    assert lines == [
        "Warning: slot.park changed after the last recorded save; no backup copy of kpark1 "
        "exists yet."
    ]


@pytest.mark.parametrize("outcome", ["same", "none", "lost"])
def test_no_warning_for_an_unchanged_or_never_paired_file(
    user: Path, tmp_path: Path, outcome: str
) -> None:
    assert warning_lines([start_check("slot", outcome)], {}, user / "save", tmp_path) == []


def test_a_file_whose_later_write_lost_its_event_warns(user: Path, tmp_path: Path) -> None:
    paired = SaveFileRecord(T0, "created", "slot", "save", T0, 1, T0)
    start = SaveFileRecord(T0, "start", "slot", "save", T0 + timedelta(minutes=9), 2, T0)
    check = StartCheck(start, "lost", pair(paired, "kpark1", 0))

    lines = warning_lines([check], {}, user / "save", tmp_path)

    assert lines == [
        "Warning: slot.park changed after the last recorded save; no backup copy of kpark1 "
        "exists yet."
    ]


def test_a_dated_copy_saved_over_while_nothing_recorded_warns(user: Path, tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    write_park(archive / "kpark1" / "Crazy Castle-2026-11-08-101010.park", b"own", 1)
    write_park(user / "save" / "Crazy Castle-last-plugin-save-2026-11-08.park", b"own", 1)
    played = "Crazy Castle-last-plugin-save-2026-11-09"
    write_park(user / "save" / f"{played}.park", b"played unrecorded", 1)

    lines = warning_lines(
        [start_check(played, "none")], {"kpark1": "Crazy Castle"}, user / "save", archive
    )

    assert lines == [
        f"Warning: {played}.park was saved over while nothing was recording; load "
        "Crazy Castle-last-plugin-save-2026-11-08.park instead."
    ]


def test_a_dated_copy_this_command_replaced_never_warns(user: Path, tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    write_park(archive / "kpark1" / "Crazy Castle-2026-11-09-201530.park", b"own", 1)
    name = "Crazy Castle-last-plugin-save-2026-11-09"
    write_park(user / "save" / f"{name}.park", b"own", 1)

    lines = warning_lines(
        [start_check(name, "changed")], {"kpark1": "Crazy Castle"}, user / "save", archive
    )

    assert lines == []


def test_an_unreadable_save_folder_gives_a_note_not_a_crash(user: Path, tmp_path: Path) -> None:
    save = user / "save"
    save.chmod(0o000)
    try:
        lines = save_backup.warn_before_play(
            tmp_path / "records",
            tmp_path / "parquet",
            T0,
            game_save_dir=save,
            archive_dir=tmp_path / "archive",
        )
    finally:
        save.chmod(0o700)

    assert lines == [] or lines[0].startswith("Could not check the save files before play:")

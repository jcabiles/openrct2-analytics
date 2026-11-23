"""The last-recorded-save backup and the pre-play warning, with real files in temp folders.

Placeholder ``.park`` files hold test bytes, never game content. Records are built from a real
``stat`` of the file, the way the watcher builds them.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO

import pytest

from openrct2_analytics.ingest import save_backup
from openrct2_analytics.ingest.save_backup import (
    BackupPlan,
    back_up,
    choose,
    file_label,
)
from openrct2_analytics.ingest.save_pairing import (
    RunPairing,
    SaveFileRecord,
    SaveJudgment,
    SavePair,
    SaveWrittenRow,
)

T0 = datetime(2026, 11, 9, 19, 0, 0, tzinfo=UTC)
ENDED = datetime(2026, 11, 9, 20, 15, 30)  # local time the run ended


def write_park(path: Path, data: bytes, modified_ns: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, ns=(modified_ns, modified_ns))


def stat_record(path: Path, kind: str, *, obs: str = "modified") -> SaveFileRecord:
    """A record as the watcher writes it: modified time cut to whole milliseconds."""
    info = path.stat()
    modified = datetime.fromtimestamp(0, UTC) + timedelta(
        milliseconds=info.st_mtime_ns // 1_000_000
    )
    return SaveFileRecord(
        T0, obs, path.name.removesuffix(".park"), kind, modified, info.st_size, T0
    )


def pair(record: SaveFileRecord, park: str, seconds: int, event: str = "") -> SavePair:
    emitted = T0 + timedelta(seconds=seconds)
    row = SaveWrittenRow(
        event or f"e-{park}-{seconds}", "s", park, "sess", emitted, emitted, "raw.jsonl", seconds
    )
    return SavePair(row, record)


def judgment(pairs: list[SavePair], unpaired: tuple[SaveFileRecord, ...] = ()) -> SaveJudgment:
    run = RunPairing(tuple(pairs), (), (), unpaired)
    return SaveJudgment(run, (), (), (), None, False, ())


@pytest.fixture(name="user")
def user_fixture(tmp_path: Path) -> Path:
    user = tmp_path / "user"
    (user / "save" / "autosave").mkdir(parents=True)
    return user


def plan_for(user: Path, tmp_path: Path, remembered: Path | None = None) -> BackupPlan:
    watched = {"save": user / "save", "autosave": user / "save" / "autosave", "parent": user}
    if remembered is not None:
        watched["remembered"] = remembered
    return BackupPlan(watched, user / "save", tmp_path / "archive", tmp_path / "parquet")


def all_files(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file())


def test_choose_takes_each_parks_last_paired_save() -> None:
    a1 = SaveFileRecord(T0, "created", "a1", "save", T0, 1, T0)
    a2 = SaveFileRecord(T0, "created", "a2", "autosave", T0 + timedelta(seconds=9), 1, T0)
    b1 = SaveFileRecord(T0, "created", "b1", "save", T0 + timedelta(seconds=5), 1, T0)
    pairs = [pair(a2, "park-a", 9), pair(a1, "park-a", 1), pair(b1, "park-b", 5)]

    chosen, skipped = choose(RunPairing(tuple(pairs), (), (), ()))

    assert [(p.row.park_id, p.record.file_name) for p in chosen] == [
        ("park-a", "a2"),
        ("park-b", "b1"),
    ]
    assert skipped == []


def test_choose_skips_a_park_with_a_later_unpaired_write_of_its_file() -> None:
    saved = SaveFileRecord(T0, "created", "Crazy", "save", T0, 1, T0)
    later = SaveFileRecord(T0, "modified", "Crazy", "save", T0 + timedelta(minutes=5), 2, T0)

    chosen, skipped = choose(RunPairing((pair(saved, "park-a", 0),), (), (), (later,)))

    assert chosen == []
    assert skipped[0].startswith("No backup made for park park-a: Crazy was written after")


def test_choose_skips_when_another_park_later_saved_over_the_same_file() -> None:
    first = SaveFileRecord(T0, "created", "slot", "save", T0, 1, T0)
    over = SaveFileRecord(T0, "modified", "slot", "save", T0 + timedelta(seconds=30), 2, T0)
    pairs = (pair(first, "park-a", 0), pair(over, "park-b", 30))

    chosen, skipped = choose(RunPairing(pairs, (), (), ()))

    assert [p.row.park_id for p in chosen] == ["park-b"]
    assert len(skipped) == 1 and "park park-a" in skipped[0]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Crazy Castle", "Crazy Castle"),
        ("A/B:C\\D", "A_B_C_D"),
        (".hidden", "_hidden"),
        ("tab\there\x7f", "tab_here_"),
        ("", "kpark1"),
        (None, "kpark1"),
        ("   ", "kpark1"),
    ],
)
def test_file_label_cleans_unsafe_characters_and_falls_back_to_the_park_id(
    name: str | None, expected: str
) -> None:
    assert file_label(name, "kpark1") == expected


@pytest.mark.parametrize("kind", ["save", "autosave", "parent", "remembered"])
def test_back_up_copies_from_each_watched_folder_kind(
    user: Path, tmp_path: Path, kind: str
) -> None:
    remembered = tmp_path / "elsewhere"
    plan = plan_for(user, tmp_path, remembered)
    source = plan.watched[kind] / "slot.park"
    write_park(source, b"recorded bytes", 1_762_714_800_123_456_789)

    lines, ok = back_up(judgment([pair(stat_record(source, kind), "kpark1", 0)]), plan, ENDED)

    assert ok, lines
    game_copy = user / "save" / "kpark1-last-plugin-save-2026-11-09.park"
    archive = tmp_path / "archive" / "kpark1" / "kpark1-2026-11-09-201530.park"
    assert game_copy.read_bytes() == b"recorded bytes" == archive.read_bytes()
    assert lines == [
        "Backup: kpark1's last recorded save (slot) copied to "
        f"save/kpark1-last-plugin-save-2026-11-09.park; archive copy {archive}."
    ]


def test_back_up_names_the_copy_after_the_park(
    user: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(save_backup, "park_names", lambda _parquet: {"kpark1": "Crazy Castle"})
    plan = plan_for(user, tmp_path)
    source = user / "save" / "autosave" / "autosave_2026-11-09_19-12-03.park"
    write_park(source, b"x", 1_762_714_800_000_000_000)

    lines, ok = back_up(judgment([pair(stat_record(source, "autosave"), "kpark1", 0)]), plan, ENDED)

    assert ok
    assert (user / "save" / "Crazy Castle-last-plugin-save-2026-11-09.park").is_file()
    assert lines[0].startswith(
        "Backup: Crazy Castle's last recorded save (autosave_2026-11-09_19-12-03) copied to "
        "save/Crazy Castle-last-plugin-save-2026-11-09.park"
    )


def test_a_second_run_the_same_day_replaces_the_game_copy_but_never_the_archive(
    user: Path, tmp_path: Path
) -> None:
    plan = plan_for(user, tmp_path)
    source = user / "save" / "slot.park"
    write_park(source, b"first", 1_762_714_800_000_000_000)
    assert back_up(judgment([pair(stat_record(source, "save"), "kpark1", 0)]), plan, ENDED)[1]
    write_park(source, b"second", 1_762_714_900_000_000_000)

    later = ENDED + timedelta(hours=1)
    lines, ok = back_up(judgment([pair(stat_record(source, "save"), "kpark1", 0)]), plan, later)

    assert ok, lines
    assert (user / "save" / "kpark1-last-plugin-save-2026-11-09.park").read_bytes() == b"second"
    assert all_files(tmp_path / "archive") == [
        "kpark1/kpark1-2026-11-09-201530.park",
        "kpark1/kpark1-2026-11-09-211530.park",
    ]


def test_an_existing_archive_copy_is_never_replaced(user: Path, tmp_path: Path) -> None:
    plan = plan_for(user, tmp_path)
    source = user / "save" / "slot.park"
    write_park(source, b"new", 1_762_714_800_000_000_000)
    archive = tmp_path / "archive" / "kpark1" / "kpark1-2026-11-09-201530.park"
    write_park(archive, b"older", 1)

    lines, ok = back_up(judgment([pair(stat_record(source, "save"), "kpark1", 0)]), plan, ENDED)

    assert not ok
    assert archive.read_bytes() == b"older"
    assert "already exists; it was left alone" in lines[0]
    assert lines[0].endswith("The recorded data is fine; only the backup copy failed.")
    assert (user / "save" / "kpark1-last-plugin-save-2026-11-09.park").read_bytes() == b"new"


def test_a_source_that_is_already_the_game_copy_is_kept(user: Path, tmp_path: Path) -> None:
    plan = plan_for(user, tmp_path)
    source = user / "save" / "kpark1-last-plugin-save-2026-11-09.park"
    write_park(source, b"loaded and saved", 1_762_714_800_000_000_000)

    lines, ok = back_up(judgment([pair(stat_record(source, "save"), "kpark1", 0)]), plan, ENDED)

    assert ok
    assert source.read_bytes() == b"loaded and saved"
    archive = tmp_path / "archive" / "kpark1" / "kpark1-2026-11-09-201530.park"
    assert lines == [
        "Backup: kpark1's last recorded save (kpark1-last-plugin-save-2026-11-09) copied to "
        "save/kpark1-last-plugin-save-2026-11-09.park (it already was that file, so it was kept "
        f"as is); archive copy {archive}."
    ]


@pytest.mark.parametrize("change", ["size", "time"])
def test_a_source_changed_before_copying_is_refused(
    user: Path, tmp_path: Path, change: str
) -> None:
    plan = plan_for(user, tmp_path)
    source = user / "save" / "slot.park"
    write_park(source, b"recorded", 1_762_714_800_000_000_000)
    record = stat_record(source, "save")
    if change == "size":
        write_park(source, b"recorded plus more", 1_762_714_800_000_000_000)
    else:
        write_park(source, b"recorded", 1_762_714_800_001_000_000)  # one millisecond later

    lines, ok = back_up(judgment([pair(record, "kpark1", 0)]), plan, ENDED)

    assert not ok
    assert "slot.park changed after it was recorded" in lines[0]
    assert all_files(user / "save") == ["slot.park"]
    assert not (tmp_path / "archive").exists()


def test_a_time_within_the_same_millisecond_matches(user: Path, tmp_path: Path) -> None:
    plan = plan_for(user, tmp_path)
    source = user / "save" / "slot.park"
    write_park(source, b"recorded", 1_762_714_800_123_000_001)
    record = stat_record(source, "save")
    os.utime(source, ns=(1_762_714_800_123_999_999, 1_762_714_800_123_999_999))

    assert back_up(judgment([pair(record, "kpark1", 0)]), plan, ENDED)[1]


def test_a_source_changed_while_copying_is_refused_and_leaves_no_file(
    user: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = plan_for(user, tmp_path)
    source = user / "save" / "slot.park"
    write_park(source, b"recorded", 1_762_714_800_000_000_000)
    record = stat_record(source, "save")
    real_copy = shutil.copyfileobj

    def copy_then_touch(src: BinaryIO, dst: BinaryIO) -> None:
        real_copy(src, dst)
        os.utime(source, ns=(1_762_714_999_000_000_000, 1_762_714_999_000_000_000))

    monkeypatch.setattr(shutil, "copyfileobj", copy_then_touch)

    lines, ok = back_up(judgment([pair(record, "kpark1", 0)]), plan, ENDED)

    assert not ok
    assert "slot.park changed while it was copied" in lines[0]
    assert all_files(tmp_path / "archive") == []
    assert all_files(user / "save") == ["slot.park"]


def test_a_game_copy_target_that_is_a_link_is_left_alone(user: Path, tmp_path: Path) -> None:
    plan = plan_for(user, tmp_path)
    source = user / "save" / "slot.park"
    write_park(source, b"recorded", 1_762_714_800_000_000_000)
    elsewhere = tmp_path / "elsewhere.park"
    elsewhere.write_bytes(b"not ours")
    link = user / "save" / "kpark1-last-plugin-save-2026-11-09.park"
    link.symlink_to(elsewhere)

    lines, ok = back_up(judgment([pair(stat_record(source, "save"), "kpark1", 0)]), plan, ENDED)

    assert ok, lines
    assert link.is_symlink() and elsewhere.read_bytes() == b"not ours"
    timed = user / "save" / "kpark1-last-plugin-save-2026-11-09-201530.park"
    assert timed.read_bytes() == b"recorded"
    assert not any(p.name.startswith(".backup-") for p in (user / "save").iterdir())


def test_a_run_with_no_recorded_save_says_so_and_passes(user: Path, tmp_path: Path) -> None:
    lines, ok = back_up(judgment([]), plan_for(user, tmp_path), ENDED)

    assert ok
    assert lines == ["Backup: no recorded save in this run, so no backup was made."]


def test_a_players_own_file_with_the_backup_name_is_never_replaced(
    user: Path, tmp_path: Path
) -> None:
    plan = plan_for(user, tmp_path)
    source = user / "save" / "slot.park"
    write_park(source, b"recorded", 1_762_714_800_000_000_000)
    players = user / "save" / "kpark1-last-plugin-save-2026-11-09.park"
    write_park(players, b"the player's own file", 1)

    lines, ok = back_up(judgment([pair(stat_record(source, "save"), "kpark1", 0)]), plan, ENDED)

    assert ok, lines
    assert players.read_bytes() == b"the player's own file"
    timed = user / "save" / "kpark1-last-plugin-save-2026-11-09-201530.park"
    assert timed.read_bytes() == b"recorded"
    assert "was changed by play, so it was left alone" in lines[0]


def test_an_unchanged_own_copy_is_left_alone_when_replacing_is_off(
    user: Path, tmp_path: Path
) -> None:
    source = user / "save" / "slot.park"
    write_park(source, b"recorded", 1_762_714_800_000_000_000)
    records = judgment([pair(stat_record(source, "save"), "kpark1", 0)])
    assert back_up(records, plan_for(user, tmp_path), ENDED)[1]
    later = datetime(2026, 11, 9, 20, 30, 45)
    off = dataclasses.replace(plan_for(user, tmp_path), replace_own_copy=False)

    lines, ok = back_up(records, off, later)

    assert ok, lines
    archive = tmp_path / "archive" / "kpark1" / "kpark1-2026-11-09-203045.park"
    assert lines == [
        "Backup: kpark1's last recorded save (slot) copied to "
        "save/kpark1-last-plugin-save-2026-11-09-203045.park "
        "(kpark1-last-plugin-save-2026-11-09.park was left alone); "
        f"archive copy {archive}."
    ]
    assert (user / "save" / "kpark1-last-plugin-save-2026-11-09-203045.park").read_bytes() == (
        b"recorded"
    )


def test_two_parks_with_one_name_never_replace_each_others_copy(
    user: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(save_backup, "park_names", lambda _p: {"park-a": "Twin", "park-b": "Twin"})
    plan = plan_for(user, tmp_path)
    first, second = user / "save" / "a.park", user / "save" / "b.park"
    write_park(first, b"park a", 1_762_714_800_000_000_000)
    write_park(second, b"park b", 1_762_714_900_000_000_000)
    pairs = [
        pair(stat_record(first, "save"), "park-a", 0),
        pair(stat_record(second, "save"), "park-b", 1),
    ]

    lines, ok = back_up(judgment(pairs), plan, ENDED)

    assert ok, lines
    assert (user / "save" / "Twin-last-plugin-save-2026-11-09.park").read_bytes() == b"park a"
    assert (user / "save" / "Twin-last-plugin-save-2026-11-09-201530.park").read_bytes() == (
        b"park b"
    )


def test_an_archive_folder_inside_a_watched_folder_is_refused(user: Path, tmp_path: Path) -> None:
    plan = BackupPlan(
        plan_for(user, tmp_path).watched, user / "save", user / "save" / "archive", tmp_path
    )
    source = user / "save" / "slot.park"
    write_park(source, b"recorded", 1_762_714_800_000_000_000)

    lines, ok = back_up(judgment([pair(stat_record(source, "save"), "kpark1", 0)]), plan, ENDED)

    assert not ok
    assert "is inside the watched save folder" in lines[0]
    assert all_files(user / "save") == ["slot.park"]


def test_a_rotated_away_source_is_skipped_with_a_note(user: Path, tmp_path: Path) -> None:
    gone = SaveFileRecord(T0, "created", "autosave_old", "autosave", T0, 1, T0)

    lines, ok = back_up(judgment([pair(gone, "kpark1", 0)]), plan_for(user, tmp_path), ENDED)

    assert ok
    assert lines == [
        "No backup made for kpark1: its last recorded save autosave_old no longer exists (the "
        "game deletes old autosaves); the previous backup was kept."
    ]


def test_a_failed_archive_copy_still_makes_the_game_copy(user: Path, tmp_path: Path) -> None:
    plan = plan_for(user, tmp_path)
    (tmp_path / "archive").write_text("a file where the archive folder should be")
    source = user / "save" / "slot.park"
    write_park(source, b"recorded", 1_762_714_800_000_000_000)

    lines, ok = back_up(judgment([pair(stat_record(source, "save"), "kpark1", 0)]), plan, ENDED)

    assert not ok
    assert lines[0].startswith("Backup FAILED for kpark1's archive copy:")
    assert (user / "save" / "kpark1-last-plugin-save-2026-11-09.park").read_bytes() == b"recorded"


def test_choose_skips_a_park_with_a_later_unpaired_write_of_another_of_its_files() -> None:
    main = SaveFileRecord(T0, "created", "Crazy", "save", T0, 1, T0)
    auto = SaveFileRecord(T0, "created", "auto", "autosave", T0 + timedelta(seconds=1), 1, T0)
    later = SaveFileRecord(T0, "modified", "Crazy", "save", T0 + timedelta(minutes=5), 2, T0)
    pairs = (pair(main, "park-a", 0), pair(auto, "park-a", 1))

    chosen, skipped = choose(RunPairing(pairs, (), (), (later,)))

    assert chosen == []
    assert "Crazy was written after" in skipped[0]


def test_the_temporary_file_never_carries_the_park_suffix(
    user: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = user / "save" / "slot.park"
    write_park(source, b"recorded", 1_762_714_800_000_000_000)
    seen: list[str] = []
    real_mkstemp = tempfile.mkstemp

    def note_name(*, dir: Path, prefix: str, suffix: str) -> tuple[int, str]:  # noqa: A002
        handle, name = real_mkstemp(dir=dir, prefix=prefix, suffix=suffix)
        seen.append(Path(name).name)
        return handle, name

    monkeypatch.setattr(tempfile, "mkstemp", note_name)
    plan = plan_for(user, tmp_path)

    assert back_up(judgment([pair(stat_record(source, "save"), "kpark1", 0)]), plan, ENDED)[1]
    assert len(seen) == 2
    assert all(name.startswith(".backup-") and not name.endswith(".park") for name in seen)


def run_twice_on_one_day(
    user: Path, tmp_path: Path, *, replace_own_copy: bool | None
) -> tuple[Path, Path]:
    """Back up a save, then a changed one an hour later; return the dated copy and its sibling."""
    options = {} if replace_own_copy is None else {"replace_own_copy": replace_own_copy}
    plan = BackupPlan(
        {"save": user / "save"},
        user / "save",
        tmp_path / "archive",
        tmp_path / "parquet",
        **options,
    )
    source = user / "save" / "slot.park"
    write_park(source, b"first", 1_762_714_800_000_000_000)
    assert back_up(judgment([pair(stat_record(source, "save"), "kpark1", 0)]), plan, ENDED)[1]
    write_park(source, b"second", 1_762_714_900_000_000_000)
    later = ENDED + timedelta(hours=1)

    lines, ok = back_up(judgment([pair(stat_record(source, "save"), "kpark1", 0)]), plan, later)

    assert ok, lines
    dated = user / "save" / "kpark1-last-plugin-save-2026-11-09.park"
    return dated, user / "save" / "kpark1-last-plugin-save-2026-11-09-211530.park"


def test_replace_own_copy_false_never_replaces_the_dated_copy(user: Path, tmp_path: Path) -> None:
    dated, sibling = run_twice_on_one_day(user, tmp_path, replace_own_copy=False)

    assert dated.read_bytes() == b"first"
    assert sibling.read_bytes() == b"second"


def test_replace_own_copy_defaults_to_replacing_its_own_dated_copy(
    user: Path, tmp_path: Path
) -> None:
    dated, sibling = run_twice_on_one_day(user, tmp_path, replace_own_copy=None)

    assert dated.read_bytes() == b"second"
    assert not sibling.exists()

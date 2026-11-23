"""Tests for the raw-recording reader (``raw_session_index``, ``unconverted_raw_file``).

The Parquet side is planted with the helpers of ``test_managed_years``; raw files are planted lines.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openrct2_analytics.ingest import managed_years
from tests.test_managed_years import JULY, plant, save, snapshot, start


def write_raw(raw: Path, name: str, sessions: list[str]) -> None:
    folder = raw / "v1"
    folder.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"session_id": session, "seq": 1}) for session in sessions]
    (folder / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_unconverted_raw_file_returns_the_first_stale_file(tmp_path: Path) -> None:
    parquet, _ = plant(
        tmp_path, [snapshot(10, (1, JULY, 1))], [save(20)], [start("s1", (1, JULY, 1))]
    )
    raw = tmp_path / "raw"
    write_raw(raw, "events-2026-11-11.jsonl", ["s1"])
    write_raw(raw, "events-2026-11-12.jsonl", ["s1", "s9"])
    write_raw(raw, "events-2026-11-13.jsonl", ["s8"])

    assert (
        managed_years.unconverted_raw_file(raw, parquet) == raw / "v1" / "events-2026-11-12.jsonl"
    )


def test_unconverted_raw_file_is_none_when_every_session_is_converted(tmp_path: Path) -> None:
    parquet, _ = plant(
        tmp_path, [snapshot(10, (1, JULY, 1))], [save(20)], [start("s1", (1, JULY, 1))]
    )
    raw = tmp_path / "raw"
    write_raw(raw, "events-2026-11-12.jsonl", ["s1", "s1"])

    assert managed_years.unconverted_raw_file(raw, parquet) is None


def test_unconverted_raw_file_is_none_for_a_missing_raw_folder(tmp_path: Path) -> None:
    # No Parquet either: a missing raw folder is clean before the Parquet is read.
    assert managed_years.unconverted_raw_file(tmp_path / "raw", tmp_path / "parquet") is None


def test_unconverted_raw_file_returns_a_file_whose_last_line_is_cut_off(tmp_path: Path) -> None:
    parquet, _ = plant(
        tmp_path, [snapshot(10, (1, JULY, 1))], [save(20)], [start("s1", (1, JULY, 1))]
    )
    raw = tmp_path / "raw"
    write_raw(raw, "events-2026-11-11.jsonl", ["s1"])
    cut = raw / "v1" / "events-2026-11-12.jsonl"
    cut.write_text('{"session_id": "s1"}\n{"session_id": "s', encoding="utf-8")

    assert managed_years.unconverted_raw_file(raw, parquet) == cut


def write_raw_lines(raw: Path, name: str, events: list[dict[str, object]]) -> Path:
    folder = raw / "v1"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    return path


def plant_two_files(raw: Path) -> tuple[Path, Path]:
    """Session ``s1`` crosses both files and both parks; ``s2`` starts at seq 2, no name."""
    first = write_raw_lines(
        raw,
        "events-2026-11-11.jsonl",
        [
            {
                "session_id": "s1",
                "park_id": "park-a",
                "seq": 1,
                "event_type": "session_start",
                "park_name": "Alpha Park",
            },
            {"session_id": "s2", "park_id": "park-b", "seq": 2, "event_type": "park_snapshot"},
        ],
    )
    second = write_raw_lines(
        raw,
        "events-2026-11-12.jsonl",
        [{"session_id": "s1", "park_id": "park-b", "seq": 2, "event_type": "park_snapshot"}],
    )
    return first, second


def test_a_session_over_two_files_and_two_parks_lists_both(tmp_path: Path) -> None:
    plant_two_files(tmp_path)

    record = managed_years.raw_session_index(tmp_path)["s1"]

    assert record.park_ids == frozenset({"park-a", "park-b"})
    assert {path.name for path in record.files} == {
        "events-2026-11-11.jsonl",
        "events-2026-11-12.jsonl",
    }


def test_a_raw_session_start_gives_the_park_name(tmp_path: Path) -> None:
    plant_two_files(tmp_path)

    assert managed_years.raw_session_index(tmp_path)["s1"].park_names == {"park-a": "Alpha Park"}


def test_a_session_whose_first_event_has_seq_2_has_no_park_name(tmp_path: Path) -> None:
    plant_two_files(tmp_path)

    assert managed_years.raw_session_index(tmp_path)["s2"].park_names == {}


def test_an_unparsable_line_is_skipped_and_raw_sessions_keeps_its_set(tmp_path: Path) -> None:
    first, _ = plant_two_files(tmp_path)
    with first.open("a", encoding="utf-8") as stream:
        stream.write('{"session_id": "s3", "park_id"\n[1, 2]\n{"seq": 1}\n\n')

    assert set(managed_years.raw_session_index(tmp_path)) == {"s1", "s2"}
    assert managed_years.raw_sessions(tmp_path) == {"s1", "s2"}


def count_reads(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Wrap ``read_raw_file`` with a counter that still calls the real parser."""
    calls: list[Path] = []
    real = managed_years.read_raw_file

    def counting(path: Path) -> managed_years.RawFile:
        calls.append(path)
        return real(path)

    monkeypatch.setattr(managed_years, "read_raw_file", counting)
    return calls


def test_a_second_call_on_an_unchanged_folder_reads_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plant_two_files(tmp_path)
    managed_years.raw_session_index(tmp_path)
    calls = count_reads(monkeypatch)

    managed_years.raw_session_index(tmp_path)

    assert calls == []


def test_a_touched_file_is_read_again_and_the_other_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = plant_two_files(tmp_path)
    managed_years.raw_session_index(tmp_path)
    calls = count_reads(monkeypatch)
    stat = second.stat()
    os.utime(second, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    managed_years.raw_session_index(tmp_path)

    assert [path.name for path in calls] == ["events-2026-11-12.jsonl"]


def test_a_park_name_on_a_non_session_start_event_is_not_the_park_name(tmp_path: Path) -> None:
    write_raw_lines(
        tmp_path,
        "events-2026-11-11.jsonl",
        [
            {
                "session_id": "s9",
                "park_id": "park-a",
                "seq": 2,
                "event_type": "park_snapshot",
                "park_name": "Snapshot Name",
            }
        ],
    )

    assert managed_years.raw_session_index(tmp_path)["s9"].park_names == {}


def test_the_first_file_in_name_order_gives_the_park_name(tmp_path: Path) -> None:
    for name, park_name in (
        ("events-2026-11-12.jsonl", "Later Name"),
        ("events-2026-11-11.jsonl", "Earlier Name"),
    ):
        write_raw_lines(
            tmp_path,
            name,
            [
                {
                    "session_id": "s1",
                    "park_id": "park-a",
                    "seq": 1,
                    "event_type": "session_start",
                    "park_name": park_name,
                }
            ],
        )

    assert managed_years.raw_session_index(tmp_path)["s1"].park_names == {"park-a": "Earlier Name"}


def test_an_appended_line_is_seen_when_the_mtime_is_restored(tmp_path: Path) -> None:
    first, _ = plant_two_files(tmp_path)
    assert set(managed_years.raw_session_index(tmp_path)) == {"s1", "s2"}
    stat = first.stat()
    with first.open("a", encoding="utf-8") as stream:
        stream.write('{"session_id": "s4", "park_id": "park-c", "seq": 1}\n')
    os.utime(first, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    assert set(managed_years.raw_session_index(tmp_path)) == {"s1", "s2", "s4"}


def test_a_list_valued_session_id_makes_the_file_unconverted(tmp_path: Path) -> None:
    parquet, _ = plant(
        tmp_path, [snapshot(10, (1, JULY, 1))], [save(20)], [start("s1", (1, JULY, 1))]
    )
    raw = tmp_path / "raw"
    path = write_raw_lines(raw, "events-2026-11-11.jsonl", [{"session_id": ["a"]}])

    assert managed_years.unconverted_raw_file(raw, parquet) == path


def test_a_returned_mapping_cannot_be_changed(tmp_path: Path) -> None:
    plant_two_files(tmp_path)
    managed_years.raw_session_index(tmp_path)
    cached = managed_years._cached_read(sorted((tmp_path / "v1").glob("events-*.jsonl"))[0])

    with pytest.raises(TypeError):
        cached.park_names[("s1", "park-a")] = "Changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        cached.park_ids["s1"] = frozenset()  # type: ignore[index]


def start_line(session: str, park: str, **fields: object) -> dict[str, object]:
    return {
        "session_id": session,
        "park_id": park,
        "seq": 1,
        "event_type": "session_start",
        "park_name": "Alpha Park",
        **fields,
    }


def test_raw_index_keeps_session_start_time(tmp_path: Path) -> None:
    write_raw_lines(
        tmp_path,
        "events-2026-11-11.jsonl",
        [start_line("s1", "park-a", emitted_at="2026-11-16T02:10:00Z")],
    )

    start_times = managed_years.raw_session_index(tmp_path)["s1"].start_times

    assert start_times == {"park-a": datetime(2026, 11, 16, 2, 10, tzinfo=UTC)}


def test_nameless_session_start_keeps_its_time(tmp_path: Path) -> None:
    line = start_line("s1", "park-a", emitted_at="2026-11-16T02:10:00Z")
    del line["park_name"]
    write_raw_lines(tmp_path, "events-2026-11-11.jsonl", [line])

    record = managed_years.raw_session_index(tmp_path)["s1"]

    assert record.start_times == {"park-a": datetime(2026, 11, 16, 2, 10, tzinfo=UTC)}
    assert record.park_names == {}


def test_unparsable_emitted_at_gives_no_time(tmp_path: Path) -> None:
    path = write_raw_lines(
        tmp_path, "events-2026-11-11.jsonl", [start_line("s1", "park-a", emitted_at="not a time")]
    )

    content = managed_years.read_raw_file(path)

    assert content.start_times == {("s1", "park-a"): None}
    assert not content.has_unreadable_line
    assert content.sessions == {"s1"}


def test_emitted_at_without_offset_gives_no_time(tmp_path: Path) -> None:
    path = write_raw_lines(
        tmp_path,
        "events-2026-11-11.jsonl",
        [start_line("s1", "park-a", emitted_at="2026-11-16T02:10:00")],
    )

    content = managed_years.read_raw_file(path)

    assert content.start_times == {("s1", "park-a"): None}
    assert not content.has_unreadable_line


def test_a_deeply_nested_line_is_unreadable_and_the_next_line_is_kept(tmp_path: Path) -> None:
    folder = tmp_path / "v1"
    folder.mkdir()
    path = folder / "events-2026-11-11.jsonl"
    path.write_bytes(
        b"[" * 100_000 + b"\n" + json.dumps(start_line("s1", "park-a")).encode() + b"\n"
    )

    content = managed_years.read_raw_file(path)

    assert content.has_unreadable_line
    assert content.sessions == {"s1"}


def test_repeated_starts_in_one_file_keep_the_earliest_time_and_its_name(tmp_path: Path) -> None:
    path = write_raw_lines(
        tmp_path,
        "events-2026-11-11.jsonl",
        [
            start_line("s1", "park-a", park_name="Late", emitted_at="2026-11-16T02:10:00Z"),
            start_line("s1", "park-a", park_name="Early", emitted_at="2026-11-12T02:10:00Z"),
            start_line("s1", "park-a", park_name="Never", emitted_at="not a time"),
        ],
    )

    content = managed_years.read_raw_file(path)

    assert content.start_times == {("s1", "park-a"): datetime(2026, 11, 12, 2, 10, tzinfo=UTC)}
    assert content.park_names == {("s1", "park-a"): "Early"}


def test_a_valid_start_replaces_an_earlier_line_with_no_time(tmp_path: Path) -> None:
    path = write_raw_lines(
        tmp_path,
        "events-2026-11-11.jsonl",
        [
            start_line("s1", "park-a", emitted_at="not a time"),
            start_line("s1", "park-a", emitted_at="2026-11-12T02:10:00Z"),
        ],
    )

    content = managed_years.read_raw_file(path)

    assert content.start_times == {("s1", "park-a"): datetime(2026, 11, 12, 2, 10, tzinfo=UTC)}


def test_starts_over_two_files_keep_the_earliest_time_and_its_name(tmp_path: Path) -> None:
    write_raw_lines(
        tmp_path,
        "events-2026-11-11.jsonl",
        [start_line("s1", "park-a", park_name="Late", emitted_at="2026-11-16T02:10:00Z")],
    )
    write_raw_lines(
        tmp_path,
        "events-2026-11-12.jsonl",
        [start_line("s1", "park-a", park_name="Early", emitted_at="2026-11-12T02:10:00Z")],
    )

    record = managed_years.raw_session_index(tmp_path)["s1"]

    assert record.start_times == {"park-a": datetime(2026, 11, 12, 2, 10, tzinfo=UTC)}
    assert record.park_names == {"park-a": "Early"}

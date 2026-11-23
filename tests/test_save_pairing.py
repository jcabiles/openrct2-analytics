"""The save-file pairing rule and the report lines (spec R12, R13, R15, R16, R17)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from openrct2_analytics.ingest.save_pairing import (
    SAVE_MATCH_WINDOW,
    SaveFileRecord,
    SaveJudgment,
    SaveWrittenRow,
    UnreadableLine,
    WatcherError,
    judge_saves,
    pair_every_run,
    render_saves,
    render_skipped,
)

T0 = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)
LATER = T0 + timedelta(hours=1)


def at(seconds: float, base: datetime = T0) -> datetime:
    return base + timedelta(seconds=seconds)


def record(
    modified: datetime,
    name: str = "park-a",
    *,
    obs: str = "modified",
    kind: str = "save",
    run: datetime = T0,
) -> SaveFileRecord:
    return SaveFileRecord(run, obs, name, kind, modified, 100, modified)


def row(
    emitted: datetime,
    event_id: str = "e1",
    save_id: str = "s1",
    *,
    park: str = "park-1",
    received: datetime | None = None,
    raw_line: int = 1,
) -> SaveWrittenRow:
    return SaveWrittenRow(
        event_id, save_id, park, "sess", emitted, received or emitted, "events.jsonl", raw_line
    )


def judge(
    records: list[SaveFileRecord],
    rows: list[SaveWrittenRow],
    *,
    started: datetime = T0,
    unreadable: list[UnreadableLine] | None = None,
    error: WatcherError | None = None,
) -> SaveJudgment:
    return judge_saves(records, rows, started, unreadable=unreadable or [], watcher_error=error)


def test_pair_one_candidate_pairs() -> None:
    j = judge([record(at(1))], [row(at(0))])
    assert [(p.row.event_id, p.record.file_name) for p in j.this_run.pairs] == [("e1", "park-a")]
    assert not j.failed


def test_candidate_none_is_no_candidate_and_fails() -> None:
    j = judge([record(at(60))], [row(at(0), save_id="s9")])
    assert [r.save_id for r in j.this_run.no_candidate] == ["s9"]
    assert j.failed
    expected = "capture failure: save_id s9 emitted at 2026-10-19T12:00:00+00:00"
    assert expected + ": no file record within 5 s" in render_saves(j)


def test_window_two_files_is_two_candidate_window() -> None:
    j = judge([record(at(1), "a"), record(at(2), "b")], [row(at(0))])
    assert not j.this_run.pairs and not j.this_run.no_candidate
    assert len(j.this_run.windows) == 1
    text = render_saves(j)
    assert "two-candidate window" in text and "s1" in text and "save/a" in text and "save/b" in text
    assert j.failed


def test_window_one_file_in_two_windows_is_two_candidate_window() -> None:
    rows = [row(at(0), "e1", "s1"), row(at(3), "e2", "s2")]
    j = judge([record(at(4))], rows)
    assert not j.this_run.pairs
    assert len(j.this_run.windows) == 1
    assert {r.save_id for r in j.this_run.windows[0].rows} == {"s1", "s2"}
    assert "s1" in render_saves(j) and "s2" in render_saves(j)


def test_one_file_saved_again_after_its_window_pairs_each_save() -> None:
    rows = [row(at(0), "e1", "s1"), row(at(150), "e2", "s2"), row(at(178), "e3", "s3")]
    records = [record(at(0.035)), record(at(150.023)), record(at(178.046))]
    j = judge(records, rows)
    assert [(p.row.save_id, p.record.modified_at) for p in j.this_run.pairs] == [
        ("s1", at(0.035)),
        ("s2", at(150.023)),
        ("s3", at(178.046)),
    ]
    assert not j.this_run.windows and not j.this_run.unpaired
    assert not j.failed


def test_one_write_in_two_windows_still_fails_when_the_file_is_saved_again() -> None:
    rows = [row(at(0), "e1", "s1"), row(at(3), "e2", "s2"), row(at(60), "e3", "s3")]
    j = judge([record(at(1)), record(at(4)), record(at(60.1))], rows)
    assert [p.row.save_id for p in j.this_run.pairs] == ["s3"]
    assert {r.save_id for r in j.this_run.windows[0].rows} == {"s1", "s2"}
    assert j.failed


def test_two_close_saves_with_two_writes_pair_each_write() -> None:
    rows = [row(at(0), "e1", "s1"), row(at(3), "e2", "s2")]
    j = judge([record(at(1)), record(at(6))], rows)
    assert [(p.row.save_id, p.record.modified_at) for p in j.this_run.pairs] == [
        ("s1", at(1)),
        ("s2", at(6)),
    ]
    assert not j.failed


def test_records_tied_on_modified_time_keep_the_first_in_file_order() -> None:
    created = SaveFileRecord(T0, "created", "park-a", "save", at(1), 0, at(1))
    modified = SaveFileRecord(T0, "modified", "park-a", "save", at(1), 500, at(1))
    j = judge([created, modified], [row(at(0))])
    assert j.this_run.pairs[0].record is created


def test_candidate_repeated_records_of_one_file_are_one_candidate() -> None:
    created = record(at(1), obs="created")
    j = judge([created, record(at(2))], [row(at(0))])
    assert len(j.this_run.pairs) == 1
    assert j.this_run.pairs[0].record.modified_at == at(2)
    assert not j.this_run.unpaired


def test_candidate_start_records_never_pair() -> None:
    j = judge([record(at(1), "x-main", obs="start", kind="parent")], [row(at(0))])
    assert not j.this_run.pairs
    assert len(j.this_run.no_candidate) == 1


def test_window_bounds_are_inside() -> None:
    assert timedelta(seconds=5) == SAVE_MATCH_WINDOW
    assert len(judge([record(at(0))], [row(at(0))]).this_run.pairs) == 1
    assert len(judge([record(at(5))], [row(at(0))]).this_run.pairs) == 1
    assert not judge([record(at(-0.001))], [row(at(0))]).this_run.pairs
    assert not judge([record(at(5.001))], [row(at(0))]).this_run.pairs


def test_delivery_repeated_event_reduces_to_first_received_and_pairs() -> None:
    rows = [row(at(0), received=at(9)), row(at(0), received=at(8), park="park-first")]
    j = judge([record(at(1))], rows)
    assert len(j.this_run.pairs) == 1
    assert j.this_run.pairs[0].row.park_id == "park-first"
    assert not j.this_run.windows


def test_candidate_categories_are_disjoint() -> None:
    rows = [row(at(0), "e1", "s1"), row(at(100), "e2", "s2")]
    j = judge([record(at(1), "a"), record(at(2), "b")], rows)
    assert [r.save_id for r in j.this_run.no_candidate] == ["s2"]
    assert [r.save_id for w in j.this_run.windows for r in w.rows] == ["s1"]


def test_adjacent_runs_do_not_pair_across() -> None:
    # Inside the 5 s window of the earlier run's event, but the file belongs to the later run.
    later_start = at(3)
    earlier_event = row(at(1))
    later_record = record(at(4), run=later_start)
    earlier = judge([later_record], [earlier_event], started=T0)
    assert not earlier.this_run.pairs
    assert len(earlier.this_run.no_candidate) == 1
    later = judge([later_record], [earlier_event], started=later_start)
    assert not later.this_run.pairs and not later.this_run.no_candidate


def test_adjacent_runs_later_run_row_does_not_pair_in_earlier_run() -> None:
    # Received after the later run started, but emitted inside the earlier run's record window.
    later_start = at(3)
    earlier_record = record(at(2), run=T0)
    later_record = record(at(50), run=later_start)
    later_row = row(at(1), received=at(4))
    j = judge([earlier_record, later_record], [later_row], started=T0)
    assert not j.this_run.pairs and not j.this_run.no_candidate
    later = judge([earlier_record, later_record], [later_row], started=later_start)
    assert len(later.this_run.no_candidate) == 1


def test_delivery_tie_on_received_at_does_not_depend_on_input_order() -> None:
    a = row(at(0), received=at(8), park="park-1", raw_line=1)
    b = row(at(0), received=at(8), park="park-2", raw_line=2)
    for rows in ([a, b], [b, a]):
        j = judge([record(at(1))], rows)
        assert [p.row.park_id for p in j.this_run.pairs] == ["park-1"]


def test_delivery_tie_on_received_at_goes_to_the_lower_raw_line_not_the_lower_save_id() -> None:
    # Matches models/staging/stg_save_written.sql: received_at, _raw_file, _raw_line.
    low_line = row(at(0), save_id="s9", received=at(8), park="park-9", raw_line=3)
    high_line = row(at(0), save_id="s1", received=at(8), park="park-1", raw_line=7)
    for rows in ([low_line, high_line], [high_line, low_line]):
        j = judge([record(at(1))], rows)
        assert [p.row.raw_line for p in j.this_run.pairs] == [3]


def test_pair_line_names_file_folder_save_and_park() -> None:
    text = render_saves(
        judge([record(at(1), "mine", kind="autosave")], [row(at(0), save_id="sv7", park="pk9")])
    )
    assert "mine" in text and "autosave" in text and "sv7" in text and "pk9" in text


def test_unpaired_record_renders_note_and_does_not_fail() -> None:
    j = judge([record(at(1))], [])
    assert not j.failed
    assert "note:" in render_saves(j)


def test_watcher_error_renders_with_time_and_fails() -> None:
    j = judge([], [], error=WatcherError(at(7), "scan broke"))
    assert j.failed
    assert "watcher error at 2026-10-19T12:00:07+00:00: scan broke" in render_saves(j)


def test_unreadable_this_run_is_failure_other_is_note() -> None:
    mine = UnreadableLine("rec-2.jsonl", 3, True)
    old = UnreadableLine("rec-1.jsonl", 9, False)
    j = judge([], [], unreadable=[old])
    assert not j.failed
    assert "note: unreadable record line rec-1.jsonl line 9" in render_saves(j)
    j = judge([], [], unreadable=[mine, old])
    assert j.failed
    text = render_saves(j)
    assert "capture failure: unreadable record line rec-2.jsonl line 3" in text
    assert "note: unreadable record line rec-1.jsonl line 9" in text


def _earlier_paired(
    modified: datetime, park: str = "park-1"
) -> tuple[SaveFileRecord, SaveWrittenRow]:
    emitted = modified - timedelta(seconds=1)
    return record(modified, "me-main", kind="parent", run=T0), row(emitted, "old", "so", park=park)


def test_main_flag_when_start_differs_from_last_paired_write() -> None:
    old_rec, old_row = _earlier_paired(at(1))
    start = record(at(5000, LATER), "me-main", obs="start", kind="parent", run=LATER)
    j = judge([old_rec, start], [old_row], started=LATER)
    assert j.main_lines == (
        "warning: me-main changed since its last paired write at "
        "2026-10-19T12:00:01+00:00; that play was not captured",
    )
    assert not j.failed


def test_main_note_without_history() -> None:
    start = record(at(5, LATER), "me-main", obs="start", kind="parent", run=LATER)
    j = judge([start], [], started=LATER)
    assert j.main_lines == ("note: me-main: no earlier paired write on record",)
    assert not j.failed


def test_main_lost_event_line_replaces_other_outcomes() -> None:
    old_rec, old_row = _earlier_paired(at(1))
    lost = record(at(500), "me-main", kind="parent", run=T0)
    start = record(at(500), "me-main", obs="start", kind="parent", run=LATER)
    j = judge([old_rec, lost, start], [old_row], started=LATER)
    assert j.main_lines == (
        "warning: me-main: last write was recorded but its save event was lost",
    )
    assert not j.failed


def test_main_unchanged_start_prints_nothing() -> None:
    old_rec, old_row = _earlier_paired(at(1))
    start = record(at(1), "me-main", obs="start", kind="parent", run=LATER)
    assert judge([old_rec, start], [old_row], started=LATER).main_lines == ()


def test_park_flag_when_history_carries_two_parks() -> None:
    old_rec, old_row = _earlier_paired(at(1), park="park-1")
    new_rec = record(at(10, LATER), "me-main", kind="parent", run=LATER)
    new_row = row(at(9, LATER), "new", "sn", park="park-2", received=at(9, LATER))
    j = judge([old_rec, new_rec], [old_row, new_row], started=LATER)
    assert j.park_lines == ("warning: me-main was written by parks park-1, park-2",)
    assert not j.failed


def test_park_flag_absent_for_one_park() -> None:
    old_rec, old_row = _earlier_paired(at(1))
    new_rec = record(at(10, LATER), "me-main", kind="parent", run=LATER)
    new_row = row(at(9, LATER), "new", "sn", park="park-1", received=at(9, LATER))
    assert judge([old_rec, new_rec], [old_row, new_row], started=LATER).park_lines == ()


def test_skipped_line_and_watcher_error() -> None:
    assert (
        render_skipped("interrupted", None)
        == "Save pairing skipped: interrupted. The save-file records were kept."
    )
    text = render_skipped("zero events", WatcherError(at(3), "boom"))
    assert (
        text.splitlines()[0]
        == "Save pairing skipped: zero events. The save-file records were kept."
    )
    assert "2026-10-19T12:00:03+00:00" in text and "boom" in text


MID = T0 + timedelta(minutes=30)


def _two_parks_in_history(
    name: str = "me-main",
) -> tuple[list[SaveFileRecord], list[SaveWrittenRow]]:
    records = [
        record(at(1), name, kind="parent", run=T0),
        record(at(1, MID), name, kind="parent", run=MID),
    ]
    rows = [
        row(at(0), "o1", "s1", park="park-1"),
        row(at(0, MID), "o2", "s2", park="park-2", received=at(0, MID)),
    ]
    return records, rows


def test_park_flag_absent_when_name_not_written_in_this_run() -> None:
    records, rows = _two_parks_in_history()
    assert judge(records, rows, started=LATER).park_lines == ()


def test_park_flag_when_name_written_in_this_run_only_as_unpaired_record() -> None:
    records, rows = _two_parks_in_history()
    records.append(record(at(10, LATER), "me-main", kind="parent", run=LATER))
    j = judge(records, rows, started=LATER)
    assert j.park_lines == ("warning: me-main was written by parks park-1, park-2",)


def test_park_flag_absent_for_name_without_main_suffix() -> None:
    records, rows = _two_parks_in_history("park-a")
    assert judge(records, rows, started=MID).park_lines == ()


def test_main_lost_line_needs_the_unpaired_record_to_match_the_start() -> None:
    old_rec, old_row = _earlier_paired(at(1))
    other = record(at(500), "me-main", kind="parent", run=T0)
    start = record(at(2), "me-main", obs="start", kind="parent", run=LATER)
    j = judge([old_rec, other, start], [old_row], started=LATER)
    assert j.main_lines == (
        "warning: me-main changed since its last paired write at "
        "2026-10-19T12:00:01+00:00; that play was not captured",
    )


def test_main_compares_start_with_the_latest_of_two_paired_writes() -> None:
    first_rec, first_row = _earlier_paired(at(1))
    second_rec = record(at(100, MID), "me-main", kind="parent", run=MID)
    second_row = row(at(99, MID), "o2", "s2", received=at(99, MID))
    start = record(at(100, MID), "me-main", obs="start", kind="parent", run=LATER)
    j = judge([first_rec, second_rec, start], [first_row, second_row], started=LATER)
    assert j.main_lines == ()


def test_main_pair_in_this_run_is_not_an_earlier_write() -> None:
    start = record(at(5, LATER), "me-main", obs="start", kind="parent", run=LATER)
    written = record(at(10, LATER), "me-main", kind="parent", run=LATER)
    j = judge([start, written], [row(at(9, LATER))], started=LATER)
    assert j.main_lines == ("note: me-main: no earlier paired write on record",)


def test_a_changed_file_without_the_main_suffix_warns_like_a_main_file() -> None:
    old_rec = record(at(1), "Crazy Castle", kind="save", run=T0)
    old_row = row(at(0), "old", "so")
    start = record(at(5000, LATER), "Crazy Castle", obs="start", kind="save", run=LATER)
    j = judge([old_rec, start], [old_row], started=LATER)
    assert j.main_lines == (
        "warning: Crazy Castle changed since its last paired write at "
        "2026-10-19T12:00:01+00:00; that play was not captured",
    )
    (check,) = j.start_checks
    assert (check.outcome, check.last_pair and check.last_pair.row.park_id) == ("changed", "park-1")


def test_a_file_without_the_main_suffix_prints_no_note_or_lost_line() -> None:
    old_rec, old_row = record(at(1), "auto", kind="autosave"), row(at(0), "old", "so")
    lost = record(at(500), "auto", kind="autosave")
    never = record(at(9, LATER), "never", obs="start", run=LATER)
    start = record(at(500), "auto", obs="start", kind="autosave", run=LATER)
    j = judge([old_rec, lost, start, never], [old_row], started=LATER)
    assert j.main_lines == ()
    assert sorted(c.outcome for c in j.start_checks) == ["lost", "none"]


def test_pair_every_run_is_the_loop_judge_saves_runs() -> None:
    later_start = at(100)
    records = [
        record(at(1), "a", run=T0),
        record(at(101), "b", run=later_start),
        record(at(102), "c", run=later_start),
    ]
    rows = [row(at(0), "e1", "s1"), row(at(100), "e2", "s2")]

    every = pair_every_run(records, rows)

    assert list(every) == [T0, later_start]
    assert [p.row.save_id for p in every[T0].pairs] == ["s1"]
    assert every[T0].no_candidate == ()
    assert [w.files for w in every[later_start].windows] == [(("save", "b"), ("save", "c"))]
    for started in (T0, later_start):
        assert judge(records, rows, started=started).this_run == every[started]


def test_pair_every_run_adds_the_given_start_as_a_run() -> None:
    assert list(pair_every_run([record(at(1))], [], T0 + timedelta(days=1))) == [
        T0,
        T0 + timedelta(days=1),
    ]

"""Behavioral tests for the converter, over JSON Lines fixtures and the real contracts."""

from __future__ import annotations

import json
import os
import resource
import shutil
import signal
import time
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest.contracts import CONTRACTS_DIR, check_all
from openrct2_analytics.ingest.convert import (
    NoInputError,
    UnsafeOutputError,
    convert,
    main,
)

PARK = "kpark1"
STATS_PAYLOAD: dict[str, object] = {
    "period_start_ticks": 0,
    "period_end_ticks": 100,
    "period_ticks": 100,
    "work_ms_total": 1.5,
    "worst_tick_ms": 0.25,
    "worst_tick_at_ticks": 40,
    "callbacks": 3,
    "warmup": True,
    "clock": "performance",
    "game_speed": 1,
    "lines_dropped_total": 0,
    "write_partial_total": 0,
    "write_error_total": 0,
    "connect_attempts_total": 1,
    "queue_length": 0,
}
SNAPSHOT_PAYLOAD: dict[str, object] = {
    "cash_tenths": -12345,
    "guests_in_park": 7,
    "park_rating": 650,
    "total_admissions": 12,
}


def event(session: str, seq: int, event_type: str = "park_snapshot", **fields: object) -> str:
    """One raw line exactly as the plugin emits it, plus the listener's received_at."""
    payload = STATS_PAYLOAD if event_type == "plugin_stats" else SNAPSHOT_PAYLOAD
    line: dict[str, object] = {
        "schema_version": 1,
        "event_type": event_type,
        "plugin_version": "0.1.0",
        "park_id": PARK,
        "session_id": session,
        "game_year": 1,
        "game_month": 0,
        "game_day": seq,
        "game_ticks_elapsed": 1000 + seq,
        "emitted_at": "2026-09-30T23:30:00.123Z",
        "seq": seq,
        "event_id": f"{session}-{seq}",
        "received_at": "2026-09-30T23:30:00.456Z",
        **payload,
    }
    line.update(fields)
    return json.dumps(line)


def session_lines(session: str, count: int) -> list[str]:
    """`count` events with seq 1..count, alternating plugin_stats and park_snapshot."""
    return [
        event(session, seq, "plugin_stats" if seq % 2 else "park_snapshot")
        for seq in range(1, count + 1)
    ]


def land(raw: Path, *lines: str, name: str = "events-2026-09-30.jsonl") -> None:
    (raw / "v1").mkdir(parents=True, exist_ok=True)
    with (raw / "v1" / name).open("a", encoding="utf-8") as handle:
        handle.write("".join(line + "\n" for line in lines))


def tree(folder: Path) -> dict[Path, bytes | None]:
    """Every path under `folder`, with file bytes (None for a folder)."""
    return {p: p.read_bytes() if p.is_file() else None for p in folder.rglob("*")}


def query(path: Path, sql: str) -> list[tuple[object, ...]]:
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("SET TimeZone='UTC'")
        return connection.execute(sql.replace("{p}", path.as_posix())).fetchall()
    finally:
        connection.close()


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's OPENRCT2_* settings out of every test."""
    for name in [n for n in os.environ if n.startswith("OPENRCT2_")]:
        monkeypatch.delenv(name)


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    return tmp_path / "raw"


@pytest.fixture
def out(tmp_path: Path) -> Path:
    return tmp_path / "parquet"


def test_writes_typed_parquet_per_event_type_in_contract_order(raw: Path, out: Path) -> None:
    land(raw, *session_lines("sa", 4))

    result = convert(raw, out)

    assert result.ok
    assert result.row_counts == {
        "finance_month": 0,
        "game_action": 0,
        "guest_arrived": 0,
        "guest_boarded": 0,
        "guest_left": 0,
        "guest_refused": 0,
        "guest_snapshot": 0,
        "park_snapshot": 2,
        "plugin_stats": 2,
        "ride_snapshot": 0,
        "save_written": 0,
        "session_start": 0,
        "weather_change": 0,
    }
    types = query(out / "v1" / "park_snapshot.parquet", "DESCRIBE SELECT * FROM '{p}'")
    assert [(row[0], row[1]) for row in types] == [
        ("schema_version", "INTEGER"),
        ("event_type", "VARCHAR"),
        ("plugin_version", "VARCHAR"),
        ("park_id", "VARCHAR"),
        ("session_id", "VARCHAR"),
        ("_raw_file", "VARCHAR"),
        ("_raw_line", "BIGINT"),
        ("seq", "BIGINT"),
        ("event_id", "VARCHAR"),
        ("game_year", "INTEGER"),
        ("game_month", "INTEGER"),
        ("game_day", "INTEGER"),
        ("game_ticks_elapsed", "BIGINT"),
        ("emitted_at", "TIMESTAMP WITH TIME ZONE"),
        ("received_at", "TIMESTAMP WITH TIME ZONE"),
        ("cash_tenths", "BIGINT"),
        ("guests_in_park", "INTEGER"),
        ("park_rating", "INTEGER"),
        ("total_admissions", "BIGINT"),
        ("weather", "VARCHAR"),
        ("temperature_c", "INTEGER"),
    ]
    stats = query(out / "v1" / "plugin_stats.parquet", "SELECT work_ms_total, warmup FROM '{p}'")
    assert stats == [(1.5, True), (1.5, True)]
    assert query(out / "v1" / "park_snapshot.parquet", "SELECT cash_tenths FROM '{p}'")[0] == (
        -12345,
    )


def test_rows_are_ordered_by_session_then_seq(raw: Path, out: Path) -> None:
    land(raw, event("sb", 2), event("sa", 2), event("sb", 1), event("sa", 1))

    convert(raw, out)

    rows = query(out / "v1" / "park_snapshot.parquet", "SELECT session_id, seq FROM '{p}'")
    assert rows == [("sa", 1), ("sa", 2), ("sb", 1), ("sb", 2)]


def test_seq_interleaved_across_event_types_and_two_files_passes(raw: Path, out: Path) -> None:
    lines = session_lines("sa", 6)
    land(raw, *lines[:3], name="events-2026-09-30.jsonl")
    land(raw, *lines[3:], name="events-2026-10-01.jsonl")

    result = convert(raw, out)

    assert result.ok
    audit = query(out / "audit" / "seq_audit.parquet", "SELECT * FROM '{p}'")
    assert audit == [(PARK, "sa", 1, 6, 6, 0, 0, 1)]


def test_timestamps_are_the_exact_utc_instant_under_a_non_utc_zone(
    raw: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    try:
        land(raw, event("sa", 1, emitted_at="2026-09-30T16:30:00.123-07:00"))

        convert(raw, out)

        emitted = query(
            out / "v1" / "park_snapshot.parquet",
            "SELECT epoch_ms(emitted_at), strftime(emitted_at, '%Y-%m-%d %H:%M:%S.%g') FROM '{p}'",
        )
        assert emitted == [(1790811000123, "2026-09-30 23:30:00.123")]
    finally:
        monkeypatch.undo()
        time.tzset()


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (event("sa", 1, "mystery_event"), "no contract for 'mystery_event'"),
        (event("sa", 1, surprise=1), "surprise: field is not in the park_snapshot contract"),
        (event("sa", 1, game_year=None), "game_year: expected integer, got JSON NULL"),
        (event("sa", 1, guests_in_park=7.5), "guests_in_park: expected integer, got JSON DOUBLE"),
        (event("sa", 1, guests_in_park="7"), "guests_in_park: expected integer, got JSON VARCHAR"),
        (event("sa", 1, emitted_at="yesterday"), "emitted_at: value does not fit"),
        (event("sa", 1, emitted_at="2026-09-30 23:30:00"), "emitted_at: value does not fit"),
        (event("sa", 1, emitted_at="2026-09-30T23:30:00.123"), "emitted_at: value does not fit"),
        (event("sa", 1, received_at="2026-09-30"), "received_at: value does not fit"),
        (event("sa", 1, cash_tenths=2**63), "cash_tenths: value does not fit BIGINT"),
        ("not json at all", "not a JSON object"),
    ],
)
def test_schema_errors_write_nothing_and_exit_non_zero(
    raw: Path, out: Path, capsys: pytest.CaptureFixture[str], *, line: str, expected: str
) -> None:
    land(raw, *session_lines("sa", 2), line)

    result = convert(raw, out)

    assert any(expected in error for error in result.schema_errors)
    assert not out.exists()
    assert main(["--raw-dir", str(raw), "--out-dir", str(out)]) == 1
    assert expected in capsys.readouterr().out
    assert not out.exists()


def test_missing_required_field_is_a_schema_error(raw: Path, out: Path) -> None:
    lines = [json.loads(line) for line in session_lines("sa", 2)]
    del lines[1]["cash_tenths"]
    land(raw, *(json.dumps(line) for line in lines))

    result = convert(raw, out)

    assert result.schema_errors == [
        "events-2026-09-30.jsonl:2: cash_tenths: missing required field"
    ]
    assert not out.exists()


def test_schema_error_keeps_the_previous_output(raw: Path, out: Path) -> None:
    land(raw, *session_lines("sa", 2))
    convert(raw, out)
    before = sorted(p.relative_to(out) for p in out.rglob("*.parquet"))
    land(raw, event("sa", 3, guests_in_park=1.5))

    result = convert(raw, out)

    assert result.schema_errors
    assert sorted(p.relative_to(out) for p in out.rglob("*.parquet")) == before
    assert query(out / "v1" / "plugin_stats.parquet", "SELECT count(*) FROM '{p}'") == [(1,)]
    assert [p.name for p in out.parent.iterdir() if p.name.startswith(".")] == []


def test_successful_rerun_replaces_the_output(raw: Path, out: Path) -> None:
    land(raw, *session_lines("sa", 2))
    convert(raw, out)
    (out / "v1" / "stale.parquet").write_bytes(b"")
    land(raw, event("sa", 3, "plugin_stats"))

    convert(raw, out)

    assert not (out / "v1" / "stale.parquet").exists()
    assert query(out / "v1" / "plugin_stats.parquet", "SELECT count(*) FROM '{p}'") == [(2,)]
    assert [p.name for p in out.parent.iterdir() if p.name.startswith(".")] == []


@pytest.mark.parametrize(
    ("seqs", "audit_row"),
    [
        ([1, 2, 4, 5], (PARK, "sa", 1, 5, 4, 1, 0, 1)),
        ([1, 2, 2, 3], (PARK, "sa", 1, 3, 4, 0, 1, 1)),
        ([2, 3, 4], (PARK, "sa", 2, 4, 3, 1, 0, 1)),
        ([0, 1, 3], (PARK, "sa", 0, 3, 3, 1, 0, 1)),
        ([-1, 1, 2], (PARK, "sa", -1, 2, 3, 0, 0, 1)),
    ],
    ids=["gap", "repeat", "does-not-start-at-1", "zero-and-gap", "negative-start"],
)
def test_seq_violation_is_audited_and_parquet_is_still_written(
    raw: Path,
    out: Path,
    capsys: pytest.CaptureFixture[str],
    *,
    seqs: list[int],
    audit_row: tuple[object, ...],
) -> None:
    land(raw, *(event("sa", seq) for seq in seqs), *session_lines("sb", 3))

    status = main(["--raw-dir", str(raw), "--out-dir", str(out)])

    assert status == 1
    printed = capsys.readouterr().out
    assert "seq violation: session sa" in printed
    assert "session sb" not in printed
    audit = query(out / "audit" / "seq_audit.parquet", "SELECT * FROM '{p}' ORDER BY session_id")
    assert audit == [audit_row, (PARK, "sb", 1, 3, 3, 0, 0, 1)]
    assert query(out / "v1" / "park_snapshot.parquet", "SELECT count(*) FROM '{p}'") == [
        (len(seqs) + 1,)
    ]


def test_malformed_lines_are_counted_never_converted(
    raw: Path, out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    land(raw, *session_lines("sa", 2))
    bad = json.dumps({"reason": "bad", "line": event("sz", 1), "received_at": "x"})
    (raw / "malformed-2026-09-30.jsonl").write_text(bad + "\n" + bad + "\n", encoding="utf-8")
    (raw / "malformed-2026-10-01.jsonl").write_text(bad + "\n", encoding="utf-8")

    assert main(["--raw-dir", str(raw), "--out-dir", str(out)]) == 0

    assert "3 malformed line(s)" in capsys.readouterr().out
    assert query(out / "v1" / "park_snapshot.parquet", "SELECT count(*) FROM '{p}'") == [(1,)]
    assert query(out / "audit" / "seq_audit.parquet", "SELECT session_id FROM '{p}'") == [("sa",)]


def test_no_input_exits_non_zero_with_a_message(
    raw: Path, out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(NoInputError):
        convert(raw, out)

    assert main(["--raw-dir", str(raw), "--out-dir", str(out)]) == 1
    assert "No input" in capsys.readouterr().out
    assert not out.exists()


@pytest.fixture
def contracts_copy(tmp_path: Path) -> Iterator[Path]:
    target = tmp_path / "contracts"
    shutil.copytree(CONTRACTS_DIR, target)
    yield target


def test_types_come_from_the_contracts(raw: Path, out: Path, contracts_copy: Path) -> None:
    path = contracts_copy / "park_snapshot.odcs.yaml"
    text = path.read_text(encoding="utf-8")
    marker = "        physicalType: INTEGER\n"
    start = text.index("name: guests_in_park")
    at = text.index(marker, start)
    path.write_text(text[:at] + "        physicalType: BIGINT\n" + text[at + len(marker) :])
    land(raw, *session_lines("sa", 2))

    convert(raw, out, contracts_copy)

    described = query(out / "v1" / "park_snapshot.parquet", "DESCRIBE SELECT * FROM '{p}'")
    assert ("guests_in_park", "BIGINT") in [(row[0], row[1]) for row in described]


def test_output_passes_the_contract_runner(raw: Path, out: Path) -> None:
    land(raw, *session_lines("sa", 6), *session_lines("sb", 4))

    assert convert(raw, out).ok

    problems = check_all(out)
    assert sorted(problems) == [
        "envelope.odcs.yaml",
        "finance_month.odcs.yaml",
        "game_action.odcs.yaml",
        "guest_arrived.odcs.yaml",
        "guest_boarded.odcs.yaml",
        "guest_left.odcs.yaml",
        "guest_refused.odcs.yaml",
        "guest_snapshot.odcs.yaml",
        "park_snapshot.odcs.yaml",
        "plugin_stats.odcs.yaml",
        "ride_snapshot.odcs.yaml",
        "save_written.odcs.yaml",
        "session_start.odcs.yaml",
        "weather_change.odcs.yaml",
    ]
    assert not any(problems.values())


def test_a_line_separator_inside_a_string_does_not_split_the_line(raw: Path, out: Path) -> None:
    (raw / "v1").mkdir(parents=True)
    tricky = "0.1.0\u2028x\u2029y\x85z"
    line = json.dumps(json.loads(event("sa", 1, plugin_version=tricky)), ensure_ascii=False)
    assert tricky in line  # the raw separators are in the file, not \u escapes
    (raw / "v1" / "events-2026-09-30.jsonl").write_text(line + "\n", encoding="utf-8")

    result = convert(raw, out)

    assert result.ok
    assert result.schema_errors == []
    version = query(out / "v1" / "park_snapshot.parquet", "SELECT plugin_version FROM '{p}'")
    assert version == [(tricky,)]


def test_one_session_under_two_parks_is_a_violation(
    raw: Path, out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    land(raw, event("sa", 1), event("sa", 2), event("sa", 1, park_id="other", event_id="x-1"))

    status = main(["--raw-dir", str(raw), "--out-dir", str(out)])

    assert status == 1
    assert "session sa" in capsys.readouterr().out
    audit = query(out / "audit" / "seq_audit.parquet", "SELECT session_id, park_count FROM '{p}'")
    assert audit == [("sa", 2)]


def test_a_failed_write_keeps_the_previous_output(raw: Path, out: Path) -> None:
    land(raw, *session_lines("sa", 2))
    convert(raw, out)
    before = {p.relative_to(out): p.read_bytes() for p in out.rglob("*.parquet")}
    land(raw, event("sa", 3, "plugin_stats"))
    # A real OS failure: with a 1 byte file-size limit every Parquet write fails (EFBIG).
    soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    old_handler = signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    resource.setrlimit(resource.RLIMIT_FSIZE, (1, hard))
    try:
        with pytest.raises(duckdb.IOException):
            convert(raw, out)
    finally:
        resource.setrlimit(resource.RLIMIT_FSIZE, (soft, hard))
        signal.signal(signal.SIGXFSZ, old_handler)

    assert {p.relative_to(out): p.read_bytes() for p in out.rglob("*.parquet")} == before
    assert [p.name for p in out.parent.iterdir() if p.name.startswith(".")] == []


def test_only_v1_and_audit_are_replaced_and_other_files_survive(raw: Path, out: Path) -> None:
    land(raw, *session_lines("sa", 2))
    out.mkdir()
    (out / "README.md").write_text("keep me", encoding="utf-8")
    (out / "notes").mkdir()
    (out / "notes" / "a.txt").write_text("keep me too", encoding="utf-8")

    assert convert(raw, out).ok
    assert convert(raw, out).ok

    assert (out / "README.md").read_text(encoding="utf-8") == "keep me"
    assert (out / "notes" / "a.txt").read_text(encoding="utf-8") == "keep me too"
    assert (out / "v1" / "park_snapshot.parquet").exists()
    assert (out / "audit" / "seq_audit.parquet").exists()


@pytest.mark.parametrize(
    "where",
    ["contains", "equals", "inside"],
    ids=["raw-inside-out", "same-folder", "out-inside-raw"],
)
def test_an_output_overlapping_the_raw_folder_is_refused_and_raw_is_intact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], *, where: str
) -> None:
    top = tmp_path / "data"
    raw_dir = {"contains": top / "raw", "equals": top, "inside": top}[where]
    out_dir = {"contains": top, "equals": top, "inside": top / "out"}[where]
    land(raw_dir, *session_lines("sa", 2))
    (top / "notes.txt").write_text("note", encoding="utf-8")
    before = tree(top)

    with pytest.raises(UnsafeOutputError):
        convert(raw_dir, out_dir)

    assert main(["--raw-dir", str(raw_dir), "--out-dir", str(out_dir)]) == 1
    assert "Refusing to write" in capsys.readouterr().out
    assert tree(top) == before


def test_unrelated_settings_do_not_break_a_run_with_both_folders_given(
    raw: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENRCT2_LISTENER_HOST", "0.0.0.0")
    land(raw, *session_lines("sa", 2))

    assert main(["--raw-dir", str(raw), "--out-dir", str(out)]) == 0


def test_a_data_set_names_both_folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path))
    land(tmp_path / "rehearsal" / "raw", *session_lines("sa", 2))

    assert main(["--data-set", "rehearsal"]) == 0
    assert (tmp_path / "rehearsal" / "parquet" / "v1" / "park_snapshot.parquet").is_file()

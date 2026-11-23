"""The real-play result command against real Parquet files built from rows."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest.real_play_check import main

SESSION = "s1"
STALL = 7
PREBUILT = 1
# Five game days. Window k holds the ride snapshots between park snapshot k and k + 1; the stall
# is placed in window 2, so the end window (n - 3 = 2) holds it and the start window (0) does not.
WINDOWS = [[PREBUILT], [PREBUILT], [PREBUILT, STALL], [PREBUILT, STALL], [PREBUILT, STALL]]
CLICKS = (100, 200, 300)
SAVES = [102, 202, 302]
GOOD_SKIPPED = (3, 0, 1, 0, 0)  # preview, prediction, confirmed, unknown, cheat
SKIPPED_FIELDS = (
    "game_actions_skipped_preview_total",
    "game_actions_skipped_prediction_total",
    "game_actions_skipped_confirmed_total",
    "game_actions_skipped_unknown_total",
    "game_actions_skipped_cheat_total",
)

Rows = list[dict[str, object]]


@pytest.fixture
def data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATA_SET", raising=False)
    folder = tmp_path / "data" / "company" / "parquet" / "v1"
    folder.mkdir(parents=True)
    return folder


def sql_value(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def copy_to_parquet(folder: Path, name: str, select: str) -> None:
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(f"COPY ({select}) TO '{folder / name}.parquet' (FORMAT parquet)")
    finally:
        connection.close()


def write_table(folder: Path, name: str, rows: Rows) -> None:
    """Write rows as one Parquet file; a later row in the list is a later delivery."""
    stamped = [
        {**row, "received_at": f"2026-10-20T10:00:{n:02d}Z", "_raw_file": "f.jsonl", "_raw_line": n}
        for n, row in enumerate(rows)
    ]
    keys = list(stamped[0])
    lines = ", ".join("(" + ", ".join(sql_value(row[key]) for key in keys) + ")" for row in stamped)
    copy_to_parquet(folder, name, f"SELECT * FROM (VALUES {lines}) AS t({', '.join(keys)})")


def action(seq: int, kind: str, **fields: object) -> dict[str, object]:
    row: dict[str, object] = {
        "session_id": SESSION,
        "seq": seq,
        "hook": "execute",
        "action": kind,
        "action_label": "confirmed",
        "player": -1,
        "args_json": "{}",
        "args_ride": None,
        "result_error": 0,
        "event_id": f"e{seq}-{kind}",
    }
    row.update(fields)
    return row


def price(seq: int, ride: int = STALL, **fields: object) -> dict[str, object]:
    return action(seq, "ridesetprice", args_ride=ride, **fields)


def stats_row(
    seq: int,
    counter: int | None,
    skipped: tuple[int, ...],
    *,
    dropped: int = 0,
    failed: int = 0,
) -> dict[str, object]:
    return {
        "session_id": SESSION,
        "seq": seq,
        "event_id": f"stats{seq}",
        "work_items_skipped_total": counter,
        "lines_dropped_total": dropped,
        "work_items_failed_total": failed,
        **dict(zip(SKIPPED_FIELDS, skipped, strict=True)),
    }


def scenario(
    windows: list[list[int]] | None = None,
    counters: tuple[int | None, ...] = (0, 0, 0, 0, 0),
    skipped: tuple[int, ...] = GOOD_SKIPPED,
    *,
    dropped: tuple[int, ...] = (0, 0, 0, 0, 0),
    failed: tuple[int, ...] = (0, 0, 0, 0, 0),
) -> dict[str, Rows]:
    """One session: a plugin_stats row at seq 10k + 1 and a park snapshot at 10k + 2 per day k."""
    windows = WINDOWS if windows is None else windows
    parks: Rows = []
    stats: Rows = []
    rides: Rows = []
    for day, ids in enumerate(windows):
        base = 10 * day
        last = day == len(windows) - 1
        stats.append(
            stats_row(
                base + 1,
                counters[day],
                skipped if last else (0,) * 5,
                dropped=dropped[day],
                failed=failed[day],
            )
        )
        parks.append({"session_id": SESSION, "seq": base + 2, "event_id": f"park{day}"})
        for offset, ride in enumerate(ids):
            rides.append(
                {
                    "session_id": SESSION,
                    "seq": base + 3 + offset,
                    "event_id": f"ride{day}-{ride}",
                    "ride_id": ride,
                }
            )
    return {
        "park_snapshot": parks,
        "plugin_stats": stats,
        "ride_snapshot": rides,
        "game_action": [price(seq) for seq in CLICKS],
    }


def write_saves(folder: Path, seqs: list[int]) -> None:
    # A seq listed twice is one event delivered twice: same event_id, later received_at.
    rows: Rows = [{"session_id": SESSION, "seq": seq, "event_id": f"v{seq}"} for seq in seqs]
    if rows:
        write_table(folder, "save_written", rows)


def write_session(folder: Path, sessions: tuple[tuple[str, int], ...] = ((SESSION, 1),)) -> None:
    lines = ", ".join(
        f"('{sid}', {seq}, TIMESTAMP '2026-10-20 10:0{seq}:00')" for sid, seq in sessions
    )
    copy_to_parquet(
        folder, "session_start", f"SELECT * FROM (VALUES {lines}) AS t(session_id, seq, emitted_at)"
    )


def build(
    data: Path, tables: dict[str, Rows] | None = None, saves: list[int] | None = None
) -> None:
    write_session(data)
    for name, rows in (scenario() if tables is None else tables).items():
        if rows:
            write_table(data, name, rows)
    write_saves(data, SAVES if saves is None else saves)


def run(
    data: Path, capsys: pytest.CaptureFixture[str], args: list[str] | None = None
) -> tuple[int, str]:
    code = main(args if args is not None else ["--data-set", "company"])
    return code, capsys.readouterr().out


def go(
    data: Path,
    capsys: pytest.CaptureFixture[str],
    tables: dict[str, Rows] | None = None,
    saves: list[int] | None = None,
) -> tuple[int, str]:
    build(data, tables, saves)
    return run(data, capsys)


def test_pass_prints_every_verdict_in_order(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    build(data)
    code, out = run(data, capsys)
    assert code == 0
    positions = [
        out.index(text)
        for text in (
            "1. Ride builds: 1 (pass",
            "2. No build actions sent: pass (0 dropped-action rows",
            "3. Save hook, per checkpoint",
            "4. Supporting tables",
            "Session: s1",
            "Delete command: make delete-company-data SESSION=s1",
        )
    ]
    assert positions == sorted(positions)
    assert "start set 1 rides, end set 2 rides; new ride IDs: 7" in out
    assert "game_actions_skipped_preview_total: 3" in out
    assert "check 1 (Save Game As): fired" in out
    assert "check 2 (plain Save Game): fired" in out
    assert "check 3 (quit save): fired" in out


# R11: no build actions sent.


@pytest.mark.parametrize(
    "bad",
    [
        action(150, "ridesetname", args_json=json.dumps({"name": "x"})),
        price(150, action_label="preview", hook="query"),
        action(150, "ridesetsetting", args_json=json.dumps({"setting": 6})),
        action(150, "notanaction"),
    ],
)
def test_a_dropped_action_row_fails_verdict_2(
    data: Path, capsys: pytest.CaptureFixture[str], bad: dict[str, object]
) -> None:
    tables = scenario()
    tables["game_action"].append(bad)
    code, out = go(data, capsys, tables)
    assert code == 1
    assert "2. No build actions sent: FAIL (1 dropped-action rows" in out


def test_an_allowed_sub_type_row_is_not_a_dropped_row(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tables = scenario()
    tables["game_action"].append(
        action(150, "ridesetsetting", args_json=json.dumps({"setting": 0}))
    )
    code, out = go(data, capsys, tables)
    assert code == 0
    assert "2. No build actions sent: pass (0 dropped-action rows" in out


@pytest.mark.parametrize("skipped", [(0, 0, 0, 0, 0), (3, 0, 0, 0, 0), (0, 0, 1, 0, 0)])
def test_skipped_totals_at_zero_fail_verdict_2(
    data: Path, capsys: pytest.CaptureFixture[str], skipped: tuple[int, ...]
) -> None:
    code, out = go(data, capsys, scenario(skipped=skipped))
    assert code == 1
    assert "2. No build actions sent: FAIL (0 dropped-action rows" in out
    assert f"game_actions_skipped_preview_total: {skipped[0]}" in out


# R12: ride builds from proven-complete snapshot windows.


def test_two_new_stalls_fail(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    windows = [*WINDOWS[:2], [PREBUILT, STALL, 8], *WINDOWS[3:]]
    code, out = go(data, capsys, scenario(windows))
    assert code == 1
    assert "1. Ride builds: 2 (FAIL" in out
    assert "new ride IDs: 7, 8" in out
    assert "cannot classify (2 new rides found, need exactly 1)" in out


def test_a_park_that_starts_with_no_rides_has_an_empty_start_set(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = go(data, capsys, scenario([[], [], [STALL], [STALL], [STALL]]))
    assert code == 0
    assert "start set 0 rides, end set 1 rides; new ride IDs: 7" in out


def test_a_ride_demolished_after_the_start_window_is_not_counted(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    windows = [
        [PREBUILT, 5],
        [PREBUILT, 5],
        [PREBUILT, STALL],
        [PREBUILT, STALL],
        [PREBUILT, STALL],
    ]
    code, out = go(data, capsys, scenario(windows))
    assert code == 0
    assert "start set 2 rides, end set 2 rides; new ride IDs: 7" in out


def test_fewer_than_four_park_snapshots_is_refused(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = go(data, capsys, scenario(WINDOWS[:3], counters=(0, 0, 0)))
    assert code == 1
    assert "1. Ride builds: FAIL (not enough game days" in out


def test_a_repeat_snapshot_delivery_counts_once(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tables = scenario()
    tables["park_snapshot"].append(dict(tables["park_snapshot"][1]))
    tables["ride_snapshot"].append(dict(tables["ride_snapshot"][-1]))
    code, out = go(data, capsys, tables)
    assert code == 0
    assert "1. Ride builds: 1 (pass" in out
    assert "end set 2 rides" in out


def test_a_cut_short_start_window_is_refused_not_counted_as_new(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The counter rises across window 1 and the prebuilt ride is missing from window 0.
    windows = [[], [PREBUILT], [PREBUILT, STALL], [PREBUILT, STALL], [PREBUILT, STALL]]
    code, out = go(data, capsys, scenario(windows, counters=(0, 1, 2, 2, 2)))
    assert code == 1
    assert "1. Ride builds: FAIL (ride snapshot window incomplete (window 1))" in out


def test_unfinished_work_in_the_end_window_is_refused(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = go(data, capsys, scenario(counters=(0, 0, 0, 3, 5)))
    assert code == 1
    assert "1. Ride builds: FAIL (ride snapshot window incomplete (window 3))" in out


def test_a_lost_snapshot_line_in_the_end_window_is_refused(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # lines_dropped_total rises between the row before window 3's snapshot and the one after it.
    code, out = go(data, capsys, scenario(dropped=(0, 0, 0, 0, 2)))
    assert code == 1
    assert "1. Ride builds: FAIL (ride snapshot window incomplete (window 3))" in out


def test_a_failed_work_item_in_the_start_window_is_refused(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # work_items_failed_total rises across window 1 (rows 0 to 2).
    code, out = go(data, capsys, scenario(failed=(0, 0, 1, 1, 1)))
    assert code == 1
    assert "1. Ride builds: FAIL (ride snapshot window incomplete (window 1))" in out


@pytest.mark.parametrize("missing", ["row", "null"])
def test_a_missing_proof_row_is_refused(
    data: Path, capsys: pytest.CaptureFixture[str], missing: str
) -> None:
    if missing == "null":
        tables = scenario(counters=(0, 0, 0, 0, None))
    else:
        tables = scenario()
        tables["plugin_stats"] = tables["plugin_stats"][:-1]
    code, out = go(data, capsys, tables)
    assert code == 1
    assert "ride snapshot window incomplete (window 3)" in out


# R13: save checkpoints are price clicks on the new stall.


def test_a_refused_ride_verdict_makes_every_checkpoint_cannot_classify(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = go(data, capsys, scenario(counters=(0, 1, 2, 2, 2)))
    assert code == 1
    for line in ("check 1 (Save Game As)", "check 2 (plain Save Game)", "check 3 (quit save)"):
        assert f"{line}: cannot classify (the ride build verdict was refused)" in out


@pytest.mark.parametrize(
    ("saves", "first", "second", "third"),
    [
        ([], "not seen", "not seen", "not seen"),
        ([102], "fired", "not seen", "not seen"),
        ([102, 105], "unknown save type", "not seen", "not seen"),
        ([102, 202, 302], "fired", "fired", "fired"),
        ([102, 202, 205, 302], "fired", "unknown save type", "fired"),
        ([102, 302], "fired", "not seen", "fired"),
        ([102, 102, 202, 302], "fired", "fired", "fired"),  # a repeat delivery counts once
        ([50, 102, 202, 302], "fired", "fired", "fired"),  # a save before check 1 is in no window
    ],
)
def test_saves_per_checkpoint_window(
    data: Path,
    capsys: pytest.CaptureFixture[str],
    *,
    saves: list[int],
    first: str,
    second: str,
    third: str,
) -> None:
    _, out = go(data, capsys, saves=saves)
    assert f"check 1 (Save Game As): {first}" in out
    assert f"check 2 (plain Save Game): {second}" in out
    assert f"check 3 (quit save): {third}" in out


def test_no_save_for_plain_and_quit_prints_stop(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = go(data, capsys, saves=[102])
    assert code == 1
    assert "Stop: the save watcher needs a redesign" in out
    assert "Save hook verdict: FAIL" in out


# Session choice, refusals and the files the command may not find.


def test_latest_session_is_read_and_session_flag_picks_another(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(data)
    write_session(data, (("old", 1), (SESSION, 2)))
    code, out = run(data, capsys)
    assert code == 0
    assert "Session: s1" in out
    code, out = run(data, capsys, ["--data-set", "company", "--session", "old"])
    assert code == 1
    assert "Session: old" in out


def test_unknown_session_is_refused(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    build(data)
    code, out = run(data, capsys, ["--data-set", "company", "--session", "nope"])
    assert code == 2
    assert "no session nope" in out


def test_refused_without_data_set(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(data, capsys, [])
    assert code == 2
    assert "name a data set" in out


def test_exported_data_set_is_ignored_by_the_module(
    data: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    build(data)
    monkeypatch.setenv("DATA_SET", "company")
    code, out = run(data, capsys, ["--data-set", "company"])
    assert code == 0
    assert "refused" not in out
    code, out = run(data, capsys, [])
    assert code == 2
    assert "name a data set" in out


def test_delete_line_prints_for_company_only(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rehearsal = tmp_path / "data" / "rehearsal" / "parquet" / "v1"
    rehearsal.mkdir(parents=True)
    build(rehearsal)
    code, out = run(data, capsys, ["--data-set", "rehearsal"])
    assert code == 0
    assert "Session: s1" in out
    assert "Delete command" not in out


def test_missing_snapshot_and_action_data_gives_failing_verdicts_and_exit_1(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_session(data)
    write_saves(data, [102])
    code, out = run(data, capsys)
    assert code == 1
    assert "1. Ride builds: FAIL (not enough game days: 0 park snapshots" in out
    assert "2. No build actions sent: FAIL (0 dropped-action rows" in out
    assert "game_actions_skipped_preview_total: null" in out
    assert "check 1 (Save Game As): cannot classify" in out
    assert "Save hook verdict: FAIL" in out


def test_refused_without_a_session(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(data, capsys)
    assert code == 2
    assert "no-session" in out

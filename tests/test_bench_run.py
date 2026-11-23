"""The benchmark's verdict mode, run in-process against temp folders and a stand-in game.

The stand-in game (``tests/bench_standin_game.py``) is a real child process launched in
place of the binary; the listener, converter and judge are the real ones. Only the clock,
the sleep and the load average are substituted. The default plan is a complete run: a ride
snapshot each game day, the three work counters and the guest counters, so it passes; a plan
without them converts but is incomplete.
"""

# WEAKENED-OK: the marker-survival dry-run line was removed by spec R15

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import pytest

from openrct2_analytics.ingest import bench_play, bench_run
from openrct2_analytics.ingest.bench_actions import ACTION_HELPER_FILE, action_helper
from openrct2_analytics.ingest.bench_setup import (
    AUTOSAVE_EVERY_5_MINUTES,
    RunFolder,
    config_ini,
)
from tests.test_capture import free_port

REPO_ROOT = Path(__file__).resolve().parents[1]
JUDGED_DAYS = 2
STATS_LINES = JUDGED_DAYS + 1
FINAL_BURST = 10_000
FIXTURE_BYTES = b"stand-in park\n" * 64
PLUGIN_BYTES = b'registerPlugin({name: "openrct2-analytics"}); // stand-in build\n'
# What a run that sends no ride snapshots and no work counters is incomplete for: the columns
# and the ride file exist (the contracts carry them) but hold nothing.
NO_RIDES_NO_COUNTERS = [
    "judged row 1 has work_queue_length not equal to 0",
    "judged row 2 has work_queue_length not equal to 0",
    "judged row 1 has no ride snapshot",
    "judged row 2 has no ride snapshot",
    "last plugin_stats row reports lost work",
    "last plugin_stats row has no work_items_failed_total",
    "judged row 1 has no boarding_polls_total rise",
    "judged row 2 has no boarding_polls_total rise",
    "last judged row has no guests_known_in_park",
    "last plugin_stats row has no arrivals_recorded_total",
    "last plugin_stats row has no boarders_queued_total",
    "last plugin_stats row has no continuous_items_pending",
]
COMPLETE_RUN: dict[str, object] = {
    "rides": 1,
    "guest_counters": True,
    "stats_fields": {
        "work_units_total": 12,
        "work_items_skipped_total": 0,
        "work_queue_length": 0,
        "work_items_failed_total": 0,
        "continuous_items_pending": 0,
        "arrivals_recorded_total": 0,
        "boarders_queued_total": 0,
        "guest_fields_ms_total": 0.0,
    },
}


def complete_run(**changes: object) -> dict[str, object]:
    """A stand-in launch that sends a complete run, with ``changes`` on top."""
    return {**COMPLETE_RUN, **changes}


class BenchHarness:
    """Temp folders, settings and a stand-in game for one test."""

    def __init__(self, root: Path) -> None:
        private = root / "private"
        self.root = root
        self.fixture = private / "fixture.park"
        self.binary = private / "bin" / "OpenRCT2"
        self.game_path = private / "rct2"
        self.user_dir = private / "user"
        self.plugin = private / "build" / "openrct2-analytics.js"
        self.bench_dir = root / "bench"
        self.sample_dir = root / "sample"
        self.script = root / "standin" / "script.json"
        self.workload_calls: list[dict[str, object]] = []
        self.listener_port = free_port()
        self.game_port = free_port()
        for folder in (self.binary.parent, self.game_path, self.user_dir, self.plugin.parent):
            folder.mkdir(parents=True, exist_ok=True)
        self.script.parent.mkdir()
        self.fixture.write_bytes(FIXTURE_BYTES)
        self.plugin.write_bytes(PLUGIN_BYTES)
        self.binary.write_text(
            f'#!/bin/sh\nPYTHONPATH="{REPO_ROOT}" exec "{sys.executable}" '
            '-m tests.bench_standin_game "$@"\n',
            encoding="utf-8",
        )
        self.binary.chmod(0o755)
        self.plan(COMPLETE_RUN)

    def environment(self) -> dict[str, str]:
        return {
            "OPENRCT2_BINARY": str(self.binary),
            "OPENRCT2_BENCH_PARK": str(self.fixture),
            "OPENRCT2_GAME_PATH": str(self.game_path),
            "OPENRCT2_USER_DIR": str(self.user_dir),
            "OPENRCT2_BENCH_DIR": str(self.bench_dir),
            "BENCH_STANDIN_SCRIPT": str(self.script),
        }

    def plan(self, *launches: dict[str, object]) -> None:
        script = {"listener_port": self.listener_port, "launches": list(launches)}
        self.script.write_text(json.dumps(script), encoding="utf-8")

    def options(self, **changes: object) -> bench_play.Options:
        fields: dict[str, object] = {
            "listener_port": self.listener_port,
            "game_port": self.game_port,
            "judged_days": JUDGED_DAYS,
            "sample_days": STATS_LINES,
            "seconds_per_day": 5.0,
            "startup_seconds": 30.0,
            "stop_grace_seconds": 5.0,
            "fixture_sha1_prefix": hashlib.sha1(FIXTURE_BYTES).hexdigest()[:8],
            "sample_dir": self.sample_dir,
            "load_average": lambda: 0.5,
        }
        fields.update(changes)
        return bench_play.Options(**fields)  # type: ignore[arg-type]

    def run(
        self,
        *,
        any_park: bool = False,
        sample: bool = False,
        dry_run: bool = False,
        **changes: object,
    ) -> int:
        options = self.options(**changes)
        code = bench_run.run(
            options, lambda: self.plugin, any_park=any_park, sample=sample, dry_run=dry_run
        )
        self.assert_every_line_landed()
        return code

    def assert_every_line_landed(self) -> None:
        """Every line each stand-in launch sent landed whole: the stop order cut nothing."""
        entries = self.launches()
        sent = {entry["session"]: entry["sent"] for entry in entries if "sent" in entry}
        assert len(sent) == sum("argv" in entry for entry in entries), entries
        landed: Counter[object] = Counter()
        for path in self.bench_dir.glob("*/raw/v1/events-*.jsonl"):
            for line in path.read_text(encoding="utf-8").splitlines():
                landed[json.loads(line)["session_id"]] += 1
        assert not list(self.bench_dir.glob("*/raw/malformed-*.jsonl"))
        assert dict(landed) == sent

    def launches(self) -> list[dict[str, object]]:
        log = self.script.parent / "launches.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def launch_argvs(self) -> list[object]:
        return [entry["argv"] for entry in self.launches() if "argv" in entry]

    def folder(self, name: str) -> RunFolder:
        return RunFolder(self.bench_dir / name)

    def verdict(self) -> dict[str, object]:
        record = json.loads((self.bench_dir / "verdict.json").read_text(encoding="utf-8"))
        assert isinstance(record, dict)
        return record

    def private_texts(self) -> list[str]:
        paths = (self.fixture, self.binary, self.game_path, self.user_dir, self.bench_dir)
        return [text for path in paths for text in (str(path), str(path.resolve()))]


def make_bench(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BenchHarness:
    """A BenchHarness whose settings are the only OPENRCT2_ variables in the environment."""
    for name in list(os.environ):
        if name.startswith("OPENRCT2_"):
            monkeypatch.delenv(name)
    made = BenchHarness(tmp_path)
    for name, value in made.environment().items():
        monkeypatch.setenv(name, value)
    return made


@pytest.fixture(name="real_bench")
def real_bench_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BenchHarness:
    """A harness whose runs go through the real action workload check."""
    return make_bench(tmp_path, monkeypatch)


@pytest.fixture(name="bench")
def bench_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BenchHarness:
    """A harness whose workload check accepts and records its arguments (the stand-in game
    cannot send the 60,032 rows a hook a real delivery has); ``real_bench`` keeps it."""
    made = make_bench(tmp_path, monkeypatch)

    def accept_workload(
        workload: object, judged_days: int, rows_per_call: int, **keywords: object
    ) -> list[str]:
        made.workload_calls.append(
            {"judged_days": judged_days, "rows_per_call": rows_per_call, **keywords}
        )
        return []

    monkeypatch.setattr(bench_run, "workload_reasons", accept_workload)
    return made


def raw_events(folder: RunFolder) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for path in sorted((folder.raw / "v1").glob("events-*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def runs_of(record: dict[str, object]) -> list[dict[str, object]]:
    runs = record["runs"]
    assert isinstance(runs, list)
    return runs


# ---- one run: launch, stop condition, stop order ----


def test_each_run_launches_the_game_headless_on_its_own_park_copy_and_config(
    bench: BenchHarness,
) -> None:
    assert bench.run() == 0

    names = [f"run-{slot}-attempt-1" for slot in (1, 2, 3)]
    expected = []
    for name in names:
        folder = bench.folder(name)
        park_copy = folder.save_dir / "bench-park.park"
        expected.append(
            [
                "host",
                str(park_copy),
                "--headless",
                "--port",
                str(bench.game_port),
                "--user-data-path",
                str(folder.user_data),
            ]
        )
        assert park_copy.read_bytes() == FIXTURE_BYTES
        assert (folder.user_data / "plugin" / "openrct2-analytics.js").read_bytes() == PLUGIN_BYTES
        assert (folder.user_data / "plugin" / ACTION_HELPER_FILE).read_text(encoding="utf-8") == (
            action_helper(1)
        )
        config = (folder.user_data / "config.ini").read_text(encoding="utf-8")
        assert config == config_ini(bench.game_path, AUTOSAVE_EVERY_5_MINUTES)
        assert "autosave = 1\n" in config
    assert bench.launch_argvs() == expected
    assert sorted(path.name for path in bench.bench_dir.iterdir()) == [*names, "verdict.json"]


def test_a_run_stops_after_n_days_then_lands_the_games_last_line_whole(bench: BenchHarness) -> None:
    # After SIGTERM the stand-in waits, then sends a burst the listener needs a while to land,
    # then exits: only terminate, then end of input, then stopping the listener lands it all.
    bench.plan(complete_run(stats=200, day_seconds=0.05, final_lines=FINAL_BURST))

    started = time.monotonic()
    assert bench.run() == 0
    assert time.monotonic() - started < 60  # 200 days would take 10 s per run

    for slot in (1, 2, 3):
        folder = bench.folder(f"run-{slot}-attempt-1")
        events = raw_events(folder)
        stats = [event for event in events if event["event_type"] == "plugin_stats"]
        assert STATS_LINES <= len(stats) < 200
        # The game's line sent after it was asked to quit landed: the listener was stopped
        # only after the connection reached end of input.
        assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
        assert events[-1]["event_type"] == "park_snapshot"
        assert len(events) > FINAL_BURST
        assert not list(folder.raw.glob("malformed-*.jsonl"))
        assert (folder.parquet / "audit" / "seq_audit.parquet").is_file()
    assert all(run["valid"] for run in runs_of(bench.verdict()))


def test_a_game_that_ignores_terminate_is_killed_after_the_grace_period(
    bench: BenchHarness,
) -> None:
    bench.plan(complete_run(ignore_term=True))

    assert bench.run(stop_grace_seconds=0.5) == 0

    assert sum("term_ignored" in entry for entry in bench.launches()) == 3
    assert all(run["valid"] for run in runs_of(bench.verdict()))


# ---- the verdict record ----


def test_the_verdict_records_three_judged_runs_without_any_private_path(
    bench: BenchHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    assert bench.run() == 0

    record = bench.verdict()
    assert record["passed"] is True
    for run in runs_of(record):
        assert run["valid"] is True and run["complete"] is True
        assert run["completion_reasons"] == []
        assert run["worst_tick_offset_ticks"] == 25 and run["worst_tick_period_ticks"] == 100
    assert record["discarded"] == []
    conditions = record["conditions"]
    assert isinstance(conditions, dict)
    assert conditions["park"] == "benchmark park"
    assert conditions["fixture_sha1_prefix"] == hashlib.sha1(FIXTURE_BYTES).hexdigest()[:8]
    assert conditions["openrct2_version"] == "OpenRCT2, v0.5.5 (standin on HEAD)"
    assert conditions["judged_days"] == "2"
    assert conditions["attempt_folders"] == "run-1-attempt-1, run-2-attempt-1, run-3-attempt-1"

    out = capsys.readouterr()
    assert "Verdict: PASSED (benchmark park" in out.out
    texts = [out.out, out.err, (bench.bench_dir / "verdict.json").read_text(encoding="utf-8")]
    for private in bench.private_texts():
        assert all(private not in text for text in texts), private
    assert bench.fixture.read_bytes() == FIXTURE_BYTES


# ---- the failure rules ----


def test_a_run_with_no_ride_snapshots_and_no_work_counters_is_valid_but_incomplete(
    bench: BenchHarness,
) -> None:
    bench.plan({})

    assert bench.run() == 1

    record = bench.verdict()
    assert record["passed"] is False
    for run in runs_of(record):
        assert run["valid"] is True and run["complete"] is False
        assert run["completion_reasons"] == NO_RIDES_NO_COUNTERS


def test_an_invalid_attempt_is_repeated_once_and_recorded_as_discarded(bench: BenchHarness) -> None:
    bench.plan(complete_run(slow_row=1), complete_run())

    assert bench.run() == 0

    assert len(bench.launch_argvs()) == 4  # a valid run is never repeated
    record = bench.verdict()
    discarded = record["discarded"]
    assert isinstance(discarded, list) and len(discarded) == 1
    assert discarded[0]["slot"] == 1
    assert discarded[0]["validity_reasons"] == ["judged row 1 has game_speed other than 1"]
    assert all(run["valid"] for run in runs_of(record))
    assert bench.folder("run-1-attempt-1").root.is_dir()  # kept
    assert not bench.folder("run-2-attempt-2").root.exists()


def test_a_run_that_times_out_is_invalid_and_repeated_at_most_once(bench: BenchHarness) -> None:
    bench.plan({"stats": 1}, {"stats": 1}, complete_run())
    other_park = "f" * 8  # the stand-in park is "not the benchmark park"

    code = bench.run(
        any_park=True, seconds_per_day=0.5, startup_seconds=2.0, fixture_sha1_prefix=other_park
    )

    assert code == 1
    assert len(bench.launch_argvs()) == 4
    record = bench.verdict()
    timed_out = "timed out after 3 s before the stop condition"
    first = runs_of(record)[0]
    assert first["valid"] is False and first["validity_reasons"] == [timed_out]
    discarded = record["discarded"]
    assert isinstance(discarded, list)
    assert [(entry["slot"], entry["validity_reasons"]) for entry in discarded] == [(1, [timed_out])]
    conditions = record["conditions"]
    assert isinstance(conditions, dict) and conditions["park"] == "not the benchmark park"


def test_a_game_that_exits_early_makes_the_run_invalid(bench: BenchHarness) -> None:
    bench.plan({"stats": 1, "exit_early": True}, complete_run())

    assert bench.run() == 0

    discarded = bench.verdict()["discarded"]
    assert isinstance(discarded, list)
    reasons = discarded[0]["validity_reasons"]
    assert reasons == ["the game exited (code 0) before the stop condition"]


def test_dry_run_uses_one_attempt_and_h_one_and_fails_without_helper_rows(
    real_bench: BenchHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    assert real_bench.run(dry_run=True) == 1  # h=0 is a failed dry run, not a pass

    assert len(real_bench.launch_argvs()) == 1
    folder = real_bench.folder("dry-run-attempt-1")
    assert (folder.user_data / "plugin" / ACTION_HELPER_FILE).read_text(encoding="utf-8") == (
        action_helper(1)
    )
    output = capsys.readouterr().out
    assert "h=0 rows per call" in output
    assert "action helper produced no rows in judged periods" in output
    assert "Helper player value(s): not seen" in output
    assert "lines_queued_max=" in output
    assert "lines_dropped_total=" in output
    assert "game_actions_dropped_preview_total=" in output


def test_dry_run_prints_the_period_lines_even_when_the_run_has_no_cost(
    bench: BenchHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    bench.plan(complete_run(stats_fields={**COMPLETE_RUN["stats_fields"], "period_ticks": 0}))  # type: ignore[dict-item]

    assert bench.run(dry_run=True) == 1

    output = capsys.readouterr().out
    assert "no cost" in output
    assert "Period 1: lines_queued_max=" in output


def test_a_verdict_run_without_helper_rows_is_incomplete(real_bench: BenchHarness) -> None:
    assert real_bench.run() == 1

    assert len(real_bench.launch_argvs()) == 3  # incomplete is not invalid: nothing is repeated
    for run in runs_of(real_bench.verdict()):
        assert run["valid"] is True and run["complete"] is False
        assert "action helper produced no rows in judged periods" in run["completion_reasons"]  # type: ignore[operator]


def test_judged_runs_use_the_named_rows_per_call_and_query_expectation(bench: BenchHarness) -> None:
    assert bench.run() == 0

    keys = ("judged_days", "rows_per_call", "expect_query")
    assert [tuple(call[key] for key in keys) for call in bench.workload_calls] == [
        (JUDGED_DAYS, 1, True)
    ] * 3


def test_judged_runs_follow_the_constants_updated_from_the_dry_run(
    bench: BenchHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bench_run, "JUDGED_ROWS_PER_CALL", 2)
    monkeypatch.setattr(bench_run, "JUDGED_EXPECT_QUERY", False)

    assert bench.run() == 0

    folder = bench.folder("run-1-attempt-1")
    assert (folder.user_data / "plugin" / ACTION_HELPER_FILE).read_text(encoding="utf-8") == (
        action_helper(2)
    )
    assert {call["expect_query"] for call in bench.workload_calls} == {False}
    assert {call["rows_per_call"] for call in bench.workload_calls} == {2}


def test_a_dry_run_checks_one_row_per_call(bench: BenchHarness) -> None:
    assert bench.run(dry_run=True) == 0

    (call,) = bench.workload_calls
    assert call["rows_per_call"] == 1


def test_a_void_invalid_attempt_is_reported_void_and_not_repeated(bench: BenchHarness) -> None:
    lossy = {**COMPLETE_RUN["stats_fields"], "write_partial_total": 1}  # type: ignore[dict-item]
    bench.plan(complete_run(slow_row=1, stats_fields=lossy), complete_run())

    assert bench.run() == 1

    assert len(bench.launch_argvs()) == 3  # one launch for slot 1: a void run is not repeated
    assert not bench.folder("run-1-attempt-2").root.exists()
    record = bench.verdict()
    assert record["void"] is True and record["discarded"] == []
    assert "run 1 is void" in record["reasons"]  # type: ignore[operator]


def test_a_fixture_changed_by_a_run_makes_that_run_and_every_later_one_invalid(
    bench: BenchHarness,
) -> None:
    bench.plan(complete_run(touch=str(bench.fixture)), complete_run())

    assert bench.run() == 1

    assert len(bench.launch_argvs()) == 6
    record = bench.verdict()
    for run in runs_of(record):
        assert "fixture changed during the run" in run["validity_reasons"]  # type: ignore[operator]
    assert bench.folder("run-1-attempt-1").save_dir.joinpath("bench-park.park").read_bytes() == (
        FIXTURE_BYTES
    )

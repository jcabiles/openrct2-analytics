"""The autopilot run against the stand-in game, and its write boundary, at function level.

Each run test plays one stand-in launch from a source save dated 20 October of game year 3 to
1 March of game year 4, through the real folder setup, listener, watcher, converter, contract
check and save pairing. A failing case starts from that clean run and changes one thing: the
stand-in's plan, an argument, or the raw capture right after the game stopped (as a game that
sent that line would have left it). The stand-in applies its own save rule and never runs the
helper's code, so these tests prove the run's order and checks, not the helper.
"""

from __future__ import annotations

import json
import os
import platform
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest import autopilot_run
from openrct2_analytics.ingest.autopilot_run import (
    RunResult,
    run_autopilot,
    work_folder_name,
    write_boundary_problem,
)
from openrct2_analytics.ingest.bench_play import Bench
from openrct2_analytics.ingest.bench_play import play as real_play
from openrct2_analytics.ingest.bench_setup import RunFolder, load_settings
from openrct2_analytics.ingest.listener import Lander
from openrct2_analytics.ingest.save_files import read_records, read_save_written
from openrct2_analytics.ingest.save_pairing import judge_saves
from tests.test_bench_run import BenchHarness, make_bench

PARK = "k1791600000000-autopil"
G = 3
SAVE_STEM = "k1791600000000-autopil-autopilot-4"
SAVE_NAME = f"{SAVE_STEM}.park"
SOURCE_BYTES = b"proven source park\n+standin-7"
WORK_NAME = "autopilot-k1791600000000-autopil-20261113T093005Z"
STOP_LINE = "1 save_written row(s); expected one, dated 1 March of game year 4."

Tamper = Callable[[RunFolder], None]


def clean_entry(**changes: object) -> dict[str, object]:
    """A launch that starts 20 October of year 3 and plays to its save on 1 March of year 4."""
    entry: dict[str, object] = {
        "park_id": PARK,
        "start_date": [G, 7, 20],
        "stats": 40,
        "speed": 8,
        "save": True,
        "final_lines": 0,  # the helper pauses the game after its save: no later line
    }
    return {**entry, **changes}


class Runner:
    """A BenchHarness, a proven source save outside the work folder, and one run of it."""

    def __init__(self, bench: BenchHarness, monkeypatch: pytest.MonkeyPatch) -> None:
        self.bench = bench
        self.monkeypatch = monkeypatch
        self.source = bench.root / "private" / "proven" / "source.park"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(SOURCE_BYTES)
        self.timeouts: list[float] = []  # the timeout each run's play was given

    def run(
        self,
        entry: dict[str, object] | None = None,
        *,
        tamper: Tamper | None = None,
        loaded_save_id: str = "save-standin-7",
        loaded_save_session_id: str = "standin-7",
        planned_days: int | None = None,
    ) -> RunResult:
        self.bench.plan(entry or clean_entry())

        def play_then_tamper(*args: object, **kwargs: object) -> str | None:
            bench: Bench = args[0]  # type: ignore[assignment]
            self.timeouts.append(bench.options.timeout_seconds(kwargs["days"]))  # type: ignore[arg-type]
            problem = real_play(*args, **kwargs)  # type: ignore[arg-type]
            folder: RunFolder = args[1]  # type: ignore[assignment]
            date_save_as_emitted(folder)
            if tamper is not None:
                tamper(folder)
            return problem

        self.monkeypatch.setattr(autopilot_run, "play", play_then_tamper)
        return run_autopilot(
            load_settings(platform.system()),
            park_id=PARK,
            source=self.source,
            work_name=WORK_NAME,
            g=G,
            loaded_save_id=loaded_save_id,
            loaded_save_session_id=loaded_save_session_id,
            built=self.bench.plugin,
            options=self.bench.options(),
            **({} if planned_days is None else {"planned_days": planned_days}),
        )


@pytest.fixture(name="runner")
def _runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Runner:
    return Runner(make_bench(tmp_path, monkeypatch), monkeypatch)


def date_save_as_emitted(folder: RunFolder) -> None:
    """Give the stand-in's save file the modified time of its ``save_written`` ``emitted_at``.

    With a start date the stand-in dates ``emitted_at`` from a fixed base in the past, while the
    file it writes carries the wall-clock time, so pairing (``emitted_at`` to ``emitted_at`` plus
    5 s) could never match. The real game writes the file just after it emits the event. This
    runs right after the game stopped, before ``watcher.stop()`` takes its last scan.
    """
    for path in sorted((folder.raw / "v1").glob("events-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event["event_type"] == "save_written":
                emitted = datetime.fromisoformat(event["emitted_at"]).timestamp()
                os.utime(folder.save_dir / SAVE_NAME, (emitted, emitted))


def raw_file(folder: RunFolder) -> Path:
    (path,) = sorted((folder.raw / "v1").glob("events-*.jsonl"))
    return path


def rewrite(
    folder: RunFolder, change: Callable[[dict[str, object]], dict[str, object] | None]
) -> None:
    """Rewrite each raw line through ``change``; None drops the line."""
    path = raw_file(folder)
    kept = []
    for line in path.read_text(encoding="utf-8").splitlines():
        event = change(json.loads(line))
        if event is not None:
            kept.append(json.dumps(event))
    path.write_text("".join(f"{line}\n" for line in kept), encoding="utf-8")


def query(path: Path, sql: str) -> list[tuple[object, ...]]:
    connection = duckdb.connect(":memory:")
    try:
        return connection.execute(sql.replace("{p}", path.as_posix())).fetchall()
    finally:
        connection.close()


def test_work_folder_name_holds_the_park_and_the_utc_time() -> None:
    moment = datetime(2026, 11, 13, 9, 30, 5, 123000, tzinfo=UTC)

    assert work_folder_name(PARK, moment) == WORK_NAME


def test_a_clean_run_stops_on_1_march_passes_every_check_and_pairs_its_save(
    runner: Runner, capsys: pytest.CaptureFixture[str]
) -> None:
    result = runner.run()

    monthly = [
        line for line in capsys.readouterr().out.splitlines() if line.startswith("autopilot: park ")
    ]
    assert monthly
    assert all(line.startswith(f"autopilot: park {PARK} \u00b7 ") for line in monthly)
    # The stand-in plays 20 October of year 3 to 1 March of year 4 with one October statement.
    assert result.summary.statement_count == 1
    assert result.summary.first_statement == (3, 7)

    assert result.problems == []
    assert result.reached_stop is True
    work = runner.bench.bench_dir / WORK_NAME
    assert result.work_dir == work
    assert result.session_id == "standin-1"
    (sent,) = [entry["sent"] for entry in runner.bench.launches() if "sent" in entry]
    assert result.event_count == sent
    assert result.watch.error is None
    assert runner.source.read_bytes() == SOURCE_BYTES
    # The helper saves as the stem and stops in game year 4; only the work folder holds it.
    helper = (work / "user-data" / "plugin" / "openrct2-analytics-bench-save.js").read_text()
    assert 'var SAVE_FILENAME = "k1791600000000-autopil-autopilot-4";' in helper
    assert "var TARGET_YEAR = 4;" in helper
    # The capture lands in raw/v1, the records in save_files/v1, the Parquet in parquet/v1.
    assert list((work / "raw" / "v1").glob("events-*.jsonl"))
    assert list((work / "save_files" / "v1").glob("save_file_observation_*.jsonl"))
    parquet = work / "parquet" / "v1"
    assert query(
        parquet / "save_written.parquet", "SELECT game_year, game_month, game_day FROM '{p}'"
    ) == [(4, 0, 1)]
    finance = "SELECT statement_year, statement_month FROM '{p}'"
    assert query(parquet / "finance_month.parquet", finance) == [(3, 7)]
    last = "SELECT max(game_year * 10000 + game_month * 100 + game_day) FROM '{p}'"
    assert query(parquet / "park_snapshot.parquet", last) == [(40001,)]
    # The returned started and watch pair the end-of-year save, as the report after landing will.
    records, unreadable = read_records(work / "save_files", result.started)
    judgment = judge_saves(
        records,
        read_save_written(work / "parquet"),
        result.started,
        unreadable=unreadable,
        watcher_error=result.watch.error,
    )
    assert not judgment.failed
    assert [pair.record.file_name for pair in judgment.this_run.pairs] == [SAVE_STEM]


def test_the_watchers_last_scan_records_the_save_before_the_pairing_reads(
    runner: Runner, monkeypatch: pytest.MonkeyPatch
) -> None:
    # With no poll during play, only the scan that watcher.stop() runs can see the save.
    monkeypatch.setattr(autopilot_run, "POLL_SECONDS", 3600.0)

    result = runner.run()

    assert result.problems == []


def test_an_early_exit_did_not_reach_the_stop(runner: Runner) -> None:
    # The game crashes after 5 game days, in October of year 3.
    result = runner.run(clean_entry(stats=5, exit_early=True))

    assert result.reached_stop is False
    assert result.problems[0] == "the game exited (code 0) before the stop condition"
    assert "No finance_month row for October of game year 3." in result.problems
    assert "0 save_written row(s); expected one, dated 1 March of game year 4." in result.problems
    assert f"Saves paired with a file: none; expected only {SAVE_STEM}." in result.problems


def test_no_october_statement_fails(runner: Runner) -> None:
    # The game never sent October's statement: the line is gone and the later seq close up.
    def drop_october(folder: RunFolder) -> None:
        dropped: list[int] = []

        def change(event: dict[str, object]) -> dict[str, object] | None:
            if event["event_type"] == "finance_month":
                dropped.append(int(event["seq"]))  # type: ignore[call-overload]
                return None
            if dropped:
                event["seq"] = int(event["seq"]) - 1  # type: ignore[call-overload]
                event["event_id"] = f"{event['session_id']}-{event['seq']}"
            return event

        rewrite(folder, change)

    result = runner.run(tamper=drop_october)

    assert result.reached_stop is True
    assert result.problems == ["No finance_month row for October of game year 3."]


def test_a_seq_gap_fails(runner: Runner) -> None:
    def drop_seq_5(event: dict[str, object]) -> dict[str, object] | None:
        return None if event["seq"] == 5 else event

    result = runner.run(tamper=lambda folder: rewrite(folder, drop_seq_5))

    assert result.reached_stop is True
    assert result.problems == [
        f"seq audit: session standin-1 (park {PARK}): first_seq=1, last_seq=27, rows=26, "
        "missing=1, duplicates=0, parks=1"
    ]


def test_a_malformed_line_fails(runner: Runner) -> None:
    def send_malformed(folder: RunFolder) -> None:
        Lander(folder.raw).land(b"{not json\n")

    result = runner.run(tamper=send_malformed)

    assert result.reached_stop is True
    assert result.problems == ["1 malformed line(s) in the capture."]


def test_a_converted_row_the_contract_refuses_fails(runner: Runner) -> None:
    # contracts/session_start.odcs.yaml line 35: api_version has minimum 1.
    def zero_api_version(event: dict[str, object]) -> dict[str, object]:
        return {**event, "api_version": 0} if event["event_type"] == "session_start" else event

    result = runner.run(tamper=lambda folder: rewrite(folder, zero_api_version))

    assert result.reached_stop is True
    assert result.problems == [
        "Contract session_start.odcs.yaml: test overall result: failed",
        "Contract session_start.odcs.yaml: test Check that field api_version has a minimum of 1: "
        "failed (Actual invalid_count(api_version) was 1, expected = 0)",
    ]


def test_an_invalid_save_file_record_fails(runner: Runner) -> None:
    def negative_size(folder: RunFolder) -> None:
        (path,) = sorted((folder.root / "save_files" / "v1").glob("save_file_observation_*.jsonl"))
        lines = path.read_text(encoding="utf-8").splitlines()
        record = {**json.loads(lines[-1]), "size_bytes": -1}
        lines[-1] = json.dumps(record)
        path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")

    result = runner.run(tamper=negative_size)

    assert result.reached_stop is True
    (record_file,) = (result.work_dir / "save_files" / "v1").glob("save_file_observation_*.jsonl")
    assert result.problems == [
        "Save-file records: test overall result: failed",
        "Save-file records: test size_bytes is at least 0: failed "
        "(Actual custom_sql(save_file_observation) was 1, expected = 0)",
        f"Save-file records: {record_file.name}: test overall result: failed",
        f"Save-file records: {record_file.name}: test size_bytes is at least 0: failed "
        "(Actual custom_sql(save_file_observation) was 1, expected = 0)",
    ]


def test_a_smaller_planned_days_gives_a_shorter_timeout(runner: Runner) -> None:
    # The harness options are 5.0 s per planned day plus 30 s.
    runner.run(planned_days=10)
    assert runner.timeouts == [80.0]


def test_the_default_planned_days_is_the_245_day_cap(runner: Runner) -> None:
    runner.run()

    assert runner.timeouts == [1255.0]


@pytest.mark.parametrize("days", [0, 246])
def test_planned_days_out_of_bounds_is_refused(runner: Runner, days: int) -> None:
    with pytest.raises(ValueError, match="from 1 to 245"):
        runner.run(planned_days=days)


def test_a_wrong_park_id_fails(runner: Runner) -> None:
    result = runner.run(clean_entry(park_id="k1791600000000-other1"))

    assert result.reached_stop is True
    assert result.problems == [
        f"Converted rows carry park_id k1791600000000-other1, expected {PARK}."
    ]


def test_lineage_that_does_not_match_the_source_fails(runner: Runner) -> None:
    result = runner.run(loaded_save_id="save-standin-6", loaded_save_session_id="standin-6")

    assert result.reached_stop is True
    assert result.problems == [
        "The session loaded save save-standin-7 of session standin-7; "
        "the source save is save-standin-6 of session standin-6."
    ]


def test_a_park_snapshot_after_1_march_fails(runner: Runner) -> None:
    # The last park_snapshot, the one just before the save, is dated 2 March.
    def second_of_march(folder: RunFolder) -> None:
        events = [json.loads(line) for line in raw_file(folder).read_text().splitlines()]
        last = max(e["seq"] for e in events if e["event_type"] == "park_snapshot")

        def move(event: dict[str, object]) -> dict[str, object]:
            if event["seq"] == last:
                event["game_day"] = 2
            return event

        rewrite(folder, move)

    result = runner.run(tamper=second_of_march)

    assert result.reached_stop is True
    (problem,) = result.problems
    assert problem.startswith("park_snapshot at seq ")
    assert problem.endswith(" is dated after 1 March of game year 4.")


def test_a_source_save_changed_during_the_run_fails(runner: Runner) -> None:
    result = runner.run(clean_entry(touch=str(runner.source)))

    assert result.reached_stop is True
    assert result.problems == ["The source save changed during the run."]


# The write boundary, on planted folders.


class Layout:
    """A project folder, a data folder, the player's folder and the archive, all in tmp_path."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.project = root / "project"
        self.data = root / "data"
        self.user = root / "player" / "OpenRCT2"
        self.archive = root / "backups" / "park-backups"
        self.bench = root / "bench"
        for folder in (
            self.project / "data" / "sample",
            self.project / "plugin" / "src",
            self.data / "rehearsal" / "raw" / "v1",
            self.data / "company" / "raw" / "v1",
            self.data / "company" / "save_files" / "v1",
            self.data / "company" / "registry" / "v1",
            self.user,
            self.archive,
            self.bench,
        ):
            folder.mkdir(parents=True)
        monkeypatch.setenv("OPENRCT2_DATA_DIR", str(self.data))

    def problem(self, work: Path) -> str | None:
        return write_boundary_problem(work, self.user, self.archive, self.project)


@pytest.fixture(name="layout")
def _layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Layout:
    return Layout(tmp_path, monkeypatch)


PROTECTED: dict[str, Callable[[Layout], Path]] = {
    "the player's OpenRCT2 folder": lambda lay: lay.user,
    "the archive folder": lambda lay: lay.archive,
    "data/sample/": lambda lay: lay.project / "data" / "sample",
    "data/rehearsal/": lambda lay: lay.data / "rehearsal",
    "data/company/": lambda lay: lay.data / "company",
    "plugin/src/": lambda lay: lay.project / "plugin" / "src",
}


def test_a_clean_layout_passes(layout: Layout) -> None:
    assert layout.problem(layout.bench / WORK_NAME) is None


@pytest.mark.parametrize("name", list(PROTECTED))
def test_a_work_folder_equal_to_a_protected_folder_is_refused(layout: Layout, name: str) -> None:
    assert layout.problem(PROTECTED[name](layout)) == (
        f"The work folder equals, contains or lies inside {name}."
    )


@pytest.mark.parametrize("name", list(PROTECTED))
def test_a_work_folder_inside_a_protected_folder_is_refused(layout: Layout, name: str) -> None:
    assert layout.problem(PROTECTED[name](layout) / WORK_NAME) == (
        f"The work folder equals, contains or lies inside {name}."
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("the player's OpenRCT2 folder", "the player's OpenRCT2 folder"),
        ("the archive folder", "the archive folder"),
        ("data/sample/", "data/sample/"),
        # The data folder holds both data sets, so containing one contains the other.
        ("data/rehearsal/", "data/rehearsal/ and data/company/"),
        ("data/company/", "data/rehearsal/ and data/company/"),
        ("plugin/src/", "plugin/src/"),
    ],
)
def test_a_work_folder_containing_a_protected_folder_is_refused(
    layout: Layout, name: str, expected: str
) -> None:
    assert layout.problem(PROTECTED[name](layout).parent) == (
        f"The work folder equals, contains or lies inside {expected}."
    )


@pytest.mark.parametrize("landing", ["raw/v1", "save_files/v1", "registry/v1"])
def test_a_company_landing_folder_that_is_a_link_is_refused(layout: Layout, landing: str) -> None:
    folder = layout.data / "company" / landing
    folder.rmdir()
    elsewhere = layout.bench.parent / "elsewhere"
    elsewhere.mkdir()
    os.symlink(elsewhere, folder)

    assert layout.problem(layout.bench / WORK_NAME) == (
        f"The company landing folder {landing} is a link or lies under one."
    )


def test_a_company_landing_folder_aliased_by_another_data_set_is_refused(layout: Layout) -> None:
    rehearsal_raw = layout.data / "rehearsal" / "raw"
    (rehearsal_raw / "v1").rmdir()
    rehearsal_raw.rmdir()
    os.symlink(layout.data / "company" / "raw", rehearsal_raw)

    assert layout.problem(layout.bench / WORK_NAME) == (
        "The company landing folders resolve to, or nest inside, another data set's folder."
    )


def test_a_company_landing_folder_inside_a_protected_folder_is_refused(
    layout: Layout, monkeypatch: pytest.MonkeyPatch
) -> None:
    inside = layout.user / "data"
    (inside / "company" / "raw" / "v1").mkdir(parents=True)
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(inside))

    assert layout.problem(layout.bench / WORK_NAME) == (
        "The company landing folder raw/v1 equals, contains or lies inside "
        "the player's OpenRCT2 folder."
    )

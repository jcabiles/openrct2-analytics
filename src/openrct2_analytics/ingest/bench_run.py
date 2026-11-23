"""Benchmark the plugin headless (``make bench``) or rebuild the sample (``make bench-sample``).

Run with ``python -m openrct2_analytics.ingest.bench_run [--any-park] [--sample] [--dry-run]``. The
command refuses before writing anything when it is unsafe to start (``bench_setup``), builds
the plugin once, then runs OpenRCT2 headless on a copy of the fixture park in an isolated
user-data folder under the work folder, with the listener on ``127.0.0.1:8765`` writing to
that run's own raw folder.

Verdict mode runs 3 runs of 35 judged game days, each stopped once the session's 36th
``plugin_stats`` line has landed, judges each (``bench_judge``), repeats an invalid run once,
and writes the combined verdict (``bench_verdict``) to ``verdict.json`` in the work folder.
Sample mode (``bench_sample``) chains 3 sessions of 36 day callbacks, each loading the
previous session's save, and converts them into ``data/sample/rehearsal/``. ``--dry-run`` plays
one 35-day run with the action helper at one row per call, prints what it measured, and writes
no verdict; it cannot be combined with ``--sample``.

Output names files relative to the work folder and never prints a private path. Exit codes:
0 a passed verdict, a rebuilt sample or a passing dry run, 1 anything else, 2 refused.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from collections.abc import Sequence
from dataclasses import replace
from functools import partial

from openrct2_analytics.ingest import bench_sample
from openrct2_analytics.ingest import plugin_install as pi
from openrct2_analytics.ingest.bench_actions import (
    ACTION_ROWS,
    BURST_DAYS,
    DROP_FIELDS,
    Workload,
    action_helper,
    read_workload,
    workload_reasons,
)
from openrct2_analytics.ingest.bench_judge import (
    FIXTURE_CHANGED,
    WARMUP_ROWS,
    RunFacts,
    RunJudgement,
    judge_run,
    unjudged_run,
)
from openrct2_analytics.ingest.bench_play import Bench, CountingLander, Options, play
from openrct2_analytics.ingest.bench_setup import (
    AUTOSAVE_EVERY_5_MINUTES,
    AUTOSAVE_EVERY_5_MINUTES_LABEL,
    SHA1_PREFIX_LENGTH,
    RunFolder,
    RunInputs,
    check_fixture,
    check_no_live_game,
    check_ports,
    check_work_folder,
    file_sha1,
    game_version,
    load_settings,
    make_run_folder,
    wait_for_low_load,
)
from openrct2_analytics.ingest.bench_verdict import (
    REQUIRED_RUNS,
    Verdict,
    combine,
    is_void,
    may_repeat,
    verdict_record,
)
from openrct2_analytics.ingest.capture import (
    EXIT_OK,
    EXIT_PROBLEM,
    EXIT_REFUSED,
    REPO_ROOT,
    Build,
    Refused,
    say,
)
from openrct2_analytics.ingest.contracts import LANDING_FOLDER
from openrct2_analytics.ingest.convert import NoInputError, convert
from openrct2_analytics.ingest.game_settings import NOTHING_WRITTEN

MAX_ATTEMPTS = 2  # an invalid run is repeated once
VERDICT_FILE = "verdict.json"
# JUDGED_ROWS_PER_CALL and JUDGED_EXPECT_QUERY were measured with the removed flag-64 helper and
# must be re-measured by a dry run of the current helper before any judged run.
# The query-drop step sets JUDGED_EXPECT_QUERY = False.
JUDGED_ROWS_PER_CALL = 1
JUDGED_EXPECT_QUERY = True


def _plugin_stats_landed(judged_days: int, lander: CountingLander) -> bool:
    """Verdict mode: the session's (N + 1)th ``plugin_stats`` line has landed."""
    return lander.count("plugin_stats") >= judged_days + WARMUP_ROWS


def _unjudged(reasons: list[str], fixture_changed: bool) -> RunJudgement:
    return unjudged_run([*reasons, FIXTURE_CHANGED] if fixture_changed else reasons)


def _verdict_attempt(
    bench: Bench,
    name: str,
    *,
    rows_per_call: int,
    check_workload: bool = True,
) -> RunJudgement:
    """Run, convert and judge one verdict attempt in ``<work folder>/<name>``."""
    folder = RunFolder(bench.settings.bench_dir / name)
    inputs = RunInputs(
        bench.settings.park,
        bench.built,
        bench.settings.game_path,
        AUTOSAVE_EVERY_5_MINUTES,
        action_helper=action_helper(rows_per_call),
    )
    park_copy = make_run_folder(folder, inputs)
    days = bench.options.judged_days
    stop = partial(_plugin_stats_landed, days)
    problem = play(bench, folder, park_copy, stop=stop, days=days)
    sha1_after = file_sha1(bench.settings.park)
    changed = sha1_after != bench.fixture_sha1
    if problem is not None:
        return _unjudged([problem], changed)
    try:
        result = convert(folder.raw, folder.parquet)
    except NoInputError:
        return _unjudged(["conversion failed: no event landed"], changed)
    if result.schema_errors:
        first = result.schema_errors[0]
        count = len(result.schema_errors)
        return _unjudged([f"conversion failed: {count} schema error(s), first {first}"], changed)
    facts = RunFacts(
        folder.parquet,
        days,
        bench.fixture_sha1,
        sha1_after,
        result.malformed_lines,
    )
    judged = judge_run(facts)
    if not check_workload:
        return judged
    reasons = workload_reasons(
        read_workload(folder.parquet),
        days,
        rows_per_call,
        expect_query=JUDGED_EXPECT_QUERY,
    )
    return replace(
        judged,
        complete=judged.complete and not reasons,
        completion_reasons=(*judged.completion_reasons, *reasons),
    )


def _conditions(bench: Bench, folders: Sequence[str]) -> dict[str, str]:
    benchmark = bench.fixture_sha1.startswith(bench.options.fixture_sha1_prefix)
    return {
        "park": "benchmark park" if benchmark else "not the benchmark park",
        "fixture_sha1_prefix": bench.fixture_sha1[:SHA1_PREFIX_LENGTH],
        "openrct2_version": bench.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "judged_days": str(bench.options.judged_days),
        "autosave": AUTOSAVE_EVERY_5_MINUTES_LABEL,
        "attempt_folders": ", ".join(folders),
    }


def _run_line(label: str, run: RunJudgement) -> str:
    state = f"{'valid' if run.valid else 'invalid'}, {'complete' if run.complete else 'incomplete'}"
    if is_void(run):
        state = f"VOID, {state}"
    if run.cost is None:
        return f"{label}: {state}; no cost"
    return (
        f"{label}: {state}; worst tick {run.cost.worst_tick_ms:g} ms at tick "
        f"{run.worst_tick_offset_ticks} of a {run.worst_tick_period_ticks}-tick period "
        f"(0 is the day callback); mean {run.cost.mean_tick_ms:g} ms per tick"
    )


def _print_verdict(verdict: Verdict, conditions: dict[str, str]) -> None:
    say(
        f"Verdict: {'PASSED' if verdict.passed else 'FAILED'} ({conditions['park']}, fixture "
        f"SHA-1 {conditions['fixture_sha1_prefix']}, {conditions['openrct2_version']}, "
        f"{conditions['platform']} {conditions['machine']})"
    )
    say(f"Worst tick {verdict.worst_tick_ms} ms; highest mean {verdict.mean_tick_ms} ms per tick.")
    for slot, run in enumerate(verdict.runs, start=1):
        say(_run_line(f"Run {slot}", run))
    for slot, attempt in verdict.discarded:
        say(f"Discarded attempt of run {slot}: {'; '.join(attempt.reasons)}")
    for reason in verdict.reasons:
        say(f"  {reason}")
    say(f"Wrote {VERDICT_FILE} in the work folder ({conditions['attempt_folders']}).")


def _verdict(bench: Bench) -> int:
    runs: list[RunJudgement] = []
    discarded: list[tuple[int, RunJudgement]] = []
    folders: list[str] = []
    for slot in range(1, REQUIRED_RUNS + 1):
        attempts: list[RunJudgement] = []
        while not attempts or may_repeat(attempts):
            if attempts:
                discarded.append((slot, attempts[-1]))
            name = _attempt_name(slot, len(attempts) + 1)
            say(f"Run {slot}, attempt {len(attempts) + 1}, in {name}.")
            attempts.append(_verdict_attempt(bench, name, rows_per_call=JUDGED_ROWS_PER_CALL))
            folders.append(name)
        runs.append(attempts[-1])
    verdict = combine(runs, discarded=discarded)
    conditions = _conditions(bench, folders)
    record = verdict_record(verdict, conditions)
    path = bench.settings.bench_dir / VERDICT_FILE
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    _print_verdict(verdict, conditions)
    return EXIT_OK if verdict.passed else EXIT_PROBLEM


def _say_periods(workload: Workload) -> None:
    for position, row in enumerate(workload.stats, start=1):
        drops = ", ".join(f"{field}={row.get(field)}" for field in DROP_FIELDS)
        say(
            f"Period {position}: lines_queued_max={row.get('lines_queued_max')}, "
            f"lines_dropped_total={row.get('lines_dropped_total')}, {drops}."
        )


def _dry_run(bench: Bench) -> int:
    """Play one action workload and print its provenance and queue diagnostics."""
    name = "dry-run-attempt-1"
    judged = _verdict_attempt(bench, name, rows_per_call=1, check_workload=False)
    folder = RunFolder(bench.settings.bench_dir / name)
    # No stats file when the run stopped before conversion; the problem is printed below.
    has_stats = (folder.parquet / LANDING_FOLDER / "plugin_stats.parquet").exists()
    workload = read_workload(folder.parquet) if has_stats else None
    if workload is not None:
        _say_periods(workload)
    if judged.cost is None or workload is None:
        say(f"Dry run: {_run_line(name, judged)}.")
        for reason in judged.reasons:
            say(f"  {reason}")
        return EXIT_PROBLEM
    observed_h = len(workload.actions) / (len(BURST_DAYS) * ACTION_ROWS)
    reasons = workload_reasons(
        workload,
        bench.options.judged_days,
        1,
        expect_query=any(row.get("hook") == "query" for row in workload.actions),
    )
    judged = replace(
        judged,
        complete=judged.complete and not reasons,
        completion_reasons=(*judged.completion_reasons, *reasons),
    )
    say(f"Dry run: {_run_line(name, judged)}; h={observed_h:g} rows per call.")
    players = sorted({str(row.get("player")) for row in workload.actions})
    say(f"Helper player value(s): {', '.join(players) if players else 'not seen'}.")
    for reason in judged.reasons:
        say(f"  {reason}")
    return EXIT_OK if judged.valid and judged.complete else EXIT_PROBLEM


def _attempt_name(slot: int, attempt: int) -> str:
    return f"run-{slot}-attempt-{attempt}"


def _reserved_names() -> list[str]:
    slots = range(1, REQUIRED_RUNS + 1)
    attempts = range(1, MAX_ATTEMPTS + 1)
    return [_attempt_name(s, a) for s in slots for a in attempts] + [VERDICT_FILE]


def run(
    options: Options,
    build: Build,
    *,
    any_park: bool = False,
    sample: bool = False,
    dry_run: bool = False,
) -> int:
    """Refuse, or run the benchmark verdict or the sample chain.

    Args:
        options: Ports, run lengths and the substituted inputs.
        build: Returns the built plugin file; raises ``BuildError`` when the build fails.
        any_park: Accept a fixture that is not the benchmark park.
        sample: Rebuild the sample instead of judging a verdict.
        dry_run: Play one action workload and print its diagnostics.

    Returns:
        0 for a passed verdict or a rebuilt sample, else 1.

    Raises:
        Refused: before anything is written; the message says why.
    """
    if sample and any_park:
        raise Refused(
            f"--sample cannot be combined with --any-park; the sample is rebuilt only from the "
            f"benchmark park. {NOTHING_WRITTEN}"
        )
    if sample and dry_run:
        raise Refused(f"--sample cannot be combined with --dry-run. {NOTHING_WRITTEN}")
    settings = load_settings(platform.system())
    reserved = (
        bench_sample.reserved_names()
        if sample
        else ["dry-run-attempt-1"]
        if dry_run
        else _reserved_names()
    )
    check_work_folder(settings.bench_dir, reserved)
    fixture_sha1 = check_fixture(settings.park, None if any_park else options.fixture_sha1_prefix)
    version = game_version(settings.binary)
    check_ports(options.listener_port, options.game_port, settings.bench_dir)
    check_no_live_game(settings.user_dir, options.clock())
    wait_for_low_load(options.load_average, options.clock, options.sleep)
    try:
        built = build()
    except pi.BuildError as exc:
        raise Refused(f"{exc}\nThe plugin did not build. {NOTHING_WRITTEN}") from exc
    bench = Bench(settings, options, built, fixture_sha1, version)
    return (
        bench_sample.run_sample(bench)
        if sample
        else _dry_run(bench)
        if dry_run
        else _verdict(bench)
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the benchmark; return 0 (passed or rebuilt), 1 (failed) or 2 (refused)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--any-park", action="store_true", help="Measure a park that is not the benchmark park"
    )
    parser.add_argument(
        "--sample", action="store_true", help="Rebuild data/sample/rehearsal instead of judging"
    )
    parser.add_argument("--dry-run", action="store_true", help="Run one 35-day action workload")
    args = parser.parse_args(argv)
    build: Build = partial(pi.build_plugin, REPO_ROOT)
    try:
        return run(
            Options(), build, any_park=args.any_park, sample=args.sample, dry_run=args.dry_run
        )
    except Refused as refusal:
        say(str(refusal))
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())

"""One autopilot run: play a proven source save headless to 1 March of the next game year.

``run_autopilot`` builds a fresh work folder
``<OPENRCT2_BENCH_DIR>/autopilot-<park id>-<UTC time>/`` with ``make_run_folder``: autosave
off, the built plugin and the speed helper (saving as ``<park id>-autopilot-<g + 1>`` once
1 March of game year g + 1 arrives) in its own plugin folder, the game's debugging tools on,
and a copy of the source save, whose SHA-1 is checked before and after. It takes ``started``,
starts a
``SaveWatcher`` on the work folder's ``user-data`` with it, plays until that save has landed, and
stops the watcher before any check reads a record (spec section 6, items 1 to 4).

The work folder holds what the landing (``autopilot_land``) reads: the raw capture in
``raw/v1/events-*.jsonl``, the watcher's records in ``save_files/v1/save_file_observation_*.jsonl``,
and the converted Parquet in ``parquet/v1/``. Nothing here reads or writes company data; the
checks read only the work folder (spec section 6, "Checks in the work folder").
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from openrct2_analytics.config import ConfigError, data_root, landing_dirs
from openrct2_analytics.ingest.autopilot_progress import AutopilotProgress, RunSummary, summarize
from openrct2_analytics.ingest.bench_play import Bench, Options, play
from openrct2_analytics.ingest.bench_sample import SAVE_SUFFIX, SaveLanded
from openrct2_analytics.ingest.bench_setup import (
    AUTOSAVE_NEVER,
    BenchSettings,
    RunFolder,
    RunInputs,
    file_sha1,
    make_run_folder,
)
from openrct2_analytics.ingest.capture import say, start_time
from openrct2_analytics.ingest.capture_session import POLL_SECONDS
from openrct2_analytics.ingest.contracts import LANDING_FOLDER, check_all
from openrct2_analytics.ingest.convert import NoInputError, convert
from openrct2_analytics.ingest.landing_paths import project_path
from openrct2_analytics.ingest.registry_feed import FEED_FOLDER, registry_dir
from openrct2_analytics.ingest.rehearsal_chain import (
    SECONDS_PER_DAY,
    STARTUP_SECONDS,
    raw_problems,
)
from openrct2_analytics.ingest.rehearsal_helper import rehearsal_helper
from openrct2_analytics.ingest.save_files import (
    SAVE_FILES_FOLDER,
    check_folder,
    read_records,
    read_save_written,
    save_files_dir,
)
from openrct2_analytics.ingest.save_pairing import RECORD_FOLDER, judge_saves
from openrct2_analytics.ingest.save_watch import SaveWatcher, WatchStop, watch_folders

# The longest play: a source saved on 1 March of g runs a whole game year, 245 days (spec
# section 6 item 4); the cap on ``planned_days``, and its default.
PLANNED_DAYS = 245
MARCH = 0  # the game's month 0
OCTOBER = 7  # the game's month 7, the last of the year
COMPANY = "company"
SOURCE_CHANGED = "The source save changed during the run."
NO_EVENTS = "No event reached the work folder."
WATCHER_LATE = "The save-file watcher did not stop in time, so the saves were not paired."


def autopilot_options() -> Options:
    """The run's options: port 8765 and the timeout of 3.0 s per planned game day plus 300 s."""
    return Options(seconds_per_day=SECONDS_PER_DAY, startup_seconds=STARTUP_SECONDS)


@dataclass(frozen=True)
class RunResult:
    """What one run found.

    Attributes:
        started: The run's start, before the watcher started; the report pairs saves with it.
        watch: What ``watcher.stop()`` returned.
        work_dir: The run's work folder.
        session_id: The session's ID, or None when the capture holds no single ``session_start``.
        event_count: Events in the raw capture (lines that are JSON objects).
        reached_stop: True when a ``save_written`` dated 1 March of game year g + 1 was seen;
            False means the run did not reach 1 March.
        problems: One line per failed check; empty when every check passed.
        summary: The run's profit, statement span and guest counts, from its raw events.
    """

    started: datetime
    watch: WatchStop
    work_dir: Path
    session_id: str | None
    event_count: int
    reached_stop: bool
    problems: list[str]
    summary: RunSummary


def work_folder_name(park_id: str, utc_time: datetime) -> str:
    """``autopilot-<park id>-<UTC time>``, the time as ``YYYYMMDDTHHMMSSZ``.

    Raises:
        ValueError: if ``utc_time`` has no time zone.
    """
    if utc_time.tzinfo is None:
        raise ValueError("utc_time must carry a time zone")
    return f"autopilot-{park_id}-{utc_time.astimezone(UTC):%Y%m%dT%H%M%SZ}"


def _overlaps(first: Path, second: Path) -> bool:
    return first.is_relative_to(second) or second.is_relative_to(first)


def _names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def write_boundary_problem(
    work_dir: Path, user_dir: Path, archive_dir: Path, project_dir: Path
) -> str | None:
    """The write-boundary problem line (spec section 6 item 2), or None when the layout is safe.

    The work folder must not equal, contain or lie inside the player's OpenRCT2 folder, the
    archive folder, ``data/sample/``, ``data/rehearsal/``, ``data/company/`` or ``plugin/src/``.
    The company landing folders (``raw/v1``, ``save_files/v1``, ``registry/v1``) must not be
    links or lie under one inside ``data/company/``, must not alias another data set's folder,
    and must not equal, contain or lie inside another protected folder. Paths are resolved
    with links followed. ``data/sample/`` and ``plugin/src/`` are the project's; the data
    folders are under ``OPENRCT2_DATA_DIR`` (a relative value is against ``project_dir``; call
    this with ``project_dir`` as the working folder, as ``rehearsal_capture`` does). The line
    names folders, never a path; the caller adds what was or was not written.
    """
    try:
        root = project_path(data_root(), project_dir)
    except ConfigError as exc:
        return f"{exc}."
    try:
        landing_dirs(COMPANY)
        save_files_dir(COMPANY)
        registry_dir(COMPANY)
        aliased = False
    except ConfigError:
        aliased = True
    protected = {
        "the player's OpenRCT2 folder": user_dir.resolve(),
        "the archive folder": archive_dir.resolve(),
        "data/sample/": (project_dir / "data" / "sample").resolve(),
        "data/rehearsal/": (root / "rehearsal").resolve(),
        "data/company/": (root / COMPANY).resolve(),
        "plugin/src/": (project_dir / "plugin" / "src").resolve(),
    }
    work = work_dir.resolve()
    hits = [name for name, folder in protected.items() if _overlaps(work, folder)]
    if hits:
        return f"The work folder equals, contains or lies inside {_names(hits)}."
    company = root / COMPANY
    landing = {
        "raw/v1": ("raw", LANDING_FOLDER),
        "save_files/v1": (SAVE_FILES_FOLDER, RECORD_FOLDER),
        "registry/v1": (FEED_FOLDER, LANDING_FOLDER),
    }
    for name, (parent, child) in landing.items():
        if any(path.is_symlink() for path in (company, company / parent, company / parent / child)):
            return f"The company landing folder {name} is a link or lies under one."
    if aliased:
        return "The company landing folders resolve to, or nest inside, another data set's folder."
    for name, (parent, child) in landing.items():
        target = (company / parent / child).resolve()
        hits = [
            label
            for label, folder in protected.items()
            if label != "data/company/" and _overlaps(target, folder)
        ]
        if hits:
            return (
                f"The company landing folder {name} equals, contains or lies inside {_names(hits)}."
            )
    return None


def run_autopilot(  # noqa: PLR0913  # the run's inputs are fixed by the autopilot-year spec
    settings: BenchSettings,
    *,
    park_id: str,
    source: Path,
    work_name: str,
    g: int,
    loaded_save_id: str,
    loaded_save_session_id: str,
    built: Path,
    options: Options | None = None,
    planned_days: int = PLANNED_DAYS,
) -> RunResult:
    """Play ``source`` in ``<bench_dir>/<work_name>`` to 1 March of game year ``g + 1``; check it.

    Args:
        settings: The checked settings; ``bench_dir`` holds the work folder.
        park_id: The park the source save holds.
        source: The proven copy of the park's last recorded save; only ever read.
        work_name: The work folder's name, from ``work_folder_name``.
        g: The source save's game year.
        loaded_save_id: The source's ``save_written`` ``save_id``, for the continuation check.
        loaded_save_session_id: That event's ``session_id``.
        built: The built plugin.
        options: Ports and timeout figures; tests shrink them. Default ``autopilot_options()``.
        planned_days: Game days from the source's date to 1 March of ``g + 1``, 1 to
            ``PLANNED_DAYS``; the timeout is computed from it.

    Raises:
        ValueError: if ``planned_days`` is below 1 or above ``PLANNED_DAYS``.
        FileExistsError: if the work folder exists; a run never reuses one.
    """
    if not 1 <= planned_days <= PLANNED_DAYS:
        raise ValueError(f"planned_days must be from 1 to {PLANNED_DAYS}, not {planned_days}.")
    stem = f"{park_id}-autopilot-{g + 1}"
    source_sha1 = file_sha1(source)
    folder = RunFolder(settings.bench_dir / work_name)
    inputs = RunInputs(
        source,
        built,
        settings.game_path,
        AUTOSAVE_NEVER,
        rehearsal_helper(stem, target_year=g + 1),
        debugging_tools=True,
    )
    park_copy = make_run_folder(folder, inputs)
    # The source's SHA-1 stands in for the fixture's; ``play`` reads neither it nor the version.
    options_ = options or autopilot_options()
    bench = Bench(settings, options_, built, source_sha1, version="")
    records_dir = folder.root / SAVE_FILES_FOLDER
    started = start_time()
    watcher = SaveWatcher(
        watch_folders(folder.user_data), records_dir, started, POLL_SECONDS, say=say
    )
    watcher.start()
    progress = AutopilotProgress(park_id, planned_days, options_.timeout_seconds(planned_days), say)
    try:
        problem = play(
            bench,
            folder,
            park_copy,
            stop=SaveLanded(folder.save_dir / f"{stem}{SAVE_SUFFIX}"),
            days=planned_days,
            watch=progress,
        )
    finally:
        watch = watcher.stop()
    progress.tick()  # print lines queued after the last poll
    problems = [] if problem is None else [problem]
    if file_sha1(source) != source_sha1:
        problems.append(SOURCE_CHANGED)
    events = _raw_events(folder.raw)
    sessions = {str(e["session_id"]) for e in events if e.get("event_type") == "session_start"}
    problems += raw_problems(folder.raw)
    problems += _converted_problems(
        folder, park_id=park_id, g=g, lineage=(loaded_save_id, loaded_save_session_id)
    )
    problems += [f"Save-file records: {line}" for line in check_folder(records_dir)]
    problems += _pairing_problems(folder, started, watch, stem)
    return RunResult(
        started=started,
        watch=watch,
        work_dir=folder.root,
        session_id=next(iter(sessions)) if len(sessions) == 1 else None,
        event_count=len(events),
        reached_stop=any(_is_stop_save(event, g + 1) for event in events),
        problems=problems,
        summary=summarize(events),
    )


def _raw_events(raw: Path) -> list[dict[str, object]]:
    """The raw capture's events; a line that is not a JSON object is left to ``raw_problems``."""
    events: list[dict[str, object]] = []
    for path in sorted((raw / LANDING_FOLDER).glob("events-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue  # raw_problems names this line as a problem
            if isinstance(event, dict):
                events.append(event)
    return events


def _is_stop_save(event: dict[str, object], year: int) -> bool:
    date = (event.get("game_year"), event.get("game_month"), event.get("game_day"))
    return event.get("event_type") == "save_written" and date == (year, MARCH, 1)


def _converted_problems(
    folder: RunFolder, *, park_id: str, g: int, lineage: tuple[str, str]
) -> list[str]:
    """Convert the capture; return its problems and those of the checks on its Parquet."""
    try:
        result = convert(folder.raw, folder.parquet)
    except NoInputError:
        return [NO_EVENTS]
    problems = [f"Schema error: {line}" for line in result.schema_errors]
    if problems:
        return problems  # a schema error writes no Parquet, so nothing more can be checked
    problems += [f"seq audit: {line}" for line in result.seq_violations]
    if result.malformed_lines:
        problems.append(f"{result.malformed_lines} malformed line(s) in the capture.")
    problems += _event_problems(folder.parquet / LANDING_FOLDER, park_id, g, lineage)
    problems += [
        f"Contract {name}: {line}"
        for name, lines in check_all(folder.parquet).items()
        for line in lines
    ]
    return problems


def _event_problems(converted: Path, park_id: str, g: int, lineage: tuple[str, str]) -> list[str]:
    """The park, continuation, October and stop checks on the converted Parquet."""

    def rows(name: str, sql: str, *params: object) -> list[tuple[object, ...]]:
        path = (converted / f"{name}.parquet").as_posix().replace("'", "''")
        source = f"read_parquet('{path}', union_by_name = true)"
        return connection.execute(sql.replace("{source}", source), list(params)).fetchall()

    problems: list[str] = []
    connection = duckdb.connect(":memory:")
    try:
        others = rows(
            "*", "SELECT DISTINCT park_id FROM {source} WHERE park_id <> ? ORDER BY 1", park_id
        )
        problems += [
            f"Converted rows carry park_id {other}, expected {park_id}." for (other,) in others
        ]
        starts = rows(
            "session_start", "SELECT loaded_save_id, loaded_save_session_id FROM {source}"
        )
        problems += [
            f"The session loaded save {saved} of session {session}; the source save is "
            f"{lineage[0]} of session {lineage[1]}."
            for saved, session in starts
            if (saved, session) != lineage
        ]
        stop = g + 1
        saves = rows("save_written", "SELECT game_year, game_month, game_day, seq FROM {source}")
        october = "SELECT seq FROM {source} WHERE statement_year = ? AND statement_month = ?"
        october_seqs = [int(str(seq)) for (seq,) in rows("finance_month", october, g, OCTOBER)]
        if not october_seqs:
            problems.append(f"No finance_month row for October of game year {g}.")
        elif len(saves) == 1 and not any(seq < int(str(saves[0][3])) for seq in october_seqs):
            # The kept timeline is cut at the save's seq (ADR 0024).
            problems.append(
                f"No finance_month row for October of game year {g} before the save_written row."
            )
        if [save[:3] for save in saves] != [(stop, MARCH, 1)]:
            problems.append(
                f"{len(saves)} save_written row(s); expected one, "
                f"dated 1 March of game year {stop}."
            )
        late = (
            "SELECT seq FROM {source} WHERE game_year > ? "
            "OR (game_year = ? AND (game_month > ? OR game_day > 1)) ORDER BY seq"
        )
        problems += [
            f"park_snapshot at seq {seq} is dated after 1 March of game year {stop}."
            for (seq,) in rows("park_snapshot", late, stop, stop, MARCH)
        ]
    finally:
        connection.close()
    return problems


def _pairing_problems(
    folder: RunFolder, started: datetime, watch: WatchStop, save_name: str
) -> list[str]:
    """``judge_saves`` on the work folder: not failed, and one pair, the end-of-year save.

    Records name a file by its base name without ``.park``, so ``save_name`` is the stem.
    """
    if watch.join_timed_out:
        return [WATCHER_LATE]
    records, unreadable = read_records(folder.root / SAVE_FILES_FOLDER, started)
    judgment = judge_saves(
        records,
        read_save_written(folder.parquet),
        started,
        unreadable=unreadable,
        watcher_error=watch.error,
    )
    problems = []
    if judgment.failed:
        this_run = judgment.this_run
        error = "none" if judgment.watcher_error is None else judgment.watcher_error.message
        problems.append(
            f"The save-file pairing failed: {len(this_run.no_candidate)} save(s) with no file, "
            f"{len(this_run.windows)} group(s) not one-to-one, watcher error {error}, "
            f"{sum(u.this_run for u in judgment.unreadable)} unreadable record line(s)."
        )
    paired = [pair.record.file_name for pair in judgment.this_run.pairs]
    if paired != [save_name]:
        shown = ", ".join(paired) if paired else "none"
        problems.append(f"Saves paired with a file: {shown}; expected only {save_name}.")
    return problems

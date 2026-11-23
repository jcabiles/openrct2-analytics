"""Pair save-file records with ``save_written`` events for one run; render the report section.

Pure functions: no file or network access. The reader (records) and the report (rows)
live in other modules; this one holds the pairing rule (spec R12), the report lines
(R13), the ``-main`` check (R15), the park check (R16) and the skip line (R17).
Timestamps are aware UTC datetimes. The record file layout and the ``-main`` suffix are named
here once, for the watcher and the reader. Requirement numbers such as R12 refer to
docs/ai-dlc/specs/save-file-watcher.md.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

# Spec R12, D3: the measured gap from the save hook to the file is under 0.2 s.
SAVE_MATCH_WINDOW = timedelta(seconds=5)

# The watcher writes, and the reader looks, at ``<landing>/v1/<prefix><date><suffix>``.
RECORD_FOLDER = "v1"
RECORD_FILE_PREFIX = "save_file_observation_"
RECORD_FILE_SUFFIX = ".jsonl"
RECORD_FILE_GLOB = f"{RECORD_FILE_PREFIX}*{RECORD_FILE_SUFFIX}"
MAIN_SUFFIX = "-main"  # the save name that carries the park's own file (spec R15)

FileKey = tuple[str, str]  # (folder_kind, file_name)


@dataclass(frozen=True)
class SaveFileRecord:
    """One watcher record (spec R8)."""

    run_started_at: datetime
    observation: str  # start, created or modified
    file_name: str
    folder_kind: str  # save, autosave, parent or remembered
    modified_at: datetime
    size_bytes: int
    observed_at: datetime

    @property
    def key(self) -> FileKey:
        """The file this record describes."""
        return (self.folder_kind, self.file_name)


@dataclass(frozen=True)
class SaveWrittenRow:
    """One ``save_written`` event as converted."""

    event_id: str
    save_id: str
    park_id: str
    session_id: str
    emitted_at: datetime
    received_at: datetime
    raw_file: str  # lineage column _raw_file
    raw_line: int  # lineage column _raw_line


@dataclass(frozen=True)
class UnreadableLine:
    """A record line the reader could not parse; ``this_run`` is the reader's attribution."""

    record_file: str
    line_number: int
    this_run: bool


@dataclass(frozen=True)
class WatcherError:
    """The watcher's error and when it happened."""

    at: datetime
    message: str


@dataclass(frozen=True)
class SavePair:
    """An event paired one-to-one with the latest record of its file."""

    row: SaveWrittenRow
    record: SaveFileRecord


@dataclass(frozen=True)
class SaveWindow:
    """Events that stay unpaired because their candidates are not one-to-one."""

    rows: tuple[SaveWrittenRow, ...]
    files: tuple[FileKey, ...]


@dataclass(frozen=True)
class RunPairing:
    """The pairing result of one capture run."""

    pairs: tuple[SavePair, ...]
    no_candidate: tuple[SaveWrittenRow, ...]
    windows: tuple[SaveWindow, ...]
    unpaired: tuple[SaveFileRecord, ...]


@dataclass(frozen=True)
class StartCheck:
    """A ``start`` record compared with its file's history in earlier runs (spec R15).

    ``outcome`` is ``lost`` (the last write was recorded but its event was lost), ``none`` (never
    paired), ``changed`` (differs from the last paired write) or ``same``.
    """

    start: SaveFileRecord
    outcome: str
    last_pair: SavePair | None


@dataclass(frozen=True)
class SaveJudgment:
    """Everything the "Save files" section prints."""

    this_run: RunPairing
    main_lines: tuple[str, ...]
    park_lines: tuple[str, ...]
    unreadable: tuple[UnreadableLine, ...]
    watcher_error: WatcherError | None
    failed: bool
    start_checks: tuple[StartCheck, ...]


def pair_run(records: Sequence[SaveFileRecord], rows: Sequence[SaveWrittenRow]) -> RunPairing:
    """Pair one run's records with that run's already-cut rows (spec R12)."""
    seen: dict[str, SaveWrittenRow] = {}
    # Same tie rule as models/staging/stg_save_written.sql: received_at, then _raw_file, _raw_line.
    for row in sorted(rows, key=lambda r: (r.received_at, r.raw_file, r.raw_line)):
        seen.setdefault(row.event_id, row)
    events = sorted(seen.values(), key=lambda r: (r.emitted_at, r.event_id))
    writes = [r for r in records if r.observation in ("created", "modified")]

    # event_id -> {file: latest record of that file inside the event's window}
    candidates: dict[str, dict[FileKey, SaveFileRecord]] = {}
    in_window: dict[str, set[SaveFileRecord]] = {}
    for event in events:
        found: dict[FileKey, SaveFileRecord] = {}
        inside = [
            rec
            for rec in writes
            if event.emitted_at <= rec.modified_at <= event.emitted_at + SAVE_MATCH_WINDOW
        ]
        for rec in inside:
            best = found.get(rec.key)
            if best is None or rec.modified_at > best.modified_at:
                found[rec.key] = rec
        candidates[event.event_id] = found
        in_window[event.event_id] = set(inside)

    pairs: list[SavePair] = []
    no_candidate: list[SaveWrittenRow] = []
    windows: list[SaveWindow] = []
    paired_records: set[SaveFileRecord] = set()
    for event in events:
        found = candidates[event.event_id]
        if not found:
            no_candidate.append(event)
            continue
        # Only one write inside two windows is shared; a later save of the file is not (ADR 0053).
        shared = len(found) > 1 or any(
            in_window[event.event_id] & inside
            for eid, inside in in_window.items()
            if eid != event.event_id
        )
        if shared:
            windows.append(SaveWindow(rows=(event,), files=tuple(sorted(found))))
            continue
        (record,) = found.values()
        pairs.append(SavePair(row=event, record=record))
        paired_records.update(in_window[event.event_id])
    unpaired = tuple(r for r in writes if r not in paired_records)
    return RunPairing(tuple(pairs), tuple(no_candidate), _merge_windows(windows), unpaired)


def _merge_windows(windows: list[SaveWindow]) -> tuple[SaveWindow, ...]:
    """Join windows that share a file, so each window names all its events and files."""
    groups: list[tuple[list[SaveWrittenRow], set[FileKey]]] = []
    for window in windows:
        files = set(window.files)
        hits = [g for g in groups if g[1] & files]
        merged_rows = list(window.rows)
        for group in hits:
            merged_rows += group[0]
            files |= group[1]
            groups.remove(group)
        groups.append((merged_rows, files))
    return tuple(SaveWindow(tuple(rows), tuple(sorted(files))) for rows, files in groups)


def cut_rows(
    rows: Sequence[SaveWrittenRow], run_start: datetime, next_start: datetime | None
) -> list[SaveWrittenRow]:
    """Return the rows one watcher run owns: received from its start until the next run starts."""
    return [
        r
        for r in rows
        if r.received_at >= run_start and (next_start is None or r.received_at < next_start)
    ]


def pair_every_run(
    records: Sequence[SaveFileRecord],
    rows: Sequence[SaveWrittenRow],
    started: datetime | None = None,
) -> dict[datetime, RunPairing]:
    """Pair every watcher run's records with the rows that run owns, keyed by the run's start.

    The runs are the distinct ``run_started_at`` values of ``records``, plus ``started`` when given.
    """
    starts = sorted({r.run_started_at for r in records} | ({started} if started else set()))
    results: dict[datetime, RunPairing] = {}
    for i, run_start in enumerate(starts):
        next_start = starts[i + 1] if i + 1 < len(starts) else None
        run_records = [r for r in records if r.run_started_at == run_start]
        results[run_start] = pair_run(run_records, cut_rows(rows, run_start, next_start))
    return results


def judge_saves(
    records: Sequence[SaveFileRecord],
    rows: Sequence[SaveWrittenRow],
    started: datetime,
    *,
    unreadable: Sequence[UnreadableLine],
    watcher_error: WatcherError | None,
) -> SaveJudgment:
    """Judge this run (``started``) and read the earlier runs for the R15 and R16 checks."""
    results = pair_every_run(records, rows, started)
    this_run = results[started]
    earlier = {s: p for s, p in results.items() if s < started}

    checks = _start_checks([r for r in records if r.run_started_at == started], earlier)
    park_lines = _park_lines(this_run, results)
    failed = bool(
        this_run.no_candidate
        or this_run.windows
        or watcher_error
        or any(u.this_run for u in unreadable)
    )
    return SaveJudgment(
        this_run,
        _main_lines(checks),
        park_lines,
        tuple(unreadable),
        watcher_error,
        failed,
        checks,
    )


def _start_checks(
    this_records: Sequence[SaveFileRecord], earlier: dict[datetime, RunPairing]
) -> tuple[StartCheck, ...]:
    """R15: compare each start record with the earlier runs' paired and unpaired writes."""
    checks: list[StartCheck] = []
    for start in sorted((r for r in this_records if r.observation == "start"), key=lambda r: r.key):
        last_pair: SavePair | None = None
        lost = False
        for run_start in sorted(earlier):
            result = earlier[run_start]
            for pair in result.pairs:
                if pair.record.key == start.key and (
                    last_pair is None or pair.record.modified_at >= last_pair.record.modified_at
                ):
                    last_pair = pair
            lost = lost or any(
                u.key == start.key and u.modified_at == start.modified_at for u in result.unpaired
            )
        if lost:
            outcome = "lost"
        elif last_pair is None:
            outcome = "none"
        elif last_pair.record.modified_at != start.modified_at:
            outcome = "changed"
        else:
            outcome = "same"
        checks.append(StartCheck(start, outcome, last_pair))
    return tuple(checks)


def _main_lines(checks: Sequence[StartCheck]) -> tuple[str, ...]:
    """R15 lines: every outcome for a ``-main`` file; only a change for any other file."""
    lines: list[str] = []
    for check in checks:
        name = check.start.file_name
        is_main = name.endswith(MAIN_SUFFIX)
        if check.outcome == "lost" and is_main:
            lines.append(f"warning: {name}: last write was recorded but its save event was lost")
        elif check.outcome == "none" and is_main:
            lines.append(f"note: {name}: no earlier paired write on record")
        elif check.outcome == "changed" and check.last_pair is not None:
            lines.append(
                f"warning: {name} changed since its last paired write at "
                f"{check.last_pair.record.modified_at.isoformat()}; that play was not captured"
            )
    return tuple(lines)


def _park_lines(this_run: RunPairing, results: dict[datetime, RunPairing]) -> tuple[str, ...]:
    """R16: a ``-main`` file written in this run whose pairs across history carry several parks."""
    written = {p.record.file_name for p in this_run.pairs} | {
        r.file_name for r in this_run.unpaired
    }
    lines: list[str] = []
    for name in sorted(n for n in written if n.endswith(MAIN_SUFFIX)):
        parks = sorted(
            {
                p.row.park_id
                for res in results.values()
                for p in res.pairs
                if p.record.file_name == name
            }
        )
        if len(parks) > 1:
            lines.append(f"warning: {name} was written by parks {', '.join(parks)}")
    return tuple(lines)


def render_saves(judgment: SaveJudgment) -> str:
    """The "Save files" section (spec R13, in item order)."""
    run = judgment.this_run
    lines = ["Save files"]
    for pair in run.pairs:
        lines.append(
            f"  {pair.record.file_name} ({pair.record.folder_kind}): save_id {pair.row.save_id}, "
            f"park_id {pair.row.park_id}"
        )
    for row in run.no_candidate:
        lines.append(
            f"  capture failure: save_id {row.save_id} emitted at {row.emitted_at.isoformat()}: "
            f"no file record within {int(SAVE_MATCH_WINDOW.total_seconds())} s"
        )
    for window in run.windows:
        events = ", ".join(f"{r.save_id} ({r.emitted_at.isoformat()})" for r in window.rows)
        files = ", ".join(f"{kind}/{name}" for kind, name in window.files)
        lines.append(f"  capture failure: two-candidate window: events {events}; files {files}")
    for rec in run.unpaired:
        lines.append(
            f"  note: {rec.observation} record of {rec.folder_kind}/{rec.file_name} at "
            f"{rec.modified_at.isoformat()} paired with no save event"
        )
    lines += [f"  {line}" for line in (*judgment.main_lines, *judgment.park_lines)]
    if judgment.watcher_error is not None:
        lines.append(
            f"  capture failure: watcher error at {judgment.watcher_error.at.isoformat()}: "
            f"{judgment.watcher_error.message}"
        )
    for u in judgment.unreadable:
        label = "capture failure" if u.this_run else "note"
        lines.append(f"  {label}: unreadable record line {u.record_file} line {u.line_number}")
    if len(lines) == 1:
        lines.append("  no save events or file records in this run")
    return "\n".join(lines)


def render_skipped(reason: str, watcher_error: WatcherError | None) -> str:
    """The R17 line, then the watcher error if any."""
    text = f"Save pairing skipped: {reason}. The save-file records were kept."
    if watcher_error is not None:
        text += f"\nWatcher error at {watcher_error.at.isoformat()}: {watcher_error.message}"
    return text

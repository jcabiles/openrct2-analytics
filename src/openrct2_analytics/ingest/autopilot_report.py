"""The autopilot-year success report (spec section 4): the dated copy to load and the end lines."""

from __future__ import annotations

import filecmp
import shutil
from dataclasses import dataclass
from pathlib import Path

from openrct2_analytics.ingest.autopilot_progress import MONTH_NAMES, RunSummary, display_usd
from openrct2_analytics.ingest.capture_session import say
from openrct2_analytics.ingest.save_backup import BACKUP_MARK


@dataclass(frozen=True)
class ReportFacts:
    """What the success report prints; ``bench_dir`` holds earlier failed run folders."""

    park_id: str
    work_dir: Path
    bench_dir: Path
    ready_ignored: str | None
    dated: str
    source_year: int
    target_year: int
    session_id: str | None
    event_count: int
    source_file: str
    source_date: tuple[int, int, int]  # (game year, game month, game day) of the source save
    summary: RunSummary


def dated_copy(game_save_dir: Path, end_save: Path) -> str | None:
    """The name of the dated copy in the game's save folder that holds the end-of-year save.

    Compared by bytes, not by ``save_backup.newest_own_copy``: that needs the park's label (its
    name), which is not known here, and it proves a copy against any archive file, not this save.
    """
    saves = sorted(game_save_dir.glob(f"*{BACKUP_MARK}*.park"))
    found = [p.name for p in saves if p.is_file() and filecmp.cmp(p, end_save, shallow=False)]
    return found[0] if found else None


def _profit_line(summary: RunSummary) -> str:
    """The R13 profit line; the dollar text is display only (ADR 0052)."""
    first, last = summary.first_statement, summary.last_statement
    if summary.statement_count == 0 or first is None or last is None:
        return "Profit: no monthly statement closed during this run."
    if first[0] == last[0]:
        span = f"{MONTH_NAMES[first[1]]} to {MONTH_NAMES[last[1]]}, year {first[0]}"
    else:
        span = f"{MONTH_NAMES[first[1]]}, year {first[0]} to {MONTH_NAMES[last[1]]}, year {last[0]}"
    noun = "statement" if summary.statement_count == 1 else "statements"
    return (
        f"Profit: {display_usd(summary.profit_tenths)} from {summary.statement_count} monthly "
        f"{noun} ({span}), the game's total of all 14 statement lines, shown in dollars for "
        "display."
    )


def _guests_line(summary: RunSummary) -> str:
    start = "unknown" if summary.guests_start is None else str(summary.guests_start)
    end = "unknown" if summary.guests_end is None else str(summary.guests_end)
    return f"Guests in the park: {start} at the start, {end} at the end."


def report(facts: ReportFacts) -> None:
    """Remove the work folder, then print the success report."""
    park_id = facts.park_id
    shutil.rmtree(facts.work_dir)
    if facts.ready_ignored:
        say(f"READY was ignored: park {park_id} has run on autopilot before.")
    if kept := sorted(p.name for p in facts.bench_dir.glob(f"autopilot-{park_id}-*")):
        say(f"Run folders kept from earlier failed runs of park {park_id}: {', '.join(kept)}.")
    year, month, day = facts.source_date
    say(f"Started from: {facts.source_file} (game date {MONTH_NAMES[month]} {day}, year {year}).")
    say(_profit_line(facts.summary))
    say(_guests_line(facts.summary))
    say(f"To refurbish the park, load save/{facts.dated}.")
    say(
        f"Park {park_id}'s older saves are now one game year behind: loading one under make "
        "play starts a newer session on the older branch, and this autopilot year leaves the "
        "kept timeline."
    )
    say(
        f"autopilot-year: park {park_id} played company year {facts.target_year} to 1 March "
        f"of game year {facts.source_year + 1}; landed session {facts.session_id} "
        f"({facts.event_count} events) and labeled it autopilot."
    )

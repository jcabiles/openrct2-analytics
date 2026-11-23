"""List, per park, the company play waiting to be filed, and print it for the launcher.

Play is waiting when the converted ``session_start.parquet`` holds a session the development
warehouse does not, when a session failed its ``seq`` audit and is not filed, or when the raw
folder holds a session never converted. ``find_unfiled`` takes the filed session IDs, the clock,
the game state and the landing lock as plain values; it writes nothing and opens no warehouse.
The command reads the real development warehouse through ``play_status.warehouse_sessions``,
which holds DuckDB's read-only lock only while it reads. Standard output is empty when the check
ran and nothing waits; otherwise line 1 is ``offer``, ``offer-after-convert`` or ``no-offer``,
then the lines for the player. Refusals and failures go to standard error. Exit 0 printed, 1
failed, 2 refused, 130 interrupted.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Never

import duckdb

from openrct2_analytics.config import DATA_SETS, ConfigError, LandingDirs
from openrct2_analytics.ingest import landing_paths, lock, managed_years, park_label, play_status
from openrct2_analytics.ingest.capture_report import AUDIT_FILE
from openrct2_analytics.ingest.contracts import LANDING_FOLDER
from openrct2_analytics.ingest.convert import VIOLATION_FILTER, landing_lock_path
from openrct2_analytics.ingest.game_check import GameState, platform_game_check

RECORDING_SECONDS = 120
BUILDING_LINE = "The warehouse is being built, so waiting play cannot be checked now."
FAILED_LINE = (
    "Nothing is offered while a session that failed its seq audit is waiting, "
    "because filing files every waiting session."
)
UNREADABLE_LINE = (
    "Nothing is offered while a recording has a line that cannot be read, "
    "because converting stops at it."
)
RECORDING_LINE = (
    "A recording is still being written (the game is running, a raw file changed in the last "
    "2 minutes, or a filing is running), so nothing is offered now."
)


@dataclass(frozen=True)
class ParkUnfiled:
    """One park's waiting play; the session tuples are sorted."""

    park_id: str
    label: str
    converted: tuple[str, ...]
    unconverted: tuple[str, ...]
    failed: tuple[str, ...]


@dataclass(frozen=True)
class Unfiled:
    """The waiting play of the company data set.

    Attributes:
        parks: Parks with waiting play, in park ID order.
        offerable_parks: The count ``k``: parks with a converted-not-filed or never-converted item.
        offer: Whether filing may be offered.
        needs_convert: Whether a session was never converted (so accepting converts first).
        reason: Why nothing is offered, when the list is not empty or the warehouse is building:
            ``building``, ``failed``, ``unreadable`` or ``recording``; None when offered or when
            nothing waits.
        recheck_at: Seconds since the epoch when a still-recording raw file stops counting, or None.
        unreadable_files: Base names, in file-name order, of raw files with a line that cannot be
            read and that the recording rule does not hide.
    """

    parks: tuple[ParkUnfiled, ...]
    offerable_parks: int
    offer: bool
    needs_convert: bool
    reason: str | None
    recheck_at: float | None
    unreadable_files: tuple[str, ...] = ()


class _Refused(Exception):
    """The command was refused before reading anything."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class _UnfiledParser(argparse.ArgumentParser):
    """Argument parser that reports invalid input as a refusal."""

    def error(self, message: str) -> Never:
        raise _Refused("usage", message)


def _live_files(raw_dir: Path, now: float) -> dict[Path, float]:
    """Raw files changed less than ``RECORDING_SECONDS`` before ``now``, with when they stop."""
    live: dict[Path, float] = {}
    for path in managed_years.raw_files(raw_dir):
        changed = path.stat().st_mtime
        if now - changed < RECORDING_SECONDS:
            live[path] = changed + RECORDING_SECONDS
    return live


def _converted_by_park(
    starts: list[tuple[str, str, str | None, datetime]], skip: set[str]
) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for session, park, _, _ in starts:
        if session not in skip:
            found.setdefault(park, set()).add(session)
    return found


def _unconverted_by_park(
    index: dict[str, managed_years.RawSession],
    skip: set[str],
    hidden: Callable[[managed_years.RawSession], bool],
) -> dict[str, set[str]]:
    """Raw sessions outside ``skip`` that ``hidden`` spares, per park."""
    found: dict[str, set[str]] = {}
    for session, raw in sorted(index.items()):
        if session in skip or hidden(raw):
            continue
        for park in raw.park_ids:
            found.setdefault(park, set()).add(session)
    return found


def failed_waiting(landing: LandingDirs, filed: set[str] | None) -> dict[str, tuple[str, ...]]:
    """Sessions whose audit row matches ``VIOLATION_FILTER`` and that are not filed.

    Args:
        landing: The company landing folders, as absolute paths.
        filed: Session IDs the warehouse holds; None means none is filed.

    Returns:
        Each such session ID mapped to its sorted park IDs: the audit park plus the parks of
        its raw ``session_start`` rows. A missing audit file gives an empty mapping.

    Raises:
        duckdb.Error: if the audit file cannot be read.
        OSError: if a raw file cannot be read.
    """
    audit = landing.parquet / AUDIT_FILE
    if not audit.is_file():
        return {}
    with duckdb.connect(":memory:") as connection:
        rows = connection.execute(
            f"SELECT session_id, park_id FROM read_parquet(?) WHERE {VIOLATION_FILTER}",
            [str(audit)],
        ).fetchall()
    known = filed or set()
    waiting = {str(session): str(park) for session, park in rows if str(session) not in known}
    if not waiting:
        return {}
    index = managed_years.raw_session_index(landing.raw)
    return {
        session: tuple(
            sorted({park} | (set(index[session].park_ids) if session in index else set()))
        )
        for session, park in waiting.items()
    }


def find_unfiled(  # noqa: PLR0913  # the labels pass-through is fixed by the sandbox-hide spec D6
    landing: LandingDirs,
    filed: set[str] | None,
    *,
    warehouse: str,
    now: float,
    game: GameState,
    lock_present: bool,
    park_labels: dict[str, str] | None = None,
) -> Unfiled:
    """Find the play waiting to be filed, per park.

    Args:
        landing: The company landing folders, as absolute paths.
        filed: Session IDs the warehouse holds; None when it is being built or missing (nothing
            is known as filed).
        warehouse: ``ready``, ``missing`` or ``building``.
        now: Seconds since the epoch.
        game: The game check's answer; running and cannot-tell both count as recording.
        lock_present: Whether the landing lock exists.
        park_labels: The park labels when the caller already read them; None reads them here.

    Returns:
        The parks, the count of offerable parks, and whether and why filing is offered.

    Raises:
        duckdb.Error: if a Parquet file cannot be read.
        OSError: if a raw file cannot be read.
    """
    known = filed or set()
    starts = play_status.converted_starts(
        landing.parquet / LANDING_FOLDER / "session_start.parquet"
    )
    failed = failed_waiting(landing, filed)
    index = managed_years.raw_session_index(landing.raw)
    live = _live_files(landing.raw, now)
    all_hidden = lock_present or game is not GameState.NOT_RUNNING
    labels = (
        park_labels
        if park_labels is not None
        else park_label.labels(park_label.park_facts(landing))
    )
    converted = _converted_by_park(starts, known | failed.keys())
    unconverted = _unconverted_by_park(
        index,
        {session for session, _, _, _ in starts} | known | failed.keys(),
        lambda raw: all_hidden or any(path in live for path in raw.files),
    )
    by_failed: dict[str, set[str]] = {}
    for session, parks_of in failed.items():
        for park in parks_of:
            by_failed.setdefault(park, set()).add(session)
    parks = tuple(
        ParkUnfiled(
            park,
            park_label.label_of(labels, park),
            tuple(sorted(converted.get(park, ()))),
            tuple(sorted(unconverted.get(park, ()))),
            tuple(sorted(by_failed.get(park, ()))),
        )
        for park in sorted(converted.keys() | unconverted.keys() | by_failed.keys())
    )
    unreadable = tuple(
        path.name
        for path in managed_years.unreadable_raw_files(landing.raw)
        if not all_hidden and path not in live
    )
    reason = _reason(
        warehouse == "building",
        bool(parks) or bool(unreadable),
        failed=bool(failed),
        unreadable=bool(unreadable),
        recording=bool(live) or all_hidden,
    )
    return Unfiled(
        parks=parks,
        offerable_parks=sum(1 for park in parks if park.converted or park.unconverted),
        offer=bool(parks) and reason is None,
        needs_convert=any(park.unconverted for park in parks),
        reason=reason,
        recheck_at=min(live.values()) if live else None,
        unreadable_files=unreadable,
    )


def _reason(
    building: bool, waiting: bool, *, failed: bool, unreadable: bool, recording: bool
) -> str | None:
    """Why nothing is offered, first match: building, failed session, unreadable line, recording."""
    if building:
        return "building"
    if not waiting:
        return None
    if failed:
        return "failed"
    if unreadable:
        return "unreadable"
    return "recording" if recording else None


def render(result: Unfiled) -> list[str]:
    """The command's output lines; empty when the check ran and nothing waits."""
    if result.reason == "building":
        return ["no-offer", BUILDING_LINE]
    if not result.parks and not result.unreadable_files:
        return []
    if not result.offer:
        first = "no-offer"
    else:
        first = "offer-after-convert" if result.needs_convert else "offer"
    lines = [first, "Play waiting to be filed:"]
    for park in result.parks:
        label = park.label
        if park.converted:
            lines.append(f"- {label}: {len(park.converted)} converted session(s) not filed yet")
        if park.unconverted:
            lines.append(f"- {label}: {len(park.unconverted)} recording(s) never converted")
        lines.extend(
            f"- {label}: session {session} failed its seq audit, so it is not offered for filing"
            for session in park.failed
        )
    lines.extend(
        f"- Recording {name} has a line that cannot be read; make convert DATA_SET=company names it"
        for name in result.unreadable_files
    )
    if result.reason == "failed":
        lines.append(FAILED_LINE)
    elif result.reason == "unreadable":
        lines.append(UNREADABLE_LINE)
    elif result.reason == "recording":
        lines.append(RECORDING_LINE)
    return lines


def input_key(landing: LandingDirs) -> tuple[object, ...]:
    """Stat-only fingerprint of every file ``find_unfiled`` reads; it changes when one does."""
    raw = tuple(
        (path.name, managed_years.file_key(path)) for path in managed_years.raw_files(landing.raw)
    )
    return (
        managed_years.file_key(landing.parquet / LANDING_FOLDER / "session_start.parquet"),
        managed_years.file_key(landing.parquet / AUDIT_FILE),
        raw,
    )


def _read(project_dir: Path) -> Unfiled:
    landing = landing_paths.landing("company", project_dir)
    state, filed = play_status.warehouse_sessions(project_dir / play_status.WAREHOUSE, project_dir)
    return find_unfiled(
        landing,
        filed,
        warehouse=state,
        now=time.time(),
        game=platform_game_check()(),
        lock_present=landing_lock_path(landing.parquet).exists(),
    )


def main(argv: Sequence[str] | None = None, *, project_dir: Path = play_status.PROJECT_DIR) -> int:
    """Print the play waiting to be filed for the launcher."""
    parser = _UnfiledParser(description=__doc__)
    parser.add_argument("--data-set", choices=DATA_SETS, required=True)
    handlers = {
        name: signal.getsignal(getattr(signal, name))
        for name in lock.SIGNAL_NAMES
        if hasattr(signal, name)
    }
    lock.set_signal_handlers(lock.raise_interrupted)
    try:
        args = parser.parse_args(argv)
        if args.data_set != "company":
            raise _Refused("data-set", f"Only company play can be filed, got: {args.data_set}")
        for line in render(_read(project_dir.resolve())):
            print(line)
        code = 0
    except _Refused as error:
        print(f"unfiled refused: {error.reason}: {error.detail}", file=sys.stderr)
        code = 2
    except ConfigError as error:
        print(f"unfiled refused: data-set: {error}", file=sys.stderr)
        code = 2
    except (OSError, ValueError, duckdb.Error) as error:
        print(f"unfiled failed: io: {error}", file=sys.stderr)
        code = 1
    except (lock.Interrupted, KeyboardInterrupt):
        print("unfiled interrupted", file=sys.stderr)
        code = 130
    finally:
        for name, handler in handlers.items():
            signal.signal(getattr(signal, name), handler)
    return code


if __name__ == "__main__":
    sys.exit(main())

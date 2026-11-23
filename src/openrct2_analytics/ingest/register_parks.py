"""Register converted company parks with a checked CSV delivery.

``--practice`` notes every pending park as a sandbox park (stored as ``practice``);
``--parks "<id>:company,<id>:practice"`` registers only the listed pending parks, each with its
own choice. ``--start-year`` gives the company start year of the one non-sandbox park a run
registers once a company park is registered (ADR 0050); the first company park and sandbox
parks get ``FIRST_START_YEAR``. Exit 0 means written or already registered, 1 a failed step, 2
a refusal before any change, and 130 an interruption. Rehearsal deliveries belong to capture.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import signal
import sys
import time
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from openrct2_analytics.config import ConfigError
from openrct2_analytics.ingest import capture_report, lock, registry_feed
from openrct2_analytics.ingest.contracts import LANDING_FOLDER
from openrct2_analytics.ingest.convert import landing_lock_path
from openrct2_analytics.ingest.landing_paths import landing, project_path

# Refused and FIRST_START_YEAR are re-exported: callers and tests read them from here.
from openrct2_analytics.ingest.start_year import (
    FIRST_START_YEAR as FIRST_START_YEAR,
)
from openrct2_analytics.ingest.start_year import (
    Refused as Refused,
)
from openrct2_analytics.ingest.start_year import check_registry_feed, source_rows, start_years

PROJECT_DIR = Path(__file__).resolve().parents[3]
NOTE = registry_feed.PRACTICE_NOTE
MAX_START_YEAR_DIGITS = 50
CHOICES = {"company": False, "practice": True}


class CheckFailed(Exception):
    """A staged delivery failed the registry contract."""


def registered_parks(feed: Path) -> dict[str, tuple[str, bool]]:
    """Return each registered park's data set and practice flag, from the deliveries in ``feed``.

    ``feed`` is a ``v1`` folder; a park is a sandbox park when its latest row carries ``NOTE``.

    Only deliveries the feed check passes and the warehouse reads by name count; a misnamed
    delivery is warned about on standard error.

    Raises:
        Refused: if the feed check fails.
    """
    check_registry_feed(feed)
    for path in sorted(feed.glob(registry_feed.FILE_GLOB)):
        if not registry_feed.is_accepted_name(path.name):
            print(
                f"warning: {path.name} is not a valid delivery name; the warehouse ignores it",
                file=sys.stderr,
            )
    return {
        park: (row.data_set, row.practice) for park, row in registry_feed.latest_rows(feed).items()
    }


def _free_names(feed: Path, today: date) -> Iterator[str]:
    """Yield today's unused delivery names in order, ``..._01.csv`` to ``..._99.csv``."""
    for number in range(1, 100):
        name = f"park_registry_{today.isoformat()}_{number:02}.csv"
        if not (feed / name).exists():
            yield name


def _free_name(feed: Path, today: date) -> str:
    for name in _free_names(feed, today):
        return name
    raise Refused("no-free-name", f"All 99 delivery names for {today} are used")


def _prepare(
    feed: Path, audit: Path, starts: Path, today: date
) -> tuple[str, list[tuple[str, int, datetime]]]:
    if not audit.is_file() or not starts.is_file():
        raise Refused("not-converted", "Run make convert DATA_SET=company first")
    if feed.exists():
        leftovers = sorted(feed.glob(f"{registry_feed.INCOMING}*"))
        if leftovers:
            raise Refused("leftover", f"Staged delivery {leftovers[0].name} already exists")
    origins = source_rows(audit, starts)
    registered = registered_parks(feed)
    for park, _, _ in origins:
        entry = registered.get(park)
        if entry is not None and entry[0] != "company":
            raise Refused("mismatch", f"Park {park} is registered as {entry[0]}")
    pending = [row for row in origins if row[0] not in registered]
    return (_free_name(feed, today) if pending else "", pending)


def parse_parks(text: str) -> dict[str, bool]:
    """Parse ``"<id>:company,<id>:practice"`` into each park's practice flag.

    Raises:
        Refused: if an item has no ``:``, an empty park ID, a choice other than company or
            practice, or a park listed twice.
    """
    parks: dict[str, bool] = {}
    for item in text.split(","):
        park, _, choice = item.strip().rpartition(":")
        if not park or choice not in CHOICES:
            raise Refused("parks", f"{item.strip()!r} is not <park id>:company or :practice")
        if park in parks:
            raise Refused("parks", f"Park {park} is listed twice")
        parks[park] = CHOICES[choice]
    return parks


def _park_choices(practice: bool, text: str | None) -> dict[str, bool] | None:
    # An empty list (``PARKS=`` on the make command line) means no list was given.
    if text is None or not text.strip():
        return None
    if practice:
        raise Refused("parks", "Give --parks or --practice, not both")
    return parse_parks(text)


def _select(
    pending: list[tuple[str, int, datetime]], practice: bool, parks: dict[str, bool] | None
) -> list[tuple[str, int, datetime, bool]]:
    """Pair each park to register with its practice flag; a park list picks pending parks only."""
    if parks is None:
        return [(*row, practice) for row in pending]
    waiting = {row[0]: row for row in pending}
    for park in parks:
        if park not in waiting:
            raise Refused("unknown-park", f"Park {park} is not a captured park waiting to register")
    return [(*row, parks[row[0]]) for row in pending if row[0] in parks]


def parse_start_year(text: str | None) -> int | None:
    """Parse a typed ``START_YEAR``; blank or None means not given.

    Raises:
        Refused: if the trimmed value is not ASCII digits only, or is longer than
            ``MAX_START_YEAR_DIGITS`` digits.
    """
    if text is None or not text.strip():
        return None
    value = text.strip()
    # The length bound keeps ``int`` from raising on a value of thousands of digits.
    if not re.fullmatch(rf"[0-9]{{1,{MAX_START_YEAR_DIGITS}}}", value):
        raise Refused(
            "start-year",
            f"START_YEAR must be a year written in digits, such as 2001; got {value!r}",
        )
    return int(value)


def _nothing_to_register(start_year: int | None) -> None:
    print("All captured parks are already registered.")
    if start_year is not None:
        print(f"START_YEAR={start_year} not used: no park waits to register.")


def _delivery(
    rows: list[tuple[str, int, datetime, bool]], years: dict[str, int], today: date
) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(registry_feed.HEADER)
    for park, origin, _, practice in rows:
        writer.writerow(
            (park, years[park], origin, "company", NOTE if practice else "", today.isoformat())
        )
    return buffer.getvalue()


def _places(project_dir: Path) -> tuple[Path, Path, Path, dict[str, Path]]:
    folders = landing("company", project_dir)
    feed = project_path(registry_feed.registry_dir("company"), project_dir) / LANDING_FOLDER
    audit = folders.parquet / capture_report.AUDIT_FILE
    starts = folders.parquet / LANDING_FOLDER / "session_start.parquet"
    places = {
        "parquet_dir": folders.parquet,
        "raw_dir": folders.raw,
        "feed": feed,
    }
    return feed, audit, starts, places


def check_registrations(project_dir: Path, today: date, count: int) -> None:
    """Run the refusals that do not depend on a park's year, before the first registration.

    Raises:
        Refused: on a registry feed check failure, a leftover staged delivery, a park registered
            with another data set, or fewer than ``count`` free delivery names today.
    """
    feed, audit, starts, _ = _places(project_dir)
    _prepare(feed, audit, starts, today)
    free = sum(1 for _ in _free_names(feed, today))
    if free < count:
        raise Refused(
            "no-free-name", f"Only {free} delivery names for {today} are free; need {count}"
        )


def _register(
    project_dir: Path,
    today: date,
    practice: bool,
    *,
    parks: dict[str, bool] | None,
    start_year: int | None,
) -> tuple[str, list[tuple[str, int, datetime, bool]]]:
    feed, audit, starts, places = _places(project_dir)
    name, pending = _prepare(feed, audit, starts, today)
    chosen = _select(pending, practice, parks)
    if not chosen:
        return "", []
    start_years({row[0]: row[3] for row in chosen}, start_year, **places)
    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with lock.hold_lock(
        landing_lock_path(places["parquet_dir"]), f"pid {os.getpid()} started {started}"
    ):
        name, pending = _prepare(feed, audit, starts, today)
        chosen = _select(pending, practice, parks)
        if not chosen:
            return "", []
        # Checked again under the lock: a delivery or convert may have landed while it was taken.
        years = start_years({row[0]: row[3] for row in chosen}, start_year, **places)
        staged = feed / f"{registry_feed.INCOMING}{name}"
        # Folders this run creates, innermost first; removed again if still empty.
        created = [folder for folder in (feed, feed.parent) if not folder.exists()]
        try:
            feed.mkdir(parents=True, exist_ok=True)
            staged.write_text(_delivery(chosen, years, today), encoding="utf-8")
            problems = registry_feed.check_file(staged)
            if problems:
                raise CheckFailed("; ".join(problems))
            staged.rename(feed / name)
        finally:
            staged.unlink(missing_ok=True)
            for folder in created:
                if folder.is_dir() and not any(folder.iterdir()):
                    folder.rmdir()
    return name, chosen


def register(
    project_dir: Path,
    today: date,
    practice: bool,
    *,
    parks: dict[str, bool] | None = None,
    start_year: int | None = None,
) -> str:
    """Register the waiting company parks in one delivery and return its file name.

    Prints nothing. Returns an empty string when no park waits to register.

    Raises:
        Refused: on any refusal; nothing was changed.
        CheckFailed: if the staged delivery fails the registry contract.
        lock.LockTaken: if the landing lock is held by another run.
        csv.Error: if the registry feed or a source file cannot be parsed.
        OSError: on a file or folder read, write or lock failure.
    """
    return _register(project_dir, today, practice, parks=parks, start_year=start_year)[0]


def _typed_start_year(text: str | None, practice: bool) -> int | None:
    """Refusals 1 and 2, made before any data is read."""
    start_year = parse_start_year(text)
    if start_year is not None and practice:
        raise Refused(
            "start-year-practice",
            'Sandbox parks take no START_YEAR; give PARKS="<id>:company" START_YEAR=<year> '
            "for the company park",
        )
    return start_year


def _note_written(
    registered: list[str] | None, chosen: list[tuple[str, int, datetime, bool]]
) -> None:
    if registered is not None:
        registered.extend(row[0] for row in chosen)


def _report(
    name: str, chosen: list[tuple[str, int, datetime, bool]], start_year: int | None
) -> None:
    if not chosen:
        _nothing_to_register(start_year)
        return
    print(f"Registered {len(chosen)} park(s) in {name}.")
    if start_year is not None:
        park = next(row[0] for row in chosen if not row[3])
        print(f"Park {park}: company start year {start_year} (START_YEAR).")


def main(
    argv: Sequence[str] | None = None,
    *,
    project_dir: Path = PROJECT_DIR,
    today: date | None = None,
    registered: list[str] | None = None,
) -> int:
    """Run the registry command and map each outcome to its documented exit code.

    ``registered``, when given, receives the ID of each park this run wrote to a delivery.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-set")
    parser.add_argument("--practice", action="store_true")
    parser.add_argument(
        "--parks",
        help='Parks to register: "<id>:company,<id>:practice" (`practice` is shown as Sandbox)',
    )
    parser.add_argument("--start-year", help="Company start year of the one company park")
    args = parser.parse_args(argv)
    if args.data_set not in ("rehearsal", "company"):
        print("register refused: data-set: Choose rehearsal or company. Nothing was changed.")
        return 2
    if args.data_set == "rehearsal":
        print(
            "register refused: rehearsal: The capture command owns rehearsal deliveries. "
            "Nothing was changed."
        )
        return 2
    handlers = {
        name: signal.getsignal(getattr(signal, name))
        for name in lock.SIGNAL_NAMES
        if hasattr(signal, name)
    }
    lock.set_signal_handlers(lock.raise_interrupted)
    try:
        start_year = _typed_start_year(args.start_year, args.practice)
        name, chosen = _register(
            project_dir.resolve(),
            today or datetime.now(UTC).date(),
            args.practice,
            parks=_park_choices(args.practice, args.parks),
            start_year=start_year,
        )
        _note_written(registered, chosen)
        _report(name, chosen, start_year)
        code = 0
    except Refused as error:
        print(f"register refused: {error.reason}: {error.detail}. Nothing was changed.")
        code = 2
    except lock.LockTaken as error:
        print(
            f'register refused: lock-taken: {error}; see ARCHITECTURE.md "Stale locks". '
            "Nothing was changed."
        )
        code = 2
    except ConfigError as error:
        print(f"register refused: data-set: {error}. Nothing was changed.")
        code = 2
    except CheckFailed as error:
        print(f"register failed: check-failed: {error}")
        code = 1
    except (OSError, duckdb.Error, csv.Error, UnicodeDecodeError, ValueError) as error:
        print(f"register failed: io: {error}")
        code = 1
    except (lock.Interrupted, KeyboardInterrupt):
        print("register interrupted")
        code = 130
    finally:
        for name, handler in handlers.items():
            signal.signal(getattr(signal, name), handler)
    return code


if __name__ == "__main__":
    sys.exit(main())

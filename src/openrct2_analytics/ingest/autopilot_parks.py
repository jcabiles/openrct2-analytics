"""Print, as one JSON object, the company parks an autopilot year could start from.

It lists every registered company park that is not a practice park, for the home dashboard's
autopilot dropdown. Per park: its label (``park_label``, from ``park_label.py``; the bare park ID
when an undecodable raw file stops the label read, which is named on standard error); the newest
archive copy (found as ``autopilot_source`` finds it, proven or not), the message of the refusal
``find_source`` gives when it cannot prove a source (null when it proves one), and whether the
park still needs its ready mark (it has no landed autopilot session). It writes nothing and takes
no lock. On success standard output holds only the JSON; refusals and failures go to standard
error. Exit 0 printed, 1 failed, 2 refused, 130 interrupted.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Never

import duckdb

from openrct2_analytics.config import DATA_SETS, ConfigError
from openrct2_analytics.ingest import lock, managed_years, registry_feed
from openrct2_analytics.ingest.autopilot_source import SourceRefused, find_source, newest_copy
from openrct2_analytics.ingest.autopilot_year import archive_dir
from openrct2_analytics.ingest.capture_session import Refused as SettingsRefused
from openrct2_analytics.ingest.contracts import LANDING_FOLDER
from openrct2_analytics.ingest.landing_paths import landing, project_path
from openrct2_analytics.ingest.park_label import label_of, labels, park_facts
from openrct2_analytics.ingest.play_status import registry_feed_dir
from openrct2_analytics.ingest.registry_feed import registry_dir
from openrct2_analytics.ingest.save_backup import file_label
from openrct2_analytics.ingest.save_files import save_files_dir

PROJECT_DIR = Path(__file__).resolve().parents[3]
COMPANY = "company"


@dataclass(frozen=True)
class Backup:
    """The newest archive copy: its base name and modification time (UTC, ISO 8601 with Z)."""

    file: str
    modified_at: str


@dataclass(frozen=True)
class ParkEntry:
    """One company park of the list."""

    park_id: str
    park_name: str | None
    park_label: str
    newest_backup: Backup | None
    source_problem: str | None
    needs_ready: bool


@dataclass(frozen=True)
class ParkList:
    """The company parks, sorted by ``park_id``."""

    data_set: str
    parks: tuple[ParkEntry, ...]


class _Refused(Exception):
    """The command was refused before reading anything."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class _ParksParser(argparse.ArgumentParser):
    """Argument parser that reports invalid input as a refusal."""

    def error(self, message: str) -> Never:
        raise _Refused("usage", message)


def _backup(copy: Path | None) -> Backup | None:
    if copy is None:
        return None
    modified = datetime.fromtimestamp(copy.stat().st_mtime, UTC).replace(microsecond=0)
    return Backup(copy.name, modified.strftime("%Y-%m-%dT%H:%M:%SZ"))


def read_parks(project_dir: Path = PROJECT_DIR) -> ParkList:
    """Read the company parks an autopilot year could start from. It writes nothing.

    Raises:
        ConfigError: if the data set's folders are misconfigured.
        SettingsRefused: if the backup folder setting is invalid.
        OSError: if a file cannot be read.
        duckdb.Error: if a Parquet file cannot be read.
    """
    parquet = landing(COMPANY, project_dir).parquet
    saves = project_path(save_files_dir(COMPANY), project_dir)
    registry = project_path(registry_dir(COMPANY), project_dir)
    archive = archive_dir(project_dir)
    starts = parquet / LANDING_FOLDER / "session_start.parquet"
    folders = landing(COMPANY, project_dir)
    try:
        facts = park_facts(folders)
    except UnicodeDecodeError:
        # Deliberate: one undecodable raw file must not hide the park list. Every park is shown by
        # its ID (as the dashboard does when a label read fails) and the file is named on stderr.
        for path in managed_years.raw_files(folders.raw):
            try:
                path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                print(
                    f"autopilot-parks: {path.name} cannot be decoded; parks are shown by ID.",
                    file=sys.stderr,
                )
        facts = {}
    park_labels = labels(facts)
    rows = registry_feed.latest_rows(registry_feed_dir(COMPANY, project_dir))
    parks = []
    for park_id in sorted(rows):
        row = rows[park_id]
        if row.data_set != COMPANY or row.practice:
            continue
        found = find_source(park_id, archive, parquet, saves)
        landed = starts.is_file() and managed_years.landed_autopilot_sessions(
            parquet, registry, park_id
        )
        parks.append(
            ParkEntry(
                park_id=park_id,
                park_name=facts[park_id].converted_name if park_id in facts else None,
                park_label=label_of(park_labels, park_id),
                newest_backup=_backup(newest_copy(archive / file_label(None, park_id))),
                source_problem=found.message if isinstance(found, SourceRefused) else None,
                needs_ready=not landed,
            )
        )
    return ParkList(COMPANY, tuple(parks))


def main(argv: Sequence[str] | None = None, *, project_dir: Path = PROJECT_DIR) -> int:
    """Print the company park list as one JSON object."""
    parser = _ParksParser(description=__doc__)
    parser.add_argument("--data-set", choices=DATA_SETS, required=True)
    handlers = {
        name: signal.getsignal(getattr(signal, name))
        for name in lock.SIGNAL_NAMES
        if hasattr(signal, name)
    }
    lock.set_signal_handlers(lock.raise_interrupted)
    try:
        args = parser.parse_args(argv)
        if args.data_set != COMPANY:
            raise _Refused("data-set", f"only the {COMPANY} data set has autopilot parks")
        print(json.dumps(asdict(read_parks(project_dir.resolve()))))
        code = 0
    except _Refused as error:
        print(f"autopilot-parks refused: {error.reason}: {error.detail}", file=sys.stderr)
        code = 2
    except (ConfigError, SettingsRefused) as error:
        print(f"autopilot-parks refused: settings: {error}", file=sys.stderr)
        code = 2
    except (OSError, ValueError, duckdb.Error) as error:
        print(f"autopilot-parks failed: io: {error}", file=sys.stderr)
        code = 1
    except (lock.Interrupted, KeyboardInterrupt):
        print("autopilot-parks interrupted", file=sys.stderr)
        code = 130
    finally:
        for name, handler in handlers.items():
            signal.signal(getattr(signal, name), handler)
    return code


if __name__ == "__main__":
    sys.exit(main())

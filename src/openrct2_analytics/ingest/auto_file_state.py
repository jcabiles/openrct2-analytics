"""Record-file state of ``make auto-file``: the converted-before record and its helpers.

The record names the sessions that existed before a play; ``auto_file`` reads it afterwards to find
which park is the play's. The data set and project folder arrive as arguments, so this module
imports nothing from ``auto_file``.
"""

from __future__ import annotations

import json
from pathlib import Path

from openrct2_analytics.ingest import managed_years, several_parks
from openrct2_analytics.ingest.landing_paths import landing

BEFORE_FILE = Path("local") / "auto-file" / "converted-before.json"


def record(project_dir: Path, data_set: str) -> None:
    """Write the sorted IDs of every converted or raw session, replacing any earlier record.

    Raw sessions count too: a capture stopped before converting is converted by the next play's
    capture, and must then be asked about as an earlier play's, not filed under this play's answer.
    """
    folders = landing(data_set, project_dir)
    parquet = folders.parquet
    starts = managed_years.table(parquet, "session_start")
    converted = managed_years.converted_sessions(parquet) if starts.is_file() else set()
    ids = sorted(converted | managed_years.raw_sessions(folders.raw))
    clear(project_dir)
    write_json(project_dir / BEFORE_FILE, ids)
    print(f"auto-file: recorded {len(ids)} converted session(s) in {BEFORE_FILE}")


def write_json(path: Path, content: object) -> None:
    """Write ``content`` as JSON through a temporary file and a rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f"{path.name}.tmp")
    staged.write_text(json.dumps(content) + "\n", encoding="utf-8")
    staged.replace(path)


def clear(project_dir: Path) -> None:
    """Remove the record and the stored answers, so a new play starts clean."""
    (project_dir / BEFORE_FILE).unlink(missing_ok=True)
    (project_dir / several_parks.ANSWERS_FILE).unlink(missing_ok=True)


def read_before(project_dir: Path) -> set[str] | None:
    """Return the session IDs converted before this play, or None when the record is unusable."""
    try:
        ids = json.loads((project_dir / BEFORE_FILE).read_text(encoding="utf-8"))
        if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
            raise ValueError("it is not a list of session IDs")
        return set(ids)
    except FileNotFoundError:
        why = "is missing"
    except (OSError, ValueError) as error:
        # Spec R3: without a usable record no park is known to be this play's, so every
        # unregistered park is asked about rather than filed by a guess; the line says why.
        why = f"cannot be read ({error})"
    print(
        f"auto-file: {BEFORE_FILE} {why}, so no park counts as this play's; "
        "every unregistered park is asked about."
    )
    return None

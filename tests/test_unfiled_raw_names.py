"""Never-converted park names are kept per (session, park): a park labelled by its own start.

Fixtures and helpers come from ``test_unfiled``; the raw file is planted under ``tmp_path``.
"""

from __future__ import annotations

import json
import os

from openrct2_analytics.config import LandingDirs
from openrct2_analytics.ingest.unfiled import render
from tests.test_unfiled import NOW, _run
from tests.test_unfiled import landing as landing  # noqa: F401  (pytest fixture)


def _two_park_raw_session(landing: LandingDirs, second: dict[str, object]) -> None:
    """Plant raw session ``r1``: a session_start for park-a (Alpha Park), then ``second``."""
    path = landing.raw / "v1" / "events-2026-11-15.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    first = {
        "session_id": "r1",
        "park_id": "park-a",
        "seq": 1,
        "event_type": "session_start",
        "park_name": "Alpha Park",
    }
    lines = [json.dumps(first), json.dumps({"session_id": "r1", "seq": 2} | second)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.utime(path, (NOW - 600, NOW - 600))


def test_raw_session_with_a_second_park_without_a_start_shows_that_park_by_id(
    landing: LandingDirs,
) -> None:
    _two_park_raw_session(landing, {"park_id": "park-b", "event_type": "park_snapshot"})
    assert render(_run(landing, set()))[2:] == [
        "- Alpha Park (park-a): 1 recording(s) never converted",
        "- park-b: 1 recording(s) never converted",
    ]


def test_raw_session_with_a_second_park_with_its_own_start_shows_its_own_name(
    landing: LandingDirs,
) -> None:
    _two_park_raw_session(
        landing, {"park_id": "park-b", "event_type": "session_start", "park_name": "Beta Park"}
    )
    assert render(_run(landing, set()))[2:] == [
        "- Alpha Park (park-a): 1 recording(s) never converted",
        "- Beta Park (park-b): 1 recording(s) never converted",
    ]


def test_never_converted_park_shows_its_raw_first_played_day(landing: LandingDirs) -> None:
    path = landing.raw / "v1" / "events-2026-11-15.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    start = {
        "session_id": "r1",
        "park_id": "park-a",
        "seq": 1,
        "event_type": "session_start",
        "park_name": "Alpha Park",
    }
    lines = [
        json.dumps(start | {"emitted_at": "2026-11-15T10:00:00Z"}),
        json.dumps(start | {"session_id": "r2", "emitted_at": "2026-11-16T10:00:00Z"}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.utime(path, (NOW - 600, NOW - 600))
    assert render(_run(landing, set()))[2] == (
        "- Alpha Park (first played Nov 15): 2 recording(s) never converted"
    )

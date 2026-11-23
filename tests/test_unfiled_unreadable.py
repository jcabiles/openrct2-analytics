"""Raw files with a line that cannot be read: ``make unfiled`` names each and offers nothing.

Every file is planted under ``tmp_path``; ``now`` and the game state are passed as values.
"""

from __future__ import annotations

import os
from pathlib import Path

from openrct2_analytics.config import LandingDirs
from openrct2_analytics.ingest import managed_years
from openrct2_analytics.ingest.unfiled import render
from tests.test_unfiled import (
    FAILED_LINE,
    NOW,
    OFFER_SESSIONS,
    RECORDING_LINE,
    RUNNING,
    _audit,
    _raw,
    _run,
    _start,
)
from tests.test_unfiled import landing as landing  # noqa: F401  (pytest fixture)

# Literal lines copied from the spec, requirement R12; not imported from the code under test.
UNREADABLE_LINE = (
    "Nothing is offered while a recording has a line that cannot be read, "
    "because converting stops at it."
)
FILE_LINE = (
    "- Recording events-2026-11-15.jsonl has a line that cannot be read; "
    "make convert DATA_SET=company names it"
)


def _break(path: Path, bad: str = '{"seq": 4') -> Path:
    """Append one line that cannot be read, keeping the file's age."""
    stat = path.stat()
    with path.open("a", encoding="utf-8") as stream:
        stream.write(bad + "\n")
    os.utime(path, (stat.st_atime, stat.st_mtime))
    return path


def test_unreadable_raw_files_lists_only_broken_files_in_name_order(landing: LandingDirs) -> None:
    _raw(landing, [("s1", "park-a")], 600, day="2026-11-14")
    second = _break(_raw(landing, [("s2", "park-a")], 600, day="2026-11-16"))
    first = _break(_raw(landing, [("s3", "park-a")], 600, day="2026-11-15"))
    assert managed_years.unreadable_raw_files(landing.raw) == [first, second]


def test_readable_raw_file_that_is_converted_prints_nothing(landing: LandingDirs) -> None:
    _start(landing, ("s1", "park-a", "Alpha Park"))
    _raw(landing, [("s1", "park-a")], 600)
    result = _run(landing, {"s1"})
    assert result.unreadable_files == ()
    assert render(result) == []


def test_only_an_unreadable_file_waiting_prints_no_offer_and_the_file(
    landing: LandingDirs,
) -> None:
    _start(landing, ("s1", "park-a", "Alpha Park"))
    _break(_raw(landing, [("s1", "park-a")], 600))
    result = _run(landing, {"s1"})
    assert result.unreadable_files == ("events-2026-11-15.jsonl",)
    assert result.offer is False
    assert render(result) == ["no-offer", "Play waiting to be filed:", FILE_LINE, UNREADABLE_LINE]


def test_a_file_of_only_unreadable_lines_is_named(landing: LandingDirs) -> None:
    path = landing.raw / "v1" / "events-2026-11-15.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"seq": 4\nnot json\n', encoding="utf-8")
    os.utime(path, (NOW - 600, NOW - 600))
    result = _run(landing, set())
    assert result.parks == ()
    assert render(result) == ["no-offer", "Play waiting to be filed:", FILE_LINE, UNREADABLE_LINE]


def test_unreadable_file_withholds_the_offer_for_a_converted_session(landing: LandingDirs) -> None:
    _start(landing, ("s1", "park-a", "Alpha Park"))
    _break(_raw(landing, [("s1", "park-a")], 600))
    result = _run(landing, set())
    assert result.offer is False
    assert render(result) == [
        "no-offer",
        "Play waiting to be filed:",
        OFFER_SESSIONS,
        FILE_LINE,
        UNREADABLE_LINE,
    ]


def test_failed_reason_comes_before_unreadable_reason(landing: LandingDirs) -> None:
    _start(landing, ("s1", "park-a", "Alpha Park"))
    _audit(landing, "s1", missing=1)
    _break(_raw(landing, [("s1", "park-a")], 600))
    assert render(_run(landing, set())) == [
        "no-offer",
        "Play waiting to be filed:",
        "- Alpha Park (first played Nov 12): session s1 failed its seq audit, "
        "so it is not offered for filing",
        FILE_LINE,
        FAILED_LINE,
    ]


def test_live_unreadable_file_is_not_listed_and_the_recording_reason_shows(
    landing: LandingDirs,
) -> None:
    _start(landing, ("s1", "park-a", "Alpha Park"))
    _break(_raw(landing, [("s1", "park-a")], 60))
    result = _run(landing, set())
    assert result.unreadable_files == ()
    assert render(result) == [
        "no-offer",
        "Play waiting to be filed:",
        OFFER_SESSIONS,
        RECORDING_LINE,
    ]


def test_game_running_leaves_the_unreadable_file_out(landing: LandingDirs) -> None:
    _break(_raw(landing, [("s1", "park-a")], 600))
    result = _run(landing, {"s1"}, game=RUNNING)
    assert result.unreadable_files == ()
    assert render(result) == []

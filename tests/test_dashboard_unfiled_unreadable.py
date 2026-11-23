"""The banner keeps its waiting line when a raw file has a line that cannot be read.

``make unfiled`` offers nothing then (reason ``unreadable``), but the dashboard banner reads as it
did before that reason existed. The expected lines are literals: the base commit's dashboard code
printed them for the same planted park (copied from its banner branches, not from the code under
test).
"""

from __future__ import annotations

import html
from pathlib import Path

from openrct2_analytics.config import LandingDirs
from tests.dashboard_unfiled_support import (
    _one_waiting,
    _page,
    _waiting_lines,
)
from tests.dashboard_unfiled_support import landing as landing  # noqa: F401  (pytest fixture)
from tests.test_unfiled import _raw
from tests.test_unfiled_unreadable import _break


def test_an_old_unreadable_raw_file_keeps_the_waiting_line(
    tmp_path: Path, landing: LandingDirs
) -> None:
    _, board = _one_waiting(tmp_path, landing)
    _break(_raw(landing, [("s1", "park-a")], 600))
    lines = _waiting_lines(_page(board))
    assert lines == [
        html.escape(
            "1 park has play waiting to be filed; open the OpenRCT2 Enterprise app to file it"
        )
    ]


def test_a_live_recording_beside_an_unreadable_file_keeps_the_recording_line(
    tmp_path: Path, landing: LandingDirs
) -> None:
    _, board = _one_waiting(tmp_path, landing)
    _break(_raw(landing, [("s1", "park-a")], 600))
    _raw(landing, [("s9", "park-a")], 60, day="2026-11-16")
    lines = _waiting_lines(_page(board))
    assert lines == [
        html.escape(
            "1 park has play that can't be filed right now; the OpenRCT2 Enterprise app will "
            "offer it when it can"
        )
    ]

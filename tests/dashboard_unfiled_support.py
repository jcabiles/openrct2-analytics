"""Lines, fakes and planting helpers for the dashboard banner tests.

Moved out of ``tests/test_dashboard_unfiled.py`` so the stale-copy tests share them.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.config import LandingDirs, landing_dirs
from openrct2_analytics.ingest import dashboard
from openrct2_analytics.ingest.game_check import GameState
from tests.test_dashboard import _project, _touch
from tests.test_unfiled import NOW, _start

TWO = "2 parks have play waiting to be filed; open the OpenRCT2 Enterprise app to file it"
ONE = "1 park has play waiting to be filed; open the OpenRCT2 Enterprise app to file it"
MARKER = "play waiting to be filed"
PAGE = "executive.html"
RECORDING_ONE = (
    "1 park has play that can't be filed right now; the OpenRCT2 Enterprise app will offer it "
    "when it can"
)
RECORDING_TWO = (
    "2 parks have play that can't be filed right now; the OpenRCT2 Enterprise app will offer it "
    "when it can"
)
FAILED_ONE = (
    "1 park has play that can't be filed right now; a session failed its recording-gap check, "
    "so the app will not offer it"
)
FAILED_TWO = (
    "2 parks have play that can't be filed right now; a session failed its recording-gap check, "
    "so the app will not offer it"
)
STALE_ONE = (
    "1 park has play that may still be waiting to be filed; this page shows older data, so check "
    "in the OpenRCT2 Enterprise app"
)
STALE_TWO = (
    "2 parks have play that may still be waiting to be filed; this page shows older data, so "
    "check in the OpenRCT2 Enterprise app"
)


class _Clock:
    def __init__(self, now: float = NOW) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _Game:
    def __init__(self, state: GameState) -> None:
        self.state = state

    def __call__(self) -> GameState:
        return self.state


@pytest.fixture
def landing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LandingDirs:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    return landing_dirs("company")


def _board(project: Path, clock: _Clock | None = None) -> dashboard.Dashboard:
    board = dashboard.Dashboard(
        project, clock=clock or _Clock(), game=lambda: GameState.NOT_RUNNING
    )
    board.start()
    return board


def _filed(project: Path, *sessions: str) -> None:
    """Record ``sessions`` as filed in the development warehouse."""
    with duckdb.connect(str(project / dashboard.DEV_WAREHOUSE)) as connection:
        connection.execute("CREATE SCHEMA IF NOT EXISTS staging")
        connection.execute("CREATE TABLE staging.stg_session_start (session_id VARCHAR)")
        for session in sessions:
            connection.execute("INSERT INTO staging.stg_session_start VALUES (?)", [session])


def _page(board: dashboard.Dashboard) -> str:
    board.refresh()
    return board.page(PAGE)[1].decode()


def _waiting_lines(page: str) -> list[str]:
    """Every waiting-play line on the page, as the escaped text between tags."""
    return re.findall(r"[^<>]*(?: has| have) play[^<>]*", page)


def _no_line(page: str) -> None:
    """The page carries no waiting-play text at all, not even a count of zero parks."""
    assert MARKER not in page
    assert " has play" not in page and " have play" not in page
    assert "0 parks" not in page


def _waiting(tmp_path: Path, landing: LandingDirs) -> tuple[Path, dashboard.Dashboard]:
    """Two parks, each with one converted session the warehouse does not hold."""
    project = _project(tmp_path)
    _filed(project)
    _start(landing, ("s1", "park-a", "Alpha Park"), ("s2", "park-b", "Beta Park"))
    return project, _board(project)


def _one_waiting(tmp_path: Path, landing: LandingDirs) -> tuple[Path, dashboard.Dashboard]:
    project = _project(tmp_path)
    _filed(project)
    _start(landing, ("s1", "park-a", "Alpha Park"))
    return project, _board(project)


def _wal_of(project: Path) -> Path:
    warehouse = project / dashboard.DEV_WAREHOUSE
    return warehouse.with_name(f"{warehouse.name}.wal")


def _stale_copy(project: Path) -> Path:
    """Make the warehouse look newly written while a build holds its wal."""
    _touch(project / dashboard.DEV_WAREHOUSE)
    wal = _wal_of(project)
    wal.touch()
    return wal

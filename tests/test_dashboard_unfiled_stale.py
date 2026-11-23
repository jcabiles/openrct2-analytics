"""The dashboard banner while it serves an older build: a rebuild under way, failed or restored.

Every file is planted under ``tmp_path``; only the clock and the game state are passed in.
"""

from __future__ import annotations

import html
import os
from pathlib import Path

import duckdb

from openrct2_analytics.config import LandingDirs
from openrct2_analytics.ingest import dashboard, managed_years
from tests.dashboard_unfiled_support import (
    FAILED_ONE,
    ONE,
    STALE_ONE,
    STALE_TWO,
    TWO,
    _board,
    _filed,
    _no_line,
    _one_waiting,
    _page,
    _stale_copy,
    _waiting,
    _waiting_lines,
    _wal_of,
)
from tests.dashboard_unfiled_support import landing as landing  # noqa: F401  (pytest fixture)
from tests.test_dashboard import _project, _touch
from tests.test_unfiled import _audit, _start


def _break_rebuild(project: Path) -> None:
    """Make the next rebuild of a newer warehouse file fail."""
    warehouse = project / dashboard.DEV_WAREHOUSE
    with duckdb.connect(str(warehouse)) as connection:
        connection.execute("drop table marts.fct_ride_day")
    _touch(warehouse)


def test_stale_one_park(tmp_path: Path, landing: LandingDirs) -> None:
    project, board = _one_waiting(tmp_path, landing)
    lines = _waiting_lines(_page(board))
    assert html.escape(ONE) in lines
    assert len(lines) == 1
    _stale_copy(project)
    lines = _waiting_lines(_page(board))
    assert html.escape(STALE_ONE) in lines
    assert len(lines) == 1


def test_stale_two_parks(tmp_path: Path, landing: LandingDirs) -> None:
    project, board = _waiting(tmp_path, landing)
    lines = _waiting_lines(_page(board))
    assert html.escape(TWO) in lines
    assert len(lines) == 1
    _stale_copy(project)
    lines = _waiting_lines(_page(board))
    assert html.escape(STALE_TWO) in lines
    assert len(lines) == 1


def test_stale_failed_session_shows_the_failed_line(tmp_path: Path, landing: LandingDirs) -> None:
    project, board = _one_waiting(tmp_path, landing)
    _page(board)
    _stale_copy(project)
    _audit(landing, "s1", missing=1)
    lines = _waiting_lines(_page(board))
    assert html.escape(FAILED_ONE) in lines
    assert len(lines) == 1


def test_a_failed_rebuild_shows_the_stale_line(tmp_path: Path, landing: LandingDirs) -> None:
    project, board = _one_waiting(tmp_path, landing)
    _page(board)
    _break_rebuild(project)
    page = _page(board)
    assert board.problem is not None and "the rebuild failed" in board.problem
    lines = _waiting_lines(page)
    assert html.escape(STALE_ONE) in lines
    assert len(lines) == 1


def test_a_failed_rebuild_still_sees_a_new_conversion(tmp_path: Path, landing: LandingDirs) -> None:
    project, board = _one_waiting(tmp_path, landing)
    lines = _waiting_lines(_page(board))
    assert html.escape(ONE) in lines
    assert len(lines) == 1
    _break_rebuild(project)
    _start(landing, ("s1", "park-a", "Alpha Park"), ("s2", "park-b", "Beta Park"))
    page = _page(board)
    assert board.problem is not None and "the rebuild failed" in board.problem
    lines = _waiting_lines(page)
    assert html.escape(STALE_TWO) in lines
    assert len(lines) == 1


def test_a_wal_with_an_unchanged_warehouse_file_is_stale(
    tmp_path: Path, landing: LandingDirs
) -> None:
    project, board = _one_waiting(tmp_path, landing)
    warehouse = project / dashboard.DEV_WAREHOUSE
    key = managed_years.file_key(warehouse)
    lines = _waiting_lines(_page(board))
    assert html.escape(ONE) in lines
    assert len(lines) == 1
    _wal_of(project).touch()
    page = _page(board)
    assert managed_years.file_key(warehouse) == key
    lines = _waiting_lines(page)
    assert html.escape(STALE_ONE) in lines
    assert len(lines) == 1


def test_a_wal_that_goes_with_an_unchanged_file_clears_the_stale_state(
    tmp_path: Path, landing: LandingDirs
) -> None:
    project, board = _one_waiting(tmp_path, landing)
    warehouse = project / dashboard.DEV_WAREHOUSE
    key = managed_years.file_key(warehouse)
    lines = _waiting_lines(_page(board))
    assert html.escape(ONE) in lines
    assert len(lines) == 1
    wal = _wal_of(project)
    wal.touch()
    lines = _waiting_lines(_page(board))
    assert html.escape(STALE_ONE) in lines
    assert len(lines) == 1
    wal.unlink()
    page = _page(board)
    assert managed_years.file_key(warehouse) == key
    assert board.problem is None
    lines = _waiting_lines(page)
    assert html.escape(ONE) in lines
    assert len(lines) == 1


def test_a_failed_rebuild_keeps_its_problem_when_a_wal_comes_and_goes(
    tmp_path: Path, landing: LandingDirs
) -> None:
    project, board = _one_waiting(tmp_path, landing)
    _page(board)
    _break_rebuild(project)
    lines = _waiting_lines(_page(board))
    assert html.escape(STALE_ONE) in lines
    assert len(lines) == 1
    wal = _wal_of(project)
    wal.touch()
    lines = _waiting_lines(_page(board))
    assert html.escape(STALE_ONE) in lines
    assert len(lines) == 1
    wal.unlink()
    page = _page(board)
    assert board.problem is not None and "the rebuild failed" in board.problem
    lines = _waiting_lines(page)
    assert html.escape(STALE_ONE) in lines
    assert len(lines) == 1


def test_a_restored_warehouse_with_the_same_file_is_not_stale(
    tmp_path: Path, landing: LandingDirs
) -> None:
    project, board = _one_waiting(tmp_path, landing)
    warehouse = project / dashboard.DEV_WAREHOUSE
    saved = project / "saved.duckdb"
    stat = warehouse.stat()
    key = managed_years.file_key(warehouse)
    lines = _waiting_lines(_page(board))
    assert html.escape(ONE) in lines
    assert len(lines) == 1
    warehouse.rename(saved)
    _page(board)
    assert board.problem is not None and "missing" in board.problem
    saved.rename(warehouse)
    os.utime(warehouse, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    page = _page(board)
    assert managed_years.file_key(warehouse) == key
    assert board.problem is None
    lines = _waiting_lines(page)
    assert html.escape(ONE) in lines
    assert len(lines) == 1


def test_a_missing_warehouse_is_not_stale_and_shows_no_stale_line(
    tmp_path: Path, landing: LandingDirs
) -> None:
    project, board = _one_waiting(tmp_path, landing)
    _page(board)
    (project / dashboard.DEV_WAREHOUSE).unlink()
    lines = _waiting_lines(_page(board))
    assert html.escape(ONE) in lines
    assert len(lines) == 1


def test_nothing_waiting_while_stale_shows_no_line(tmp_path: Path, landing: LandingDirs) -> None:
    project = _project(tmp_path)
    _filed(project, "s1")
    _start(landing, ("s1", "park-a", "Alpha Park"))
    board = _board(project)
    _no_line(_page(board))
    _stale_copy(project)
    _no_line(_page(board))

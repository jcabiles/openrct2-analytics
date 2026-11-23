"""The dashboard banner line for play waiting to be filed: refresh exits, clock and counting.

Every file is planted under ``tmp_path``; only the clock and the game state are passed in.
"""

from __future__ import annotations

import html
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.config import LandingDirs
from openrct2_analytics.ingest import dashboard, managed_years, unfiled
from openrct2_analytics.ingest.convert import landing_lock_path
from openrct2_analytics.ingest.game_check import GameState
from tests.dashboard_unfiled_support import (
    FAILED_ONE,
    FAILED_TWO,
    MARKER,
    ONE,
    PAGE,
    RECORDING_ONE,
    RECORDING_TWO,
    TWO,
    _board,
    _Clock,
    _filed,
    _Game,
    _no_line,
    _one_waiting,
    _page,
    _waiting,
    _waiting_lines,
)
from tests.dashboard_unfiled_support import landing as landing  # noqa: F401  (pytest fixture)
from tests.test_dashboard import _project, _touch
from tests.test_play_status import _writer_holds
from tests.test_unfiled import NOW, _audit, _raw, _start


def test_no_line_when_nothing_waits(tmp_path: Path, landing: LandingDirs) -> None:
    project = _project(tmp_path)
    _filed(project, "s1")
    _start(landing, ("s1", "park-a", "Alpha Park"))
    _no_line(_page(_board(project)))


def test_the_line_for_two_parks(tmp_path: Path, landing: LandingDirs) -> None:
    _, board = _waiting(tmp_path, landing)
    lines = _waiting_lines(_page(board))
    assert html.escape(TWO) in lines
    assert len(lines) == 1


def test_the_line_for_one_park(tmp_path: Path, landing: LandingDirs) -> None:
    _, board = _one_waiting(tmp_path, landing)
    lines = _waiting_lines(_page(board))
    assert html.escape(ONE) in lines
    assert len(lines) == 1


def test_the_banner_has_no_link(tmp_path: Path, landing: LandingDirs) -> None:
    _, board = _waiting(tmp_path, landing)
    page = _page(board)
    banner = page[page.index("role='status'") : page.index("</div>", page.index("role='status'"))]
    assert TWO in banner
    assert "<a" not in banner


def test_recording_raw_for_one_park_uses_recording_line(
    tmp_path: Path, landing: LandingDirs
) -> None:
    _, board = _one_waiting(tmp_path, landing)
    _raw(landing, [("s1", "park-a")], 60)
    page = _page(board)

    lines = _waiting_lines(page)
    assert html.escape(RECORDING_ONE) in page
    assert html.escape(ONE) not in page
    assert html.escape(RECORDING_ONE) in lines
    assert len(lines) == 1


def test_recording_raw_for_two_parks_counts_parks(tmp_path: Path, landing: LandingDirs) -> None:
    _, board = _waiting(tmp_path, landing)
    _raw(landing, [("s1", "park-a")], 60)
    page = _page(board)

    lines = _waiting_lines(page)
    assert html.escape(RECORDING_TWO) in page
    assert html.escape(TWO) not in page
    assert html.escape(RECORDING_TWO) in lines
    assert len(lines) == 1


def test_recording_running_game_uses_recording_line(tmp_path: Path, landing: LandingDirs) -> None:
    project = _project(tmp_path)
    _filed(project)
    _start(landing, ("s1", "park-a", "Alpha Park"))
    game = _Game(GameState.RUNNING)
    board = dashboard.Dashboard(project, clock=_Clock(), game=game)
    board.start()
    page = _page(board)
    lines = _waiting_lines(page)
    assert html.escape(RECORDING_ONE) in page
    assert html.escape(ONE) not in page
    assert html.escape(RECORDING_ONE) in lines
    assert len(lines) == 1


def test_recording_running_game_for_two_parks_counts_parks(
    tmp_path: Path, landing: LandingDirs
) -> None:
    project = _project(tmp_path)
    _filed(project)
    _start(landing, ("s1", "park-a", "Alpha Park"), ("s2", "park-b", "Beta Park"))
    board = dashboard.Dashboard(project, clock=_Clock(), game=_Game(GameState.RUNNING))
    board.start()
    page = _page(board)
    lines = _waiting_lines(page)
    assert html.escape(RECORDING_TWO) in page
    assert html.escape(TWO) not in page
    assert html.escape(RECORDING_TWO) in lines
    assert len(lines) == 1


def test_failed_one_park_uses_failed_line(tmp_path: Path, landing: LandingDirs) -> None:
    _, board = _one_waiting(tmp_path, landing)
    _audit(landing, "s1", missing=1)
    page = _page(board)

    lines = _waiting_lines(page)
    assert html.escape(FAILED_ONE) in page
    assert html.escape(ONE) not in page
    assert html.escape(FAILED_ONE) in lines
    assert len(lines) == 1


def test_failed_two_parks_counts_failed_only_park(tmp_path: Path, landing: LandingDirs) -> None:
    _, board = _waiting(tmp_path, landing)
    _audit(landing, "s1", missing=1)
    page = _page(board)

    lines = _waiting_lines(page)
    assert html.escape(FAILED_TWO) in page
    assert html.escape(TWO) not in page
    assert html.escape(FAILED_TWO) in lines
    assert len(lines) == 1


def test_mixed_park_uses_failed_line_once(tmp_path: Path, landing: LandingDirs) -> None:
    project = _project(tmp_path)
    _filed(project)
    _start(landing, ("s1", "park-a", "Alpha Park"), ("s2", "park-a", "Alpha Park"))
    _audit(landing, "s2", missing=1)

    page = _page(_board(project))

    lines = _waiting_lines(page)
    assert html.escape(FAILED_ONE) in page
    assert html.escape(ONE) not in page
    assert html.escape(FAILED_ONE) in lines
    assert len(lines) == 1


def test_a_writer_holding_the_warehouse_does_not_stop_the_line(
    tmp_path: Path, landing: LandingDirs, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    _filed(project, "s1")
    _start(landing, ("s1", "park-a", "Alpha Park"), ("s2", "park-b", "Beta Park"))
    board = _board(project)
    assert ONE in _page(board)
    real = duckdb.connect
    warehouse = str(project / dashboard.DEV_WAREHOUSE)

    def guarded(database: str, *args: object, **kwargs: object) -> duckdb.DuckDBPyConnection:
        assert str(database) != warehouse, "the dashboard opened the real warehouse"
        return real(database, *args, **kwargs)  # type: ignore[arg-type]

    with _writer_holds(project / dashboard.DEV_WAREHOUSE):
        monkeypatch.setattr(duckdb, "connect", guarded)
        page = _page(board)
    assert ONE in page
    assert TWO not in page


def _file_more(project: Path, session: str) -> None:
    """Record one more filed session and make the warehouse look newly built."""
    warehouse = project / dashboard.DEV_WAREHOUSE
    with duckdb.connect(str(warehouse)) as connection:
        connection.execute("INSERT INTO staging.stg_session_start VALUES (?)", [session])
    _touch(warehouse)


def test_filing_a_session_in_the_warehouse_clears_the_line(
    tmp_path: Path, landing: LandingDirs
) -> None:
    project = _project(tmp_path)
    _filed(project)
    _start(landing, ("s1", "park-a", "Alpha Park"))
    board = _board(project)
    assert ONE in _page(board)

    _file_more(project, "s1")

    assert MARKER not in _page(board)


def test_a_game_that_quits_shows_the_hidden_recording(tmp_path: Path, landing: LandingDirs) -> None:
    project = _project(tmp_path)
    _filed(project)
    _raw(landing, [("r1", "park-a")], 600)
    game = _Game(GameState.RUNNING)
    board = dashboard.Dashboard(project, clock=_Clock(), game=game)
    board.start()
    assert MARKER not in _page(board)

    game.state = GameState.NOT_RUNNING

    assert ONE in _page(board)


def test_a_landing_lock_that_goes_shows_the_hidden_recording(
    tmp_path: Path, landing: LandingDirs
) -> None:
    project = _project(tmp_path)
    _filed(project)
    _raw(landing, [("r1", "park-a")], 600)
    lock = landing_lock_path(landing.parquet)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("")
    board = _board(project)
    assert MARKER not in _page(board)

    lock.unlink()

    assert ONE in _page(board)


def test_a_deleted_warehouse_counts_the_filed_session_as_waiting(
    tmp_path: Path, landing: LandingDirs
) -> None:
    project = _project(tmp_path)
    _filed(project, "s1")
    _start(landing, ("s1", "park-a", "Alpha Park"))
    board = _board(project)
    assert MARKER not in _page(board)

    (project / dashboard.DEV_WAREHOUSE).unlink()

    assert ONE in _page(board)


def test_an_unchanged_key_does_not_call_find_unfiled_again(
    tmp_path: Path, landing: LandingDirs, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, board = _one_waiting(tmp_path, landing)
    calls: list[int] = []
    real = unfiled.find_unfiled

    def counting(
        landing: LandingDirs,
        filed: set[str] | None,
        *,
        warehouse: str,
        now: float,
        game: GameState,
        lock_present: bool,
    ) -> unfiled.Unfiled:
        calls.append(1)
        return real(
            landing, filed, warehouse=warehouse, now=now, game=game, lock_present=lock_present
        )

    monkeypatch.setattr(unfiled, "find_unfiled", counting)
    assert ONE in _page(board)
    assert ONE in _page(board)
    assert len(calls) == 1


def test_a_raw_file_ending_in_a_torn_character_gives_the_could_not_check_line(
    tmp_path: Path, landing: LandingDirs, capsys: pytest.CaptureFixture[str]
) -> None:
    _, board = _one_waiting(tmp_path, landing)
    torn = landing.raw / "v1" / "events-2026-11-15.jsonl"
    torn.parent.mkdir(parents=True)
    torn.write_bytes(b'{"session_id": "r1", "park_id": "park-a", "park_name": "Caf\xc3')
    first = _page(board)
    assert "Play waiting to be filed could not be checked: " in first

    second = _page(board)

    assert "Play waiting to be filed could not be checked: " in second
    assert ONE not in second


def test_the_same_failure_before_the_key_exists_is_logged_once(
    tmp_path: Path,
    landing: LandingDirs,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def broken(_: LandingDirs) -> tuple[object, ...]:
        raise OSError("input folder unreadable")

    monkeypatch.setattr(unfiled, "input_key", broken)
    _, board = _waiting(tmp_path, landing)
    assert "could not be checked: input folder unreadable" in _page(board)
    assert "could not be checked: input folder unreadable" in _page(board)
    assert capsys.readouterr().err.count("input folder unreadable") == 1


def test_a_new_conversion_changes_the_count_without_a_warehouse_change(
    tmp_path: Path, landing: LandingDirs
) -> None:
    project, board = _one_waiting(tmp_path, landing)
    assert ONE in _page(board)
    _start(landing, ("s1", "park-a", "Alpha Park"), ("s2", "park-b", "Beta Park"))

    assert TWO in _page(board)


def test_a_missing_warehouse_counts_every_converted_session(
    tmp_path: Path, landing: LandingDirs
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _start(landing, ("s1", "park-a", "Alpha Park"))
    board = _board(project)
    board.refresh()
    code, body = board.page(PAGE)
    assert code == 503 and ONE in body.decode()

    _start(landing, ("s1", "park-a", "Alpha Park"), ("s2", "park-b", "Beta Park"))

    assert TWO in _page(board)


def test_an_unchanged_raw_folder_is_not_parsed_again(
    tmp_path: Path, landing: LandingDirs, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    _filed(project)
    calls: list[Path] = []
    real = managed_years.read_raw_file

    def counting(path: Path) -> managed_years.RawFile:
        calls.append(path)
        return real(path)

    monkeypatch.setattr(managed_years, "read_raw_file", counting)
    raw = _raw(landing, [("r1", "park-a")], 600)
    board = _board(project)
    assert ONE in _page(board)
    assert calls == [raw]

    assert ONE in _page(board)
    assert calls == [raw]

    _raw(landing, [("r1", "park-a"), ("r2", "park-b")], 600)
    assert TWO in _page(board)
    assert calls == [raw, raw]


def test_a_recording_is_left_out_until_the_clock_passes_the_window(
    tmp_path: Path, landing: LandingDirs
) -> None:
    project = _project(tmp_path)
    _filed(project)
    _raw(landing, [("r1", "park-a")], 60)
    clock = _Clock()
    board = _board(project, clock)
    assert MARKER not in _page(board)

    clock.now = NOW + 59
    assert MARKER not in _page(board)

    clock.now = NOW + 120
    assert ONE in _page(board)


def test_a_damaged_audit_file_gives_the_could_not_check_line(
    tmp_path: Path, landing: LandingDirs, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    _filed(project)
    _start(landing, ("s1", "park-a", "Alpha Park"))
    audit = landing.parquet / "audit" / "seq_audit.parquet"
    audit.parent.mkdir(parents=True)
    audit.write_bytes(b"not parquet" * 50)
    board = _board(project)

    page = _page(board)

    line = board.unfiled_line
    assert line is not None
    assert line.startswith("Play waiting to be filed could not be checked: ")
    assert line.endswith(".")
    assert html.escape(line) in page
    assert MARKER not in page.replace(html.escape(line), "")
    assert line in capsys.readouterr().err

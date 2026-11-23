"""The dashboard's practice-park warning names each practice park by its label.

Every file is planted under ``tmp_path``; the labels come from ``park_label`` over the landing
files, never from the warehouse.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from datetime import timedelta, timezone, tzinfo
from pathlib import Path

import pytest

from openrct2_analytics.config import LandingDirs
from openrct2_analytics.ingest import dashboard, park_label, register_parks
from tests.dashboard_unfiled_support import ONE, PAGE, _board, _filed, _page
from tests.dashboard_unfiled_support import landing as landing  # noqa: F401  (pytest fixture)
from tests.test_dashboard import _project
from tests.test_park_label import converted, raw

WARNING = (
    "Sandbox park {label} is left out of the All parks figures unless Sandbox parks are "
    "included; remove it with make delete-company-data PARK={park}."
)
FALLBACK = "p2 (first-played date unavailable)"
BARE = "Park names could not be read: "
BARE_END = "; Sandbox parks are shown by ID, first-played date unavailable."


def _lines(page: str) -> list[str]:
    """Every banner line on the page, unescaped."""
    found = re.findall(r"<p style='margin:0.25em 0'>(.*?)</p>", page, flags=re.DOTALL)
    return [html.unescape(line) for line in found]


def _practice(lines: list[str]) -> list[str]:
    return [line for line in lines if line.startswith("Sandbox park ")]


def _board_with(
    tmp_path: Path,
    zone: Callable[[tzinfo], None],
    *,
    parks: tuple[tuple[str, str], ...],
    rows: list[tuple[str, str, str | None, str]],
    landing: LandingDirs,
) -> dashboard.Dashboard:
    """Practice parks in the warehouse, their converted starts planted and every session filed."""
    zone(timezone(timedelta(hours=-8)))
    notes = ("",) + (register_parks.NOTE,) * (len(parks) - 1)
    project = _project(tmp_path, parks=parks, notes=notes)
    _filed(project, *(session for _, session, _, _ in rows))
    converted(landing, rows)
    return _board(project)


ONE_PRACTICE = (("p1", "Alpha Park"), ("p2", "Beta Park"))
BETA: tuple[str, str, str | None, str] = ("p2", "s2", "Beta Park", "2026-10-17T00:00:00Z")


def test_a_practice_park_is_named_by_its_label(
    tmp_path: Path, landing: LandingDirs, fixed_local_zone: Callable[[tzinfo], None]
) -> None:
    board = _board_with(
        tmp_path, fixed_local_zone, parks=ONE_PRACTICE, rows=[BETA], landing=landing
    )

    lines = _lines(_page(board))

    label = "Beta Park (first played Oct 16)"
    assert _practice(lines) == [WARNING.format(label=label, park="p2")]
    assert not any(line.startswith(BARE) for line in lines)


def test_two_same_named_practice_parks_get_one_sentence_each(
    tmp_path: Path, landing: LandingDirs, fixed_local_zone: Callable[[tzinfo], None]
) -> None:
    parks = (("p1", "Alpha Park"), ("p2", "Beta Park"), ("p3", "Beta Park"))
    rows: list[tuple[str, str, str | None, str]] = [
        ("p2", "s2", "Beta Park", "2026-10-17T20:00:00Z"),
        ("p3", "s3", "Beta Park", "2026-10-17T21:30:00Z"),
    ]
    board = _board_with(tmp_path, fixed_local_zone, parks=parks, rows=rows, landing=landing)

    lines = _lines(_page(board))

    assert _practice(lines) == [
        WARNING.format(label="Beta Park (Oct 17, 12:00 pm)", park="p2"),
        WARNING.format(label="Beta Park (Oct 17, 1:30 pm)", park="p3"),
    ]


def test_a_new_session_updates_the_label_without_a_warehouse_change(
    tmp_path: Path, landing: LandingDirs, fixed_local_zone: Callable[[tzinfo], None]
) -> None:
    board = _board_with(
        tmp_path, fixed_local_zone, parks=ONE_PRACTICE, rows=[BETA], landing=landing
    )
    first = _practice(_lines(_page(board)))
    assert first == [WARNING.format(label="Beta Park (first played Oct 16)", park="p2")]
    built = board.current

    converted(landing, [BETA, ("p2", "s3", "Gamma Park", "2026-10-18T00:00:00Z")])

    assert _practice(_lines(_page(board))) == [
        WARNING.format(label="Gamma Park (first played Oct 16)", park="p2")
    ]
    assert board.current is built


def test_an_unreadable_parquet_shows_the_bare_id_and_names_the_failure(
    tmp_path: Path, landing: LandingDirs, fixed_local_zone: Callable[[tzinfo], None]
) -> None:
    board = _board_with(
        tmp_path, fixed_local_zone, parks=ONE_PRACTICE, rows=[BETA], landing=landing
    )
    (landing.parquet / "v1" / "session_start.parquet").write_bytes(b"not parquet")

    page = _page(board)

    _assert_bare_id_page(board, page)


def test_a_raw_file_ending_in_a_torn_character_shows_the_bare_id_and_names_the_failure(
    tmp_path: Path, landing: LandingDirs, fixed_local_zone: Callable[[tzinfo], None]
) -> None:
    board = _board_with(
        tmp_path, fixed_local_zone, parks=ONE_PRACTICE, rows=[BETA], landing=landing
    )
    torn = landing.raw / "v1" / "events-2026-11-15.jsonl"
    torn.parent.mkdir(parents=True)
    torn.write_bytes(b'{"session_id": "r1", "park_id": "p2", "park_name": "Caf\xc3')

    page = _page(board)

    _assert_bare_id_page(board, page)


def _assert_bare_id_page(board: dashboard.Dashboard, page: str) -> None:
    lines = _lines(page)
    assert board.page(PAGE)[0] == 200
    assert board.current is not None and (board.static_root() / dashboard.DATA_FILE).is_file()
    assert _practice(lines) == [WARNING.format(label=FALLBACK, park="p2")]
    names = [line for line in lines if line.startswith(BARE)]
    assert len(names) == 1 and names[0].endswith(BARE_END)


def test_labels_are_not_read_when_the_build_has_no_practice_park(
    tmp_path: Path, landing: LandingDirs
) -> None:
    project = _project(tmp_path)
    _filed(project, "s2")
    converted(landing, [BETA])
    (landing.parquet / "v1" / "session_start.parquet").write_bytes(b"not parquet")
    board = _board(project)

    lines = _lines(_page(board))

    assert _practice(lines) == []
    assert not any(line.startswith(BARE) for line in lines)
    unfiled = [line for line in lines if line.startswith("Play waiting to be filed could not")]
    assert len(unfiled) == 1


def test_a_failed_label_read_keeps_the_waiting_play_line(
    tmp_path: Path,
    landing: LandingDirs,
    fixed_local_zone: Callable[[tzinfo], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_local_zone(timezone(timedelta(hours=-8)))
    project = _project(tmp_path, parks=ONE_PRACTICE, notes=("", register_parks.NOTE))
    _filed(project)
    converted(landing, [BETA])
    board = _board(project)

    real_facts = park_label.park_facts
    calls: list[LandingDirs] = []

    def fail_the_dashboards_read(landing_dirs: LandingDirs) -> object:
        # The dashboard's own read fails; find_unfiled then gets an empty label map, so the
        # waiting-play lines show bare park IDs.
        calls.append(landing_dirs)
        if len(calls) == 1:
            raise OSError("planted")
        return real_facts(landing_dirs)

    monkeypatch.setattr(park_label, "park_facts", fail_the_dashboards_read)

    lines = _lines(_page(board))

    assert _practice(lines) == [WARNING.format(label=FALLBACK, park="p2")]
    assert [line for line in lines if line.startswith(BARE)] == [
        "Park names could not be read: planted; Sandbox parks are shown by ID, "
        "first-played date unavailable."
    ]
    assert ONE in lines
    assert not any("could not be checked" in line for line in lines)


def test_a_label_read_failure_is_logged_once_per_change_of_the_files(
    tmp_path: Path,
    landing: LandingDirs,
    fixed_local_zone: Callable[[tzinfo], None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    board = _board_with(
        tmp_path, fixed_local_zone, parks=ONE_PRACTICE, rows=[BETA], landing=landing
    )
    (landing.parquet / "v1" / "session_start.parquet").write_bytes(b"not parquet")

    _page(board)
    _page(board)
    raw(landing, "r1", "p2", "Beta Park", when="2026-10-18T00:00:00Z")
    _page(board)

    logged = [
        line
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("dashboard: " + BARE)
    ]
    assert len(logged) == 1

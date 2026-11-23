"""Behaviour at the callers of the landing-folder join: reading and checking commands.

Every test passes on the code as it stands and must keep passing when the private copies of the
join move into one module. The relative-root tests set ``OPENRCT2_DATA_DIR=data-x``, plant files
under ``<project>/data-x/company/`` and run from a different, empty working folder, so a lost
join looks in the wrong place and the planted file changes the outcome. The filing commands are
in ``tests/test_landing_paths_callers_filing.py``.
"""

from __future__ import annotations

import html
import json
from collections.abc import Callable
from datetime import UTC, datetime, tzinfo
from pathlib import Path

import pytest

from openrct2_analytics.config import LandingDirs
from openrct2_analytics.ingest import (
    autopilot_parks,
    delete_data,
    play_status,
    register_parks,
    results,
    unfiled,
)
from openrct2_analytics.ingest.autopilot_run import write_boundary_problem
from openrct2_analytics.ingest.autopilot_year import archive_dir
from openrct2_analytics.ingest.delete_plan import Scope
from openrct2_analytics.ingest.game_check import GameState
from openrct2_analytics.ingest.play_mode_feed import AUTOPILOT, ready_phrase
from tests.autopilot_fixtures import (
    event_row,
    plant_archive_copy,
    plant_label,
    plant_paired_save,
    plant_registry,
    plant_save_written,
    plant_session_start,
)
from tests.dashboard_unfiled_support import ONE, _one_waiting, _page, _waiting_lines
from tests.landing_paths_support import EMPTY_ROOT
from tests.landing_paths_support import relative_root as relative_root  # noqa: F401  (fixture)
from tests.test_capture import free_port
from tests.test_delete_plan import event, write
from tests.test_play_status import _warehouse
from tests.test_results import run_results
from tests.test_results import warehouse as results_warehouse

SAVED = datetime(2026, 11, 12, 20, 0, 0, tzinfo=UTC)
SIZE = 7


def _plant_play(data: Path) -> None:
    """Two converted sessions (park-a registered, park-b with one paired save file)."""
    company = data / "company"
    plant_session_start(
        company / "parquet",
        [
            event_row(1, session_id="s1", park_id="park-a", park_name="Alpha Park"),
            event_row(1, session_id="s2", park_id="park-b", park_name="Beta Park"),
        ],
    )
    saved = event_row(2, session_id="s2", park_id="park-b", save_id="save-2")
    plant_save_written(
        company / "parquet",
        [plant_paired_save(company / "save_files", saved, "beta-main.park", SIZE)],
    )
    plant_registry(company / "registry" / "v1", [("park-a", 2000, 3, "company", "", "2026-10-01")])


def _plant_autopilot(
    data: Path, archive: Path, name: str, *, saves: bool = True, archived: bool = True
) -> None:
    """One registered company park, park-a, named ``name``; saves and a proven backup if asked."""
    company = data / "company"
    plant_session_start(
        company / "parquet",
        [event_row(1, emitted_at=SAVED, park_name=name, session_id="sess-1")],
    )
    if saves:
        saved = event_row(2, emitted_at=SAVED, save_id="save-2")
        plant_save_written(
            company / "parquet", [plant_paired_save(company / "save_files", saved, "Alpha", SIZE)]
        )
    plant_registry(company / "registry" / "v1", [("park-a", 2000, 1, "company", "", "2026-11-12")])
    if archived:
        plant_archive_copy(
            archive,
            "park-a",
            "Alpha",
            datetime(2026, 11, 12, 21, 0, 0),
            data=b"x" * SIZE,
            modified_at=datetime(2026, 11, 14, 10, 0, 0, tzinfo=UTC),
        )


# R5: results keeps .resolve() on top of the join, on the recorded side and the configured side.


def _built(out: str) -> bool:
    return "Park days (game date and company date) — marts.fct_park_day\n1 rows" in out


def test_results_resolves_a_recorded_root_that_reaches_the_folder_through_a_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real = (tmp_path / "real").resolve()
    parquet = real / "company" / "parquet"
    parquet.mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(parquet)
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(real))
    project = tmp_path / "project"
    results_warehouse(project)
    run_results(project, root=str(link))
    assert results.main(["--data-set", "company"], project_dir=project) == 0
    assert _built(capsys.readouterr().out)


def test_results_resolves_a_configured_root_that_reaches_the_folder_through_a_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real = (tmp_path / "real").resolve()
    parquet = real / "company" / "parquet"
    parquet.mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real)
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(link))
    project = tmp_path / "project"
    results_warehouse(project)
    run_results(project, root=str(parquet))
    assert results.main(["--data-set", "company"], project_dir=project) == 0
    assert _built(capsys.readouterr().out)


# R12: a relative data root, from a working folder that is not the project folder.


def test_results_joins_a_relative_recorded_root_and_data_root_under_the_project(
    relative_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    results_warehouse(relative_root)
    run_results(relative_root, root="data-x/company/parquet")
    assert results.main(["--data-set", "company"], project_dir=relative_root) == 0
    assert _built(capsys.readouterr().out)


def test_play_status_last_save_files_reads_the_save_folder_under_the_project(
    relative_root: Path,
) -> None:
    _plant_play(relative_root / "data-x")
    found = play_status._last_save_files(
        "company", relative_root / "data-x" / "company" / "parquet", relative_root
    )
    assert found == {("s2", "park-b"): "beta-main.park"}


def test_play_status_registry_feed_dir_is_under_the_project(relative_root: Path) -> None:
    _plant_play(relative_root / "data-x")
    feed = play_status.registry_feed_dir("company", relative_root)
    assert feed == relative_root / "data-x" / "company" / "registry" / "v1"
    assert set(register_parks.registered_parks(feed)) == {"park-a"}


def test_play_status_read_status_reads_the_parquet_under_the_project(
    relative_root: Path,
) -> None:
    _plant_play(relative_root / "data-x")
    status = play_status.read_status("company", relative_root)
    assert [
        (session.session_id, [(p.park_id, p.registered, p.last_save_file) for p in session.parks])
        for session in status.sessions_waiting
    ] == [("s1", [("park-a", True, None)]), ("s2", [("park-b", False, "beta-main.park")])]


def test_dashboard_refresh_lists_the_waiting_session_under_the_project(
    tmp_path: Path, relative_root: Path
) -> None:
    company = relative_root / "data-x" / "company"
    landing = LandingDirs(raw=company / "raw", parquet=company / "parquet")
    _, board = _one_waiting(tmp_path, landing)
    assert html.escape(ONE) in _waiting_lines(_page(board))


def test_unfiled_company_lookup_lists_the_waiting_session_under_the_project(
    relative_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fixed_local_zone: Callable[[tzinfo], None],
) -> None:
    fixed_local_zone(UTC)
    monkeypatch.setattr(unfiled, "platform_game_check", lambda: lambda: GameState.NOT_RUNNING)
    _warehouse(relative_root, [])
    plant_session_start(
        relative_root / "data-x" / "company" / "parquet",
        [event_row(1, emitted_at=SAVED, session_id="s1", park_id="park-a", park_name="Alpha")],
    )
    assert unfiled.main(["--data-set", "company"], project_dir=relative_root) == 0
    assert capsys.readouterr().out == (
        "offer\nPlay waiting to be filed:\n"
        "- Alpha (first played Nov 12): 1 converted session(s) not filed yet\n"
    )


def test_autopilot_parks_reads_the_parquet_saves_and_registry_under_the_project(
    relative_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fixed_local_zone: Callable[[tzinfo], None],
) -> None:
    fixed_local_zone(UTC)
    archive = relative_root.parent / "archive"
    monkeypatch.setenv("OPENRCT2_BACKUP_DIR", str(archive))
    data = relative_root / "data-x"
    _plant_autopilot(data, archive, "Alpha")
    plant_label(
        data / "company" / "registry" / "v1",
        [("sess-1", "park-a", AUTOPILOT, ready_phrase("park-a"), "company", "2026-11-13")],
    )
    assert autopilot_parks.main(["--data-set", "company"], project_dir=relative_root) == 0
    assert json.loads(capsys.readouterr().out) == {
        "data_set": "company",
        "parks": [
            {
                "park_id": "park-a",
                "park_name": "Alpha",
                "park_label": "Alpha (first played Nov 12)",
                "newest_backup": {
                    "file": "Alpha-2026-11-12-210000.park",
                    "modified_at": "2026-11-14T10:00:00Z",
                },
                "source_problem": None,
                "needs_ready": False,
            }
        ],
    }


def test_autopilot_run_boundary_places_the_company_folder_under_the_project(
    relative_root: Path, tmp_path: Path
) -> None:
    user, archive = tmp_path / "user", tmp_path / "archive"
    work = relative_root / "data-x" / "company" / "autopilot-park-a"
    assert write_boundary_problem(work, user, archive, relative_root) == (
        "The work folder equals, contains or lies inside data/company/."
    )


def test_delete_data_settings_find_the_company_data_under_the_project(
    relative_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Called directly: main() changes into the project folder first, which hides a lost join.
    monkeypatch.setenv("OPENRCT2_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("OPENRCT2_LISTENER_PORT", str(free_port()))
    write(relative_root / "data-x" / "company" / "raw" / "v1" / "events-a.jsonl", event("p", "s"))
    root, _, _ = delete_data._settings(relative_root, Scope(session="s"))
    assert root == relative_root / "data-x"


# R8: autopilot_parks keeps a second, fresh lookup for the names-and-labels read.


def test_autopilot_parks_reads_names_and_labels_from_a_root_changed_after_the_parquet_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fixed_local_zone: Callable[[tzinfo], None],
) -> None:
    fixed_local_zone(UTC)
    root_a, root_b = tmp_path / "root-a", tmp_path / "root-b"
    monkeypatch.setenv("OPENRCT2_BACKUP_DIR", str(tmp_path / "archive"))
    _plant_autopilot(root_a, tmp_path / "archive", "Alpha")
    _plant_autopilot(root_b, tmp_path / "archive", "Bravo", saves=False, archived=False)
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(root_a))

    def archive_dir_then_switch(project_dir: Path) -> Path:
        found = archive_dir(project_dir)
        monkeypatch.setenv("OPENRCT2_DATA_DIR", str(root_b))
        return found

    monkeypatch.setattr(autopilot_parks, "archive_dir", archive_dir_then_switch)
    assert autopilot_parks.main(["--data-set", "company"], project_dir=tmp_path) == 0
    (park,) = json.loads(capsys.readouterr().out)["parks"]
    assert (park["park_name"], park["park_label"]) == ("Bravo", "Bravo (first played Nov 12)")


# R9: the line and exit code of a lookup error, through a path that reaches the company lookup.


def test_autopilot_parks_refuses_an_empty_data_root_with_a_settings_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "")
    assert autopilot_parks.main(["--data-set", "company"], project_dir=tmp_path) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"autopilot-parks refused: settings: {EMPTY_ROOT}\n"


def test_results_refuses_an_empty_data_root_for_the_company_data_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "")
    assert results.main(["--data-set", "company"], project_dir=tmp_path) == 2
    assert capsys.readouterr().out == f"results refused: config: {EMPTY_ROOT}\n"


def test_play_status_refuses_an_empty_data_root_for_the_company_data_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "")
    assert play_status.main(["--data-set", "company"], project_dir=tmp_path) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"play-status refused: data-set: {EMPTY_ROOT}\n"


def test_unfiled_refuses_an_empty_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "")
    assert unfiled.main(["--data-set", "company"], project_dir=tmp_path) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"unfiled refused: data-set: {EMPTY_ROOT}\n"

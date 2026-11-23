"""Real files in a temporary project for the autopilot park list command."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, tzinfo
from pathlib import Path

import pytest

from openrct2_analytics.ingest import autopilot_parks, park_label
from openrct2_analytics.ingest.play_mode_feed import AUTOPILOT, ready_phrase
from openrct2_analytics.ingest.register_parks import NOTE
from tests.autopilot_fixtures import (
    event_row,
    plant_archive_copy,
    plant_label,
    plant_paired_save,
    plant_registry,
    plant_save_written,
    plant_session_start,
)

SAVED = datetime(2026, 11, 12, 20, 0, 0, tzinfo=UTC)
SIZE = 7
COPY_ENDED = datetime(2026, 11, 12, 21, 0, 0)
COPY_MODIFIED = datetime(2026, 11, 14, 10, 0, 0, tzinfo=UTC)
BACKUP = {"file": "Alpha-2026-11-12-210000.park", "modified_at": "2026-11-14T10:00:00Z"}


@pytest.fixture(autouse=True)
def utc(fixed_local_zone: Callable[[tzinfo], None]) -> None:
    fixed_local_zone(UTC)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """One registered company park, park-a, named Alpha, with a proven backup."""
    data = tmp_path / "data" / "company"
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENRCT2_BACKUP_DIR", str(tmp_path / "archive"))
    plant_session_start(
        data / "parquet", [event_row(1, emitted_at=SAVED, park_name="Alpha", session_id="sess-1")]
    )
    saved = event_row(2, emitted_at=SAVED, save_id="save-2")
    plant_save_written(
        data / "parquet", [plant_paired_save(data / "save_files", saved, "Alpha", SIZE)]
    )
    plant_registry(data / "registry" / "v1", [("park-a", 2000, 1, "company", "", "2026-11-12")])
    plant_archive_copy(
        tmp_path / "archive",
        "park-a",
        "Alpha",
        COPY_ENDED,
        data=b"x" * SIZE,
        modified_at=COPY_MODIFIED,
    )
    return tmp_path


def _run(project: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    code = autopilot_parks.main(["--data-set", "company"], project_dir=project)
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    parsed: dict[str, object] = json.loads(captured.out)
    return parsed


def _listing(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(path): (path.stat().st_mtime_ns, path.stat().st_size)
        for path in sorted(root.rglob("*"))
    }


def _park(**changes: object) -> dict[str, object]:
    park: dict[str, object] = {
        "park_id": "park-a",
        "park_name": "Alpha",
        "park_label": "Alpha (first played Nov 12)",
        "newest_backup": BACKUP,
        "source_problem": None,
        "needs_ready": True,
    }
    return {**park, **changes}


def test_a_proven_source_prints_no_problem_and_writes_nothing(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _listing(project)

    result = _run(project, capsys)

    assert result == {"data_set": "company", "parks": [_park()]}
    assert _listing(project) == before


def test_no_backup_gives_null_backup_and_the_no_backup_refusal(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (project / "archive" / "park-a" / "Alpha-2026-11-12-210000.park").unlink()

    result = _run(project, capsys)

    problem = (
        f"Park park-a has no backup in {project}/archive/park-a/. Play and save it with make "
        "play DATA_SET=company, quit normally, and check that the report prints a Backup: line."
    )
    assert result == {
        "data_set": "company",
        "parks": [_park(newest_backup=None, source_problem=problem)],
    }


def test_an_unproven_newest_backup_is_listed_with_the_refusal(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    copy = project / "archive" / "park-a" / "Alpha-2026-11-12-210000.park"
    copy.write_bytes(b"x" * (SIZE + 1))
    os.utime(copy, (COPY_MODIFIED.timestamp(), COPY_MODIFIED.timestamp()))

    result = _run(project, capsys)

    problem = (
        f"The newest backup of park park-a ({copy}) is not its last recorded save "
        "(Alpha.park, recorded 2026-11-12T20:00:00+00:00); starting from it would drop the "
        "play recorded after it. Play and save once with make play DATA_SET=company so a new "
        "backup is made."
    )
    assert result == {"data_set": "company", "parks": [_park(source_problem=problem)]}


def test_a_practice_park_is_left_out_and_parks_sort_by_id(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plant_registry(
        project / "data" / "company" / "registry" / "v1",
        [
            ("park-c", 2001, 1, "company", "", "2026-11-13"),
            ("park-a", 2000, 1, "company", "", "2026-11-12"),
            ("park-b", 2000, 1, "company", NOTE, "2026-11-13"),
        ],
    )

    parks = _run(project, capsys)["parks"]

    assert isinstance(parks, list)
    assert [park["park_id"] for park in parks] == ["park-a", "park-c"]
    assert parks[1]["park_name"] is None
    assert parks[1]["newest_backup"] is None


def test_needs_ready_turns_false_once_an_autopilot_session_landed(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(project, capsys)["parks"] == [_park(needs_ready=True)]
    plant_label(
        project / "data" / "company" / "registry" / "v1",
        [("sess-1", "park-a", AUTOPILOT, ready_phrase("park-a"), "company", "2026-11-13")],
    )

    assert _run(project, capsys)["parks"] == [_park(needs_ready=False)]


def test_a_non_company_data_set_is_refused(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _listing(project)

    code = autopilot_parks.main(["--data-set", "rehearsal"], project_dir=project)

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert captured.err == (
        "autopilot-parks refused: data-set: only the company data set has autopilot parks\n"
    )
    assert _listing(project) == before


def test_each_park_has_its_label(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plant_registry(
        project / "data" / "company" / "registry" / "v1",
        [
            ("park-a", 2000, 1, "company", "", "2026-11-12"),
            ("park-c", 2001, 1, "company", "", "2026-11-13"),
        ],
    )
    plant_session_start(
        project / "data" / "company" / "parquet",
        [
            event_row(1, emitted_at=SAVED, park_name="Alpha", session_id="sess-1"),
            event_row(
                1,
                emitted_at=datetime(2026, 11, 14, 8, 30, 0, tzinfo=UTC),
                park_name="Gamma",
                session_id="sess-3",
                park_id="park-c",
            ),
        ],
    )

    parks = _run(project, capsys)["parks"]

    assert isinstance(parks, list)
    assert [park["park_label"] for park in parks] == [
        "Alpha (first played Nov 12)",
        "Gamma (first played Nov 14)",
    ]


def test_rows_with_no_game_year_or_instant_do_not_stop_the_list(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    earlier = datetime(2026, 11, 1, 20, 0, 0, tzinfo=UTC)
    plant_session_start(
        project / "data" / "company" / "parquet",
        [
            event_row(1, emitted_at=SAVED, park_name="Alpha", session_id="sess-1"),
            event_row(1, emitted_at=earlier, park_name="Alpha", session_id="sess-2")
            | {"game_year": None},
            {**event_row(1, park_name="Alpha", session_id="sess-3"), "emitted_at": None},
        ],
    )

    assert _run(project, capsys) == {"data_set": "company", "parks": [_park()]}


def test_the_converted_names_are_read_once(
    project: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    reads: list[Path] = []
    real = park_label.park_names

    def counted(parquet_dir: Path) -> dict[str, str | None]:
        reads.append(parquet_dir)
        return real(parquet_dir)

    monkeypatch.setattr(park_label, "park_names", counted)
    monkeypatch.setattr(autopilot_parks, "park_names", counted, raising=False)

    _run(project, capsys)

    assert len(reads) == 1


def test_a_registry_only_park_is_listed_by_its_id(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plant_registry(
        project / "data" / "company" / "registry" / "v1",
        [
            ("park-a", 2000, 1, "company", "", "2026-11-12"),
            ("park-c", 2001, 1, "company", "", "2026-11-13"),
        ],
    )

    parks = _run(project, capsys)["parks"]

    assert isinstance(parks, list)
    assert [(park["park_id"], park["park_name"], park["park_label"]) for park in parks] == [
        ("park-a", "Alpha", "Alpha (first played Nov 12)"),
        ("park-c", None, "park-c"),
    ]


def test_an_undecodable_raw_file_gives_id_labels_and_names_the_file(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    torn = project / "data" / "company" / "raw" / "v1" / "events-2026-11-15.jsonl"
    torn.parent.mkdir(parents=True)
    torn.write_bytes(b'{"session_id": "r1", "park_id": "park-a", "park_name": "Caf\xc3')

    code = autopilot_parks.main(["--data-set", "company"], project_dir=project)

    captured = capsys.readouterr()
    assert code == 0
    parks = json.loads(captured.out)["parks"]
    assert [(park["park_id"], park["park_label"]) for park in parks] == [("park-a", "park-a")]
    assert captured.err == (
        "autopilot-parks: events-2026-11-15.jsonl cannot be decoded; parks are shown by ID.\n"
    )

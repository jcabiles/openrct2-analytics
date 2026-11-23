"""Publish data-set refusal coverage."""

import shutil
from pathlib import Path

import pytest

from openrct2_analytics.ingest.publish import main
from tests.test_publish import candidate_folders, land_sample, project_for

pytestmark = pytest.mark.usefixtures("landing_root")


def test_main_refuses_empty_data_root_before_creating_warehouse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = project_for(tmp_path)
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "")

    result = main(["--data-set", "rehearsal"], project_dir=project)

    output_lines = capsys.readouterr().out.splitlines()
    refusal_lines = [
        line for line in output_lines if line.startswith("publish refused: data-set: ")
    ]
    assert result == 2
    assert output_lines == refusal_lines
    assert len(refusal_lines) == 1
    assert not (project / "warehouse").exists()


def test_main_refuses_aliased_data_folders_before_creating_warehouse(
    tmp_path: Path,
    landing_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (landing_root / "rehearsal").mkdir(parents=True)
    (landing_root / "company").symlink_to(landing_root / "rehearsal", target_is_directory=True)
    project = project_for(tmp_path)

    result = main(["--data-set", "rehearsal"], project_dir=project)

    output_lines = capsys.readouterr().out.splitlines()
    refusal_lines = [
        line for line in output_lines if line.startswith("publish refused: data-set: ")
    ]
    assert result == 2
    assert output_lines == refusal_lines
    assert len(refusal_lines) == 1
    assert not (project / "warehouse").exists()


def test_main_refuses_aliased_registry_folders_before_creating_candidate(
    tmp_path: Path,
    landing_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    land_sample(landing_root, "rehearsal")
    company_registry = landing_root / "company" / "registry"
    company_registry.parent.mkdir(parents=True)
    shutil.move(landing_root / "rehearsal" / "registry", company_registry)
    (landing_root / "rehearsal" / "registry").symlink_to(company_registry, target_is_directory=True)
    project = project_for(tmp_path)

    result = main(["--data-set", "rehearsal"], project_dir=project)

    output_lines = capsys.readouterr().out.splitlines()
    assert result == 2
    assert len(output_lines) == 1
    assert output_lines[0].startswith("publish refused: data-set:")
    assert not (project / "warehouse" / "rehearsal.lock").exists()
    assert candidate_folders(project) == []

"""Deletion of the company site outputs, on temporary project folders only."""

from __future__ import annotations

from pathlib import Path

import pytest

from openrct2_analytics.ingest.delete_data import main
from openrct2_analytics.ingest.site_company_land import INPUT_PREFIX, STAGE_PREFIX, write_stamp
from tests.test_delete_data import ALL, setup, tree


def make_outputs(project: Path, *, stamped: bool) -> None:
    """Write the folders a site build leaves, plus committed sample files that must survive."""
    (project / "local/site-data").mkdir(parents=True)
    (project / "local/site-data/park_month.json").write_text("[1]\n")
    (project / "site/_data").mkdir(parents=True)
    (project / "site/_data/sample.json").write_text("{}\n")
    (project / "site/page.njk").write_text("page\n")
    built = project / "site/_site"
    built.mkdir()
    (built / "index.html").write_text("<html>built</html>\n")
    if stamped:
        write_stamp(built)


def test_preview_lists_both_outputs_and_removes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, _, _, args = setup(tmp_path, monkeypatch)
    make_outputs(project, stamped=True)
    before = tree(tmp_path)
    assert main(args, project_dir=project) == 0
    out = capsys.readouterr().out
    assert f"remove derived: {project.resolve() / 'local/site-data'}" in out
    assert f"remove derived: {project.resolve() / 'site/_site'}" in out
    assert tree(tmp_path) == before


def test_confirmed_deletion_removes_both_and_keeps_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, _, _, args = setup(tmp_path, monkeypatch)
    make_outputs(project, stamped=True)
    kept = {
        name: digest
        for name, digest in tree(project).items()
        if name.startswith("site/") and not name.startswith("site/_site/")
    }
    assert main([*args, *ALL], project_dir=project) == 0
    assert "2 paths removed" in capsys.readouterr().out
    assert not (project / "local/site-data").exists()
    assert not (project / "site/_site").exists()
    assert {k: v for k, v in tree(project).items() if k.startswith("site/")} == kept


def test_unstamped_site_build_is_neither_listed_nor_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, _, _, args = setup(tmp_path, monkeypatch)
    make_outputs(project, stamped=False)
    built = tree(project / "site/_site")
    assert main(args, project_dir=project) == 0
    out = capsys.readouterr().out
    assert "remove derived: " + str(project.resolve() / "site/_site") not in out
    assert main([*args, *ALL], project_dir=project) == 0
    assert tree(project / "site/_site") == built
    assert not (project / "local/site-data").exists()


def test_linked_site_build_is_kept_with_a_note_and_not_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, _, _, args = setup(tmp_path, monkeypatch)
    make_outputs(project, stamped=True)
    target = tmp_path / "elsewhere"
    (project / "site/_site").rename(target)
    (project / "site/_site").symlink_to(target)
    before = tree(target)
    assert main(args, project_dir=project) == 0
    out = capsys.readouterr().out
    assert "remove derived: " + str(project.resolve() / "site/_site") not in out
    assert "site build kept (a symbolic link)" in out
    assert main([*args, *ALL], project_dir=project) == 0
    assert (project / "site/_site").is_symlink()
    assert tree(target) == before


def test_rewritten_stamped_site_build_is_kept_with_a_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, _, _, args = setup(tmp_path, monkeypatch)
    make_outputs(project, stamped=True)
    (project / "site/_site/index.html").write_text("<html>sample build</html>\n")
    built = tree(project / "site/_site")
    assert main(args, project_dir=project) == 0
    out = capsys.readouterr().out
    assert "remove derived: " + str(project.resolve() / "site/_site") not in out
    assert "site build kept (not a company build)" in out
    assert main([*args, *ALL], project_dir=project) == 0
    assert tree(project / "site/_site") == built


def test_linked_local_folder_keeps_site_data_with_a_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, _, _, args = setup(tmp_path, monkeypatch)
    target = tmp_path / "local-target"
    site_data = target / "site-data"
    site_data.mkdir(parents=True)
    (site_data / "park_month.json").write_text("[1]\n")
    before = tree(site_data)
    (project / "local").symlink_to(target)

    assert main(args, project_dir=project) == 0
    out = capsys.readouterr().out
    assert "remove derived: " + str(project.resolve() / "local/site-data") not in out
    assert (
        "site data kept (local/ is a link or resolves outside the project): "
        f"{project / 'local/site-data'}" in out
    )
    assert main([*args, *ALL], project_dir=project) == 0
    assert tree(site_data) == before


def test_linked_site_folder_keeps_stamped_build_with_a_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, _, _, args = setup(tmp_path, monkeypatch)
    target = tmp_path / "site-target"
    built = target / "_site"
    built.mkdir(parents=True)
    (built / "index.html").write_text("<html>built</html>\n")
    write_stamp(built)
    before = tree(built)
    (project / "site").symlink_to(target)

    assert main(args, project_dir=project) == 0
    out = capsys.readouterr().out
    assert "remove derived: " + str(project.resolve() / "site/_site") not in out
    assert (
        "site build kept (site/ is a link or resolves outside the project): "
        f"{project / 'site/_site'}" in out
    )
    assert main([*args, *ALL], project_dir=project) == 0
    assert tree(built) == before


def test_leftover_temporary_folders_are_listed_and_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, _, _, args = setup(tmp_path, monkeypatch)
    make_outputs(project, stamped=True)
    stage = project / "local" / f"{STAGE_PREFIX}4242"
    export_input = project / "local" / f"{INPUT_PREFIX}abcd"
    (stage / "old-site").mkdir(parents=True)
    (stage / "old-site" / "index.html").write_text("company page\n")
    (export_input / "input" / "_data").mkdir(parents=True)
    (export_input / "input" / "_data" / "park_month.json").write_text("[1]\n")
    other = project / "local" / "notes.txt"
    other.write_text("keep\n")

    assert main(args, project_dir=project) == 0
    out = capsys.readouterr().out
    assert f"remove derived: {stage.resolve()}" in out
    assert f"remove derived: {export_input.resolve()}" in out
    assert stage.exists() and export_input.exists()

    assert main([*args, *ALL], project_dir=project) == 0
    assert not stage.exists()
    assert not export_input.exists()
    assert other.read_text() == "keep\n"

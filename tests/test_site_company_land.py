"""Cases 14 to 17 of the company site command: landing by rename, re-check and stamp."""

from __future__ import annotations

import hashlib
import os
import signal
from pathlib import Path

import pytest

from openrct2_analytics.ingest import register_parks, site_company
from openrct2_analytics.ingest import site_company_land as land
from tests.test_site_company import (
    BUILT_WITHOUT_SAMPLE,
    REPO,
    _never_built,
    _no_stage,
    _outputs,
    _reach_landing,
    _warehouse,
    _write_outputs,
    _writes,
)
from tests.test_site_company import _project as _site_project
from tests.test_site_company import _run as _run_site


def _project(tmp_path: Path) -> tuple[Path, Path]:
    """A project folder with a published file, existing outputs and a stage folder."""
    project = tmp_path / "project"
    (project / "warehouse").mkdir(parents=True)
    (project / "warehouse" / "company.duckdb").write_bytes(b"published")
    (project / "site" / "_data").mkdir(parents=True)
    (project / "site" / "_data" / "park_month.json").write_text("sample")
    (project / "local" / "site-data").mkdir(parents=True)
    (project / "local" / "site-data" / "old.json").write_text("old exports")
    (project / "site" / "_site").mkdir()
    (project / "site" / "_site" / "old.html").write_text("old site")
    stage = project / "local" / ".site-company-stage-1"
    (stage / land.EXPORTS_STAGE).mkdir(parents=True)
    (stage / land.EXPORTS_STAGE / "new.json").write_text("new exports")
    (stage / land.SITE_STAGE).mkdir()
    (stage / land.SITE_STAGE / "index.html").write_text("new site")
    return project, stage


def test_landing_renames_the_staged_folders_over_the_old_ones(tmp_path: Path) -> None:
    project, stage = _project(tmp_path)
    exports_inode = (stage / land.EXPORTS_STAGE).stat().st_ino
    site_inode = (stage / land.SITE_STAGE).stat().st_ino

    land.land(project, stage, land.snapshot(project))

    exports, site = project / "local" / "site-data", project / "site" / "_site"
    assert (exports / "new.json").read_text() == "new exports"
    assert (site / "index.html").read_text() == "new site"
    assert not (exports / "old.json").exists()
    assert not (site / "old.html").exists()
    assert exports.stat().st_ino == exports_inode
    assert site.stat().st_ino == site_inode
    assert list(stage.iterdir()) == []


def test_landing_defers_termination_signals_and_restores_the_handlers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, stage = _project(tmp_path)
    numbers = [signal.SIGINT, signal.SIGHUP, signal.SIGTERM]
    before = {number: signal.getsignal(number) for number in numbers}
    observed: list[dict[signal.Signals, object]] = []
    real_replace = os.replace

    def observe_replace(source: Path, target: Path) -> None:
        observed.append({number: signal.getsignal(number) for number in numbers})
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", observe_replace)

    land.land(project, stage, land.snapshot(project))

    assert observed
    assert all(
        handler not in (before[number], signal.SIG_DFL)
        for handlers in observed
        for number, handler in handlers.items()
    )
    assert {number: signal.getsignal(number) for number in numbers} == before


def test_a_link_inside_an_old_output_folder_is_not_followed(tmp_path: Path) -> None:
    project, stage = _project(tmp_path)
    committed = project / "site" / "_data" / "park_month.json"
    linked = project / "local" / "site-data" / "park_month.json"
    linked.symlink_to(committed)

    land.land(project, stage, land.snapshot(project))

    assert committed.read_text() == "sample"
    assert not (project / "local" / "site-data" / "park_month.json").exists()
    assert {path.name for path in (project / "site" / "_data").iterdir()} == {"park_month.json"}


def _assert_nothing_landed(project: Path, stage: Path) -> None:
    assert (project / "local" / "site-data" / "old.json").read_text() == "old exports"
    assert (project / "site" / "_site" / "old.html").read_text() == "old site"
    assert (stage / land.EXPORTS_STAGE / "new.json").is_file()
    assert (stage / land.SITE_STAGE / "index.html").is_file()


def test_a_lock_created_after_the_start_refuses_landing(tmp_path: Path) -> None:
    project, stage = _project(tmp_path)
    start = land.snapshot(project)
    (project / "warehouse" / "company.lock").write_text("held")

    with pytest.raises(land.LandRefused) as refused:
        land.land(project, stage, start)

    assert refused.value.reason == "published-file"
    assert "changed during the run" in refused.value.detail
    _assert_nothing_landed(project, stage)


def test_a_replaced_published_file_refuses_landing(tmp_path: Path) -> None:
    project, stage = _project(tmp_path)
    start = land.snapshot(project)
    published = project / "warehouse" / "company.duckdb"
    replacement = project / "warehouse" / "candidate.duckdb"
    replacement.write_bytes(b"published")
    os.utime(replacement, ns=(start.mtime_ns, start.mtime_ns))
    os.replace(replacement, published)

    assert land.snapshot(project).inode != start.inode
    with pytest.raises(land.LandRefused):
        land.land(project, stage, start)

    _assert_nothing_landed(project, stage)


def test_a_changed_modified_time_refuses_landing(tmp_path: Path) -> None:
    project, stage = _project(tmp_path)
    start = land.snapshot(project)
    published = project / "warehouse" / "company.duckdb"
    later = start.mtime_ns + 5_000_000_000
    os.utime(published, ns=(later, later))

    with pytest.raises(land.LandRefused):
        land.land(project, stage, start)

    _assert_nothing_landed(project, stage)


def test_the_stamp_names_the_source_and_the_page_hash(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<p>company</p>")

    land.write_stamp(site)

    lines = (site / land.BUILD_STAMP).read_text().splitlines()
    assert lines[0] == "built from warehouse/company.duckdb by make site-company"
    digest = lines[1].removeprefix("index.html sha256 ")
    assert len(digest) == 64
    assert digest == hashlib.sha256(b"<p>company</p>").hexdigest()
    assert land.is_company_build(site)


def test_a_rewritten_page_is_no_longer_a_company_build(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<p>company</p>")
    land.write_stamp(site)

    (site / "index.html").write_text("<p>sample build</p>")

    assert not land.is_company_build(site)


def test_a_link_to_a_stamped_folder_is_not_a_company_build(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<p>company</p>")
    land.write_stamp(site)
    link = tmp_path / "link"
    link.symlink_to(site, target_is_directory=True)

    assert land.is_company_build(site)
    assert not land.is_company_build(link)


def test_a_failed_second_rename_puts_the_first_target_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, stage = _project(tmp_path)
    real_replace = os.replace
    site_target = project / "site" / "_site"

    def fail_onto_site(source: Path, target: Path) -> None:
        if Path(target) == site_target and Path(source) == stage / land.SITE_STAGE:
            raise PermissionError("site is read-only")
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_onto_site)

    with pytest.raises(PermissionError):
        land.land(project, stage, land.snapshot(project))

    _assert_nothing_landed(project, stage)


def test_a_published_file_swapped_after_the_start_is_not_landed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _site_project(tmp_path)
    before = _write_outputs(project)
    _reach_landing(monkeypatch)
    real_check = site_company._check_practice_parks

    def check_then_swap(published: Path) -> None:
        """Seam: a publish lands a practice-park file right after the practice check read it."""
        real_check(published)
        candidate = published.with_name("candidate.duckdb")
        _warehouse(candidate, notes=("", register_parks.NOTE))
        os.replace(candidate, published)

    monkeypatch.setattr(site_company, "_check_practice_parks", check_then_swap)

    assert _run_site(project, _writes(BUILT_WITHOUT_SAMPLE)) == 2

    assert "changed during the run" in capsys.readouterr().out
    assert _outputs(project) == before
    _no_stage(project)


def test_an_output_that_is_not_a_folder_is_refused_before_landing(tmp_path: Path) -> None:
    project = _site_project(tmp_path)
    (project / "local").mkdir()
    (project / "local" / "site-data").write_text("a file")

    assert _run_site(project, _never_built) == 2

    assert (project / "local" / "site-data").read_text() == "a file"
    _no_stage(project)


def test_a_signal_during_the_landing_still_exits_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _site_project(tmp_path)
    _write_outputs(project)
    _reach_landing(monkeypatch)
    real_swap = land._swap

    def swap_then_signal(moves: tuple[tuple[Path, Path], ...], stage: Path) -> None:
        """Seam: the signal arrives while landing defers signals, after the renames are done."""
        real_swap(moves, stage)
        os.kill(os.getpid(), signal.SIGINT)

    monkeypatch.setattr(land, "_swap", swap_then_signal)

    assert _run_site(project, _writes(BUILT_WITHOUT_SAMPLE)) == 0

    assert capsys.readouterr().out.strip().splitlines()[-1].startswith("site-company: exported")
    assert (project / "site" / "_site" / "index.html").read_text() == BUILT_WITHOUT_SAMPLE
    assert (project / "local" / "site-data" / "park_month.json").is_file()
    _no_stage(project)


def test_a_signal_right_after_the_landing_returns_exits_130_with_the_outputs_landed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _site_project(tmp_path)
    _write_outputs(project)
    _reach_landing(monkeypatch)
    real_land = land.land

    def land_then_signal(project: Path, stage: Path, start: land.PublishedStamp) -> None:
        """Seam: the signal arrives once landing has restored the handlers, before main returns."""
        real_land(project, stage, start)
        os.kill(os.getpid(), signal.SIGINT)

    monkeypatch.setattr(land, "land", land_then_signal)

    assert _run_site(project, _writes(BUILT_WITHOUT_SAMPLE)) == 130

    assert (project / "site" / "_site" / "index.html").read_text() == BUILT_WITHOUT_SAMPLE
    assert (project / "local" / "site-data" / "park_month.json").is_file()
    _no_stage(project)


def _fail_renames(
    monkeypatch: pytest.MonkeyPatch, failing: set[int], *, signal_on_failure: bool = False
) -> None:
    """Make the numbered `os.replace` calls fail; the landing makes four before it fails."""
    real_replace = os.replace
    calls = []

    def replace(source: Path, target: Path) -> None:
        calls.append(source)
        if len(calls) in failing:
            if signal_on_failure:
                os.kill(os.getpid(), signal.SIGINT)
            raise PermissionError("rename refused")
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", replace)


@pytest.mark.parametrize(("signalled", "code"), [(False, 1), (True, 130)])
def test_a_partial_landing_that_is_put_back_leaves_every_output_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, signalled: bool, code: int
) -> None:
    project = _site_project(tmp_path)
    before = _write_outputs(project)
    _reach_landing(monkeypatch)
    _fail_renames(monkeypatch, {4}, signal_on_failure=signalled)

    assert _run_site(project, _writes(BUILT_WITHOUT_SAMPLE)) == code

    assert _outputs(project) == before
    _no_stage(project)


def test_a_failed_restore_keeps_the_stage_and_deletes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _site_project(tmp_path)
    _write_outputs(project)
    _reach_landing(monkeypatch)
    _fail_renames(monkeypatch, {4, 5})

    assert _run_site(project, _writes(BUILT_WITHOUT_SAMPLE)) == 1

    stage = project.resolve() / "local" / f"{land.STAGE_PREFIX}{os.getpid()}"
    assert str(stage) in capsys.readouterr().out
    assert (stage / "old-site-data" / "earlier.json").read_text() == "earlier exports"
    assert (stage / "old-site" / "index.html").read_text() == "earlier site"


def test_only_the_company_command_writes_the_build_stamp() -> None:
    """The deletion selector is the `index.html` stamp; no sample build source may carry it.

    The only writer is `write_stamp` in site_company_land.py (the `write_text` of the stamp).
    """
    markers = (land.BUILD_STAMP.encode(), land.STAMP_LINE.encode())
    allowed = {REPO / "src" / "openrct2_analytics" / "ingest" / "site_company_land.py"}
    roots = (REPO / "site", REPO / "scripts", REPO / "src")
    for root in roots:
        for path in root.rglob("*"):
            skipped = {"_site", "node_modules", "__pycache__"} & set(path.parts)
            if skipped or not path.is_file() or path in allowed:
                continue
            content = path.read_bytes()
            assert not any(marker in content for marker in markers), path
    assert all(marker in next(iter(allowed)).read_bytes() for marker in markers)


def test_the_allowlist_is_read_from_the_project_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _site_project(tmp_path)
    (project / "site" / "exports.toml").write_text("not [valid toml\n")

    assert _run_site(project, _never_built) == 2

    out = capsys.readouterr().out
    assert "refused: export:" in out
    assert str(project.resolve() / "site" / "exports.toml") in out


def test_a_link_inside_the_site_tree_is_refused(tmp_path: Path) -> None:
    project = _site_project(tmp_path)
    before = _write_outputs(project)
    secret = tmp_path / "secret.txt"
    secret.write_text("outside the project")
    (project / "site" / "assets").mkdir()
    (project / "site" / "assets" / "linked.txt").symlink_to(secret)

    assert _run_site(project, _never_built) == 2

    assert _outputs(project) == before
    _no_stage(project)


def test_every_temporary_folder_is_made_under_local(tmp_path: Path) -> None:
    project = _site_project(tmp_path)
    local = project.resolve() / "local"
    seen: list[Path] = []

    def build(page_input: Path, output: Path) -> int:
        seen.extend([page_input.parent, output.parent])
        return 1

    assert _run_site(project, build) == 1

    stage_and_input = sorted(seen, key=lambda path: path.name)
    assert [path.parent for path in stage_and_input] == [local, local]
    assert stage_and_input[0].name.startswith(land.INPUT_PREFIX)
    assert stage_and_input[1].name.startswith(land.STAGE_PREFIX)
    _no_stage(project)

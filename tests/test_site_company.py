"""Cases 1 to 11 of the company site command, on fixture warehouses in temporary folders."""

from __future__ import annotations

import hashlib
import os
import shutil
import signal
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb
import pytest

from openrct2_analytics.ingest import lock, register_parks, site_company
from openrct2_analytics.ingest import site_company_land as land
from openrct2_analytics.showcase import page_check

REPO = Path(__file__).resolve().parents[1]
BUILT_WITHOUT_SAMPLE = "<html><body><p>Nothing about the sample.</p></body></html>\n"

Build = Callable[[Path, Path], int]


def _exports() -> list[dict[str, Any]]:
    """The allowlist entries of the committed `site/exports.toml`."""
    with (REPO / "site" / "exports.toml").open("rb") as handle:
        entries: list[dict[str, Any]] = tomllib.load(handle)["export"]
    return entries


def _mart_select(columns: list[str]) -> str:
    """A one-row select whose columns are the listed ones, typed by name."""
    values = []
    for column in columns:
        if column == "close_status":
            values.append("'open'")
        elif column.endswith(("_key", "_id", "_name", "_status")):
            values.append("'p1'")
        elif "date" in column:
            values.append("date '2026-03-31'")
        elif column.startswith("is_"):
            values.append("false")
        elif column.endswith("year"):
            values.append("2026")
        elif column.startswith(("parks_", "months_", "statements_")) or column in (
            "ride_days",
            "riders",
        ):
            values.append("4")
        else:
            values.append("4.5::decimal(18,2)")
    return f"select * from (values ({', '.join(values)})) t({', '.join(columns)})"


def _warehouse(
    path: Path,
    *,
    notes: tuple[str, ...] = ("",),
    skip: str | None = None,
    drop_column: tuple[str, str] | None = None,
) -> None:
    connection = duckdb.connect(str(path))
    for schema in ("marts", "intermediate"):
        connection.execute(f"create schema {schema}")
    tables = {
        export["relation"]: _mart_select(
            [c for c in export["columns"] if drop_column != (export["relation"], c)]
        )
        for export in _exports()
    }
    # The sample record's sources: two company parks, five sessions, one of them with a player.
    tables["marts.dim_park"] = (
        "select * from (values ('p1', 1, 'company'), ('p2', 2, 'company')) "
        "t(park_id, park_number, data_set)"
    )
    tables["marts.fct_park_day"] = (
        "select * from (values ('s1'), ('s2'), ('s3'), ('s4'), ('s5')) t(session_id)"
    )
    tables["staging.stg_session_start"] = (
        "select * from (values ('s1', true), ('s2', true), ('s3', true), ('s4', true), "
        "('s5', false)) t(session_id, headless)"
    )
    connection.execute("create schema staging")
    for name, select in tables.items():
        if name != skip:
            connection.execute(f"create table {name} as {select}")
    if skip != "marts.obt_park_year":
        connection.execute(
            "insert into marts.obt_park_year "
            "select * replace ('p2' as park_id, 'p2' as park_year_key) from marts.obt_park_year"
        )
    if skip != "intermediate.int_park_registry__current":
        values = ", ".join(f"('p{index}', '{note}')" for index, note in enumerate(notes, start=1))
        connection.execute(
            "create table intermediate.int_park_registry__current as "
            f"select * from (values {values}) t(park_id, note)"
        )
    connection.close()
    path.chmod(0o444)


def _project(
    tmp_path: Path,
    *,
    copy_repo_site: bool = False,
    notes: tuple[str, ...] = ("",),
    skip: str | None = None,
    drop_column: tuple[str, str] | None = None,
) -> Path:
    """A project folder with a published fixture warehouse and a copy of `site/`."""
    project = tmp_path / "project"
    site = project / "site"
    if copy_repo_site:
        shutil.copytree(REPO / "site", site, ignore=shutil.ignore_patterns("_site"))
    else:
        shutil.copytree(REPO / "site" / "_data", site / "_data")
        shutil.copy(REPO / "site" / "exports.toml", site / "exports.toml")
    (project / "warehouse").mkdir()
    _warehouse(
        project / "warehouse" / "company.duckdb", notes=notes, skip=skip, drop_column=drop_column
    )
    return project


def _tree(root: Path) -> dict[str, str]:
    """Relative path to content hash for every file under ``root`` (links followed)."""
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _write_outputs(project: Path) -> dict[str, dict[str, str]]:
    """Write earlier outputs and return their trees, to compare after a failed run."""
    (project / "local" / "site-data").mkdir(parents=True)
    (project / "local" / "site-data" / "earlier.json").write_text("earlier exports")
    (project / "site" / "_site").mkdir()
    (project / "site" / "_site" / "index.html").write_text("earlier site")
    return _outputs(project)


def _outputs(project: Path) -> dict[str, dict[str, str]]:
    return {
        "exports": _tree(project / "local" / "site-data"),
        "site": _tree(project / "site" / "_site"),
    }


def _run(project: Path, build: Build, *args: str) -> int:
    return site_company.main(
        ["--data-set", "company", *args], project_dir=project, site_build=build
    )


def _writes(page: str) -> Build:
    def build(page_input: Path, output: Path) -> int:
        assert (page_input / "_data" / "park_month.json").is_file()
        output.mkdir()
        (output / "index.html").write_text(page)
        return 0

    return build


def _never_built(page_input: Path, output: Path) -> int:
    raise AssertionError("the site build must not run")


def _no_stage(project: Path) -> None:
    assert list((project / "local").glob(f"{land.STAGE_PREFIX}*")) == []
    assert list((project / "local").glob(f"{land.INPUT_PREFIX}*")) == []


def test_missing_or_rehearsal_data_set_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)

    assert site_company.main([], project_dir=project, site_build=_never_built) == 2
    assert (
        site_company.main(["--data-set", "rehearsal"], project_dir=project, site_build=_never_built)
        == 2
    )

    assert "rehearsal figures never reach the site" in capsys.readouterr().out
    assert not (project / "local").exists()
    assert not (project / "site" / "_site").exists()


def test_no_published_file_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = _project(tmp_path)
    (project / "warehouse" / "company.duckdb").unlink()

    assert _run(project, _never_built) == 2

    assert "make publish DATA_SET=company" in capsys.readouterr().out
    assert not (project / "local").exists()
    assert not (project / "site" / "_site").exists()


def test_a_lock_is_refused(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "warehouse" / "company.lock").write_text("held")

    assert _run(project, _never_built) == 2

    assert not (project / "local").exists()
    assert not (project / "site" / "_site").exists()


def test_a_practice_park_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = _project(tmp_path, notes=("", register_parks.NOTE))
    before = _tree(project / "site" / "_data")

    assert _run(project, _never_built) == 2

    out = capsys.readouterr().out
    assert "sandbox park p2" in out
    assert "make delete-company-data PARK=p2" in out
    assert not (project / "local").exists()
    assert _tree(project / "site" / "_data") == before


def test_a_missing_registry_table_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path, skip="intermediate.int_park_registry__current")

    assert _run(project, _never_built) == 2

    out = capsys.readouterr().out
    assert "refused: registry: intermediate.int_park_registry__current is missing" in out
    assert not (project / "local").exists()


def test_a_linked_exports_folder_is_refused(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "local").mkdir()
    (project / "local" / "site-data").symlink_to(project / "site" / "_data")
    before = _tree(project / "site" / "_data")

    assert _run(project, _never_built) == 2

    assert _tree(project / "site" / "_data") == before
    assert [path.name for path in (project / "local").iterdir()] == ["site-data"]
    assert not (project / "site" / "_site").exists()


def test_a_linked_site_output_is_refused(tmp_path: Path) -> None:
    project = _project(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "keep.html").write_text("kept")
    (project / "site" / "_site").symlink_to(elsewhere)

    assert _run(project, _never_built) == 2

    assert (elsewhere / "keep.html").read_text() == "kept"
    assert list(elsewhere.iterdir()) == [elsewhere / "keep.html"]


def test_a_local_folder_linked_to_site_is_refused(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "local").symlink_to(project / "site", target_is_directory=True)

    assert _run(project, _never_built) == 2

    assert not (project / "site" / "site-data").exists()
    assert sorted(path.name for path in (project / "site").iterdir()) == [
        "_data",
        "exports.toml",
    ]


def test_a_failing_build_exits_1_and_keeps_earlier_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    before = _write_outputs(project)

    assert _run(project, lambda _input, _output: 1) == 1

    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert line.startswith("site-company failed: site-build:")
    assert not line.endswith("Nothing was changed.")
    assert _outputs(project) == before
    _no_stage(project)


def test_a_page_check_failure_exits_1_and_keeps_earlier_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    before = _write_outputs(project)

    assert _run(project, _writes(BUILT_WITHOUT_SAMPLE)) == 1

    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert line.startswith("site-company failed: page-check:")
    assert _outputs(project) == before
    _no_stage(project)


def test_a_missing_allowlisted_mart_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path, skip="marts.obt_company_year")

    assert _run(project, _never_built) == 2

    assert "refused: export:" in capsys.readouterr().out
    assert not (project / "local").exists()
    assert not (project / "site" / "_site").exists()


def test_a_missing_allowlisted_column_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    export = _exports()[0]
    project = _project(tmp_path, drop_column=(export["relation"], export["columns"][-1]))

    assert _run(project, _never_built) == 2

    assert "site-company refused: export:" in capsys.readouterr().out
    assert not (project / "local").exists()
    assert not (project / "site" / "_site").exists()


def test_an_export_refusal_keeps_a_local_folder_it_did_not_create(tmp_path: Path) -> None:
    project = _project(tmp_path, skip="marts.obt_company_year")
    (project / "local").mkdir()

    assert _run(project, _never_built) == 2

    assert list((project / "local").iterdir()) == []


def test_an_interrupt_exits_130_and_leaves_no_folder(tmp_path: Path) -> None:
    project = _project(tmp_path)
    before = _write_outputs(project)

    def interrupted(_input: Path, _output: Path) -> int:
        raise lock.Interrupted("SIGINT")

    assert _run(project, interrupted) == 130
    assert _outputs(project) == before
    _no_stage(project)


def test_a_missing_npm_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    assert _run(project, _never_built) == 2

    assert "make setup" in capsys.readouterr().out
    assert not (project / "local").exists()


def test_the_output_folders_are_ignored_by_git() -> None:
    for path in ("local/site-data/park_month.json", "site/_site/.site-company-build"):
        ignored = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO, check=False)
        assert ignored.returncode == 0, path


def test_a_linked_site_folder_is_refused(tmp_path: Path) -> None:
    project = _project(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    shutil.move(project / "site", elsewhere)
    (project / "site").symlink_to(elsewhere, target_is_directory=True)

    assert _run(project, _never_built) == 2

    assert not (elsewhere / "_site").exists()
    assert not (project / "local").exists()


def test_an_output_folder_reached_through_a_link_is_refused(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "site" / "_site").mkdir()
    through_link = tmp_path / "through-link"
    through_link.symlink_to(project, target_is_directory=True)

    with pytest.raises(site_company._Refused) as refused:
        site_company._check_output_folders(through_link)

    assert refused.value.reason == "output-folders"
    assert "resolves outside" in refused.value.detail


def test_output_folders_on_two_filesystems_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    site = project.resolve() / "site"
    real_stat = Path.stat

    def other_device(self: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        info = real_stat(self, follow_symlinks=follow_symlinks)
        if self != site:
            return info
        fields = list(info)
        fields[2] += 1
        return os.stat_result(fields)

    monkeypatch.setattr(Path, "stat", other_device)

    assert _run(project, _never_built) == 2

    assert "local/ and site/ are on different filesystems" in capsys.readouterr().out
    assert not (project / "local").exists()


def test_the_signal_handlers_are_restored_after_a_run(tmp_path: Path) -> None:
    project = _project(tmp_path)
    names = [name for name in lock.SIGNAL_NAMES if hasattr(signal, name)]
    before = {name: signal.getsignal(getattr(signal, name)) for name in names}

    assert _run(project, _writes(BUILT_WITHOUT_SAMPLE)) == 1

    assert {name: signal.getsignal(getattr(signal, name)) for name in names} == before


def test_a_missing_npm_is_reported_before_a_practice_park(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path, notes=("", register_parks.NOTE))
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    assert _run(project, _never_built) == 2

    assert "refused: tools:" in capsys.readouterr().out


def _reach_landing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the page check so a fixture page reaches the landing step.

    The page check has its own tests; a page that passes it needs the real site build.
    """
    monkeypatch.setattr(page_check, "check_page", lambda _site, _served: None)


def test_a_linked_published_file_is_refused(tmp_path: Path) -> None:
    project = _project(tmp_path)
    real = tmp_path / "real.duckdb"
    (project / "warehouse" / "company.duckdb").rename(real)
    (project / "warehouse" / "company.duckdb").symlink_to(real)

    assert _run(project, _never_built) == 2

    assert not (project / "local").exists()
    assert not (project / "site" / "_site").exists()


def test_a_linked_warehouse_folder_is_refused(tmp_path: Path) -> None:
    project = _project(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    (project / "warehouse").rename(elsewhere)
    (project / "warehouse").symlink_to(elsewhere, target_is_directory=True)

    assert _run(project, _never_built) == 2

    assert not (project / "local").exists()
    assert not (project / "site" / "_site").exists()

"""Archive corruption, partial changes and safe candidate ownership."""

import json
import os
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest import delete_apply, delete_archive
from openrct2_analytics.ingest.delete_plan import Scope
from openrct2_analytics.ingest.publish_errors import PublishFailed, PublishRefused
from openrct2_analytics.ingest.save_files import save_files_dir
from tests.test_delete_plan import event, write


def test_corrupt_copy_stops_before_manifest_or_original_change(tmp_path: Path) -> None:
    data = tmp_path / "data"
    raw = write(data / "company/raw/v1/events-a.jsonl", event("p", "s"))
    plan = delete_apply.build_plan(Scope(), data / "company", tmp_path / "warehouse", None)

    def corrupt(source: Path, target: Path) -> None:
        target.write_bytes(source.read_bytes() + b"corruption")

    with pytest.raises(PublishFailed, match="archive-mismatch"):
        delete_archive.archive(plan, tmp_path / "state", data, tmp_path / "project", copy=corrupt)
    assert raw.read_bytes() == event("p", "s")
    assert not list((tmp_path / "state").rglob("manifest.json"))


def test_archive_bounds_an_unrestricted_id_but_keeps_it_in_the_manifest(tmp_path: Path) -> None:
    data = tmp_path / "data"
    identifier = "a/b" * 100
    raw = write(data / "company/raw/v1/events-a.jsonl", event(identifier, "s"))
    plan = delete_apply.build_plan(
        Scope(park=identifier), raw.parents[2], tmp_path / "warehouse", None
    )
    folder = delete_archive.archive(plan, tmp_path / "state", data, tmp_path / "project")
    assert len(folder.name.encode()) <= 255
    assert "/" not in folder.name
    assert json.loads((folder / "manifest.json").read_text())["scope"]["park"] == identifier


def test_resume_after_second_original_stop(tmp_path: Path) -> None:
    data = tmp_path / "data"
    company = data / "company"
    first = write(company / "raw/v1/events-a.jsonl", event("p", "s"))
    second = write(company / "raw/v1/events-b.jsonl", event("p", "s", 2) + event("q", "kept"))
    derived = write(company / "parquet/v1/a.parquet")
    plan = delete_apply.build_plan(Scope(session="s"), company, tmp_path / "warehouse", None)
    archive = delete_archive.archive(plan, tmp_path / "state", data, tmp_path / "project")
    changes = 0

    def stop(step: str) -> None:
        nonlocal changes
        if step == "changing-original":
            changes += 1
            if changes == 2:
                raise RuntimeError("stop")

    with pytest.raises(RuntimeError):
        delete_apply.apply(plan, company, stop)
    assert not derived.exists()
    assert not first.exists()
    assert second.read_bytes().startswith(event("p", "s", 2))
    resumed = delete_apply.build_plan(Scope(session="s"), company, tmp_path / "warehouse", None)
    delete_apply.apply(resumed, company, lambda _: None)
    assert second.read_bytes() == event("q", "kept")
    assert json.loads((archive / "manifest.json").read_text())["completed"] is False


def test_resume_after_derived_removal_stop(tmp_path: Path) -> None:
    data = tmp_path / "data"
    company = data / "company"
    raw = write(company / "raw/v1/events-a.jsonl", event("p", "s"))
    warehouse = tmp_path / "warehouse"
    published = warehouse / "company.duckdb"
    published.parent.mkdir(parents=True)
    with duckdb.connect(str(published)) as connection:
        connection.execute("CREATE TABLE company AS SELECT 'p' AS park_id")
    plan = delete_apply.build_plan(Scope(session="s"), company, warehouse, None)

    def stop(step: str) -> None:
        if step == "changing-original":
            raise RuntimeError("stop after derived removal")

    with pytest.raises(RuntimeError, match="derived removal"):
        delete_apply.apply(plan, company, stop)
    assert raw.read_bytes() == event("p", "s")
    assert not published.exists()

    resumed = delete_apply.build_plan(Scope(session="s"), company, warehouse, None)
    delete_apply.apply(resumed, company, lambda _: None)
    assert not raw.exists()


def test_symlinked_raw_folder_outside_company_is_refused_untouched(tmp_path: Path) -> None:
    company = tmp_path / "data/company"
    outside = tmp_path / "outside"
    content = event("p", "s") + event("p", "other", 2)
    target = write(outside / "events-a.jsonl", content)
    (company / "raw").mkdir(parents=True)
    (company / "raw/v2").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PublishRefused) as refused:
        delete_apply.build_plan(Scope(session="s"), company, tmp_path / "warehouse", None)
    assert refused.value.reason == "unsafe-path"
    assert target.read_bytes() == content


def test_delete_all_refuses_a_raw_file_resolving_outside_company(tmp_path: Path) -> None:
    company = tmp_path / "data/company"
    content = event("p", "s")
    target = write(tmp_path / "rehearsal/events-2026-10-18.jsonl", content)
    (company / "raw/v1").mkdir(parents=True)
    (company / "raw/v1/events-2026-10-18.jsonl").symlink_to(target)
    with pytest.raises(PublishRefused) as refused:
        delete_apply.build_plan(Scope(), company, tmp_path / "warehouse", None)
    assert refused.value.reason == "unsafe-path"
    assert target.read_bytes() == content


def test_unreadable_registry_copy_keeps_and_lists_the_candidate(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse"
    folder = warehouse / "candidate/run-1"
    write(folder / "landing/registry/v1/park_registry_a.csv", b"\xff")
    paths, notes = delete_apply.derived_paths(tmp_path / "company", warehouse)
    assert folder not in paths
    assert [note for note in notes if str(folder) in note]


def test_rewrite_replaces_through_a_temp_file_even_when_read_only(tmp_path: Path) -> None:
    company = tmp_path / "data/company"
    kept = event("p", "other", 2)
    raw = write(company / "raw/v1/events-a.jsonl", event("p", "s") + kept)
    raw.chmod(0o444)
    plan = delete_apply.build_plan(Scope(session="s"), company, tmp_path / "warehouse", None)
    delete_apply.apply(plan, company, lambda _: None)
    assert raw.read_bytes() == kept
    assert not list(raw.parent.glob("*.delete-tmp"))
    assert os.access(raw.parent, os.W_OK)


def test_delete_all_plan_includes_a_save_file_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(data))
    record = write(
        save_files_dir("company") / "v1" / "save_file_observation_2026-10-18.jsonl",
        b'{"placeholder": true}\n',
    )
    plan = delete_apply.build_plan(Scope(), data / "company", tmp_path / "warehouse", None)
    assert record in [change.path for change in plan.changes]

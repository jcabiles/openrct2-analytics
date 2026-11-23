"""Real-file command tests for archive-before-delete and refusal boundaries."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
from collections.abc import Callable
from datetime import UTC, datetime, tzinfo
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics import state
from openrct2_analytics.ingest.delete_data import main
from tests.test_capture import free_port
from tests.test_delete_plan import event, write


def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path, list[str]]:
    project = tmp_path / "project"
    project.mkdir()
    data, folder = tmp_path / "data", tmp_path / "state"
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(data))
    monkeypatch.setenv("OPENRCT2_STATE_DIR", str(folder))
    monkeypatch.setenv("OPENRCT2_LISTENER_PORT", str(free_port()))
    return (
        project,
        data,
        folder,
        ["--game-check-command", "/usr/bin/false", "--port", str(free_port())],
    )


def tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def tree_of(paths: list[Path]) -> dict[str, str]:
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


ALL = ["--confirm", "delete all company data"]


def test_preview_wrong_phrase_and_unknown_id_are_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    write(data / "company/raw/v1/events-2026-10-17.jsonl", event("a.b", "s"))
    before = tree(tmp_path)
    assert main(args, project_dir=project) == 0
    assert "delete all company data" in capsys.readouterr().out
    assert main([*args, "--confirm", "wrong"], project_dir=project) == 2
    assert main([*args, "--park", "missing"], project_dir=project) == 2
    assert main([*args, "--park", ""], project_dir=project) == 2
    assert "unknown-id" in capsys.readouterr().out
    assert main([*args, "--session", ""], project_dir=project) == 2
    assert "unknown-id" in capsys.readouterr().out
    assert tree(tmp_path) == before


def test_all_archives_unknown_and_malformed_files_but_not_derived(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project, data, folder, args = setup(tmp_path, monkeypatch)
    company = data / "company"
    originals = [
        write(company / name)
        for name in (
            "raw/v1/events-a.jsonl",
            "raw/malformed-a.jsonl",
            "registry/rejected/bad.csv",
            "future/new.bin",
        )
    ]
    hashes = {
        str(p.relative_to(data)): hashlib.sha256(p.read_bytes()).hexdigest() for p in originals
    }
    for name in ("parquet/v1/a.parquet", "parquet/audit/seq.parquet", ".parquet-old/stale"):
        write(company / name)
    warehouse = project / "warehouse"
    published = warehouse / "company.duckdb"
    published.parent.mkdir(parents=True)
    with duckdb.connect(str(published)) as connection:
        connection.execute("CREATE TABLE company AS SELECT 'old' AS park")
    published.chmod(0o444)
    warehouse_derived = [
        write(warehouse / name)
        for name in (
            "company.duckdb.wal",
            "previous/company.duckdb",
            "previous/company.duckdb.wal",
            "previous/company.duckdb.new",
            "previous/company.duckdb.new.wal",
        )
    ]
    kept = [
        write(warehouse / "dev/dev.duckdb"),
        write(data / "capture/record"),
        write(data / "rehearsal/raw/v1/events-a.jsonl"),
    ]
    for name in ("mixed/company.duckdb", "mixed/rehearsal.duckdb", "rehearsal/rehearsal.duckdb"):
        label, file = name.split("/")
        kept.append(write(warehouse / f"candidate/run-{label}/{file}"))
    kept_before = tree_of(kept)
    candidate = warehouse / "candidate/run-company"
    write(candidate / "landing/registry/v1/feed.csv", b"park_id,data_set\na,company\n")
    write(candidate / "landing/v1/a.parquet")
    assert main([*args, "--confirm", "delete all company data"], project_dir=project) == 0
    output = capsys.readouterr().out
    assert tree_of(kept) == kept_before
    assert all(not path.exists() for path in warehouse_derived)
    assert not candidate.exists()
    assert not list(company.rglob("*"))
    manifest = next(folder.rglob("manifest.json"))
    payload = json.loads(manifest.read_text())
    assert payload["completed"]
    assert {item["path"]: item["sha256"] for item in payload["files"]} == hashes
    for name, digest in hashes.items():
        assert hashlib.sha256((manifest.parent / name).read_bytes()).hexdigest() == digest
    for item in payload["files"]:
        copy = manifest.parent / item["path"]
        assert hashlib.sha256(copy.read_bytes()).hexdigest() == item["sha256"]
    assert not published.exists()
    assert "the dev warehouse may still hold company rows" in output
    assert "4 files archived" in output
    assert "candidate kept (not exclusively company)" in output


@pytest.mark.parametrize("port_kind", ["capture", "listener"])
def test_bound_port_refuses_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, port_kind: str
) -> None:
    project, _, _, args = setup(tmp_path, monkeypatch)
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        port = str(held.getsockname()[1])
        if port_kind == "listener":
            monkeypatch.setenv("OPENRCT2_LISTENER_PORT", port)
        else:
            args[-1] = port
        assert main(args, project_dir=project) == 2


@pytest.mark.parametrize("marker_index", [0, 1])
def test_live_all_preserves_originals_and_named_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    marker_index: int,
) -> None:
    project, data, folder, args = setup(tmp_path, monkeypatch)
    raw = write(data / "company/raw/v1/events-a.jsonl", event("p", "s"))
    derived = write(data / "company/parquet/v1/a.parquet")
    published = write(project / "warehouse/company.duckdb")
    previous = write(project / "warehouse/previous/company.duckdb")
    state.write_go_live_marker(folder, data, datetime.now(UTC))
    state.marker_paths(folder, data)[marker_index].unlink()
    assert main([*args, "--park", "p"], project_dir=project) == 2
    assert main([*args, "--confirm", "delete all company data"], project_dir=project) == 0
    assert raw.read_bytes() == event("p", "s")
    assert not derived.exists()
    assert not published.exists()
    assert not previous.exists()
    assert not (folder / "archive").exists()
    output = capsys.readouterr().out
    assert "only rebuildable files removed" in output
    assert "raw captures and registry deliveries kept (live since" in output


@pytest.mark.parametrize("lock_name", ["publish", "landing"])
def test_held_locks_refuse_but_preview_does_not_take_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    lock_name: str,
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    path = (
        project / "warehouse/company.lock"
        if lock_name == "publish"
        else data / "company/parquet.lock"
    )
    write(path, b"existing holder\n")
    assert main(args, project_dir=project) == 0
    assert main([*args, "--confirm", "delete all company data"], project_dir=project) == 2
    assert path.read_bytes() == b"existing holder\n"
    output = capsys.readouterr().out
    assert "existing holder" in output
    assert 'ARCHITECTURE.md "Stale locks"' in output


@pytest.mark.parametrize("step", ["copying", "changing-original", "archived"])
def test_interrupt_and_changed_original_preserve_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    raw = write(data / "company/raw/v1/events-a.jsonl", event("p", "s"))
    derived = write(data / "company/parquet/v1/a.parquet")

    def observe(current: str) -> None:
        if current != step:
            return
        if current == "archived":
            with raw.open("ab") as stream:
                stream.write(event("p", "s", 2))
        else:
            os.kill(os.getpid(), signal.SIGTERM)

    expected = 1 if step == "archived" else 130
    assert (
        main([*args, "--confirm", "delete all company data"], project_dir=project, on_step=observe)
        == expected
    )
    assert raw.read_bytes().startswith(event("p", "s"))
    assert derived.exists() == (step == "copying")
    assert not (project / "warehouse/company.lock").exists()
    assert not (data / "company/parquet.lock").exists()


def test_confirmed_run_holds_both_ports_and_empty_run_creates_lock_folders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    ports = [int(args[-1]), int(os.environ["OPENRCT2_LISTENER_PORT"])]

    def observe(step: str) -> None:
        if step == "locked":
            for port in ports:
                with socket.socket() as probe, pytest.raises(OSError):
                    probe.bind(("127.0.0.1", port))

    assert (
        main([*args, "--confirm", "delete all company data"], project_dir=project, on_step=observe)
        == 0
    )
    assert "no company data" in capsys.readouterr().out
    assert (project / "warehouse").is_dir()
    assert (data / "company").is_dir()


def test_confirmed_run_deduplicates_equal_probe_ports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, _, _, args = setup(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENRCT2_LISTENER_PORT", args[-1])
    assert main([*args, "--confirm", "delete all company data"], project_dir=project) == 0


@pytest.mark.parametrize("setting", ["empty", "project", "data", "ancestor", "warehouse", "user"])
def test_unsafe_state_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setting: str
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    user = tmp_path / "user"
    monkeypatch.setenv("OPENRCT2_USER_DIR", str(user))
    values = {
        "empty": "",
        "project": str(project / "state"),
        "data": str(data / "registry/rejected"),
        "ancestor": str(tmp_path),
        "warehouse": str(project / "warehouse"),
        "user": str(user / "state"),
    }
    monkeypatch.setenv("OPENRCT2_STATE_DIR", values[setting])
    before = tree(tmp_path)
    assert main(args, project_dir=project) == 2
    assert tree(tmp_path) == before


def test_game_check_refuses_and_unknown_id_precedes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, _, _, args = setup(tmp_path, monkeypatch)
    args[1] = "/usr/bin/true"
    assert main(args, project_dir=project) == 2
    assert "capture-running" in capsys.readouterr().out
    assert main([*args, "--park", "unknown"], project_dir=project) == 2
    assert "unknown-id" in capsys.readouterr().out


def test_indeterminate_game_check_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, _, _, args = setup(tmp_path, monkeypatch)
    check = write(tmp_path / "unknown-game", b"#!/bin/sh\nexit 2\n")
    check.chmod(0o755)
    args[1] = str(check)
    assert main(args, project_dir=project) == 2
    assert "capture-running: game check: cannot tell" in capsys.readouterr().out


@pytest.mark.parametrize("alias", ["company", "registry"])
def test_alias_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, alias: str) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    if alias == "company":
        (data / "rehearsal").mkdir(parents=True)
        (data / "company").symlink_to(data / "rehearsal", target_is_directory=True)
    else:
        rehearsal = data / "rehearsal/registry"
        rehearsal.mkdir(parents=True)
        (data / "company").mkdir(parents=True)
        (data / "company/registry").symlink_to(rehearsal, target_is_directory=True)
    assert main(args, project_dir=project) == 2


def test_unsafe_warehouse_symlink_is_refused_without_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, _, _, args = setup(tmp_path, monkeypatch)
    outside = write(tmp_path / "outside.duckdb")
    published = project / "warehouse/company.duckdb"
    published.parent.mkdir(parents=True)
    published.symlink_to(outside)
    before = tree(tmp_path)
    assert main(args, project_dir=project) == 2
    assert tree(tmp_path) == before
    assert "unsafe-path" in capsys.readouterr().out


def test_session_then_park_removes_matching_rows_and_keeps_csv_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, data, folder, args = setup(tmp_path, monkeypatch)
    company = data / "company"
    first = write(company / "raw/v1/events-2026-10-16.jsonl", event("a.b", "first"))
    second = write(
        company / "raw/v1/events-2026-10-17.jsonl", event("a.b", "second") + event("keep", "third")
    )
    sample = next(
        (Path(__file__).resolve().parents[1] / "data/sample/rehearsal/registry/v1").glob(
            "park_registry_*.csv"
        )
    )
    header, row = sample.read_bytes().splitlines(keepends=True)
    row = row.replace(b"rehearsal", b"company")
    original_id = row.split(b",")[0]
    kept = row.replace(original_id, b"keep").replace(
        b"Rehearsal values; not company data.", b'"quoted\nmultiline note"'
    )
    delivery = write(
        company / "registry/v1/park_registry_2026-10-10_01.csv",
        header + row.replace(original_id, b"a.b") + kept,
    )
    assert (
        main(
            [*args, "--session", "first", "--confirm", "delete company session first"],
            project_dir=project,
        )
        == 0
    )
    assert not first.exists()
    assert (
        main([*args, "--park", "a.b", "--confirm", "delete company park a.b"], project_dir=project)
        == 0
    )
    assert second.read_bytes() == event("keep", "third")
    assert delivery.read_bytes() == header + kept
    output = capsys.readouterr().out
    assert "'a.b'" in output
    assert "replay the save" in output
    assert len(list(folder.rglob("manifest.json"))) == 2
    manifests = [json.loads(path.read_text()) for path in folder.rglob("manifest.json")]
    session = next(item for item in manifests if item["scope"]["session"] == "first")
    archived = session["files"][0]
    assert archived["lines_removed_per_session"] == {"first": 1}
    assert archived["action"] == "remove"
    for path in folder.rglob("manifest.json"):
        for item in json.loads(path.read_text())["files"]:
            copy = path.parent / item["path"]
            assert hashlib.sha256(copy.read_bytes()).hexdigest() == item["sha256"]
    assert any(item["action"] == "rewrite" for entry in manifests for item in entry["files"])


def test_registry_only_park_deletes_one_park_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    sample = next(
        (Path(__file__).resolve().parents[1] / "data/sample/rehearsal/registry/v1").glob(
            "park_registry_*.csv"
        )
    )
    header, row = sample.read_bytes().splitlines(keepends=True)
    row = row.replace(b"rehearsal", b"company")
    delivery = write(
        data / "company/registry/v1/park_registry_2026-10-17_01.csv",
        header + row.replace(row.split(b",")[0], b"p"),
    )
    assert (
        main([*args, "--park", "p", "--confirm", "delete company park p"], project_dir=project) == 0
    )
    assert not delivery.exists()


def test_a_deeply_nested_raw_line_does_not_stop_the_park_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fixed_local_zone: Callable[[tzinfo], None],
) -> None:
    fixed_local_zone(UTC)
    project, data, _, args = setup(tmp_path, monkeypatch)
    write(
        data / "company/raw/v1/events-2026-10-17.jsonl",
        event("p", "s") + b"[" * 100_000 + b"\n",
    )

    assert main([*args, "--park", "p"], project_dir=project) == 0

    assert "park p: p (first played Oct 17)\n" in capsys.readouterr().out


def test_relative_data_root_uses_project_dir_from_another_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, _, _, args = setup(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "data")
    write(project / "data/company/raw/v1/events-a.jsonl", event("p", "s"))
    monkeypatch.chdir(tmp_path)
    assert main([*args, "--session", "s"], project_dir=Path("project")) == 0
    assert Path.cwd() == tmp_path

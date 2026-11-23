"""Refusals that keep rehearsal data safe, the capture probe, and the delete-all preview."""

from __future__ import annotations

import contextlib
import json
import socket
from pathlib import Path

import pytest

from openrct2_analytics.ingest import delete_archive
from openrct2_analytics.ingest.delete_data import main
from openrct2_analytics.ingest.delete_plan import Scope, named_plan
from openrct2_analytics.ingest.publish_errors import PublishRefused
from tests.test_delete_data import ALL, setup, tree
from tests.test_delete_plan import event, write


def rehearsal_files(data: Path) -> None:
    write(data / "rehearsal/raw/v1/events-2026-10-01.jsonl", event("r", "rs"))
    write(data / "sample/rehearsal/keep.txt", b"sample\n")
    write(data / "sample/rehearsal/registry/v1/park_registry_2026-10-01_01.csv", b"sample\n")


@pytest.mark.parametrize("target", ["data root", "sample"])
def test_company_link_to_other_data_is_refused_even_as_a_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], target: str
) -> None:
    project, data, folder, args = setup(tmp_path, monkeypatch)
    rehearsal_files(data)
    (data / "company").symlink_to(
        "." if target == "data root" else data / "sample/rehearsal", target_is_directory=True
    )
    before = tree(tmp_path)
    for extra in ([], ALL, ["--park", "r"]):
        assert main([*args, *extra], project_dir=project) == 2
        assert "delete refused: unsafe-path" in capsys.readouterr().out
    assert tree(tmp_path) == before
    assert not folder.exists()
    assert not (project / "warehouse").exists()


@pytest.mark.parametrize("target", ["rehearsal", "project"])
def test_archive_link_into_the_repo_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], target: str
) -> None:
    project, data, folder, args = setup(tmp_path, monkeypatch)
    rehearsal_files(data)
    write(data / "company/raw/v1/events-a.jsonl", event("p", "s"))
    destination = project / "somewhere" if target == "project" else data / "rehearsal"
    destination.mkdir(parents=True, exist_ok=True)
    folder.mkdir()
    (folder / "archive").symlink_to(destination, target_is_directory=True)
    before = tree(tmp_path)
    assert main([*args, *ALL], project_dir=project) == 2
    assert "delete refused: unsafe-path" in capsys.readouterr().out
    assert tree(tmp_path) == before


def test_archive_link_made_after_the_refusal_stage_is_refused_before_any_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, data, folder, args = setup(tmp_path, monkeypatch)
    rehearsal_files(data)
    company = write(data / "company/raw/v1/events-a.jsonl", event("p", "s"))
    before = tree(tmp_path)

    def link_archive(step: str) -> None:
        if step == "locked":
            folder.mkdir(exist_ok=True)
            (folder / "archive").symlink_to(data / "rehearsal", target_is_directory=True)

    assert main([*args, *ALL], project_dir=project, on_step=link_archive) == 2
    assert "delete refused: unsafe-path" in capsys.readouterr().out
    assert tree(tmp_path) == before
    assert company.read_bytes() == event("p", "s")


def test_dated_run_folder_link_is_refused(tmp_path: Path) -> None:
    state, data, project = tmp_path / "state", tmp_path / "data", tmp_path / "project"
    run = state / "archive/20261017T000000Z-all"
    run.parent.mkdir(parents=True)
    run.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(PublishRefused, match="symbolic link"):
        delete_archive.check_destination(state, data, project, run)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.2"])
def test_probe_covers_the_configured_listener_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    project, _, _, args = setup(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENRCT2_LISTENER_HOST", host)
    with socket.socket() as held:
        # 127.0.0.2 is not a loopback address on macOS, so the bind fails there and the probe
        # refuses on the same bind error; on Linux this holds the listener's address for real.
        with contextlib.suppress(OSError):
            held.bind((host, 0))
            held.listen()
        monkeypatch.setenv("OPENRCT2_LISTENER_PORT", str(held.getsockname()[1]))
        assert main([*args, *ALL], project_dir=project) == 2


def test_localhost_listener_host_is_one_bind_with_127_0_0_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, _, _, args = setup(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENRCT2_LISTENER_HOST", "localhost")
    assert main([*args, *ALL], project_dir=project) == 0
    assert "no company data" in capsys.readouterr().out


def test_delete_all_preview_lists_every_file_session_and_unreadable_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, data, folder, args = setup(tmp_path, monkeypatch)
    raw = write(
        data / "company/raw/v1/events-2026-10-17.jsonl",
        event("p", "s1")
        + event("p", "s1", 2)
        + event("q", "s2")
        + b"not json\n"
        + b'{"park_id": "p", "session_id": 7}\n'
        + b"[" * 100000
        + b"\n",
    )
    other = write(data / "company/future/new.bin", b"a\nb\n")
    before = tree(tmp_path)
    assert main(args, project_dir=project) == 0
    output = capsys.readouterr().out
    assert f"archive and remove: {raw}; 6 lines removed of 6" in output
    assert "session 's1': 2 lines removed" in output
    assert "session 's2': 1 lines removed" in output
    assert "3 lines removed without a readable session_id" in output
    assert f"archive and remove: {other}; 2 lines removed of 2" in output
    assert tree(tmp_path) == before
    assert main([*args, *ALL], project_dir=project) == 0
    assert not raw.exists()
    assert not other.exists()
    files = {
        item["path"]: item
        for item in json.loads(next(folder.rglob("manifest.json")).read_text())["files"]
    }
    archived = files["company/raw/v1/events-2026-10-17.jsonl"]
    assert archived["lines_removed_per_session"] == {"s1": 2, "s2": 1}
    assert (archived["unattributed_lines_removed"], archived["unattributed_lines_kept"]) == (3, 0)


def test_candidate_with_only_rehearsal_registry_copies_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    write(data / "company/raw/v1/events-a.jsonl", event("p", "s"))
    candidate = project / "warehouse/candidate/run-killed-rehearsal-publish"
    copy = write(
        candidate / "landing/registry/v1/park_registry_2026-10-01_01.csv",
        b"park_id,data_set\na,rehearsal\n",
    )
    assert main([*args, *ALL], project_dir=project) == 0
    assert copy.exists()
    assert f"candidate kept (not exclusively company): {candidate}" in capsys.readouterr().out


def test_empty_ids_never_match_a_raw_line_with_an_empty_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    raw = write(data / "company/raw/v1/events-a.jsonl", event("", "") + event("p", "s"))
    for flag in ("--session", "--park"):
        assert main([*args, flag, ""], project_dir=project) == 2
        assert "unknown-id" in capsys.readouterr().out
    confirm = [*args, "--session", "", "--confirm", "delete company session "]
    assert main(confirm, project_dir=project) == 2
    assert raw.read_bytes() == event("", "") + event("p", "s")


def test_blank_registry_row_is_kept_not_an_index_error(tmp_path: Path) -> None:
    header = b"park_id,data_set\n"
    delivery = write(
        tmp_path / "registry/v1/park_registry_2026-10-10_01.csv",
        header + b"a,company\n\nb,company\n",
    )
    plan = named_plan(Scope(park="a"), tmp_path)
    assert [change.path for change in plan.changes] == [delivery]
    assert plan.changes[0].kept == header + b"\nb,company\n"


@pytest.mark.parametrize(
    "content", [b'park_id,data_set\n"a"b,company\n', b"park_id,data_set\n\xff,company\n"]
)
def test_unreadable_delivery_is_an_io_failure_not_a_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    content: bytes,
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    write(data / "company/registry/v1/park_registry_2026-10-10_01.csv", content)
    assert main([*args, "--park", "a"], project_dir=project) == 1
    assert "delete failed: io:" in capsys.readouterr().out


def test_relative_data_root_from_another_cwd_refuses_a_company_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, _, _, args = setup(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "data")
    (project / "data/rehearsal").mkdir(parents=True)
    (project / "data/company").symlink_to(project / "data/rehearsal", target_is_directory=True)
    monkeypatch.chdir(tmp_path)
    assert main(args, project_dir=Path("project")) == 2
    assert "unsafe-path" in capsys.readouterr().out
    assert Path.cwd() == tmp_path


def test_relative_data_root_from_another_cwd_still_checks_the_project_landing_folders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, _, _, args = setup(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "data")
    (project / "data/rehearsal/raw").mkdir(parents=True)
    (project / "data/company").mkdir()
    (project / "data/company/raw").symlink_to(
        project / "data/rehearsal/raw", target_is_directory=True
    )
    monkeypatch.chdir(tmp_path)
    assert main(args, project_dir=Path("project")) == 2
    assert "delete refused: data-set: Two landing folders are one folder" in capsys.readouterr().out
    assert Path.cwd() == tmp_path

"""Confirmed-run safety tests: held locks, probe ports, and refusals during a delete run."""

from __future__ import annotations

import json
import os
import re
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openrct2_analytics import state
from openrct2_analytics.ingest.delete_data import main
from tests.test_delete_data import ALL, setup, tree
from tests.test_delete_plan import event, write


def test_locks_hold_their_lines_while_the_plan_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    seen: list[tuple[str, str]] = []

    def observe(step: str) -> None:
        if step == "locked":
            seen.append(
                (
                    (project / "warehouse/company.lock").read_text(),
                    (data / "company/parquet.lock").read_text(),
                )
            )

    assert main([*args, *ALL], project_dir=project, on_step=observe) == 0
    publish, landing = seen[0]
    assert re.match(r"^delete \d+ \d{4}-\d\d-\d\dT", publish)
    assert re.match(r"^pid \d+ started \d{4}-\d\d-\d\dT", landing)


def test_both_locks_held_reports_the_publish_lock_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    write(project / "warehouse/company.lock", b"publish holder\n")
    write(data / "company/parquet.lock", b"landing holder\n")
    assert main([*args, *ALL], project_dir=project) == 2
    output = capsys.readouterr().out
    assert "publish holder" in output
    assert "landing holder" not in output
    assert (data / "company/parquet.lock").read_bytes() == b"landing holder\n"


def test_plan_is_rebuilt_inside_the_locks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, data, folder, args = setup(tmp_path, monkeypatch)
    company = data / "company"
    write(company / "raw/v1/events-2026-10-17.jsonl", event("p", "s"))
    late = company / "raw/v1/events-2026-10-18.jsonl"

    def observe(step: str) -> None:
        if step == "locked":
            write(late, event("p", "late"))

    assert main([*args, *ALL], project_dir=project, on_step=observe) == 0
    manifest = next(folder.rglob("manifest.json"))
    names = {item["path"] for item in json.loads(manifest.read_text())["files"]}
    assert "company/raw/v1/events-2026-10-18.jsonl" in names
    assert (manifest.parent / "company/raw/v1/events-2026-10-18.jsonl").read_bytes() == event(
        "p", "late"
    )
    assert not late.exists()


@pytest.mark.parametrize("target", ["locked", "archived", "changing-original"])
def test_probe_ports_stay_bound_through_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    write(data / "company/raw/v1/events-a.jsonl", event("p", "s"))
    ports = [int(args[-1]), int(os.environ["OPENRCT2_LISTENER_PORT"])]
    checked: list[str] = []

    def observe(step: str) -> None:
        if step == target and target not in checked:
            checked.append(step)
            for port in ports:
                with socket.socket() as probe, pytest.raises(OSError):
                    probe.bind(("127.0.0.1", port))

    assert main([*args, *ALL], project_dir=project, on_step=observe) == 0
    assert checked == [target]


def test_session_delete_refuses_when_an_original_grows_after_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    day = write(data / "company/raw/v1/events-a.jsonl", event("p", "s") + event("p", "keep"))
    original = day.read_bytes()
    appended = event("p", "keep", 2)

    def observe(step: str) -> None:
        if step == "archived":
            with day.open("ab") as stream:
                stream.write(appended)

    command = [*args, "--session", "s", "--confirm", "delete company session s"]
    assert main(command, project_dir=project, on_step=observe) == 1
    assert "changed-during-delete" in capsys.readouterr().out
    assert day.read_bytes() == original + appended


SAMPLE = next(
    (Path(__file__).resolve().parents[1] / "data/sample/rehearsal/registry/v1").glob(
        "park_registry_*.csv"
    )
)


def registry_row(park: str) -> bytes:
    row = SAMPLE.read_bytes().splitlines(keepends=True)[1].replace(b"rehearsal", b"company")
    return row.replace(row.split(b",")[0], park.encode())


def test_park_delete_checks_the_whole_feed_after_the_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, data, folder, args = setup(tmp_path, monkeypatch)
    header = SAMPLE.read_bytes().splitlines(keepends=True)[0]
    feed = data / "company/registry/v1"
    first = write(feed / "park_registry_2026-10-10_01.csv", header + registry_row("a"))
    second = write(feed / "park_registry_2026-10-11_01.csv", header + registry_row("c"))

    def break_the_feed(step: str) -> None:
        if step == "changing-original":
            second.write_bytes(b"park_id,data_set\nc,company\n")

    command = [*args, "--park", "a", "--confirm", "delete company park a"]
    assert main(command, project_dir=project, on_step=break_the_feed) == 1
    assert "delete failed: registry-check" in capsys.readouterr().out
    assert not first.exists()
    assert (folder / "archive").is_dir()


def test_park_delete_refuses_a_failing_delivery_before_archiving_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, data, folder, args = setup(tmp_path, monkeypatch)
    header = SAMPLE.read_bytes().splitlines(keepends=True)[0]
    feed = data / "company/registry/v1"
    write(feed / "park_registry_2026-10-10_01.csv", header + registry_row("a") + registry_row("b"))
    write(feed / "park_registry_2026-10-11_01.csv", b"park_id,data_set\nc,company\n")
    raw = write(data / "company/raw/v1/events-a.jsonl", event("a", "s"))
    before = tree(tmp_path)
    command = [*args, "--park", "a", "--confirm", "delete company park a"]
    assert main(command, project_dir=project) == 2
    output = capsys.readouterr().out
    assert "delete refused: registry-check:" in output
    assert "park_registry_2026-10-11_01.csv" in output
    assert "fix the failing delivery first" in output
    assert not folder.exists()
    assert raw.read_bytes() == event("a", "s")
    assert tree(tmp_path) == before


def test_park_delete_with_a_valid_feed_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    header = SAMPLE.read_bytes().splitlines(keepends=True)[0]
    feed = data / "company/registry/v1"
    write(feed / "park_registry_2026-10-10_01.csv", header + registry_row("a") + registry_row("b"))
    write(feed / "park_registry_2026-10-11_01.csv", header + registry_row("c"))
    assert (
        main([*args, "--park", "a", "--confirm", "delete company park a"], project_dir=project) == 0
    )


def test_delete_all_keeps_and_lists_an_empty_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    write(data / "company/raw/v1/events-a.jsonl", event("p", "s"))
    empty = project / "warehouse/candidate/run-empty"
    empty.mkdir(parents=True)
    assert main([*args, *ALL], project_dir=project) == 0
    assert empty.is_dir()
    assert f"candidate kept (not exclusively company): {empty}" in capsys.readouterr().out


def test_corrupted_archive_copy_stops_before_any_original_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    company = data / "company"
    first = write(company / "raw/v1/events-a.jsonl", event("p", "s"))
    second = write(company / "raw/v1/events-b.jsonl", event("p", "t"))
    derived = write(company / "parquet/v1/a.parquet")

    def observe(step: str) -> None:
        if step == "copying" and first.read_bytes() == event("p", "s"):
            first.write_bytes(b"changed between snapshot and copy\n")

    assert main([*args, *ALL], project_dir=project, on_step=observe) == 1
    assert "archive-mismatch" in capsys.readouterr().out
    assert first.read_bytes() == b"changed between snapshot and copy\n"
    assert second.read_bytes() == event("p", "t")
    assert derived.read_bytes() == b"payload\n"


def test_go_live_marker_written_inside_the_locks_refuses_a_named_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, data, folder, args = setup(tmp_path, monkeypatch)
    raw = write(data / "company/raw/v1/events-a.jsonl", event("p", "s"))

    def observe(step: str) -> None:
        if step == "locked":
            state.write_go_live_marker(folder, data, datetime.now(UTC))

    command = [*args, "--park", "p", "--confirm", "delete company park p"]
    assert main(command, project_dir=project, on_step=observe) == 2
    assert "delete refused: live:" in capsys.readouterr().out
    assert raw.read_bytes() == event("p", "s")


def test_config_error_is_a_data_set_refusal_not_unsafe_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, _, _, args = setup(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENRCT2_LISTENER_PORT", "not-a-port")
    assert main(args, project_dir=project) == 2
    output = capsys.readouterr().out
    assert "data-set" in output
    assert "unsafe-state-dir" not in output


@pytest.mark.parametrize("port", ["0", "65536", "-1"])
def test_port_outside_range_is_an_argument_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], port: str
) -> None:
    project, _, _, args = setup(tmp_path, monkeypatch)
    args[-1] = port
    with pytest.raises(SystemExit) as raised:
        main(args, project_dir=project)
    assert raised.value.code == 2
    assert "--port" in capsys.readouterr().err

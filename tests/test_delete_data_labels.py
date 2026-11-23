"""Delete tests for the play-mode label files: orphan rows, the label check, the ready phrase."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openrct2_analytics.ingest import play_mode_feed
from openrct2_analytics.ingest.delete_apply import derived_paths
from openrct2_analytics.ingest.delete_data import main
from openrct2_analytics.ingest.delete_plan import Scope, named_plan
from tests.test_delete_data import setup, tree
from tests.test_delete_data_run import SAMPLE, registry_row
from tests.test_delete_plan import event, write

HEADER = b"session_id,park_id,play_mode,ready_confirmation,data_set,delivered_on\n"
PHRASE = "p is profitable and its scenario challenge is complete"
FIRST = "session_play_mode_2026-11-13_01.csv"
SECOND = "session_play_mode_2026-11-14_01.csv"


def row(session: str, park: str, mode: str, ready: str, *, delivered: str = "2026-11-13") -> bytes:
    return f"{session},{park},{mode},{ready},company,{delivered}\n".encode()


def labels(data: Path, name: str = FIRST) -> Path:
    return data / "company/registry/v1" / name


def plant_orphan_folder(data: Path) -> Path:
    """One valid company folder: an autopilot session with raw lines and a labeled orphan."""
    write(data / "company/raw/v1/events-2026-11-13.jsonl", event("p", "auto-1"))
    return write(
        labels(data),
        HEADER + row("auto-1", "p", "autopilot", PHRASE) + row("orphan", "p", "managed", ""),
    )


def test_session_removes_an_orphan_label_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    delivery = plant_orphan_folder(data)
    raw = data / "company/raw/v1/events-2026-11-13.jsonl"
    command = [*args, "--session", "orphan", "--confirm", "delete company session orphan"]
    assert main(command, project_dir=project) == 0
    assert delivery.read_bytes() == HEADER + row("auto-1", "p", "autopilot", PHRASE)
    assert raw.read_bytes() == event("p", "auto-1")


def test_session_rewrite_is_followed_by_the_label_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    plant_orphan_folder(data)

    def break_the_feed(step: str) -> None:
        if step == "changing-original":
            write(
                labels(data, SECOND), HEADER + row("late", "p", "robot", "", delivered="2026-11-14")
            )

    command = [*args, "--session", "orphan", "--confirm", "delete company session orphan"]
    assert main(command, project_dir=project, on_step=break_the_feed) == 1
    assert "delete failed: label-check" in capsys.readouterr().out


def test_header_only_label_file_does_not_hide_a_company_candidate(tmp_path: Path) -> None:
    company, warehouse = tmp_path / "company", tmp_path / "warehouse"
    candidate = warehouse / "candidate/run-one"
    write(
        candidate / "landing/registry/v1/park_registry_2026-11-13_01.csv",
        b"park_id,data_set\np,company\n",
    )
    write(candidate / "landing/registry/v1" / FIRST, HEADER)
    write(candidate / "landing/v1/a.parquet")
    paths, notes = derived_paths(company, warehouse)
    assert candidate in paths
    assert notes == []


def stamped(session: str, stamp: str) -> bytes:
    line = json.loads(event("p", session))
    line["received_at"] = stamp
    return (json.dumps(line) + "\n").encode()


def plant_one_date(company: Path) -> None:
    """A managed raw file and an autopilot raw file on one date; autopilot received later."""
    write(company / "raw/v1/events-2026-11-13.jsonl", stamped("managed-1", "2026-11-13T01:00:00Z"))
    write(
        company / "raw/v1/events-2026-11-13-autopilot-run1.jsonl",
        stamped("auto-1", "2026-11-13T09:00:00Z"),
    )


def test_latest_note_names_the_managed_session_when_autopilot_came_later(tmp_path: Path) -> None:
    plant_one_date(tmp_path / "company")
    plan = named_plan(Scope(session="managed-1"), tmp_path / "company")
    assert [n for n in plan.notes if "is not its park's latest" in n] == [
        "session 'managed-1' is not its park's latest: missing days of a closed month "
        "fail the missing-day test in make pipeline by design; later sessions that "
        "loaded its saves may become orphans; replay the save"
    ]


def test_latest_note_is_absent_for_the_autopilot_session_that_came_later(tmp_path: Path) -> None:
    plant_one_date(tmp_path / "company")
    plan = named_plan(Scope(session="auto-1"), tmp_path / "company")
    assert [n for n in plan.notes if "is not its park's latest" in n] == []


def plant_two_autopilot_folder(data: Path) -> dict[str, Path]:
    """Two autopilot sessions of park p, the first holding the ready phrase, and one of park q."""
    raw = write(
        data / "company/raw/v1/events-2026-11-13.jsonl",
        event("p", "auto-1") + event("p", "auto-2") + event("q", "other"),
    )
    delivery = write(
        labels(data),
        HEADER
        + row("auto-1", "p", "autopilot", PHRASE)
        + row("auto-2", "p", "autopilot", "")
        + row("other", "q", "managed", ""),
    )
    return {"raw": raw, "labels": delivery}


def test_ready_phrase_session_is_refused_while_another_autopilot_session_remains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    plant_two_autopilot_folder(data)
    before = tree(tmp_path)
    listing = sorted(str(path) for path in tmp_path.rglob("*"))
    command = [*args, "--session", "auto-1", "--confirm", "delete company session auto-1"]
    assert main(command, project_dir=project) == 2
    assert capsys.readouterr().out.splitlines()[-1] == (
        "delete refused: ready-phrase-row: session auto-1 holds the ready phrase of park p; "
        "delete the other autopilot sessions of that park first, one at a time with "
        "SESSION=<id> (auto-2), or the whole park with PARK=p. "
        "Nothing was changed."
    )
    assert sorted(str(path) for path in tmp_path.rglob("*")) == listing
    assert tree(tmp_path) == before


def test_orphan_with_the_phrase_is_deleted_beside_a_landed_retry_with_the_phrase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    write(data / "company/raw/v1/events-2026-11-13.jsonl", event("p", "landed"))
    orphan = write(labels(data), HEADER + row("orphan", "p", "autopilot", PHRASE))
    landed = write(
        labels(data, "session_play_mode_2026-11-13_02.csv"),
        HEADER + row("landed", "p", "autopilot", PHRASE),
    )
    command = [*args, "--session", "orphan", "--confirm", "delete company session orphan"]
    assert main(command, project_dir=project) == 0
    assert not orphan.exists() or orphan.read_bytes() == HEADER
    assert landed.read_bytes() == HEADER + row("landed", "p", "autopilot", PHRASE)
    assert play_mode_feed.check_feed(data / "company/registry") == []


def test_ready_phrase_session_is_deleted_when_no_other_autopilot_session_remains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    write(data / "company/raw/v1/events-2026-11-13.jsonl", event("p", "auto-1"))
    delivery = write(
        labels(data),
        HEADER + row("auto-1", "p", "autopilot", PHRASE) + row("kept", "p", "managed", ""),
    )
    command = [*args, "--session", "auto-1", "--confirm", "delete company session auto-1"]
    assert main(command, project_dir=project) == 0
    assert delivery.read_bytes() == HEADER + row("kept", "p", "managed", "")


def test_park_removes_every_label_row_of_the_park(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    files = plant_two_autopilot_folder(data)
    assert (
        main([*args, "--park", "p", "--confirm", "delete company park p"], project_dir=project) == 0
    )
    assert files["labels"].read_bytes() == HEADER + row("other", "q", "managed", "")
    assert files["raw"].read_bytes() == event("q", "other")


BAD_LABELS = HEADER + row("late", "q", "robot", "", delivered="2026-11-14")
LABEL_REFUSAL = (
    "delete refused: label-check: test overall result: failed; test play_mode is managed or "
    "autopilot: failed (Actual custom_sql(session_play_mode) was 1, expected = 0); "
    "fix the failing delivery first. Nothing was changed."
)
YEAR_MISSING = (
    "test Check that field company_start_year has no missing values: failed "
    "(Actual missing_count(company_start_year) was 1, expected = 0)"
)
REGISTRY_REFUSAL = (
    "delete refused: registry-check: test overall result: failed; "
    f"{YEAR_MISSING}; park_registry_2026-11-13_01.csv: test overall result: failed; "
    f"park_registry_2026-11-13_01.csv: {YEAR_MISSING}; "
    "fix the failing delivery first. Nothing was changed."
)


def plant_registry(data: Path, year: bytes = b"2000") -> Path:
    """A one-park company registry delivery for park p, valid unless `year` is changed."""
    header = SAMPLE.read_bytes().splitlines(keepends=True)[0]
    line = registry_row("p").replace(b",2000,", b"," + year + b",", 1)
    return write(data / "company/registry/v1/park_registry_2026-11-13_01.csv", header + line)


def assert_refused_unchanged(
    tmp_path: Path,
    command: list[str],
    *,
    paths: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    expected: str,
) -> None:
    """Refuse with `expected` as the last line: no archive, the company files untouched."""
    project, folder = paths
    before = tree(tmp_path)
    listing = sorted(str(path) for path in (tmp_path / "data").rglob("*"))
    assert main(command, project_dir=project) == 2
    assert capsys.readouterr().out.splitlines()[-1] == expected
    assert not folder.exists()
    assert sorted(str(path) for path in (tmp_path / "data").rglob("*")) == listing
    assert tree(tmp_path) == before


def test_session_delete_with_a_valid_registry_and_labels_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    delivery = plant_orphan_folder(data)
    plant_registry(data)
    command = [*args, "--session", "orphan", "--confirm", "delete company session orphan"]
    assert main(command, project_dir=project) == 0
    assert delivery.read_bytes() == HEADER + row("auto-1", "p", "autopilot", PHRASE)


def test_session_delete_refuses_a_bad_label_row_before_any_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, data, folder, args = setup(tmp_path, monkeypatch)
    plant_orphan_folder(data)
    plant_registry(data)
    write(labels(data, SECOND), BAD_LABELS)
    command = [*args, "--session", "orphan", "--confirm", "delete company session orphan"]
    assert_refused_unchanged(
        tmp_path, command, paths=(project, folder), capsys=capsys, expected=LABEL_REFUSAL
    )


def test_session_delete_refuses_a_bad_registry_row_before_any_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, data, folder, args = setup(tmp_path, monkeypatch)
    plant_orphan_folder(data)
    plant_registry(data, b"notayear")
    command = [*args, "--session", "orphan", "--confirm", "delete company session orphan"]
    assert_refused_unchanged(
        tmp_path, command, paths=(project, folder), capsys=capsys, expected=REGISTRY_REFUSAL
    )


def test_park_delete_refuses_a_bad_label_row_before_any_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project, data, folder, args = setup(tmp_path, monkeypatch)
    plant_orphan_folder(data)
    plant_registry(data)
    write(labels(data, SECOND), BAD_LABELS)
    command = [*args, "--park", "p", "--confirm", "delete company park p"]
    assert_refused_unchanged(
        tmp_path, command, paths=(project, folder), capsys=capsys, expected=LABEL_REFUSAL
    )

"""Tests for the save-file record folder, reader and contract check.

Records come from the real watcher over temp folders; bad rows are written by hand. Every case runs
the real contract check.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from openrct2_analytics.config import ConfigError
from openrct2_analytics.ingest import registry_feed, save_files
from openrct2_analytics.ingest.contracts import CONTRACTS_DIR, load_reference_fields
from openrct2_analytics.ingest.save_watch import SaveWatcher, watch_folders

STARTED = datetime(2026, 10, 19, 8, 0, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 19, 8, 30, 0, tzinfo=UTC)
GOOD = {
    "run_started_at": "2026-10-19T08:00:00.000Z",
    "observation": "modified",
    "file_name": "Park One-main",
    "folder_kind": "save",
    "modified_at": "2026-10-19T08:10:00.123Z",
    "size_bytes": 2048,
    "observed_at": "2026-10-19T08:10:01.000Z",
}
RULE_BREAKS: dict[str, dict[str, object]] = {
    "observation outside the three": {"observation": "deleted"},
    "folder_kind outside the four": {"folder_kind": "backup"},
    "negative size_bytes": {"size_bytes": -1},
    "slash in file_name": {"file_name": "sub/Park One"},
    "empty file_name": {"file_name": ""},
}
RULE_LINE = {
    "observation outside the three": "observation is start, created or modified",
    "folder_kind outside the four": "folder_kind is save, autosave, parent or remembered",
    "negative size_bytes": "size_bytes is at least 0",
    "slash in file_name": "file_name is not empty and holds no slash",
    "empty file_name": "file_name is not empty and holds no slash",
}
UNREADABLE = {
    "torn": '{"run_started_at": "2026-10-19T08:00:00.000Z", "observ',
    "missing field": json.dumps({k: v for k, v in GOOD.items() if k != "size_bytes"}),
}


def line(**changes: object) -> str:
    return json.dumps({**GOOD, **changes})


def record_file(folder: Path, name: str, lines: list[str], *, modified: datetime) -> Path:
    path = folder / "v1" / f"save_file_observation_{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{text}\n" for text in lines), encoding="utf-8")
    os.utime(path, (modified.timestamp(), modified.timestamp()))
    return path


@pytest.fixture(autouse=True)
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project folder of its own, so relative landing paths never touch the real repository."""
    folder = tmp_path / "project"
    folder.mkdir()
    monkeypatch.setattr(registry_feed, "PROJECT_DIR", folder)
    monkeypatch.delenv("OPENRCT2_DATA_DIR", raising=False)
    return folder


def test_fields_match_the_record_contract() -> None:
    fields = load_reference_fields(CONTRACTS_DIR / "reference")["save_file_observation"]
    assert [(f.name, f.logical, f.required) for f in fields] == [
        ("run_started_at", "timestamp", True),
        ("observation", "string", True),
        ("file_name", "string", True),
        ("folder_kind", "string", True),
        ("modified_at", "timestamp", True),
        ("size_bytes", "integer", True),
        ("observed_at", "timestamp", True),
    ]


def test_watcher_records_pass_the_check_and_read_back_in_utc(tmp_path: Path) -> None:
    user = tmp_path / "user"
    (user / "save" / "autosave").mkdir(parents=True)
    (user / "Park One-main.park").write_bytes(b"x" * 10)
    lines: list[str] = []
    landing = tmp_path / "root" / "save_files"
    watcher = SaveWatcher(
        watch_folders(user), landing, STARTED, 0.01, say=lines.append, clock=lambda: NOW
    )
    watcher.scan()
    (user / "save" / "Park One-main.park").write_bytes(b"y" * 20)
    (user / "save" / "autosave" / "auto.park").write_bytes(b"z" * 30)
    watcher.scan()
    (user / "save" / "Park One-main.park").write_bytes(b"y" * 40)
    os.utime(user / "save" / "Park One-main.park", (1.0e9, 1.0e9))
    watcher.scan()

    assert save_files.check_folder(landing) == []
    assert save_files.main(["--data-root", str(tmp_path / "root")]) == 0
    records, unreadable = save_files.read_records(landing, STARTED)
    assert unreadable == []
    assert sorted(r.observation for r in records) == ["created", "created", "modified", "start"]
    for record in records:
        for moment in (record.run_started_at, record.modified_at, record.observed_at):
            assert moment.utcoffset() == timedelta(0)
    assert lines == []


@pytest.mark.parametrize("rule", RULE_BREAKS)
def test_rule_break_fails_with_a_line_naming_the_rule(tmp_path: Path, rule: str) -> None:
    record_file(tmp_path, "2026-10-19", [line(), line(**RULE_BREAKS[rule])], modified=NOW)
    problems = save_files.check_folder(tmp_path)
    assert any(RULE_LINE[rule] in problem for problem in problems), problems


def test_rule_good_row_of_every_kind_passes(tmp_path: Path) -> None:
    record_file(
        tmp_path,
        "2026-10-19",
        [
            line(observation="start", file_name="Park One-main"),
            line(observation="created", folder_kind="autosave", size_bytes=0),
            line(folder_kind="parent"),
        ],
        modified=NOW,
    )
    assert save_files.check_folder(tmp_path) == []


def test_remembered_folder_kind_passes_and_backup_is_rejected(tmp_path: Path) -> None:
    record_file(tmp_path, "2026-10-19", [line(folder_kind="remembered")], modified=NOW)
    assert save_files.check_folder(tmp_path) == []
    record_file(tmp_path, "2026-10-20", [line(folder_kind="backup")], modified=NOW)
    problems = save_files.check_folder(tmp_path)
    rule_line = RULE_LINE["folder_kind outside the four"]
    assert any(rule_line in problem for problem in problems), problems


@pytest.mark.parametrize(
    "change", [{"size_bytes": 1.5}, {"size_bytes": "12"}, {"modified_at": "yesterday"}]
)
def test_rule_bad_cell_shape_fails(tmp_path: Path, change: dict[str, object]) -> None:
    path = record_file(tmp_path, "2026-10-19", [line(**change)], modified=NOW)
    assert save_files.check_file(path)
    assert save_files.check_folder(tmp_path)


def test_over_range_size_fails_as_one_named_rule(tmp_path: Path) -> None:
    # The reader accepts any JSON integer; the contract sees a NULL, not a database error.
    path = record_file(tmp_path, "2026-10-19", [line(size_bytes=10**23)], modified=NOW)
    problems = save_files.check_file(path)
    assert problems == [
        "test overall result: failed",
        "test Check that field size_bytes has no missing values: failed"
        " (Actual missing_count(size_bytes) was 1, expected = 0)",
    ]
    assert save_files.main(["--file", str(path)]) == 1


def test_torn_line_in_one_file_does_not_hide_a_rule_break_in_another(tmp_path: Path) -> None:
    record_file(tmp_path, "2026-10-18", [line(), UNREADABLE["torn"]], modified=NOW)
    record_file(tmp_path, "2026-10-19", [line(size_bytes=-1)], modified=NOW)
    problems = save_files.check_folder(tmp_path)
    rule = RULE_LINE["negative size_bytes"]
    assert any(rule in p and not p.startswith("save_file_observation_") for p in problems), problems
    assert any(
        p.startswith("save_file_observation_2026-10-19.jsonl: ") and rule in p for p in problems
    )
    assert not any("Malformed JSON" in p for p in problems), problems
    assert any("save_file_observation_2026-10-18.jsonl: line 2" in p for p in problems)


def test_legal_save_names_pass_the_check(tmp_path: Path) -> None:
    user = tmp_path / "user"
    (user / "save").mkdir(parents=True)
    landing = tmp_path / "root" / "save_files"
    watcher = SaveWatcher(
        watch_folders(user), landing, STARTED, 0.01, say=lambda _: None, clock=lambda: NOW
    )
    watcher.scan()
    (user / "save" / "Back\\slash.park").write_bytes(b"x")
    (user / "save" / "Twice.park.park").write_bytes(b"x")
    watcher.scan()
    records, unreadable = save_files.read_records(landing, STARTED)
    assert unreadable == []
    assert sorted(r.file_name for r in records) == ["Back\\slash", "Twice.park"]
    assert save_files.main(["--data-root", str(tmp_path / "root")]) == 0


def test_absent_and_empty_folders_pass(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert save_files.main(["--data-root", str(tmp_path)]) == 0
    (tmp_path / "save_files" / "v1").mkdir(parents=True)
    assert save_files.main(["--data-root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.count(f"No save-file records in {tmp_path / 'save_files'}.") == 2


def test_absent_data_set_folder_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path))
    assert save_files.main(["--data-set", "rehearsal"]) == 0
    assert "No save-file records in" in capsys.readouterr().out


def test_cli_file_checks_one_file_alone(tmp_path: Path) -> None:
    good = record_file(tmp_path, "2026-10-18", [line()], modified=NOW)
    bad = record_file(tmp_path, "2026-10-19", [line(size_bytes=-5)], modified=NOW)
    assert save_files.main(["--file", str(good)]) == 0
    assert save_files.main(["--file", str(bad)]) == 1
    assert save_files.main(["--file", str(tmp_path / "missing.jsonl")]) == 2


def test_reader_attributes_unreadable_lines_by_file_and_reads_the_rest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = [line(), UNREADABLE["torn"], line(observation="created"), UNREADABLE["missing field"]]
    folder = tmp_path / "root" / "save_files"
    record_file(folder, "2026-10-18", lines, modified=STARTED - timedelta(hours=1))
    record_file(folder, "2026-10-19", lines, modified=STARTED + timedelta(hours=1))

    records, unreadable = save_files.read_records(folder, STARTED)

    assert len(records) == 4
    assert [(u.record_file, u.line_number, u.this_run) for u in unreadable] == [
        ("save_file_observation_2026-10-18.jsonl", 2, False),
        ("save_file_observation_2026-10-18.jsonl", 4, False),
        ("save_file_observation_2026-10-19.jsonl", 2, True),
        ("save_file_observation_2026-10-19.jsonl", 4, True),
    ]
    assert save_files.main(["--data-root", str(tmp_path / "root")]) == 1
    out = capsys.readouterr().out
    assert "save_file_observation_2026-10-18.jsonl: line 2" in out
    assert "save_file_observation_2026-10-19.jsonl: line 4" in out


@pytest.mark.parametrize(
    "change",
    [
        {"size_bytes": True},
        {"size_bytes": "12"},
        {"size_bytes": 1.5},
        {"observation": 7},
        {"modified_at": "2026-13-45T08:10:00.123Z"},
        {"modified_at": "2026-10-19T08:10:00Z"},
        {"observed_at": None},
    ],
)
def test_reader_rejects_wrong_shapes(tmp_path: Path, change: dict[str, object]) -> None:
    record_file(tmp_path, "2026-10-19", [line(**change), "[]", ""], modified=NOW)
    records, unreadable = save_files.read_records(tmp_path, STARTED)
    assert records == []
    assert [u.line_number for u in unreadable] == [1, 2, 3]


def test_reader_file_modified_exactly_at_started_is_this_runs(tmp_path: Path) -> None:
    record_file(tmp_path, "2026-10-19", [UNREADABLE["torn"]], modified=STARTED)
    _, unreadable = save_files.read_records(tmp_path, STARTED)
    assert [u.this_run for u in unreadable] == [True]


def test_save_written_reader_returns_aware_utc_rows_and_none_when_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The reader's own connection runs in a zone that is not UTC, whatever the machine's zone is.
    def zoned_connect() -> duckdb.DuckDBPyConnection:
        connection = duckdb.connect()
        connection.execute("SET TimeZone = 'America/Los_Angeles'")
        return connection

    monkeypatch.setattr(save_files, "duckdb", SimpleNamespace(connect=zoned_connect))
    assert save_files.read_save_written(tmp_path) == []
    (tmp_path / "v1").mkdir()
    connection = duckdb.connect()
    connection.execute("SET TimeZone = 'America/Los_Angeles'")
    connection.execute(
        "COPY (SELECT 'e1' AS event_id, 's1' AS save_id, 'p1' AS park_id, 'ss1' AS session_id,"
        " TIMESTAMPTZ '2026-10-19 08:00:00.5+00' AS emitted_at,"
        " TIMESTAMPTZ '2026-10-19 08:00:01+00' AS received_at,"
        " 'events-2026-10-19.jsonl' AS _raw_file, 4::BIGINT AS _raw_line)"
        f" TO '{(tmp_path / 'v1' / 'save_written.parquet').as_posix()}' (FORMAT PARQUET)"
    )
    connection.close()
    (row,) = save_files.read_save_written(tmp_path)
    assert (row.event_id, row.save_id, row.park_id, row.session_id) == ("e1", "s1", "p1", "ss1")
    assert row.emitted_at == datetime(2026, 10, 19, 8, 0, 0, 500_000, tzinfo=UTC)
    assert row.received_at == datetime(2026, 10, 19, 8, 0, 1, tzinfo=UTC)
    assert row.emitted_at.utcoffset() == timedelta(0)
    assert (row.raw_file, row.raw_line) == ("events-2026-10-19.jsonl", 4)


def test_folders_follow_the_landing_folders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert save_files.save_files_dir("rehearsal") == Path("data/rehearsal/save_files")
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path))
    assert save_files.save_files_dir("company") == tmp_path / "company" / "save_files"


ALIAS_TARGETS = [
    "rehearsal/raw",
    "rehearsal/parquet",
    "company/raw",
    "company/parquet",
    "rehearsal/registry",
    "rehearsal/registry/v1",
    "company/registry",
    "company/registry/v1",
    "company/save_files",
    "company/save_files/v1",
]


@pytest.mark.parametrize("target", ALIAS_TARGETS)
def test_alias_save_files_linked_to_another_landing_folder_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path))
    for name in ALIAS_TARGETS:
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    (tmp_path / "rehearsal" / "save_files").symlink_to(tmp_path / target)
    with pytest.raises(ConfigError):
        save_files.save_files_dir("rehearsal")
    assert save_files.main(["--data-set", "rehearsal"]) == 2


@pytest.mark.parametrize("linked", ["save_files", "save_files/v1"])
def test_link_leading_outside_the_data_set_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, linked: str
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "data" / "rehearsal" / linked
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)
    with pytest.raises(ConfigError, match="outside the data set"):
        save_files.save_files_dir("rehearsal")
    assert save_files.main(["--data-set", "rehearsal"]) == 2


def test_relocated_data_folder_is_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "data").symlink_to(real)
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    assert save_files.save_files_dir("rehearsal") == tmp_path / "data" / "rehearsal" / "save_files"


def test_relative_data_dir_resolves_against_the_project_folder(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "data")
    (project / "data" / "rehearsal" / "raw").mkdir(parents=True)
    (project / "data" / "rehearsal" / "save_files").symlink_to(
        project / "data" / "rehearsal" / "raw"
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    with pytest.raises(ConfigError):
        save_files.save_files_dir("rehearsal")


def test_a_start_row_of_any_save_name_passes(tmp_path: Path) -> None:
    lines = [line(observation="start", file_name="Park One")]
    record_file(tmp_path, "2026-10-19", lines, modified=NOW)
    assert save_files.check_folder(tmp_path) == []

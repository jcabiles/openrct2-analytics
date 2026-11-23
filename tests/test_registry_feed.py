"""Tests for the park registry feed check: probe, paths, alias guard, CLI and landing rules.

Every case builds CSV files in a temporary folder and runs the real contract check over them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openrct2_analytics.config import ConfigError
from openrct2_analytics.ingest import registry_feed
from openrct2_analytics.ingest.contracts import CONTRACTS_DIR, load_reference_fields

HEADER = "park_id,company_start_year,game_year_origin,data_set,note,delivered_on"
GOOD_ROWS = [
    "parkone,2020,1,rehearsal,first delivery,2026-10-09",
    "parktwo,2021,3,rehearsal,,2026-10-09",
]
FAULTS = {
    "text in company_start_year": [
        "parkone,2020,1,rehearsal,,2026-10-09",
        "parktwo,later,1,rehearsal,,2026-10-09",
    ],
    "empty delivered_on": ["parkone,2020,1,rehearsal,,2026-10-09", "parktwo,2021,1,rehearsal,,"],
    "empty park_id": ["parkone,2020,1,rehearsal,,2026-10-09", ",2021,1,rehearsal,,2026-10-09"],
    "game_year_origin of 0": [
        "parkone,2020,1,rehearsal,,2026-10-09",
        "parktwo,2021,0,rehearsal,,2026-10-09",
    ],
    "game_year_origin of 1.5": [
        "parkone,2020,1,rehearsal,,2026-10-09",
        "parktwo,2021,1.5,rehearsal,,2026-10-09",
    ],
    "company_start_year of 2020.5": [
        "parkone,2020,1,rehearsal,,2026-10-09",
        "parktwo,2020.5,1,rehearsal,,2026-10-09",
    ],
    "company_start_year of 1e3": [
        "parkone,2020,1,rehearsal,,2026-10-09",
        "parktwo,1e3,1,rehearsal,,2026-10-09",
    ],
    "data_set outside the two": [
        "parkone,2020,1,rehearsal,,2026-10-09",
        "parktwo,2021,1,staging,,2026-10-09",
    ],
}
MISSING_COLUMN = [
    "park_id,company_start_year,data_set,note,delivered_on",
    "parkone,2020,rehearsal,,2026-10-09",
    "parktwo,2021,rehearsal,,2026-10-09",
]


def write_csv(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def good(path: Path) -> Path:
    return write_csv(path, [HEADER, *GOOD_ROWS])


def bad(path: Path) -> Path:
    return write_csv(path, [HEADER, *FAULTS["empty park_id"]])


def tree(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


@pytest.fixture(autouse=True)
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project folder of its own, so relative landing paths never touch the real repository."""
    folder = tmp_path / "project"
    folder.mkdir()
    monkeypatch.setattr(registry_feed, "PROJECT_DIR", folder)
    monkeypatch.delenv("OPENRCT2_DATA_DIR", raising=False)
    return folder


def test_registry_fields_match_the_feed_contract() -> None:
    fields = load_reference_fields(CONTRACTS_DIR / "reference")["park_registry"]
    assert [(f.name, f.logical, f.required) for f in fields] == [
        ("park_id", "string", True),
        ("company_start_year", "integer", True),
        ("game_year_origin", "integer", True),
        ("data_set", "string", True),
        ("note", "string", False),
        ("delivered_on", "date", True),
    ]


def test_probe_good_file_passes(tmp_path: Path) -> None:
    good(tmp_path / "v1" / "park_registry_2026-10-09_01.csv")
    assert registry_feed.check_feed(tmp_path) == []


@pytest.mark.parametrize("fault", FAULTS)
def test_probe_planted_fault_fails(tmp_path: Path, fault: str) -> None:
    write_csv(tmp_path / "v1" / "park_registry_2026-10-09_01.csv", [HEADER, *FAULTS[fault]])
    assert registry_feed.check_feed(tmp_path), fault


def test_all_digit_text_columns_pass(tmp_path: Path) -> None:
    write_csv(
        tmp_path / "v1" / "park_registry_2026-10-09_01.csv",
        [HEADER, "12345,2020,1,rehearsal,7,2026-10-09", "67890,2021,1,company,,2026-10-09"],
    )
    assert registry_feed.check_feed(tmp_path) == []


def test_header_only_delivery_gets_the_same_verdict_alone_and_landed(tmp_path: Path) -> None:
    empty = write_csv(tmp_path / "v1" / "park_registry_2026-10-08_01.csv", [HEADER])
    alone = registry_feed.check_file(empty)
    good(tmp_path / "v1" / "park_registry_2026-10-09_01.csv")
    assert alone == registry_feed.check_feed(tmp_path)


def test_probe_missing_column_fails(tmp_path: Path) -> None:
    write_csv(tmp_path / "v1" / "park_registry_2026-10-09_01.csv", MISSING_COLUMN)
    assert registry_feed.check_feed(tmp_path)


def test_folders_follow_the_landing_folders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert registry_feed.registry_dir("rehearsal") == Path("data/rehearsal/registry")
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path))
    assert registry_feed.registry_dir("company") == tmp_path / "company" / "registry"


def test_alias_company_feed_linked_to_rehearsal_feed_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path))
    (tmp_path / "rehearsal" / "registry").mkdir(parents=True)
    (tmp_path / "company").mkdir()
    (tmp_path / "company" / "registry").symlink_to(tmp_path / "rehearsal" / "registry")
    with pytest.raises(ConfigError, match="registry"):
        registry_feed.registry_dir("company")
    assert registry_feed.main(["--data-set", "company"]) == 2


@pytest.mark.parametrize("target", [("rehearsal", "raw"), ("company", "parquet")])
def test_alias_feed_linked_to_a_raw_or_parquet_folder_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: tuple[str, str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path))
    folder = tmp_path.joinpath(*target)
    folder.mkdir(parents=True)
    (tmp_path / "rehearsal").mkdir(exist_ok=True)
    (tmp_path / "rehearsal" / "registry").symlink_to(folder)
    with pytest.raises(ConfigError):
        registry_feed.registry_dir("rehearsal")


def test_relative_data_dir_resolves_against_the_project_folder(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "data")
    (project / "data" / "rehearsal" / "registry").mkdir(parents=True)
    (project / "data" / "company").mkdir()
    (project / "data" / "company" / "registry").symlink_to(
        project / "data" / "rehearsal" / "registry"
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    with pytest.raises(ConfigError):
        registry_feed.registry_dir("company")


def test_cli_data_set_checks_the_data_sets_feed_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path))
    good(tmp_path / "rehearsal" / "registry" / "v1" / "park_registry_2026-10-09_01.csv")
    assert registry_feed.main(["--data-set", "rehearsal"]) == 0
    assert "passed" in capsys.readouterr().out


def test_cli_data_root_reads_its_registry_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good(tmp_path / "registry" / "v1" / "park_registry_2026-10-09_01.csv")
    assert registry_feed.main(["--data-root", str(tmp_path)]) == 0
    bad(tmp_path / "registry" / "v1" / "park_registry_2026-10-10_01.csv")
    assert registry_feed.main(["--data-root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "park_registry.odcs.yaml" in out


def test_cli_empty_folder_fails_naming_the_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "registry" / "v1").mkdir(parents=True)
    assert registry_feed.main(["--data-root", str(tmp_path)]) == 1
    assert str(tmp_path / "registry" / "v1") in capsys.readouterr().out


def test_cli_failing_folder_names_every_failing_file_and_no_good_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    v1 = tmp_path / "registry" / "v1"
    good(v1 / "park_registry_2026-10-09_01.csv")
    bad(v1 / "park_registry_2026-10-10_01.csv")
    bad(v1 / "park_registry_2026-10-11_01.csv")
    assert registry_feed.main(["--data-root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "park_registry_2026-10-10_01.csv:" in out
    assert "park_registry_2026-10-11_01.csv:" in out
    assert "park_registry_2026-10-09_01.csv:" not in out


def test_prelanding_file_check_fails_a_bad_file_and_leaves_the_landing_folder_alone(
    tmp_path: Path,
) -> None:
    landing = tmp_path / "registry"
    good(landing / "v1" / "park_registry_2026-10-09_01.csv")
    incoming = bad(tmp_path / "incoming" / ".incoming-park_registry_2026-10-10_01.csv")
    before = tree(landing)
    assert registry_feed.main(["--file", str(incoming)]) == 1
    assert tree(landing) == before
    assert registry_feed.main(["--file", str(good(tmp_path / "incoming" / "ok.csv"))]) == 0


def test_prelanding_missing_file_fails(tmp_path: Path) -> None:
    assert registry_feed.main(["--file", str(tmp_path / "absent.csv")]) == 1


def test_rejected_bad_file_is_named_until_it_is_moved_to_rejected(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    good(registry / "v1" / "park_registry_2026-10-09_01.csv")
    landed = bad(registry / "v1" / "park_registry_2026-10-10_01.csv")
    problems = registry_feed.check_feed(registry)
    assert any(line.startswith(f"{landed.name}:") for line in problems)
    rejected = registry / "rejected"
    rejected.mkdir()
    landed.rename(rejected / landed.name)
    (rejected / f"{landed.name}.reason").write_text("empty park_id\n", encoding="utf-8")
    assert registry_feed.check_feed(registry) == []


def test_latest_rows_takes_each_parks_row_from_the_latest_delivery_file(tmp_path: Path) -> None:
    """Delivery order is the file name (date, then sequence), not the write order."""
    feed = tmp_path / "v1"
    feed.mkdir()
    # Written first, but named last: its row for parkone must win over the _01 and _02 rows.
    (feed / "park_registry_2026-10-10_01.csv").write_text(
        f"{HEADER}\nparkone,2022,4,company,,2026-10-10\n", encoding="utf-8"
    )
    (feed / "park_registry_2026-10-09_02.csv").write_text(
        f"{HEADER}\nparkone,2021,3,rehearsal,,2026-10-09\nparktwo,2030,1,company,,2026-10-09\n",
        encoding="utf-8",
    )
    (feed / "park_registry_2026-10-09_01.csv").write_text(
        f"{HEADER}\nparkone,2020,1,rehearsal,,2026-10-09\n", encoding="utf-8"
    )
    (feed / "park_registry_2026-10-11.csv").write_text(
        f"{HEADER}\nparkone,2099,9,company,,2026-10-11\n", encoding="utf-8"
    )

    assert registry_feed.latest_rows(feed) == {
        "parkone": registry_feed.RegistryRow(2022, 4, "company", False),
        "parktwo": registry_feed.RegistryRow(2030, 1, "company", False),
    }


def test_latest_rows_flags_a_practice_park_from_its_latest_note(tmp_path: Path) -> None:
    feed = tmp_path / "v1"
    feed.mkdir()
    (feed / "park_registry_2026-10-09_01.csv").write_text(
        f"{HEADER}\nparkone,2000,1,company,{registry_feed.PRACTICE_NOTE},2026-10-09\n",
        encoding="utf-8",
    )
    (feed / "park_registry_2026-10-09_02.csv").write_text(
        f"{HEADER}\nparktwo,2000,1,company,{registry_feed.PRACTICE_NOTE},2026-10-09\n"
        "parkone,2000,1,company,,2026-10-09\n",
        encoding="utf-8",
    )

    rows = registry_feed.latest_rows(feed)

    assert rows["parkone"].practice is False
    assert rows["parktwo"].practice is True

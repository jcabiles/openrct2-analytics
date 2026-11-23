"""Real Parquet and CSV coverage for the company registry command."""

from __future__ import annotations

import csv
import hashlib
import os
import shutil
import signal
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest import lock, register_parks, registry_feed
from openrct2_analytics.ingest.convert import landing_lock_path

TODAY = date(2026, 10, 19)
HEADER = ",".join(registry_feed.HEADER)


def _copy(path: Path, query: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(f"COPY ({query}) TO '{path.as_posix()}' (FORMAT PARQUET)")


def _inputs(
    root: Path, *, bad_year: bool = False, mixed: bool = False, missing: bool = False
) -> Path:
    parquet = root / "company" / "parquet" / "v1"
    _copy(
        parquet.parent / "audit" / "seq_audit.parquet",
        "SELECT 'park-b' AS park_id, 's2' AS session_id, 1 AS park_count "
        "UNION ALL SELECT 'park-a', 's1', " + ("2" if mixed else "1"),
    )
    if not missing:
        year = 0 if bad_year else 3
        _copy(
            parquet / "session_start.parquet",
            "SELECT 'park-b' AS park_id, 's2' AS session_id, 5 AS game_year, "
            "TIMESTAMP '2026-10-02 10:00:00' AS emitted_at "
            f"UNION ALL SELECT 'park-a', 's1', {year}, TIMESTAMP '2026-10-01 10:00:00' "
            "UNION ALL SELECT 'park-a', 's0', 7, TIMESTAMP '2026-10-03 10:00:00'",
        )
    return root / "company" / "registry" / "v1"


def _delivery(
    feed: Path, name: str, park: str = "park-a", label: str = "company", *, note: str = ""
) -> Path:
    feed.mkdir(parents=True, exist_ok=True)
    path = feed / name
    path.write_text(f"{HEADER}\n{park},2000,3,{label},{note},2026-10-19\n", encoding="utf-8")
    return path


def _tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(str(path.relative_to(root)).encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    root = tmp_path / "data"
    feed = _inputs(root)
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(root))
    return root, feed


def _run(tmp_path: Path, *args: str) -> int:
    return register_parks.main(args, project_dir=tmp_path, today=TODAY)


def test_two_parks_in_clock_order_and_practice_note(
    setup: tuple[Path, Path], tmp_path: Path
) -> None:
    _, feed = setup
    assert _run(tmp_path, "--data-set", "company", "--practice") == 0
    path = feed / "park_registry_2026-10-19_01.csv"
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["park_id"] for row in rows] == ["park-a", "park-b"]
    assert [row["game_year_origin"] for row in rows] == ["3", "5"]
    assert {row["company_start_year"] for row in rows} == {"2000"}
    assert {row["data_set"] for row in rows} == {"company"}
    assert {row["delivered_on"] for row in rows} == {"2026-10-19"}
    assert {row["note"] for row in rows} == {register_parks.NOTE}
    assert registry_feed.check_feed(feed.parent) == []


def test_registered_park_skipped_and_nothing_to_do(
    setup: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, feed = setup
    _delivery(feed, "park_registry_2026-10-18_01.csv", note=register_parks.NOTE)
    assert _run(tmp_path, "--data-set", "company") == 0
    with (feed / "park_registry_2026-10-19_01.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1 and rows[0]["park_id"] == "park-b" and rows[0]["note"] == ""
    before = _tree(tmp_path)
    capsys.readouterr()
    assert _run(tmp_path, "--data-set", "company") == 0
    assert "already registered" in capsys.readouterr().out
    assert _tree(tmp_path) == before


def test_next_free_name(setup: tuple[Path, Path], tmp_path: Path) -> None:
    _, feed = setup
    _delivery(feed, "park_registry_2026-10-19_01.csv", "other")
    assert _run(tmp_path, "--data-set", "company", "--practice") == 0
    assert (feed / "park_registry_2026-10-19_02.csv").is_file()


def _plant_refusal(case: str, root: Path, feed: Path) -> None:
    if case == "no-audit":
        (root / "company" / "parquet" / "audit" / "seq_audit.parquet").unlink()
    elif case == "no-start":
        (root / "company" / "parquet" / "v1" / "session_start.parquet").unlink()
    elif case == "mixed":
        _inputs(root, mixed=True)
    elif case == "leftover":
        feed.mkdir(parents=True)
        (feed / ".incoming-park_registry_2026-10-19_01.csv").write_text("pending")
    elif case == "invalid-feed":
        _delivery(feed, "park_registry_2026-10-18_01.csv").write_text("bad\n")
    elif case == "no-free-name":
        for number in range(1, 100):
            _delivery(feed, f"park_registry_2026-10-19_{number:02}.csv", "other")
    elif case == "mismatch":
        _delivery(feed, "park_registry_2026-10-18_01.csv", label="rehearsal")
    elif case == "no-session-start":
        _copy(
            root / "company" / "parquet" / "v1" / "session_start.parquet",
            "SELECT 'park-a' AS park_id, 's1' AS session_id, 3 AS game_year, "
            "TIMESTAMP '2026-10-01 10:00:00' AS emitted_at",
        )


@pytest.mark.parametrize(
    "scenario",
    [
        ("no-set", "data-set"),
        ("unknown", "data-set"),
        ("config", "data-set"),
        ("rehearsal", "rehearsal"),
        ("no-audit", "not-converted"),
        ("no-start", "not-converted"),
        ("mixed", "mixed-session"),
        ("leftover", "leftover"),
        ("invalid-feed", "registry-check"),
        ("no-free-name", "no-free-name"),
        ("mismatch", "mismatch"),
        ("lock", "lock-taken"),
        ("no-session-start", "no-session-start"),
    ],
)
def test_refusals_leave_folder_tree_unchanged(
    setup: tuple[Path, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    scenario: tuple[str, str],
) -> None:
    root, feed = setup
    case, reason = scenario
    args = ["--data-set", "company"]
    if case == "no-set":
        args = []
    elif case == "unknown":
        args = ["--data-set", "unknown"]
    elif case == "rehearsal":
        args = ["--data-set", "rehearsal"]
    elif case == "config":
        os.environ["OPENRCT2_DATA_DIR"] = ""
    else:
        _plant_refusal(case, root, feed)
    before = _tree(tmp_path)
    if case == "lock":
        path = landing_lock_path(root / "company" / "parquet")
        with lock.hold_lock(path, "test holder"):
            before = _tree(tmp_path)
            assert _run(tmp_path, *args, "--practice") == 2
            assert _tree(tmp_path) == before
    else:
        assert _run(tmp_path, *args) == 2
        assert _tree(tmp_path) == before
    assert f"register refused: {reason}:" in capsys.readouterr().out


def test_rejected_and_unaccepted_name_do_not_register(
    setup: tuple[Path, Path], tmp_path: Path
) -> None:
    _, feed = setup
    _delivery(feed.parent / "rejected", "park_registry_2026-10-18_01.csv")
    _delivery(feed, "other.csv")
    assert _run(tmp_path, "--data-set", "company", "--practice") == 0
    with (feed / "park_registry_2026-10-19_01.csv").open(newline="", encoding="utf-8") as stream:
        assert [row["park_id"] for row in csv.DictReader(stream)] == ["park-a", "park-b"]


def test_bad_year_fails_check_and_removes_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "data"
    feed = _inputs(root, bad_year=True)
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(root))
    assert _run(tmp_path, "--data-set", "company", "--practice") == 1
    assert "register failed: check-failed:" in capsys.readouterr().out
    assert not list(feed.glob(".incoming-*"))
    assert not list(feed.glob("park_registry_*.csv"))


def test_sigterm_at_check_removes_stage(
    setup: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, feed = setup
    real_check = registry_feed.check_file

    def signal_at_check(path: Path) -> list[str]:
        assert path.is_file()
        os.kill(os.getpid(), signal.SIGTERM)
        return real_check(path)

    monkeypatch.setattr(registry_feed, "check_file", signal_at_check)
    assert _run(tmp_path, "--data-set", "company", "--practice") == 130
    assert not list(feed.glob(".incoming-*"))
    assert not list(feed.glob("park_registry_*.csv"))
    assert not landing_lock_path(feed.parent.parent / "parquet").exists()


def test_registers_the_committed_sample_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = Path(__file__).resolve().parents[1] / "data" / "sample" / "rehearsal"
    parquet = tmp_path / "data" / "company" / "parquet"
    shutil.copytree(sample / "audit", parquet / "audit")
    shutil.copytree(sample / "v1", parquet / "v1")
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    assert _run(tmp_path, "--data-set", "company") == 0
    feed = tmp_path / "data" / "company" / "registry" / "v1"
    with (feed / "park_registry_2026-10-19_01.csv").open(newline="", encoding="utf-8") as stream:
        assert len(list(csv.DictReader(stream))) == 1
    assert registry_feed.check_feed(feed.parent) == []


@pytest.mark.parametrize("name", ["park_registry_bad.csv", "park_registry_2026-10-18_00.csv"])
def test_misnamed_delivery_is_warned_and_park_registers_again(
    setup: tuple[Path, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    name: str,
) -> None:
    _, feed = setup
    _delivery(feed, name)
    assert _run(tmp_path, "--data-set", "company", "--practice") == 0
    with (feed / "park_registry_2026-10-19_01.csv").open(newline="", encoding="utf-8") as stream:
        assert [row["park_id"] for row in csv.DictReader(stream)] == ["park-a", "park-b"]
    err = capsys.readouterr().err
    assert name in err and "warehouse ignores it" in err


@pytest.mark.parametrize(
    ("name", "accepted"),
    [
        ("park_registry_2026-10-19_01.csv", True),
        ("park_registry_2026-10-19_99.csv", True),
        ("park_registry_2026-10-19_00.csv", False),
        ("park_registry_2026-10-19_1.csv", False),
        ("park_registry_20261019_01.csv", False),
        ("park_registry_2026-10-19_01.CSV", False),
        ("park_registry_2026-10-19_01.csv\n", False),
        ("park_registry_2026-1a-19_01.csv", False),
    ],
)
def test_accepted_delivery_names(name: str, accepted: bool) -> None:
    assert registry_feed.is_accepted_name(name) is accepted


def test_delivery_landing_during_lock_wait_is_not_duplicated(
    setup: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, feed = setup
    real_hold = lock.hold_lock

    @contextmanager
    def hold_after_delivery(path: Path, note: str) -> Iterator[None]:
        _delivery(feed, "park_registry_2026-10-19_01.csv", "park-a")
        _delivery(feed, "park_registry_2026-10-19_02.csv", "park-b")
        with real_hold(path, note):
            yield

    monkeypatch.setattr(lock, "hold_lock", hold_after_delivery)
    assert _run(tmp_path, "--data-set", "company", "--practice") == 0
    assert "already registered" in capsys.readouterr().out
    assert sorted(path.name for path in feed.iterdir()) == [
        "park_registry_2026-10-19_01.csv",
        "park_registry_2026-10-19_02.csv",
    ]


def test_failed_check_leaves_no_registry_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "data"
    _inputs(root, bad_year=True)
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(root))
    assert _run(tmp_path, "--data-set", "company", "--practice") == 1
    assert not (root / "company" / "registry").exists()


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_park_list_sets_each_practice_flag_in_one_delivery(
    setup: tuple[Path, Path], tmp_path: Path
) -> None:
    _, feed = setup
    assert _run(tmp_path, "--data-set", "company", "--parks", "park-b:company,park-a:practice") == 0
    assert sorted(path.name for path in feed.iterdir()) == ["park_registry_2026-10-19_01.csv"]
    rows = _rows(feed / "park_registry_2026-10-19_01.csv")
    assert [(row["park_id"], row["note"]) for row in rows] == [
        ("park-a", register_parks.NOTE),
        ("park-b", ""),
    ]
    assert {row["data_set"] for row in rows} == {"company"}
    assert registry_feed.check_feed(feed.parent) == []


def test_park_list_registers_only_the_listed_parks(
    setup: tuple[Path, Path], tmp_path: Path
) -> None:
    _, feed = setup
    assert _run(tmp_path, "--data-set", "company", "--parks", "park-b:practice") == 0
    rows = _rows(feed / "park_registry_2026-10-19_01.csv")
    assert [(row["park_id"], row["note"]) for row in rows] == [("park-b", register_parks.NOTE)]
    assert _run(tmp_path, "--data-set", "company") == 0
    rows = _rows(feed / "park_registry_2026-10-19_02.csv")
    assert [(row["park_id"], row["note"]) for row in rows] == [("park-a", "")]


@pytest.mark.parametrize(
    "scenario",
    [
        (["--parks", "park-z:company"], "unknown-park"),
        (["--parks", "park-a:company,park-z:practice"], "unknown-park"),
        (["--parks", "park-a:company", "--practice"], "parks"),
        (["--parks", "park-a"], "parks"),
        (["--parks", "park-a:other"], "parks"),
        (["--parks", ":company"], "parks"),
        (["--parks", "park-a:company,park-a:practice"], "parks"),
    ],
)
def test_park_list_refusals_leave_folder_tree_unchanged(
    setup: tuple[Path, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    scenario: tuple[list[str], str],
) -> None:
    args, reason = scenario
    before = _tree(tmp_path)
    assert _run(tmp_path, "--data-set", "company", *args) == 2
    assert _tree(tmp_path) == before
    assert f"register refused: {reason}:" in capsys.readouterr().out


def test_park_list_refuses_an_already_registered_park(
    setup: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, feed = setup
    _delivery(feed, "park_registry_2026-10-18_01.csv")
    before = _tree(tmp_path)
    assert _run(tmp_path, "--data-set", "company", "--parks", "park-a:company") == 2
    assert _tree(tmp_path) == before
    assert "register refused: unknown-park: Park park-a" in capsys.readouterr().out


def test_empty_park_list_is_no_list(
    setup: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, feed = setup
    assert _run(tmp_path, "--data-set", "company", "--practice", "--parks", "") == 0
    rows = _rows(feed / "park_registry_2026-10-19_01.csv")
    assert [(row["park_id"], row["note"]) for row in rows] == [
        ("park-a", register_parks.NOTE),
        ("park-b", register_parks.NOTE),
    ]
    capsys.readouterr()
    before = _tree(tmp_path)
    assert _run(tmp_path, "--data-set", "company", "--parks", " ") == 0
    assert "already registered" in capsys.readouterr().out
    assert _tree(tmp_path) == before


def test_register_returns_the_delivery_name_and_prints_nothing(
    setup: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, feed = setup
    name = register_parks.register(tmp_path, TODAY, True)
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "")
    assert name == "park_registry_2026-10-19_01.csv"
    assert [path.name for path in feed.iterdir()] == [name]


def test_register_raises_on_refusal_and_writes_nothing(
    setup: tuple[Path, Path], tmp_path: Path
) -> None:
    _, feed = setup
    _delivery(feed, "park_registry_2026-10-18_01.csv", label="rehearsal")
    before = _tree(tmp_path)
    with pytest.raises(register_parks.Refused) as refusal:
        register_parks.register(tmp_path, TODAY, False)
    assert refusal.value.reason == "mismatch"
    assert refusal.value.detail == "Park park-a is registered as rehearsal"
    assert _tree(tmp_path) == before


def _use_names(feed: Path, used: int) -> None:
    for number in range(1, used + 1):
        _delivery(feed, f"park_registry_2026-10-19_{number:02}.csv", "other")


def test_check_registrations_refuses_when_fewer_free_names_than_parks(
    setup: tuple[Path, Path], tmp_path: Path
) -> None:
    _, feed = setup
    _use_names(feed, 98)
    register_parks.check_registrations(tmp_path, TODAY, 1)
    before = _tree(tmp_path)
    with pytest.raises(register_parks.Refused) as refusal:
        register_parks.check_registrations(tmp_path, TODAY, 2)
    assert refusal.value.reason == "no-free-name"
    assert refusal.value.detail == "Only 1 delivery names for 2026-10-19 are free; need 2"
    assert _tree(tmp_path) == before


def test_check_registrations_refuses_a_leftover_staged_delivery(
    setup: tuple[Path, Path], tmp_path: Path
) -> None:
    _, feed = setup
    register_parks.check_registrations(tmp_path, TODAY, 1)
    feed.mkdir(parents=True)
    (feed / ".incoming-park_registry_2026-10-19_01.csv").write_text("pending")
    with pytest.raises(register_parks.Refused) as refusal:
        register_parks.check_registrations(tmp_path, TODAY, 1)
    assert refusal.value.reason == "leftover"
    assert (
        refusal.value.detail
        == "Staged delivery .incoming-park_registry_2026-10-19_01.csv already exists"
    )

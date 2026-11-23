"""Behaviour at the callers of the landing-folder join: the filing and registering commands.

Every test passes on the code as it stands and must keep passing when the private copies of the
join move into one module. The relative-root tests set ``OPENRCT2_DATA_DIR=data-x``, plant files
under ``<project>/data-x/company/`` and run from a different, empty working folder. The reading
and checking commands are in ``tests/test_landing_paths_callers.py``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest

from openrct2_analytics.domain.start_year_plan import Planned
from openrct2_analytics.ingest import (
    after_play,
    auto_file,
    auto_file_state,
    lock,
    register_parks,
    several_parks,
)
from openrct2_analytics.ingest.convert import landing_lock_path
from openrct2_analytics.ingest.start_year import plan_start_years
from tests.landing_paths_support import EMPTY_ROOT
from tests.landing_paths_support import relative_root as relative_root  # noqa: F401  (fixture)
from tests.test_register_parks_start_year import _first_park, later_year, park_one, plant

TODAY = date(2026, 11, 13)
PARKS = "park-1:company,park-2:company"
UNCONVERTED = (
    "events-2026-11-13.jsonl holds a session that was never converted, so the latest managed "
    "year is unknown; run make convert DATA_SET=company first"
)


def _unconverted(data: Path) -> None:
    """Plant a raw file that holds a session no converted file holds."""
    raw = data / "company" / "raw" / "v1" / "events-2026-11-13.jsonl"
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps({"session_id": "s9", "park_id": "park-2"}) + "\n", encoding="utf-8")


def _written(data: Path) -> list[str]:
    feed = data / "company" / "registry" / "v1"
    return sorted(path.name for path in feed.glob("park_registry_*.csv"))


# R12: a relative data root, from a working folder that is not the project folder.


def test_after_play_check_can_start_finds_the_landing_lock_under_the_project(
    relative_root: Path,
) -> None:
    plant(relative_root / "data-x", park_one())
    held = relative_root / "data-x" / "company" / "parquet.lock"
    held.touch()
    with pytest.raises(after_play.Refused) as caught:
        after_play.check_can_start("company", relative_root)
    assert caught.value.reason == "lock-taken"
    assert caught.value.detail == f'{held} exists; see ARCHITECTURE.md "Stale locks"'


def test_after_play_registers_through_the_raw_and_parquet_folders_under_the_project(
    relative_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(after_play, "_make", lambda target, data_set: lambda: 0)
    plant(relative_root / "data-x", park_one())
    argv = ["--data-set", "company", "--parks", PARKS, "--start-year", "2001"]
    assert after_play.main(argv, project_dir=relative_root) == 0
    assert capsys.readouterr().out.endswith("after-play: every step passed\n")
    assert len(_written(relative_root / "data-x")) == 2


def test_after_play_refuses_an_unconverted_raw_session_under_the_project(
    relative_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(after_play, "_make", lambda target, data_set: lambda: 0)
    plant(relative_root / "data-x", park_one())
    _unconverted(relative_root / "data-x")
    argv = ["--data-set", "company", "--parks", PARKS, "--start-year", "2001"]
    assert after_play.main(argv, project_dir=relative_root) == 2
    assert capsys.readouterr().out == (
        f"after-play refused: not-converted: {UNCONVERTED}. Nothing was changed.\n"
    )
    assert len(_written(relative_root / "data-x")) == 1


def test_auto_file_start_year_reads_the_folders_under_the_project(relative_root: Path) -> None:
    # The later-year world: park-1 played on into 2001, which only the Parquet files say.
    plant(relative_root / "data-x", later_year(park_one()))
    assert auto_file._start_year({"park-2": False}, relative_root) == 2002


def test_auto_file_start_year_refuses_an_unconverted_raw_session_under_the_project(
    relative_root: Path,
) -> None:
    plant(relative_root / "data-x", park_one())
    _unconverted(relative_root / "data-x")
    with pytest.raises(register_parks.Refused) as caught:
        auto_file._start_year({"park-2": False}, relative_root)
    assert (caught.value.reason, caught.value.detail) == ("not-converted", UNCONVERTED)


def test_auto_file_state_record_lists_converted_and_raw_sessions_under_the_project(
    relative_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plant(relative_root / "data-x", _first_park(1))
    _unconverted(relative_root / "data-x")
    auto_file_state.record(relative_root, "company")
    recorded = relative_root / "local" / "auto-file" / "converted-before.json"
    assert json.loads(recorded.read_text(encoding="utf-8")) == ["s2", "s9"]
    assert capsys.readouterr().out == (
        "auto-file: recorded 2 converted session(s) in local/auto-file/converted-before.json\n"
    )


def test_start_year_plan_reads_the_folders_under_the_project(relative_root: Path) -> None:
    plant(relative_root / "data-x", park_one())
    assert plan_start_years(relative_root, [("park-2", False)]) == [Planned("park-2", 2001, 1)]


def test_start_year_plan_refuses_an_unconverted_raw_session_under_the_project(
    relative_root: Path,
) -> None:
    plant(relative_root / "data-x", park_one())
    _unconverted(relative_root / "data-x")
    with pytest.raises(register_parks.Refused) as caught:
        plan_start_years(relative_root, [("park-2", False)])
    assert (caught.value.reason, caught.value.detail) == ("not-converted", UNCONVERTED)


def test_several_parks_plan_chain_reads_the_parquet_under_the_project(
    relative_root: Path,
) -> None:
    plant(relative_root / "data-x", park_one())
    planned = several_parks.plan_chain(
        relative_root, {"park-2": False}, {"park-1", "park-2"}, TODAY
    )
    assert planned == [Planned("park-2", 2001, 1)]


def test_register_later_year_refuses_an_unconverted_raw_session_under_the_project(
    relative_root: Path,
) -> None:
    plant(relative_root / "data-x", park_one())
    _unconverted(relative_root / "data-x")
    with pytest.raises(register_parks.Refused) as caught:
        register_parks.register(relative_root, TODAY, False, start_year=2001)
    assert (caught.value.reason, caught.value.detail) == ("not-converted", UNCONVERTED)
    assert len(_written(relative_root / "data-x")) == 1


# R6: register_parks looks up once per call, before the lock, and reuses the paths inside it.


def test_register_uses_the_first_lookup_inside_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_a, root_b = tmp_path / "root-a", tmp_path / "root-b"
    plant(root_a, _first_park(1))
    plant(root_b, _first_park(1))
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(root_a))
    real_hold = lock.hold_lock
    held: list[Path] = []

    @contextmanager
    def hold_then_switch(path: Path, note: str) -> Iterator[None]:
        held.append(path)
        monkeypatch.setenv("OPENRCT2_DATA_DIR", str(root_b))
        with real_hold(path, note):
            yield

    monkeypatch.setattr(lock, "hold_lock", hold_then_switch)
    assert register_parks.register(tmp_path, TODAY, False) == "park_registry_2026-11-13_01.csv"
    assert held == [landing_lock_path(root_a / "company" / "parquet")]
    assert _written(root_a) == ["park_registry_2026-11-13_01.csv"]
    assert not (root_b / "company" / "registry").exists()


def test_register_looks_up_again_on_each_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_a, root_b = tmp_path / "root-a", tmp_path / "root-b"
    plant(root_a, _first_park(1))
    plant(root_b, _first_park(1))
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(root_a))
    assert register_parks.register(tmp_path, TODAY, False) == "park_registry_2026-11-13_01.csv"
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(root_b))
    assert register_parks.register(tmp_path, TODAY, False) == "park_registry_2026-11-13_01.csv"
    assert _written(root_a) == ["park_registry_2026-11-13_01.csv"]
    assert _written(root_b) == ["park_registry_2026-11-13_01.csv"]


# R7 and R8: the order of refusals and the laziness of lookups.


def test_after_play_refuses_rehearsal_before_any_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "")
    assert after_play.main(["--data-set", "rehearsal"], project_dir=tmp_path) == 2
    assert capsys.readouterr().out == (
        "after-play refused: rehearsal: The capture command owns rehearsal deliveries. "
        "Nothing was changed.\n"
    )


def test_auto_file_start_year_looks_up_nothing_when_every_park_is_a_sandbox_park(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "")
    assert auto_file._start_year({"park-a": True}, tmp_path) is None


# R9: the line and exit code of a lookup error, through a path that reaches the company lookup.


def test_after_play_refuses_an_empty_data_root_with_a_data_set_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "")
    assert after_play.main(["--data-set", "company"], project_dir=tmp_path) == 2
    assert capsys.readouterr().out == (
        f"after-play refused: data-set: {EMPTY_ROOT}. Nothing was changed.\n"
    )


def test_auto_file_record_refuses_an_empty_data_root_with_a_data_set_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "")
    assert auto_file.main(["--data-set", "company", "--record"], project_dir=tmp_path) == 2
    assert capsys.readouterr().out == (
        f"auto-file refused: data-set: {EMPTY_ROOT}. Nothing was changed.\n"
    )


def test_auto_file_count_as_refuses_an_empty_data_root_with_a_data_set_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "")
    argv = ["--data-set", "company", "--count-as", "company"]
    assert auto_file.main(argv, project_dir=tmp_path) == 2
    assert capsys.readouterr().out == (
        f"auto-file refused: data-set: {EMPTY_ROOT}. Nothing was changed.\n"
    )


def test_register_refuses_an_empty_data_root_with_a_data_set_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "")
    assert register_parks.main(["--data-set", "company"], project_dir=tmp_path) == 2
    assert capsys.readouterr().out == (
        f"register refused: data-set: {EMPTY_ROOT}. Nothing was changed.\n"
    )

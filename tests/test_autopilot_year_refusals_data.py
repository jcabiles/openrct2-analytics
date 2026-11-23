"""The autopilot-year command's data refusals 12 to 20, the ready mark, roadmap cases 1 to 3,
and the run's inputs.

Each case starts from the valid company world of ``test_autopilot_year_refusals.py`` and changes
one thing; ``World.run`` asserts nothing was written. Expected texts are copied from
docs/ai-dlc/specs/autopilot-year.md, section 4; the roadmap cases are section 5's.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from openrct2_analytics.ingest.register_parks import NOTE
from tests.autopilot_fixtures import event_row
from tests.test_autopilot_year_refusals import (
    BREAKERS,
    COMPANY_ROW,
    FIRST_RUN,
    LAST_SAVE,
    NO_CONVERTED,
    READY,
    TAIL,
    WORK_NAME,
    World,
    assert_refused,
    reached_the_run,
    refused_by,
)

NOT_REGISTERED = (
    "Park park-a is not a registered company park; register it with make register-parks "
    "DATA_SET=company first." + TAIL
)
NO_OTHER_PARK_2001 = (
    "Park park-a would play company year 2001, but no other registered company park has a "
    "managed day in 2001 yet. An autopilot park runs only a company year the managed park runs; "
    "play the managed park into 2001 first."
)


@pytest.fixture(name="world")
def world_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return World(tmp_path, monkeypatch)


@pytest.mark.parametrize("number", ["12", "13", "14", "15", "16", "17a", "17b", "18", "19", "20"])
def test_each_refusal_12_to_20_prints_its_text_exits_2_and_writes_nothing(
    world: World, capsys: pytest.CaptureFixture[str], number: str
) -> None:
    refused_by(world, capsys, number)


def test_refusal_12_a_missing_parquet(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.session_start = False
    assert_refused(world, capsys, NO_CONVERTED)


def test_refusal_12_a_missing_audit(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.audit = False
    assert_refused(world, capsys, NO_CONVERTED)


def test_refusal_12_an_unconverted_managed_raw_file(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.raw_sessions.append("sess-new")
    assert_refused(
        world,
        capsys,
        "data/company/raw/v1/events-2026-11-12.jsonl holds a session that was never converted; "
        "run make convert DATA_SET=company first." + TAIL,
    )


def test_refusal_12_a_raw_file_cut_off_in_its_last_line(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = world.company / "raw" / "v1" / "events-2026-11-13.jsonl"
    world.after_plant.append(
        lambda: raw.write_text('{"session_id": "sess-a1"}\n{"session_id": "se', encoding="utf-8")
    )
    assert_refused(
        world,
        capsys,
        "data/company/raw/v1/events-2026-11-13.jsonl holds a session that was never converted; "
        "run make convert DATA_SET=company first." + TAIL,
    )


def test_refusal_13_an_unregistered_park(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.registry.remove(COMPANY_ROW)
    assert_refused(world, capsys, NOT_REGISTERED)


def test_refusal_13_a_park_registered_to_another_data_set(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.registry[0] = ("park-a", 2000, 1, "rehearsal", "", "2026-11-12")
    assert_refused(world, capsys, NOT_REGISTERED)


def test_refusal_13_a_practice_park(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.registry[0] = ("park-a", 2000, 1, "company", NOTE, "2026-11-12")
    assert_refused(
        world,
        capsys,
        "Park park-a is registered as a throwaway sandbox park; autopilot runs only company "
        "parks." + TAIL,
    )


def test_refusal_13_a_malformed_registry_is_refused(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.registry[0] = ("park-a", "", 1, "company", "", "2026-11-12")  # type: ignore[assignment]
    code, lines = world.run(capsys)
    assert code == 2
    assert lines[-1].endswith(TAIL)
    assert "test Check that field company_start_year has no missing values: failed" in lines[-1]


def test_refusal_13_a_failing_label_feed_is_refused(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.labels.append(("sess-a0", "park-a", "bogus", READY, "company", "2026-11-12"))
    code, lines = world.run(capsys)
    assert code == 2
    assert lines[-1].endswith(TAIL)
    assert "test play_mode is managed or autopilot: failed" in lines[-1]


def test_refusal_17a_names_a_park_waiting_to_register(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.registry.pop()  # park-b, the only park with a managed day in 2001
    assert_refused(
        world,
        capsys,
        NO_OTHER_PARK_2001
        + " Waiting to register (they count once registered): park-b (Park B)."
        + TAIL,
    )


def test_a_first_run_without_ready_is_refused(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    del world.args["--ready"]
    assert_refused(world, capsys, FIRST_RUN)


def test_a_first_run_with_a_wrong_ready_is_refused(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.args["--ready"] = "park-a is ready"
    assert_refused(world, capsys, FIRST_RUN)


def test_a_first_run_with_the_ready_phrase_passes(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    assert world.args["--ready"] == READY
    assert world.run(capsys) == reached_the_run(world)


def earlier_autopilot_run(world: World) -> None:
    """A landed autopilot session of park-a: its label row and its converted session_start."""
    world.starts.append(world.start("park-a", "sess-a0", (1, 4, 1), "Park A"))
    world.labels.append(("sess-a0", "park-a", "autopilot", READY, "company", "2026-11-12"))


def test_a_later_run_with_a_wrong_ready_passes_and_reaches_the_run(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    # The "READY was ignored" line belongs to the success report: test_autopilot_year.py.
    earlier_autopilot_run(world)
    world.args["--ready"] = "anything at all"
    assert world.run(capsys) == reached_the_run(world)


def test_a_later_run_with_an_empty_ready_passes_and_reaches_the_run(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    # The absence of the "READY was ignored" line is asserted in test_autopilot_year.py.
    earlier_autopilot_run(world)
    world.args["--ready"] = ""
    assert world.run(capsys) == reached_the_run(world)


def test_a_later_run_without_ready_passes(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    earlier_autopilot_run(world)
    del world.args["--ready"]
    assert world.run(capsys) == reached_the_run(world)


def test_an_orphan_label_row_does_not_make_a_later_run(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.labels.append(("sess-lost", "park-a", "autopilot", READY, "company", "2026-11-12"))
    del world.args["--ready"]
    assert_refused(world, capsys, FIRST_RUN)


def test_roadmap_1_park_1_is_refused_until_park_2_has_a_managed_session(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    # Park 2 is registered but has no session at all.
    world.snapshots = [row for row in world.snapshots if row["park_id"] != "park-b"]
    world.saves = [save for save in world.saves if save[0]["park_id"] != "park-b"]
    world.starts = [row for row in world.starts if row["park_id"] != "park-b"]
    world.raw_sessions.remove("sess-b1")
    assert_refused(world, capsys, NO_OTHER_PARK_2001 + TAIL)


def test_roadmap_2_park_1_may_run_once_park_2_has_a_managed_day(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    assert [row["park_id"] for row in world.snapshots].count("park-b") == 1
    assert world.run(capsys) == reached_the_run(world)


def test_roadmap_3_park_1_is_refused_the_year_after_park_2s_latest(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    # Park 1's autopilot session plays game year 2 to its save on 1 March of game year 3.
    later_save = LAST_SAVE + timedelta(hours=1)
    world.starts.append(world.start("park-a", "sess-a2", (2, 0, 1), "Park A"))
    world.snapshots.append(
        event_row(100, park_id="park-a", session_id="sess-a2", game_date=(2, 5, 1))
    )
    world.saves.append(
        (world.save("park-a", "sess-a2", 300, date=(3, 0, 1), emitted=later_save), "Park A", 7)
    )
    world.labels.append(("sess-a2", "park-a", "autopilot", READY, "company", "2026-11-12"))
    world.raw_sessions.append("sess-a2")
    assert_refused(
        world,
        capsys,
        "Park park-a would play company year 2002, but no other registered company park has a "
        "managed day in 2002 yet. An autopilot park runs only a company year the managed park "
        "runs; play the managed park into 2002 first." + TAIL,
    )


def test_breakers_cover_every_refusal_of_section_4() -> None:
    assert list(BREAKERS) == [str(n) for n in range(1, 17)] + ["17a", "17b", "18", "19", "20"]


def test_the_run_receives_the_proven_archive_copy_and_the_source_facts(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    assert world.run(capsys) == reached_the_run(world)
    ((settings, inputs),) = world.runs
    assert settings.park == world.copy
    assert inputs["source"] == world.copy
    assert {key: inputs[key] for key in ("park_id", "work_name", "g")} == {
        "park_id": "park-a",
        "work_name": WORK_NAME,
        "g": 2,
    }
    assert (inputs["loaded_save_id"], inputs["loaded_save_session_id"]) == (
        "save-sess-a1-905",
        "sess-a1",
    )
    assert inputs["built"] == world.bench.plugin
    assert inputs["planned_days"] == 245  # the source was saved on 1 March of game year 2


def test_a_kept_older_work_folder_does_not_block(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    kept = world.bench.bench_dir / "autopilot-park-a-20261112T090000Z"
    world.after_plant.append(lambda: kept.mkdir(parents=True))
    assert world.run(capsys) == reached_the_run(world)


def test_a_relative_backup_dir_is_resolved_against_the_project_folder(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    elsewhere = world.root / "elsewhere"
    elsewhere.mkdir()
    world.monkeypatch.chdir(elsewhere)
    world.monkeypatch.setenv("OPENRCT2_BACKUP_DIR", "backups")
    world.copy_size = None
    world.after_plant.append(lambda: setattr(world, "copy_size", 7))
    world.after_plant.append(lambda: world.plant_copy(world.project / "backups"))
    assert world.run(capsys) == reached_the_run(world)


def test_a_relative_data_dir_is_resolved_against_the_project_folder(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    elsewhere = world.root / "elsewhere"
    elsewhere.mkdir()
    world.monkeypatch.chdir(elsewhere)
    world.monkeypatch.setenv("OPENRCT2_DATA_DIR", "data")
    world.company = world.project / "data" / "company"
    world.parquet = world.company / "parquet"
    assert world.run(capsys) == reached_the_run(world)


def test_refusal_13_problems_from_two_feeds_print_one_line_each(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.registry[0] = ("park-a", "", 1, "company", "", "2026-11-12")  # type: ignore[assignment]
    world.labels.append(("sess-a0", "park-a", "bogus", READY, "company", "2026-11-12"))
    code, lines = world.run(capsys)
    assert code == 2
    assert lines == [
        "test overall result: failed",
        "test Check that field company_start_year has no missing values: failed "
        "(Actual missing_count(company_start_year) was 1, expected = 0)",
        "park_registry_2026-11-12_01.csv: test overall result: failed",
        "park_registry_2026-11-12_01.csv: test Check that field company_start_year has no "
        "missing values: failed (Actual missing_count(company_start_year) was 1, expected = 0)",
        "test overall result: failed",
        "test play_mode is managed or autopilot: failed "
        "(Actual custom_sql(session_play_mode) was 1, expected = 0)" + TAIL,
    ]

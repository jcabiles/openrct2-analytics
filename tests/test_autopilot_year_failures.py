"""The autopilot-year command's exit 1 texts, through ``main`` against the stand-in game.

Each case starts from the clean full run of ``test_autopilot_year.py`` and changes one thing. It
asserts exit 1, the exact text of docs/ai-dlc/specs/autopilot-year.md, section 4, "Exit 1 and
130 texts", and a kept work folder. A problem line inside a text comes from the run's own checks
(``autopilot_run``), whose function-level tests own it; here it is copied as printed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from openrct2_analytics.ingest import autopilot_land, capture_session
from openrct2_analytics.ingest.bench_setup import RunFolder
from openrct2_analytics.ingest.register_parks import NOTE
from tests.autopilot_fixtures import plant_label, plant_registry
from tests.test_autopilot_year import SESSION, STEM, Full, handlers

UNTOUCHED = "Company data was not touched; the run folder is kept at {work}."


PROGRESS = (
    "autopilot: park ",
    "autopilot: no events for ",
    "autopilot: events are arriving again.",
)


@pytest.fixture(name="full")
def full_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Full:
    return Full(tmp_path, monkeypatch)


def rewrite(change: Callable[[dict[str, object]], dict[str, object] | None]) -> Callable[..., None]:
    """A step that rewrites each raw line of the work folder through ``change``; None drops it."""

    def step(folder: RunFolder) -> None:
        (path,) = (folder.raw / "v1").glob("events-*.jsonl")
        kept = []
        for line in path.read_text(encoding="utf-8").splitlines():
            event = change(json.loads(line))
            if event is not None:
                kept.append(json.dumps(event) + "\n")
        path.write_text("".join(kept), encoding="utf-8")

    return step


def run(full: Full, capsys: pytest.CaptureFixture[str]) -> tuple[int, list[str]]:
    """Run ``full``; return the code and its lines without the autopilot progress lines."""
    code, lines = full.go(capsys)
    return code, [line for line in lines if not line.startswith(PROGRESS)]


def failed_checks(full: Full, *problems: str) -> list[str]:
    return [
        "The autopilot run failed its checks:",
        *(f"  {problem}" for problem in problems),
        UNTOUCHED.format(work=full.work),
    ]


def nothing_landed(full: Full) -> None:
    assert full.landing_steps == []
    assert full.landed("raw") == []
    assert [n for n in full.landed("registry") if n.startswith("session_play_mode_")] == []


def test_a_game_that_exits_early_did_not_reach_1_march(
    full: Full, capsys: pytest.CaptureFixture[str]
) -> None:
    full.entry = {**full.entry, "stats": 3, "save": False, "exit_early": True}
    code, lines = run(full, capsys)
    assert (code, lines) == (
        1,
        [
            "The autopilot run did not reach 1 March of game year 3: the game exited (code 0) "
            "before the stop condition; No finance_month row for October of game year 2; 0 "
            "save_written row(s); expected one, dated 1 March of game year 3; Saves paired with "
            "a file: none; expected only park-a-autopilot-3. Company data was not touched; the "
            f"run folder is kept at {full.work}."
        ],
    )
    assert full.work.is_dir()
    nothing_landed(full)


def test_no_october_statement_fails_the_checks(
    full: Full, capsys: pytest.CaptureFixture[str]
) -> None:
    dropped: list[int] = []

    def no_statement(event: dict[str, object]) -> dict[str, object] | None:
        """Drop October's statement and close the gap it leaves in ``seq`` and ``event_id``."""
        if event["event_type"] == "finance_month":
            dropped.append(1)
            return None
        seq = event["seq"]
        assert isinstance(seq, int)
        moved = seq - len(dropped)
        return {**event, "seq": moved, "event_id": f"{event['session_id']}-{moved}"}

    full.after_game.append(rewrite(no_statement))
    code, lines = run(full, capsys)
    assert (code, lines) == (
        1,
        failed_checks(full, "No finance_month row for October of game year 2."),
    )
    assert full.work.is_dir()
    nothing_landed(full)


def test_a_seq_gap_fails_the_checks(full: Full, capsys: pytest.CaptureFixture[str]) -> None:
    full.after_game.append(rewrite(lambda e: None if e["seq"] == 5 else e))
    code, lines = run(full, capsys)
    assert (code, lines) == (
        1,
        failed_checks(
            full,
            "seq audit: session standin-1 (park park-a): first_seq=1, last_seq=27, rows=26, "
            "missing=1, duplicates=0, parks=1",
        ),
    )
    assert full.work.is_dir()
    nothing_landed(full)


def test_a_malformed_line_fails_the_checks(full: Full, capsys: pytest.CaptureFixture[str]) -> None:
    def malformed(folder: RunFolder) -> None:
        (path,) = (folder.raw / "v1").glob("events-*.jsonl")
        with path.open("a", encoding="utf-8") as raw:
            raw.write("not json\n")

    full.after_game.append(malformed)
    code, lines = run(full, capsys)
    raw = f"events-{datetime.now(UTC).date().isoformat()}.jsonl"
    assert (code, lines) == (
        1,
        failed_checks(
            full,
            f"{raw} line 28 is not valid JSON (Expecting value)",
            f"Schema error: {raw}:28: not a JSON object",
            "Saves paired with a file: none; expected only park-a-autopilot-3.",
        ),
    )
    assert full.work.is_dir()
    nothing_landed(full)


def test_a_wrong_park_id_fails_the_checks(full: Full, capsys: pytest.CaptureFixture[str]) -> None:
    full.entry = {**full.entry, "park_id": "park-z"}
    code, lines = run(full, capsys)
    assert (code, lines) == (
        1,
        failed_checks(full, "Converted rows carry park_id park-z, expected park-a."),
    )
    assert full.work.is_dir()
    nothing_landed(full)


def test_lineage_keys_that_do_not_match_fail_the_checks(
    full: Full, capsys: pytest.CaptureFixture[str]
) -> None:
    def other_save(event: dict[str, object]) -> dict[str, object]:
        if event["event_type"] == "session_start":
            return {**event, "loaded_save_id": "save-standin-6"}
        return event

    full.after_game.append(rewrite(other_save))
    code, lines = run(full, capsys)
    assert (code, lines) == (
        1,
        failed_checks(
            full,
            "The session loaded save save-standin-6 of session standin-7; the source save is "
            "save-standin-7 of session standin-7.",
        ),
    )
    assert full.work.is_dir()
    nothing_landed(full)


def test_a_park_registered_as_practice_during_the_run_is_not_landed(
    full: Full, capsys: pytest.CaptureFixture[str]
) -> None:
    feed = full.company / "registry" / "v1"
    full.after_game.append(
        lambda folder: plant_registry(
            feed,
            [("park-a", 2000, 1, "company", NOTE, "2026-11-13")],
            name="park_registry_2026-11-13_01.csv",
        )
    )
    code, lines = run(full, capsys)
    assert (code, lines) == (
        1,
        failed_checks(
            full,
            "Park park-a is registered as a throwaway sandbox park; autopilot runs only company "
            "parks.",
        ),
    )
    assert full.work.is_dir()
    nothing_landed(full)


def test_a_staged_label_that_fails_the_checker_lands_nothing(
    full: Full, capsys: pytest.CaptureFixture[str]
) -> None:
    # An earlier delivery already labels the run's session, so the staged row repeats it.
    full.labels.append((SESSION, "park-b", "managed", "", "company", "2026-11-12"))
    code, lines = run(full, capsys)
    assert (code, lines) == (
        1,
        failed_checks(
            full,
            "test overall result: failed",
            "test session_id is unique across every delivery: failed (Actual "
            "custom_sql(session_play_mode) was 1, expected = 0)",
        ),
    )
    assert full.work.is_dir()
    assert full.landed("raw") == []
    assert full.landed("save_files") == ["save_file_observation_2026-11-12.jsonl"]


def test_a_taken_lock_lands_nothing(full: Full, capsys: pytest.CaptureFixture[str]) -> None:
    lock_file = full.company / "parquet.lock"
    full.after_game.append(lambda folder: lock_file.write_text("pid 1 started test\n"))
    code, lines = run(full, capsys)
    assert (code, lines) == (
        1,
        [
            "The company landing lock is held (pid 1 started test); nothing was landed. The run "
            f"folder is kept at {full.work}; rerun make autopilot-year when the other command "
            "ends."
        ],
    )
    assert full.work.is_dir()
    nothing_landed(full)


def test_a_link_that_fails_between_the_label_and_the_raw_file(
    full: Full, capsys: pytest.CaptureFixture[str]
) -> None:
    def disk_full() -> None:
        raise OSError("No space left on device (test)")

    full.on_landing["raw"] = disk_full
    code, lines = run(full, capsys)
    (record,) = [n for n in full.landed("save_files") if n.endswith(f"-autopilot-{SESSION}.jsonl")]
    label = f"session_play_mode_{date.today().isoformat()}_01.csv"
    assert (code, lines) == (
        1,
        [
            "Landing failed at raw: No space left on device (test). Landed: "
            f"data/company/registry/v1/{label}, data/company/save_files/v1/{record}; no raw "
            f"session landed. The run folder is kept at {full.work}."
        ],
    )
    assert full.work.is_dir()
    assert full.landed("raw") == []


def test_a_backup_copy_that_fails_prints_the_recovery_steps(
    full: Full, capsys: pytest.CaptureFixture[str]
) -> None:
    park_archive = full.archive / "park-a"
    full.after_plant.append(lambda: park_archive.chmod(0o555))  # no new archive copy can land
    try:
        code, lines = run(full, capsys)
    finally:
        park_archive.chmod(0o755)
    end_save = full.work / "user-data" / "save" / f"{STEM}.park"
    assert code == 1
    archive_failed = lines[-2]
    assert archive_failed.startswith(
        "Backup FAILED for Test Park's archive copy: [Errno 13] Permission denied: "
    )
    assert archive_failed.endswith(". The recorded data is fine; only the backup copy failed.")
    assert (
        f"To make the backup: copy {end_save} into {full.game_saves}, load it with make play "
        "DATA_SET=company, save while paused, and quit. The next autopilot run of this park is "
        "refused until then."
    ) == lines[-1]
    assert full.work.is_dir()


def test_a_skipped_backup_prints_the_recovery_steps(
    full: Full, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    skip = (
        "No backup made for park park-a: park-a-autopilot-3.park was written after its last "
        "recorded save, so newer unrecorded play may exist; the previous backup was kept."
    )
    # A skip is not a failure: back_up returns its line and True, and the archive gets no copy.
    monkeypatch.setattr(capture_session, "back_up", lambda *args: ([skip], True))
    code, lines = run(full, capsys)
    end_save = full.work / "user-data" / "save" / f"{STEM}.park"
    assert code == 1
    assert lines[-2:] == [
        skip,
        f"To make the backup: copy {end_save} into {full.game_saves}, load it with make play "
        "DATA_SET=company, save while paused, and quit. The next autopilot run of this park is "
        "refused until then.",
    ]
    assert list((full.archive / "park-a").iterdir()) == [full.copy]
    assert full.work.is_dir()


def test_a_park_that_turns_practice_during_the_lock_wait_lands_nothing(
    full: Full, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    feed = full.company / "registry" / "v1"
    real_hold = autopilot_land._hold

    def hold_then_register(*args: object, **kwargs: object) -> None:
        real_hold(*args, **kwargs)  # type: ignore[arg-type]
        plant_registry(  # the registry changes after the lock was taken
            feed,
            [("park-a", 2000, 1, "company", NOTE, "2026-11-13")],
            name="park_registry_2026-11-13_01.csv",
        )

    monkeypatch.setattr(autopilot_land, "_hold", hold_then_register)
    code, lines = run(full, capsys)
    assert (code, lines) == (
        1,
        failed_checks(
            full,
            "Park park-a is registered as a throwaway sandbox park; autopilot runs only company "
            "parks.",
        ),
    )
    assert full.work.is_dir()
    nothing_landed(full)


def test_a_bad_registry_and_label_feed_under_the_lock_print_one_line_each(
    full: Full, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = full.company / "registry" / "v1"
    real_hold = autopilot_land._hold

    def hold_then_break_feeds(*args: object, **kwargs: object) -> None:
        real_hold(*args, **kwargs)  # type: ignore[arg-type]
        plant_registry(  # a missing start year, planted after the lock was taken
            registry,
            [("park-a", "", 1, "company", "", "2026-11-13")],  # type: ignore[list-item]
            name="park_registry_2026-11-13_01.csv",
        )
        plant_label(  # a play mode the contract does not allow
            registry,
            [("sess-x", "park-a", "bogus", "", "company", "2026-11-13")],
            name="session_play_mode_2026-11-13_01.csv",
        )

    monkeypatch.setattr(autopilot_land, "_hold", hold_then_break_feeds)
    code, lines = run(full, capsys)
    assert (code, lines) == (
        1,
        failed_checks(
            full,
            "test overall result: failed",
            "test Check that field company_start_year has no missing values: failed "
            "(Actual missing_count(company_start_year) was 1, expected = 0)",
            "park_registry_2026-11-13_01.csv: test overall result: failed",
            "park_registry_2026-11-13_01.csv: test Check that field company_start_year has no "
            "missing values: failed (Actual missing_count(company_start_year) was 1, expected = 0)",
            "test overall result: failed",
            "test play_mode is managed or autopilot: failed "
            "(Actual custom_sql(session_play_mode) was 1, expected = 0)",
        ),
    )
    assert full.work.is_dir()
    assert full.landing_steps == []
    assert full.landed("raw") == []


def test_signal_handlers_are_restored_after_an_exit_1(
    full: Full, capsys: pytest.CaptureFixture[str]
) -> None:
    full.after_game.append(rewrite(lambda e: None if e["seq"] == 5 else e))
    before = handlers()
    code, _ = full.go(capsys)
    assert code == 1
    assert handlers() == before

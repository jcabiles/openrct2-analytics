"""Real Parquet, raw-file and warehouse coverage for the list of play waiting to be filed.

Every file is planted under ``tmp_path``; ``now`` and the game state are passed as values.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.config import LandingDirs, landing_dirs
from openrct2_analytics.ingest import play_status, unfiled
from openrct2_analytics.ingest.game_check import GameState
from openrct2_analytics.ingest.unfiled import Unfiled, find_unfiled, render
from tests.autopilot_fixtures import T0, event_row, plant_session_start
from tests.test_play_status import _warehouse, _writer_holds

NOW = 1_000_000.0
RUNNING, QUIET, UNKNOWN = GameState.RUNNING, GameState.NOT_RUNNING, GameState.UNKNOWN
OFFER_SESSIONS = "- Alpha Park (first played Nov 12): 1 converted session(s) not filed yet"
FAILED_S1 = (
    "- Alpha Park (first played Nov 12): session s1 failed its seq audit, "
    "so it is not offered for filing"
)
# Literal reason lines copied from the spec, section 4.2; not imported from the code under test.
FAILED_LINE = (
    "Nothing is offered while a session that failed its seq audit is waiting, "
    "because filing files every waiting session."
)
RECORDING_LINE = (
    "A recording is still being written (the game is running, a raw file changed in the last "
    "2 minutes, or a filing is running), so nothing is offered now."
)


@pytest.fixture
def landing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[LandingDirs]:
    """The company landing folders under ``tmp_path``, with the local zone fixed at UTC."""
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield landing_dirs("company")
    monkeypatch.undo()
    time.tzset()


def _start(landing: LandingDirs, *rows: tuple[str, str, str | None]) -> None:
    """Plant ``session_start.parquet`` with (session, park, park name) rows."""
    plant_session_start(
        landing.parquet,
        [
            event_row(1, session_id=session, park_id=park, park_name=name)
            for session, park, name in rows
        ],
    )


def _audit(landing: LandingDirs, session: str, **columns: int) -> None:
    """Plant ``audit/seq_audit.parquet`` with one session row; a clean row unless overridden."""
    values = {
        "first_seq": 1,
        "last_seq": 3,
        "row_count": 3,
        "missing": 0,
        "duplicates": 0,
        "park_count": 1,
    } | columns
    path = landing.parquet / "audit" / "seq_audit.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    selects = ", ".join(f"{value}::BIGINT AS {name}" for name, value in values.items())
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"COPY (SELECT 'park-a' AS park_id, '{session}' AS session_id, {selects}) "
            f"TO '{path.as_posix()}' (FORMAT PARQUET)"
        )


def _raw(
    landing: LandingDirs,
    sessions: list[tuple[str, str]],
    age: float,
    *,
    first_seq: int = 1,
    name: str | None = None,
    day: str = "2026-11-15",
) -> Path:
    """Plant one daily raw file of (session, park) rows, last changed ``age`` seconds before NOW."""
    path = landing.raw / "v1" / f"events-{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for session, park in sessions:
        event: dict[str, object] = {"session_id": session, "park_id": park, "seq": first_seq}
        if first_seq == 1:
            event |= {"event_type": "session_start"}
            if name is not None:
                event |= {"park_name": name}
        lines.append(json.dumps(event))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.utime(path, (NOW - age, NOW - age))
    return path


def _run(
    landing: LandingDirs,
    filed: set[str] | None = None,
    *,
    state: str = "ready",
    game: GameState = QUIET,
    lock: bool = False,
    now: float = NOW,
) -> Unfiled:
    return find_unfiled(landing, filed, warehouse=state, now=now, game=game, lock_present=lock)


def test_session_in_parquet_and_warehouse_gives_an_empty_list(landing: LandingDirs) -> None:
    _start(landing, ("s1", "park-a", "Alpha Park"))
    result = _run(landing, {"s1"})
    assert result.parks == ()
    assert render(result) == []


def test_converted_session_waiting_is_offered(landing: LandingDirs) -> None:
    _start(landing, ("s1", "park-a", "Alpha Park"), ("s2", "park-a", "Alpha Park"))
    result = _run(landing, {"s1"})
    assert render(result) == [
        "offer",
        "Play waiting to be filed:",
        OFFER_SESSIONS,
    ]
    assert result.offerable_parks == 1


def test_unconverted_recording_is_offered_after_convert(landing: LandingDirs) -> None:
    _raw(landing, [("r1", "park-b")], 600)
    result = _run(landing, set())
    assert render(result) == [
        "offer-after-convert",
        "Play waiting to be filed:",
        "- park-b: 1 recording(s) never converted",
    ]


def test_list_names_parks_by_first_played_day(landing: LandingDirs) -> None:
    later = T0 + timedelta(days=2)
    plant_session_start(
        landing.parquet,
        [
            event_row(1, session_id="s1", park_name="Alpha Park"),
            event_row(
                1, session_id="s2", park_id="park-b", park_name="Beta Park", emitted_at=later
            ),
        ],
    )
    _audit(landing, "s1", missing=1)
    assert render(_run(landing, set()))[2:4] == [
        FAILED_S1,
        "- Beta Park (first played Nov 14): 1 converted session(s) not filed yet",
    ]


def test_each_park_is_listed_with_its_kind_and_count(landing: LandingDirs) -> None:
    _start(
        landing,
        ("s1", "park-a", "Alpha Park"),
        ("s2", "park-a", "Alpha Park"),
        ("s3", "park-b", "Beta Park"),
    )
    _raw(landing, [("r1", "park-b"), ("r2", "park-b")], 600)
    result = _run(landing, set())
    assert [(p.park_id, p.converted, p.unconverted) for p in result.parks] == [
        ("park-a", ("s1", "s2"), ()),
        ("park-b", ("s3",), ("r1", "r2")),
    ]
    assert render(result)[2:] == [
        "- Alpha Park (first played Nov 12): 2 converted session(s) not filed yet",
        "- Beta Park (first played Nov 12): 1 converted session(s) not filed yet",
        "- Beta Park (first played Nov 12): 2 recording(s) never converted",
    ]
    assert result.offerable_parks == 2


@pytest.mark.parametrize(
    "violation",
    [{"missing": 2}, {"duplicates": 1}, {"first_seq": 2}, {"park_count": 2}],
    ids=["missing", "duplicates", "first_seq", "park_count"],
)
def test_failed_audit_is_named_and_not_offered(
    landing: LandingDirs, violation: dict[str, int]
) -> None:
    _start(landing, ("s1", "park-a", "Alpha Park"))
    _audit(landing, "s1", **violation)
    result = _run(landing, set())
    assert render(result) == [
        "no-offer",
        "Play waiting to be filed:",
        FAILED_S1,
        FAILED_LINE,
    ]
    assert result.offer is False
    assert result.offerable_parks == 0


def test_failed_audit_without_a_session_start_is_failed_not_unconverted(
    landing: LandingDirs,
) -> None:
    _raw(landing, [("s9", "park-a")], 600, first_seq=2)
    _audit(landing, "s9", first_seq=2)
    result = _run(landing, set())
    assert [(p.unconverted, p.failed) for p in result.parks] == [((), ("s9",))]
    assert render(result)[0] == "no-offer"
    assert "recording(s) never converted" not in "\n".join(render(result))


def test_raw_file_changed_119_seconds_ago_is_left_out_with_no_offer(landing: LandingDirs) -> None:
    _raw(landing, [("r1", "park-a")], 119)
    result = _run(landing, set())
    assert result.parks == ()
    assert result.offer is False
    assert render(result) == []
    assert result.recheck_at == NOW + 1


def test_raw_file_changed_121_seconds_ago_is_listed(landing: LandingDirs) -> None:
    _raw(landing, [("r1", "park-a")], 121)
    result = _run(landing, set())
    assert [p.unconverted for p in result.parks] == [("r1",)]
    assert result.offer is True
    assert result.recheck_at is None


def test_two_sessions_in_one_file_at_60_seconds_are_both_left_out(landing: LandingDirs) -> None:
    _raw(landing, [("r1", "park-a"), ("r2", "park-a")], 60)
    assert _run(landing, set()).parks == ()


def test_two_sessions_in_one_file_at_121_seconds_are_both_listed(landing: LandingDirs) -> None:
    _raw(landing, [("r1", "park-a"), ("r2", "park-a")], 121)
    assert [p.unconverted for p in _run(landing, set()).parks] == [("r1", "r2")]


@pytest.mark.parametrize("game", [RUNNING, UNKNOWN], ids=["running", "cannot-tell"])
def test_game_running_or_unreadable_leaves_the_recording_out(
    landing: LandingDirs, game: GameState
) -> None:
    _raw(landing, [("r1", "park-a")], 600)
    result = _run(landing, set(), game=game)
    assert result.parks == ()
    assert result.offer is False


def test_landing_lock_leaves_the_recording_out(landing: LandingDirs) -> None:
    _raw(landing, [("r1", "park-a")], 600)
    result = _run(landing, set(), lock=True)
    assert result.parks == ()
    assert result.offer is False


def test_live_recording_withholds_the_offer_for_a_converted_session(landing: LandingDirs) -> None:
    _start(landing, ("s1", "park-a", "Alpha Park"))
    result = _run(landing, set(), game=RUNNING)
    assert render(result) == [
        "no-offer",
        "Play waiting to be filed:",
        OFFER_SESSIONS,
        RECORDING_LINE,
    ]


def test_building_warehouse_with_nothing_converted_prints_only_the_building_line(
    landing: LandingDirs,
) -> None:
    result = _run(landing, None, state="building")
    assert render(result) == [
        "no-offer",
        "The warehouse is being built, so waiting play cannot be checked now.",
    ]


def test_building_warehouse_read_by_a_writer_hold_prints_only_the_building_line(
    landing: LandingDirs, tmp_path: Path
) -> None:
    path = _warehouse(tmp_path, [])
    _start(landing, ("s1", "park-a", "Alpha Park"))
    with _writer_holds(path):
        state, filed = play_status.warehouse_sessions(path, tmp_path)
    result = _run(landing, filed, state=state)
    assert (state, filed) == ("building", None)
    assert render(result) == [
        "no-offer",
        "The warehouse is being built, so waiting play cannot be checked now.",
    ]


def test_raw_only_park_is_named_from_its_raw_session_start(landing: LandingDirs) -> None:
    _raw(landing, [("r1", "park-b")], 600, name="Gamma Park")
    assert (
        render(_run(landing, set()))[2] == "- Gamma Park (park-b): 1 recording(s) never converted"
    )


def test_raw_only_park_without_a_session_start_is_shown_by_id_only(landing: LandingDirs) -> None:
    _raw(landing, [("r1", "park-b")], 600)
    assert render(_run(landing, set()))[2] == "- park-b: 1 recording(s) never converted"


def test_missing_warehouse_means_every_converted_session_waits(landing: LandingDirs) -> None:
    _start(landing, ("s1", "park-a", "Alpha Park"), ("s2", "park-a", "Alpha Park"))
    result = _run(landing, set(), state="missing")
    assert [p.converted for p in result.parks] == [("s1", "s2")]
    assert result.offer is True


def test_missing_audit_file_means_no_session_failed(landing: LandingDirs) -> None:
    _start(landing, ("s1", "park-a", "Alpha Park"))
    assert [p.failed for p in _run(landing, set()).parks] == [()]


def test_session_with_two_parks_counts_for_both(landing: LandingDirs) -> None:
    _start(landing, ("s1", "park-a", "Alpha Park"), ("s1", "park-b", "Beta Park"))
    assert [(p.park_id, p.converted) for p in _run(landing, set()).parks] == [
        ("park-a", ("s1",)),
        ("park-b", ("s1",)),
    ]


def test_failed_session_withholds_the_offer_even_with_another_offerable_park(
    landing: LandingDirs,
) -> None:
    _start(landing, ("s1", "park-a", "Alpha Park"), ("s2", "park-b", "Beta Park"))
    _audit(landing, "s1", missing=1)
    result = _run(landing, set())
    assert render(result) == [
        "no-offer",
        "Play waiting to be filed:",
        FAILED_S1,
        "- Beta Park (first played Nov 12): 1 converted session(s) not filed yet",
        FAILED_LINE,
    ]
    assert (result.offer, result.offerable_parks) == (False, 1)


def test_audit_failure_of_a_filed_session_is_not_listed(landing: LandingDirs) -> None:
    _start(landing, ("s1", "park-a", "Alpha Park"), ("s2", "park-b", "Beta Park"))
    _audit(landing, "s1", missing=1)
    assert render(_run(landing, {"s1"})) == [
        "offer",
        "Play waiting to be filed:",
        "- Beta Park (first played Nov 12): 1 converted session(s) not filed yet",
    ]


def test_failed_session_is_listed_under_its_audit_park_and_its_raw_park(
    landing: LandingDirs,
) -> None:
    _raw(landing, [("s9", "park-b")], 600, first_seq=2)
    _audit(landing, "s9", first_seq=2)
    result = _run(landing, set())
    assert [(p.park_id, p.failed) for p in result.parks] == [
        ("park-a", ("s9",)),
        ("park-b", ("s9",)),
    ]


def test_live_raw_file_withholds_the_offer_for_a_converted_session(landing: LandingDirs) -> None:
    _start(landing, ("s1", "park-a", "Alpha Park"))
    _raw(landing, [("r1", "park-a")], 60)
    assert render(_run(landing, set())) == [
        "no-offer",
        "Play waiting to be filed:",
        OFFER_SESSIONS,
        RECORDING_LINE,
    ]


def test_failed_reason_comes_before_recording_reason(landing: LandingDirs) -> None:
    _start(landing, ("s1", "park-a", "Alpha Park"))
    _audit(landing, "s1", missing=1)
    _raw(landing, [("r1", "park-a")], 60)
    assert render(_run(landing, set())) == [
        "no-offer",
        "Play waiting to be filed:",
        FAILED_S1,
        FAILED_LINE,
    ]


def test_park_name_comes_from_the_latest_converted_start(landing: LandingDirs) -> None:
    plant_session_start(
        landing.parquet,
        [
            event_row(1, session_id="s1", park_name="Old Name", emitted_at=T0),
            event_row(1, session_id="s2", park_name="New Name", emitted_at=T0 + timedelta(days=1)),
        ],
    )
    assert render(_run(landing, set()))[2] == (
        "- New Name (first played Nov 12): 2 converted session(s) not filed yet"
    )


@pytest.fixture
def command(
    landing: LandingDirs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[LandingDirs, Path]:
    """The command's inputs: a warehouse holding ``s1`` and a game check that says not running."""
    monkeypatch.setattr(unfiled, "platform_game_check", lambda: lambda: QUIET)
    return landing, _warehouse(tmp_path, ["s1"])


def _main(project: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = unfiled.main(["--data-set", "company"], project_dir=project)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_command_prints_nothing_when_nothing_waits(
    command: tuple[LandingDirs, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _start(command[0], ("s1", "park-a", "Alpha Park"))
    assert _main(tmp_path, capsys) == (0, "", "")


def test_command_prints_offer(
    command: tuple[LandingDirs, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _start(command[0], ("s1", "park-a", "Alpha Park"), ("s2", "park-a", "Alpha Park"))
    assert _main(tmp_path, capsys) == (
        0,
        f"offer\nPlay waiting to be filed:\n{OFFER_SESSIONS}\n",
        "",
    )


def test_command_prints_offer_after_convert(
    command: tuple[LandingDirs, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _raw(command[0], [("r1", "park-b")], 600)
    # The planted file is NOW - 600; the command reads the real clock, so it is long quiet.
    code, out, err = _main(tmp_path, capsys)
    assert (code, err) == (0, "")
    assert out == (
        "offer-after-convert\nPlay waiting to be filed:\n- park-b: 1 recording(s) never converted\n"
    )


def test_command_prints_no_offer_for_a_failed_session(
    command: tuple[LandingDirs, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _start(command[0], ("s2", "park-a", "Alpha Park"))
    _audit(command[0], "s2", missing=1)
    code, out, _ = _main(tmp_path, capsys)
    assert code == 0
    assert out.splitlines()[0] == "no-offer"
    assert out.splitlines()[-1] == FAILED_LINE


def test_command_with_a_building_warehouse_prints_only_the_building_line(
    command: tuple[LandingDirs, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with _writer_holds(command[1]):
        result = _main(tmp_path, capsys)
    assert result == (
        0,
        "no-offer\nThe warehouse is being built, so waiting play cannot be checked now.\n",
        "",
    )


def test_command_refuses_another_data_set(
    command: tuple[LandingDirs, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = unfiled.main(["--data-set", "rehearsal"], project_dir=tmp_path)
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert captured.err == (
        "unfiled refused: data-set: Only company play can be filed, got: rehearsal\n"
    )


def test_command_refuses_a_missing_data_set(
    command: tuple[LandingDirs, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert unfiled.main([], project_dir=tmp_path) == 2
    assert capsys.readouterr().err.startswith("unfiled refused: usage:")


def test_command_fails_on_a_damaged_warehouse(
    command: tuple[LandingDirs, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    command[1].write_bytes(b"not a database" * 100)
    code, out, err = _main(tmp_path, capsys)
    assert (code, out) == (1, "")
    assert err.startswith("unfiled failed: io:")

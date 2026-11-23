"""Tests for ``park_facts`` on odd landing rows: NULL columns, repeated starts, NULL names.

The planting helpers and fixtures are those of ``test_park_label``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from openrct2_analytics.config import LandingDirs
from openrct2_analytics.ingest import park_label
from openrct2_analytics.ingest.game_check import GameState
from openrct2_analytics.ingest.unfiled import find_unfiled, render
from tests.autopilot_fixtures import event_row, plant_session_start
from tests.test_managed_years_raw import start_line, write_raw_lines
from tests.test_park_label import _utc_minus_8 as _utc_minus_8  # noqa: F401  (pytest fixture)
from tests.test_park_label import converted, label_map, raw
from tests.test_park_label import landing as landing  # noqa: F401  (pytest fixture)

SAVED = datetime(2026, 11, 15, 20, 0, tzinfo=UTC)
EARLIER = datetime(2026, 11, 10, 20, 0, tzinfo=UTC)


def test_a_row_with_no_game_year_gives_no_first_played(landing: LandingDirs) -> None:
    plant_session_start(
        landing.parquet,
        [
            event_row(1, session_id="s1", park_id="pa", park_name="Alpha", emitted_at=EARLIER)
            | {"game_year": None},
            event_row(1, session_id="s2", park_id="pa", park_name="Alpha", emitted_at=SAVED),
            event_row(1, session_id="s3", park_id="pb", park_name="Beta", emitted_at=EARLIER)
            | {"game_year": None},
        ],
    )

    assert label_map(landing) == {"pa": "Alpha (first played Nov 15)", "pb": "Beta (pb)"}


def test_a_row_with_no_emitted_at_gives_no_first_played(landing: LandingDirs) -> None:
    plant_session_start(
        landing.parquet,
        [
            {**event_row(1, session_id="s1", park_id="pa", park_name="Alpha"), "emitted_at": None},
            event_row(1, session_id="s2", park_id="pa", park_name="Alpha", emitted_at=SAVED),
            {**event_row(1, session_id="s3", park_id="pb", park_name="Beta"), "emitted_at": None},
        ],
    )

    assert label_map(landing) == {"pa": "Alpha (first played Nov 15)", "pb": "Beta (pb)"}


def test_a_converted_row_with_no_emitted_at_does_not_stop_a_raw_instant(
    landing: LandingDirs,
) -> None:
    plant_session_start(
        landing.parquet,
        [{**event_row(1, session_id="s1", park_id="pa", park_name="Alpha"), "emitted_at": None}],
    )
    raw(landing, "s2", "pa", "Alpha", when="2026-11-12T20:00:00Z")

    assert label_map(landing) == {"pa": "Alpha (first played Nov 12)"}


def test_unfiled_lists_a_park_whose_rows_have_no_year_or_instant(landing: LandingDirs) -> None:
    plant_session_start(
        landing.parquet,
        [
            event_row(1, session_id="s1", park_id="pa", park_name="Alpha", emitted_at=EARLIER)
            | {"game_year": None},
            {**event_row(1, session_id="s2", park_id="pa", park_name="Alpha"), "emitted_at": None},
            event_row(1, session_id="s3", park_id="pa", park_name="Alpha", emitted_at=SAVED),
        ],
    )

    result = find_unfiled(
        landing, set(), warehouse="ready", now=1.0e9, game=GameState.NOT_RUNNING, lock_present=False
    )

    assert render(result) == [
        "offer",
        "Play waiting to be filed:",
        "- Alpha (first played Nov 15): 3 converted session(s) not filed yet",
    ]


def test_a_null_latest_name_falls_back_to_the_latest_name(landing: LandingDirs) -> None:
    converted(
        landing,
        [
            ("pa", "s1", "Bumbly", "2026-11-15T20:00:00Z"),
            ("pa", "s2", None, "2026-11-16T20:00:00Z"),
        ],
    )

    facts = park_label.park_facts(landing)

    assert park_label.labels(facts) == {"pa": "Bumbly (first played Nov 15)"}
    assert facts["pa"].converted_name == "Bumbly"


def test_repeated_raw_starts_in_reverse_order_keep_the_earliest(landing: LandingDirs) -> None:
    write_raw_lines(
        landing.raw,
        "events-a.jsonl",
        [
            start_line("s1", "pa", park_name="Late", emitted_at="2026-11-16T20:00:00Z"),
            start_line("s1", "pa", park_name="Early", emitted_at="2026-11-12T20:00:00Z"),
        ],
    )

    assert label_map(landing) == {"pa": "Early (first played Nov 12)"}


def test_repeated_raw_starts_across_files_keep_the_earliest(landing: LandingDirs) -> None:
    write_raw_lines(
        landing.raw,
        "events-a.jsonl",
        [start_line("s1", "pa", park_name="Late", emitted_at="2026-11-16T20:00:00Z")],
    )
    write_raw_lines(
        landing.raw,
        "events-b.jsonl",
        [start_line("s1", "pa", park_name="Early", emitted_at="2026-11-12T20:00:00Z")],
    )

    assert label_map(landing) == {"pa": "Early (first played Nov 12)"}

"""Negative control for the rules of the event types after park_snapshot and their new fields.

Covers finance_month, session_start (with its climate and loaded-save fields), ride_snapshot,
save_written, game_action, the new plugin_stats counters and the park_snapshot weather fields.
Each case breaks one thing in the good data from ``tests.test_contracts.write_data`` and must
fail on its named check; empty statement, session and save files must pass, and so must the
placeholders a ride snapshot is sent with and the new optional fields left null.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest import contracts
from tests.test_contracts import GAME_ACTION, WEATHER, failures, write_data

WORK_COUNTERS = ("work_units_total", "work_items_skipped_total", "work_queue_length")
LOADED_SAVE_FIELDS = (
    "loaded_save_id",
    "loaded_save_session_id",
    "loaded_save_seq_floor",
    "loaded_save_lines_waiting",
)
RIDE_REQUIRED_FIELDS = (
    "ride_id",
    "ride_name",
    "ride_type",
    "ride_object",
    "classification",
    "status",
    "total_customers",
    "build_date_months_elapsed",
    "age_months",
    "station_count",
)
RIDE_OPTIONAL_FIELDS = (
    "excitement_hundredths",
    "intensity_hundredths",
    "nausea_hundredths",
    "price_1_tenths",
    "price_2_tenths",
    "shop_item",
    "shop_item_secondary",
    "running_cost_per_fortnight_tenths",
    "total_profit_tenths",
    "income_per_game_hour_tenths",
    "profit_per_game_hour_tenths",
    "value_tenths",
    "reliability_pct",
    "downtime_pct",
    "satisfaction_pct",
    "guests_on_ride",
    "queue_time_max_minutes",
    "max_speed_mph",
    "average_speed_mph",
    "ride_time_seconds",
    "ride_length_meters",
    "max_positive_vertical_g",
    "max_negative_vertical_g",
    "max_lateral_g",
    "total_air_time_seconds",
    "drop_count",
    "lift_hill_count",
    "highest_drop_height_units",
    "inversion_count",
    "ride_category",
)


def test_write_data_builds_every_event_file_with_rows(tmp_path: Path) -> None:
    root = write_data(tmp_path / "good")

    counts = {
        path.stem: duckdb.sql(f"SELECT count(*) FROM '{path.as_posix()}'").fetchall()[0][0]
        for path in sorted((root / "v1").glob("*.parquet"))
    }

    assert counts == {
        "finance_month": 1,
        "game_action": 0,
        "guest_arrived": 1,
        "guest_boarded": 1,
        "guest_left": 1,
        "guest_refused": 1,
        "guest_snapshot": 1,
        "park_snapshot": 2,
        "plugin_stats": 2,
        "ride_snapshot": 1,
        "save_written": 1,
        "session_start": 1,
        "weather_change": 0,
    }


def test_zero_row_statement_and_session_files_pass(tmp_path: Path) -> None:
    root = write_data(tmp_path / "empty", "DELETE FROM finance; DELETE FROM start")

    assert failures(root) == []
    assert contracts.main(["--data-root", str(root)]) == 0


def test_a_statement_with_the_booked_amount_passes(tmp_path: Path) -> None:
    mutation = "UPDATE finance SET new_month_booked_tenths = -75"

    assert failures(write_data(tmp_path / "booked", mutation)) == []


def test_a_zero_row_ride_snapshot_file_passes(tmp_path: Path) -> None:
    root = write_data(tmp_path / "empty", "DELETE FROM ride")

    assert failures(root) == []


def test_every_classification_and_status_passes(tmp_path: Path) -> None:
    # One extra row per value, each with its own ride_id and seq so the key stays unique.
    rows = [
        (14, "ride", "closed"),
        (15, "stall", "open"),
        (16, "facility", "testing"),
        (17, "ride", "simulating"),
    ]
    values = ", ".join(f"({n}, '{c}', '{s}')" for n, c, s in rows)
    mutation = (
        "INSERT INTO ride SELECT r.* REPLACE ('sess-' || v.n AS event_id, v.n::BIGINT AS seq,"
        " v.n::INTEGER AS ride_id, v.c AS classification, v.s AS status)"
        f" FROM ride AS r, (VALUES {values}) AS v(n, c, s)"
    )

    assert failures(write_data(tmp_path / "all", mutation)) == []


def test_ride_snapshot_placeholders_and_nulls_pass(tmp_path: Path) -> None:
    placeholders = (
        "UPDATE ride SET excitement_hundredths = -1, intensity_hundredths = -1,"
        " nausea_hundredths = -1, satisfaction_pct = 1275, shop_item = 255,"
        " shop_item_secondary = 255, station_count = 0"
    )
    nulls = "UPDATE ride SET " + ", ".join(f"{name} = NULL" for name in RIDE_OPTIONAL_FIELDS)

    assert failures(write_data(tmp_path / "placeholders", placeholders)) == []
    assert failures(write_data(tmp_path / "nulls", nulls)) == []


def test_the_new_session_start_and_park_snapshot_fields_null_pass(tmp_path: Path) -> None:
    # Events from plugins before 0.3.0, and parks never saved, leave these fields null.
    nulls = (
        "UPDATE start SET climate = NULL, "
        + ", ".join(f"{name} = NULL" for name in LOADED_SAVE_FIELDS)
        + "; UPDATE snapshot SET weather = NULL, temperature_c = NULL"
    )

    assert failures(write_data(tmp_path / "old", nulls)) == []


def test_a_zero_row_save_written_file_passes(tmp_path: Path) -> None:
    assert failures(write_data(tmp_path / "empty", "DELETE FROM save")) == []


def test_a_weather_change_with_its_optional_fields_null_passes(tmp_path: Path) -> None:
    row = f"INSERT INTO weather SELECT * FROM (SELECT {WEATHER.format(seq=14, day=2, ticks=8400)})"
    nulls = "; UPDATE weather SET upcoming_weather = NULL, temperature_c = NULL"

    assert failures(write_data(tmp_path / "optional", row + nulls)) == []


# Seq 15 sits outside write_data's gap-free run; the contract runner does not audit seq.
GAME_ACTION_ROW = (
    "INSERT INTO game_action SELECT * FROM (SELECT "
    + GAME_ACTION.format(seq=15, day=2, ticks=8400)
    + ")"
)
GAME_ACTION_OPTIONAL_FIELDS = (
    "args_flags",
    "type",
    "args_ride",
    "args_ride_type",
    "args_ride_object",
    "args_price_tenths",
    "args_x",
    "args_y",
    "args_z",
    "result_error",
    "result_cost_tenths",
    "result_ride",
)
GAME_ACTION_REQUIRED_FIELDS = (
    "hook",
    "action",
    "action_label",
    "is_client_only",
    "player",
    "args_json",
    "action_at_ticks",
    "action_game_year",
    "action_game_month",
    "action_game_day",
)


def test_a_game_action_with_its_optional_fields_null_passes(tmp_path: Path) -> None:
    nulls = "; UPDATE game_action SET " + ", ".join(
        f"{name} = NULL" for name in GAME_ACTION_OPTIONAL_FIELDS
    )

    assert failures(write_data(tmp_path / "optional", GAME_ACTION_ROW + nulls)) == []


def test_a_game_action_with_every_field_set_passes(tmp_path: Path) -> None:
    assert failures(write_data(tmp_path / "full", GAME_ACTION_ROW)) == []


def test_plugin_stats_with_null_work_counters_passes(tmp_path: Path) -> None:
    # The converter writes every contract column, null for events from a plugin before 0.3.0.
    nulls = "UPDATE stats SET " + ", ".join(f"{name} = NULL" for name in WORK_COUNTERS)

    assert failures(write_data(tmp_path / "old", nulls)) == []


# (case name, SQL that breaks the good data, text of the check that must fail)
BROKEN_CASES = [
    (
        "two_statements_for_one_session_and_month",
        "INSERT INTO finance SELECT * REPLACE ('sess-14' AS event_id, 14::BIGINT AS seq)"
        " FROM finance",
        "primary key (session_id, statement_year, statement_month) has no duplicate",
    ),
    (
        "statement_not_on_day_1",
        "UPDATE finance SET game_day = 2",
        "every statement is read on game day 1",
    ),
    (
        "statement_month_not_before_the_envelope_date",
        "UPDATE finance SET statement_month = 1",
        "the statement month is the month before the envelope date",
    ),
    (
        "statement_year_wrong_across_the_year_wrap",
        "UPDATE finance SET game_year = 2, game_month = 0, statement_year = 2, statement_month = 7",
        "the statement month is the month before the envelope date",
    ),
    (
        "statement_year_wrong_outside_the_year_wrap",
        "UPDATE finance SET statement_year = 2",
        "the statement month is the month before the envelope date",
    ),
    *[
        (
            f"fractional_money_value_in_{field}",
            f"ALTER TABLE finance ALTER {field} TYPE DOUBLE; UPDATE finance SET {field} = -12.5",
            "every money field is a whole number",
        )
        for field in ("wages_tenths", "cash_tenths", "bank_loan_tenths", "new_month_booked_tenths")
    ],
    (
        "statement_year_below_one",
        "UPDATE finance SET statement_year = 0",
        "field statement_year has a minimum of 1",
    ),
    (
        "statement_month_above_7",
        "UPDATE finance SET statement_month = 8, game_month = 0, game_year = 2",
        "field statement_month has a maximum of 7",
    ),
    (
        "negative_bank_loan",
        "UPDATE finance SET bank_loan_tenths = -1",
        "field bank_loan_tenths has a minimum of 0",
    ),
    (
        "api_version_below_one",
        "UPDATE start SET api_version = 0",
        "field api_version has a minimum of 1",
    ),
    (
        "negative_game_speed_in_session_start",
        "UPDATE start SET game_speed = -1",
        "field game_speed has a minimum of 0",
    ),
    (
        "negative_unread_months_counter",
        "UPDATE stats SET finance_months_unread_total = -1",
        "field finance_months_unread_total has a minimum of 0",
    ),
    (
        "session_start_not_at_seq_1",
        "UPDATE start SET seq = 7, event_id = 'sess-7'",
        "session_start is the session's first event",
    ),
    *[
        (
            f"{field}_below_minus_1",
            f"UPDATE ride SET {field} = -2",
            f"field {field} has a minimum of -1",
        )
        for field in ("excitement_hundredths", "intensity_hundredths", "nausea_hundredths")
    ],
    (
        "negative_station_count",
        "UPDATE ride SET station_count = -1",
        "field station_count has a minimum of 0",
    ),
    (
        "unknown_classification",
        "UPDATE ride SET classification = 'attraction'",
        "classification is ride, stall or facility",
    ),
    (
        "unknown_status",
        "UPDATE ride SET status = 'broken'",
        "status is closed, open, testing or simulating",
    ),
    *[
        (
            f"ride_missing_{field}",
            f"UPDATE ride SET {field} = NULL",
            f"{field} has no missing values",
        )
        for field in RIDE_REQUIRED_FIELDS
    ],
    (
        "two_snapshots_of_one_ride_on_one_tick",
        "INSERT INTO ride SELECT * REPLACE ('sess-14' AS event_id, 14::BIGINT AS seq) FROM ride",
        "primary key (session_id, ride_id, game_ticks_elapsed) has no duplicate",
    ),
    *[
        (f"negative_{field}", f"UPDATE stats SET {field} = -1", f"field {field} has a minimum of 0")
        for field in WORK_COUNTERS
    ],
    (
        "save_written_missing_save_id",
        "UPDATE save SET save_id = NULL",
        "save_id has no missing values",
    ),
    (
        "two_save_written_rows_for_one_save_id",
        "INSERT INTO save SELECT * REPLACE ('sess-14' AS event_id, 14::BIGINT AS seq) FROM save",
        "primary key field save_id has no duplicate",
    ),
    (
        "weather_change_to_the_same_weather",
        "INSERT INTO weather SELECT * REPLACE ('rain' AS previous_weather) FROM (SELECT "
        + WEATHER.format(seq=14, day=2, ticks=8400)
        + ")",
        "a change has a different weather from the one before it",
    ),
    (
        "weather_change_missing_previous_weather",
        "INSERT INTO weather SELECT * REPLACE (NULL AS previous_weather) FROM (SELECT "
        + WEATHER.format(seq=14, day=2, ticks=8400)
        + ")",
        "previous_weather has no missing values",
    ),
    *[
        (
            f"game_action_missing_{field}",
            GAME_ACTION_ROW + f"; UPDATE game_action SET {field} = NULL",
            f"{field} has no missing values",
        )
        for field in GAME_ACTION_REQUIRED_FIELDS
    ],
    (
        "game_action_with_an_unknown_hook",
        GAME_ACTION_ROW + "; UPDATE game_action SET hook = 'run'",
        "the hook is query or execute",
    ),
    (
        "game_action_with_an_unknown_label",
        GAME_ACTION_ROW + "; UPDATE game_action SET action_label = 'guess'",
        "the label is confirmed, preview or prediction",
    ),
    (
        "game_action_on_a_month_above_7",
        GAME_ACTION_ROW + "; UPDATE game_action SET action_game_month = 8",
        "field action_game_month has a maximum of 7",
    ),
    *[
        (f"negative_{field}", f"UPDATE start SET {field} = -1", f"field {field} has a minimum of 0")
        for field in ("loaded_save_seq_floor", "loaded_save_lines_waiting")
    ],
    (
        "two_session_starts_for_one_session",
        "INSERT INTO start SELECT * REPLACE ('sess-8' AS event_id, 8::BIGINT AS seq) FROM start",
        "primary key field session_id has no duplicate",
    ),
]


@pytest.mark.parametrize(("name", "mutation", "failed_check"), BROKEN_CASES)
def test_each_broken_case_fails_on_its_named_check(
    tmp_path: Path, name: str, mutation: str, failed_check: str
) -> None:
    root = write_data(tmp_path / name, mutation)

    problems = failures(root)

    assert any(failed_check in line and ": failed (" in line for line in problems), problems
    assert contracts.main(["--data-root", str(root)]) == 1


def test_the_year_wrap_statement_passes(tmp_path: Path) -> None:
    root = write_data(
        tmp_path / "wrap",
        "UPDATE finance SET game_year = 2, game_month = 0, statement_year = 1, statement_month = 7",
    )

    assert failures(root) == []

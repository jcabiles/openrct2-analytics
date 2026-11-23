"""Converter tests for the lineage columns `_raw_file` and `_raw_line`, over raw fixtures.

One session sends one line of every contracted type across two raw files with blank
lines between them. Each expected row is written here by hand from its fixture JSON, as
SQL literals that carry the column name, type and value, so no expectation is read back
from the converter.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest.convert import convert
from tests.test_convert import land

FIRST, SECOND = "events-2026-10-01.jsonl", "events-2026-10-02.jsonl"
ENVELOPE_JSON = (
    '"schema_version": 1, "event_type": "{kind}", "plugin_version": "0.4.0",'
    ' "park_id": "lpark1", "session_id": "sa", "seq": {seq}, "event_id": "sa-{seq}",'
    ' "game_year": 2, "game_month": 3, "game_day": {seq}, "game_ticks_elapsed": 5000000000,'
    ' "emitted_at": "2026-10-01T08:00:00.250Z", "received_at": "2026-10-01T10:00:01.5+02:00"'
)
ENVELOPE_SQL = """
    1::INTEGER AS schema_version, '{kind}' AS event_type, '0.4.0' AS plugin_version,
    'lpark1' AS park_id, 'sa' AS session_id, {seq}::BIGINT AS seq, 'sa-{seq}' AS event_id,
    2::INTEGER AS game_year, 3::INTEGER AS game_month, {seq}::INTEGER AS game_day,
    5000000000::BIGINT AS game_ticks_elapsed,
    TIMESTAMPTZ '2026-10-01 08:00:00.25+00' AS emitted_at,
    TIMESTAMPTZ '2026-10-01 08:00:01.5+00' AS received_at
"""
# event type: (seq, payload JSON, the payload's expected columns as SQL literals)
EVENTS: dict[str, tuple[int, str, str]] = {
    "session_start": (
        1,
        '"api_version": 110, "park_name": "Lineage Park", "scenario_name": "Test Scenario",'
        ' "headless": true, "game_speed": 4, "climate": "coolAndWet"',
        """110::INTEGER AS api_version, 'Lineage Park' AS park_name,
        'Test Scenario' AS scenario_name, true AS headless, 4::INTEGER AS game_speed,
        'coolAndWet' AS climate, NULL::VARCHAR AS loaded_save_id,
        NULL::VARCHAR AS loaded_save_session_id, NULL::BIGINT AS loaded_save_seq_floor,
        NULL::INTEGER AS loaded_save_lines_waiting""",
    ),
    "plugin_stats": (
        2,
        '"period_start_ticks": 0, "period_end_ticks": 4000, "period_ticks": 4000,'
        ' "work_ms_total": 1.5, "worst_tick_ms": 0.25, "worst_tick_at_ticks": 40,'
        ' "callbacks": 3, "warmup": true, "clock": "performance", "game_speed": 4,'
        ' "lines_dropped_total": 0, "write_partial_total": 1, "write_error_total": 2,'
        ' "connect_attempts_total": 1, "queue_length": 5, "finance_months_unread_total": 0,'
        ' "work_units_total": 6000000000, "work_items_skipped_total": 2,'
        ' "work_queue_length": 7, "work_items_failed_total": 0, "worst_step_ms": 0.125,'
        ' "worst_step_kind": "ride", "worst_tick_kind_ms": "ride=0.2",'
        ' "worst_day_start_tick_ms": 0.75, "guest_fields_ms_total": 0.5,'
        ' "continuous_items_pending": 3, "lines_queued_max": 9, "guests_known": 11,'
        ' "guests_known_in_park": 10, "arrivals_recorded_total": 12,'
        ' "boarding_polls_total": 13, "boarders_queued_total": 14,'
        ' "game_actions_sent_preview_total": 15, "game_actions_sent_prediction_total": 16,'
        ' "game_actions_sent_confirmed_total": 17, "game_actions_dropped_preview_total": 0,'
        ' "game_actions_dropped_prediction_total": 1, "game_actions_dropped_confirmed_total": 2,'
        ' "action_query_ms_total": 0.5, "action_execute_ms_total": 1.25,'
        ' "game_actions_skipped_preview_total": 18, "game_actions_skipped_prediction_total": 19,'
        ' "game_actions_skipped_confirmed_total": 20, "game_actions_skipped_unknown_total": 3,'
        ' "game_actions_skipped_cheat_total": 1',
        """0::BIGINT AS period_start_ticks, 4000::BIGINT AS period_end_ticks,
        4000::BIGINT AS period_ticks, 1.5::DOUBLE AS work_ms_total,
        0.25::DOUBLE AS worst_tick_ms, 40::BIGINT AS worst_tick_at_ticks,
        3::INTEGER AS callbacks, true AS warmup, 'performance' AS clock,
        4::INTEGER AS game_speed, 0::BIGINT AS lines_dropped_total,
        1::BIGINT AS write_partial_total, 2::BIGINT AS write_error_total,
        1::BIGINT AS connect_attempts_total, 5::INTEGER AS queue_length,
        0::BIGINT AS finance_months_unread_total, 6000000000::BIGINT AS work_units_total,
        2::BIGINT AS work_items_skipped_total, 7::INTEGER AS work_queue_length,
        0::BIGINT AS work_items_failed_total, 0.125::DOUBLE AS worst_step_ms,
        'ride' AS worst_step_kind, 'ride=0.2' AS worst_tick_kind_ms,
        0.75::DOUBLE AS worst_day_start_tick_ms, 0.5::DOUBLE AS guest_fields_ms_total,
        3::INTEGER AS continuous_items_pending, 9::INTEGER AS lines_queued_max,
        11::INTEGER AS guests_known, 10::INTEGER AS guests_known_in_park,
        12::BIGINT AS arrivals_recorded_total, 13::BIGINT AS boarding_polls_total,
        14::BIGINT AS boarders_queued_total, 15::BIGINT AS game_actions_sent_preview_total,
        16::BIGINT AS game_actions_sent_prediction_total,
        17::BIGINT AS game_actions_sent_confirmed_total,
        0::BIGINT AS game_actions_dropped_preview_total,
        1::BIGINT AS game_actions_dropped_prediction_total,
        2::BIGINT AS game_actions_dropped_confirmed_total,
        0.5::DOUBLE AS action_query_ms_total, 1.25::DOUBLE AS action_execute_ms_total,
        18::BIGINT AS game_actions_skipped_preview_total,
        19::BIGINT AS game_actions_skipped_prediction_total,
        20::BIGINT AS game_actions_skipped_confirmed_total,
        3::BIGINT AS game_actions_skipped_unknown_total,
        1::BIGINT AS game_actions_skipped_cheat_total""",
    ),
    "park_snapshot": (
        3,
        '"cash_tenths": -12345, "guests_in_park": 7, "park_rating": 650,'
        ' "total_admissions": 12, "weather": "heavyRain", "temperature_c": -3',
        """-12345::BIGINT AS cash_tenths, 7::INTEGER AS guests_in_park,
        650::INTEGER AS park_rating, 12::BIGINT AS total_admissions,
        'heavyRain' AS weather, -3::INTEGER AS temperature_c""",
    ),
    "finance_month": (
        4,
        '"statement_year": 1, "statement_month": 0, "ride_construction_tenths": -10,'
        ' "ride_runningcosts_tenths": -20, "land_purchase_tenths": 40,'
        ' "landscaping_tenths": -40, "park_entrance_tickets_tenths": 2500000000000,'
        ' "park_ride_tickets_tenths": 60, "shop_sales_tenths": 70, "shop_stock_tenths": -80,'
        ' "food_drink_sales_tenths": 90, "food_drink_stock_tenths": -100,'
        ' "wages_tenths": -110, "marketing_tenths": -120, "research_tenths": -130,'
        ' "interest_tenths": -140, "cash_tenths": -12345, "bank_loan_tenths": 100000',
        """1::INTEGER AS statement_year, 0::INTEGER AS statement_month,
        -10::BIGINT AS ride_construction_tenths, -20::BIGINT AS ride_runningcosts_tenths,
        40::BIGINT AS land_purchase_tenths, -40::BIGINT AS landscaping_tenths,
        2500000000000::BIGINT AS park_entrance_tickets_tenths,
        60::BIGINT AS park_ride_tickets_tenths, 70::BIGINT AS shop_sales_tenths,
        -80::BIGINT AS shop_stock_tenths, 90::BIGINT AS food_drink_sales_tenths,
        -100::BIGINT AS food_drink_stock_tenths, -110::BIGINT AS wages_tenths,
        -120::BIGINT AS marketing_tenths, -130::BIGINT AS research_tenths,
        -140::BIGINT AS interest_tenths, -12345::BIGINT AS cash_tenths,
        100000::BIGINT AS bank_loan_tenths, NULL::BIGINT AS new_month_booked_tenths""",
    ),
    "ride_snapshot": (
        5,
        '"ride_id": 3, "ride_name": "Carousel 1", "ride_type": 28,'
        ' "ride_object": "rct2.ride.cars", "classification": "ride", "status": "open",'
        ' "excitement_hundredths": 652, "intensity_hundredths": 410,'
        ' "nausea_hundredths": 120, "price_1_tenths": 20, "price_2_tenths": 0,'
        ' "shop_item": 255, "shop_item_secondary": 255, "total_customers": 4800,'
        ' "build_date_months_elapsed": 2, "age_months": 5,'
        ' "running_cost_per_fortnight_tenths": 960, "total_profit_tenths": null,'
        ' "income_per_game_hour_tenths": 300, "profit_per_game_hour_tenths": 120,'
        ' "value_tenths": 70, "reliability_pct": 97, "downtime_pct": 3,'
        ' "satisfaction_pct": 80, "guests_on_ride": 6, "station_count": 1,'
        ' "queue_time_max_minutes": 2',
        """3::INTEGER AS ride_id, 'Carousel 1' AS ride_name, 28::INTEGER AS ride_type,
        'rct2.ride.cars' AS ride_object, 'ride' AS classification, 'open' AS status,
        652::INTEGER AS excitement_hundredths, 410::INTEGER AS intensity_hundredths,
        120::INTEGER AS nausea_hundredths, 20::BIGINT AS price_1_tenths,
        0::BIGINT AS price_2_tenths, 255::INTEGER AS shop_item,
        255::INTEGER AS shop_item_secondary, 4800::BIGINT AS total_customers,
        2::INTEGER AS build_date_months_elapsed, 5::INTEGER AS age_months,
        960::BIGINT AS running_cost_per_fortnight_tenths, NULL::BIGINT AS total_profit_tenths,
        300::BIGINT AS income_per_game_hour_tenths, 120::BIGINT AS profit_per_game_hour_tenths,
        70::BIGINT AS value_tenths, 97::INTEGER AS reliability_pct,
        3::INTEGER AS downtime_pct, 80::INTEGER AS satisfaction_pct,
        6::INTEGER AS guests_on_ride, 1::INTEGER AS station_count,
        2::INTEGER AS queue_time_max_minutes, NULL::DOUBLE AS max_speed_mph,
        NULL::DOUBLE AS average_speed_mph, NULL::DOUBLE AS ride_time_seconds,
        NULL::DOUBLE AS ride_length_meters, NULL::DOUBLE AS max_positive_vertical_g,
        NULL::DOUBLE AS max_negative_vertical_g, NULL::DOUBLE AS max_lateral_g,
        NULL::DOUBLE AS total_air_time_seconds, NULL::INTEGER AS drop_count,
        NULL::INTEGER AS lift_hill_count, NULL::DOUBLE AS highest_drop_height_units,
        NULL::INTEGER AS inversion_count, NULL::VARCHAR AS ride_category""",
    ),
    "save_written": (6, '"save_id": "v1790000000000-abc"', "'v1790000000000-abc' AS save_id"),
    "guest_arrived": (
        7,
        '"guest_key": 1, "guest_id": 40, "generated_at_ticks": 7990, "in_cohort": true,'
        ' "guest_cash_tenths": 1200',
        """1::INTEGER AS guest_key, 40::INTEGER AS guest_id,
        7990::BIGINT AS generated_at_ticks, true AS in_cohort,
        1200::BIGINT AS guest_cash_tenths""",
    ),
    "guest_boarded": (
        8,
        '"guest_id": 40, "guest_key": null, "ride_id": 3, "detected_at_ticks": 8080,'
        ' "ride_price_listed_tenths": 20, "happiness": 180, "min_intensity": 2,'
        ' "max_intensity": 9, "nausea_tolerance": 1, "guest_cash_tenths": 900',
        """40::INTEGER AS guest_id, NULL::INTEGER AS guest_key, 3::INTEGER AS ride_id,
        8080::BIGINT AS detected_at_ticks, 20::BIGINT AS ride_price_listed_tenths,
        180::INTEGER AS happiness, 2::INTEGER AS min_intensity,
        9::INTEGER AS max_intensity, 1::INTEGER AS nausea_tolerance,
        900::BIGINT AS guest_cash_tenths""",
    ),
    "guest_left": (
        9,
        '"guest_key": 1, "guest_id": 40, "exit_reason": "id_reused", "entered_park": false,'
        ' "arrived_in_session": true, "in_cohort": false',
        """1::INTEGER AS guest_key, 40::INTEGER AS guest_id, 'id_reused' AS exit_reason,
        false AS entered_park, true AS arrived_in_session, false AS in_cohort""",
    ),
    "guest_refused": (
        10,
        '"guest_key": 1, "guest_id": 40, "thought_type": "bad_value", "ride_id": 3',
        """1::INTEGER AS guest_key, 40::INTEGER AS guest_id,
        'bad_value' AS thought_type, 3::INTEGER AS ride_id""",
    ),
    "guest_snapshot": (
        11,
        '"guest_key": 1, "guest_id": 40, "happiness": 180, "hunger": 20, "thirst": 30,'
        ' "nausea": 0, "energy": 100, "guest_cash_tenths": 900, "items_carried": "",'
        ' "thought_type": "hungry", "thought_item": 255',
        """1::INTEGER AS guest_key, 40::INTEGER AS guest_id, 180::INTEGER AS happiness,
        20::INTEGER AS hunger, 30::INTEGER AS thirst, 0::INTEGER AS nausea,
        100::INTEGER AS energy, 900::BIGINT AS guest_cash_tenths, '' AS items_carried,
        'hungry' AS thought_type, 255::INTEGER AS thought_item""",
    ),
    "game_action": (
        13,
        '"hook": "execute", "action": "ridesetprice", "action_label": "preview",'
        ' "args_flags": -2147483584, "is_client_only": true, "player": -1, "type": 2,'
        ' "args_json": "{\\"ride\\":3}", "args_ride": 3, "args_ride_type": 28,'
        ' "args_ride_object": 4, "args_price_tenths": 125, "args_x": 10, "args_y": 11,'
        ' "args_z": 12, "result_error": 0, "result_cost_tenths": 40, "result_ride": 3,'
        ' "action_at_ticks": 7990, "action_game_year": 2, "action_game_month": 3,'
        ' "action_game_day": 4',
        """'execute' AS hook, 'ridesetprice' AS action, 'preview' AS action_label,
        -2147483584::BIGINT AS args_flags, true AS is_client_only, -1::INTEGER AS player,
        2::INTEGER AS type, '{"ride":3}' AS args_json, 3::INTEGER AS args_ride,
        28::INTEGER AS args_ride_type, 4::INTEGER AS args_ride_object,
        125::BIGINT AS args_price_tenths, 10::INTEGER AS args_x, 11::INTEGER AS args_y,
        12::INTEGER AS args_z, 0::INTEGER AS result_error, 40::BIGINT AS result_cost_tenths,
        3::INTEGER AS result_ride, 7990::BIGINT AS action_at_ticks,
        2::INTEGER AS action_game_year, 3::INTEGER AS action_game_month,
        4::INTEGER AS action_game_day""",
    ),
    "weather_change": (
        12,
        '"weather": "rain", "previous_weather": "sunny", "upcoming_weather": "cloudy",'
        ' "temperature_c": -3',
        """'rain' AS weather, 'sunny' AS previous_weather, 'cloudy' AS upcoming_weather,
        -3::INTEGER AS temperature_c""",
    ),
}
# Each raw file's physical lines in order; "" and "   " are blank lines, still counted.
LAYOUT: dict[str, list[str]] = {
    FIRST: ["", "session_start", "plugin_stats", "", "   ", "park_snapshot", "finance_month"]
    + ["game_action"],
    SECOND: ["ride_snapshot", "save_written", "", "guest_arrived", "guest_boarded"]
    + ["", "", "guest_left", "guest_refused", "guest_snapshot", "weather_change"],
}
# Where each event type's line sits, counted by hand from LAYOUT.
LINEAGE: dict[str, tuple[str, int]] = {
    "session_start": (FIRST, 2),
    "plugin_stats": (FIRST, 3),
    "park_snapshot": (FIRST, 6),
    "finance_month": (FIRST, 7),
    "game_action": (FIRST, 8),
    "ride_snapshot": (SECOND, 1),
    "save_written": (SECOND, 2),
    "guest_arrived": (SECOND, 4),
    "guest_boarded": (SECOND, 5),
    "guest_left": (SECOND, 8),
    "guest_refused": (SECOND, 9),
    "guest_snapshot": (SECOND, 10),
    "weather_change": (SECOND, 11),
}


def raw_line(kind: str, **extra: str) -> str:
    """The fixture JSON line of ``kind``, with any extra keys appended as JSON text."""
    seq, payload, _ = EVENTS[kind]
    added = "".join(f', "{key}": {value}' for key, value in extra.items())
    return "{" + ENVELOPE_JSON.format(kind=kind, seq=seq) + ", " + payload + added + "}"


def land_layout(raw: Path, planted: tuple[str, str] | None = None) -> None:
    """Write LAYOUT under ``raw/v1``; ``planted`` adds one lineage key to the last line."""
    for name, lines in LAYOUT.items():
        texts = [raw_line(text) if text in EVENTS else text for text in lines]
        if planted and name == SECOND:
            texts[-1] = raw_line(lines[-1], **{planted[0]: planted[1]})
        land(raw, *texts, name=name)


@pytest.fixture
def converted(tmp_path: Path) -> Path:
    land_layout(tmp_path / "raw")
    result = convert(tmp_path / "raw", tmp_path / "out")
    assert result.ok, result
    assert result.row_counts == dict.fromkeys(sorted(EVENTS), 1)
    return tmp_path / "out" / "v1"


def described(relation: duckdb.DuckDBPyRelation) -> list[tuple[str, str]]:
    return [(name, str(kind)) for name, kind in zip(relation.columns, relation.types, strict=True)]


@pytest.mark.parametrize("kind", list(EVENTS))
def test_every_column_but_the_lineage_matches_the_fixture_json(converted: Path, kind: str) -> None:
    seq, _, payload_sql = EVENTS[kind]
    path = (converted / f"{kind}.parquet").as_posix()
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("SET TimeZone='UTC'")
        actual = connection.sql(
            f"SELECT * EXCLUDE (_raw_file, _raw_line) FROM read_parquet('{path}')"
        )
        expected = connection.sql(
            f"SELECT {ENVELOPE_SQL.format(kind=kind, seq=seq)}, {payload_sql}"
        )
        assert described(actual) == described(expected)
        assert actual.fetchall() == expected.fetchall()
    finally:
        connection.close()


@pytest.mark.parametrize("kind", list(EVENTS))
def test_lineage_holds_the_raw_base_name_and_physical_line(converted: Path, kind: str) -> None:
    path = (converted / f"{kind}.parquet").as_posix()
    connection = duckdb.connect(":memory:")
    try:
        lineage = connection.sql(f"SELECT _raw_file, _raw_line FROM read_parquet('{path}')")
        assert described(lineage) == [("_raw_file", "VARCHAR"), ("_raw_line", "BIGINT")]
        assert lineage.fetchall() == [LINEAGE[kind]]
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("key", "value"), [("_raw_file", '"events-forged.jsonl"'), ("_raw_line", "99")]
)
def test_a_raw_line_carrying_a_lineage_key_is_a_field_error(
    tmp_path: Path, key: str, value: str
) -> None:
    land_layout(tmp_path / "raw", planted=(key, value))

    result = convert(tmp_path / "raw", tmp_path / "out")

    assert result.schema_errors == [
        f"{SECOND}:11: {key}: the converter fills this field; a raw line must not carry it"
    ]
    assert not (tmp_path / "out").exists()

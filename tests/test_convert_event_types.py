"""Converter tests for every contract's event type: zero-row files, new types, old events."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openrct2_analytics.ingest.contracts import check_all
from openrct2_analytics.ingest.convert import NoInputError, convert, main
from tests.test_contracts import LEDGER
from tests.test_convert import SNAPSHOT_PAYLOAD, STATS_PAYLOAD, event, land, query, session_lines

ENVELOPE_TYPES = [
    ("schema_version", "INTEGER"),
    ("event_type", "VARCHAR"),
    ("plugin_version", "VARCHAR"),
    ("park_id", "VARCHAR"),
    ("session_id", "VARCHAR"),
    ("_raw_file", "VARCHAR"),
    ("_raw_line", "BIGINT"),
    ("seq", "BIGINT"),
    ("event_id", "VARCHAR"),
    ("game_year", "INTEGER"),
    ("game_month", "INTEGER"),
    ("game_day", "INTEGER"),
    ("game_ticks_elapsed", "BIGINT"),
    ("emitted_at", "TIMESTAMP WITH TIME ZONE"),
    ("received_at", "TIMESTAMP WITH TIME ZONE"),
]
FINANCE_TYPES = [
    *ENVELOPE_TYPES,
    ("statement_year", "INTEGER"),
    ("statement_month", "INTEGER"),
    *((name, "BIGINT") for name in LEDGER),
    ("cash_tenths", "BIGINT"),
    ("bank_loan_tenths", "BIGINT"),
    ("new_month_booked_tenths", "BIGINT"),
]
START_TYPES = [
    *ENVELOPE_TYPES,
    ("api_version", "INTEGER"),
    ("park_name", "VARCHAR"),
    ("scenario_name", "VARCHAR"),
    ("headless", "BOOLEAN"),
    ("game_speed", "INTEGER"),
    ("climate", "VARCHAR"),
    ("loaded_save_id", "VARCHAR"),
    ("loaded_save_session_id", "VARCHAR"),
    ("loaded_save_seq_floor", "BIGINT"),
    ("loaded_save_lines_waiting", "INTEGER"),
]
START_PAYLOAD: dict[str, object] = {
    "api_version": 110,
    "park_name": "Test Park",
    "scenario_name": "Test Scenario",
    "headless": True,
    "game_speed": 1,
}
# The fields plugin 0.3.0 adds: session_start after loading a save, and a day's weather.
START_FIELDS_0_3_0: dict[str, object] = {
    "climate": "coolAndWet",
    "loaded_save_id": "v1790000000000-abc",
    "loaded_save_session_id": "s1790000000000-def",
    "loaded_save_seq_floor": 5_000_000_000,
    "loaded_save_lines_waiting": 4,
}
WEATHER_FIELDS: dict[str, object] = {"weather": "heavyRain", "temperature_c": -3}
# One ride's snapshot as the plugin sends it: a ride with two prices and one used station.
RIDE_PAYLOAD: dict[str, object] = {
    "ride_id": 3,
    "ride_name": "Carousel 1",
    "ride_type": 28,
    "ride_object": "rct2.ride.cars",
    "classification": "ride",
    "status": "open",
    "excitement_hundredths": 652,
    "intensity_hundredths": 410,
    "nausea_hundredths": 120,
    "price_1_tenths": 20,
    "price_2_tenths": 0,
    "shop_item": 255,
    "shop_item_secondary": 255,
    "total_customers": 4_800,
    "build_date_months_elapsed": 2,
    "age_months": 5,
    "running_cost_per_fortnight_tenths": 960,
    "total_profit_tenths": 1_500,
    "income_per_game_hour_tenths": 300,
    "profit_per_game_hour_tenths": 120,
    "value_tenths": 70,
    "reliability_pct": 97,
    "downtime_pct": 3,
    "satisfaction_pct": 80,
    "guests_on_ride": 6,
    "station_count": 1,
    "queue_time_max_minutes": 2,
    "max_speed_mph": 41.5,
    "average_speed_mph": 22.25,
    "ride_time_seconds": 95,
    "ride_length_meters": 1040.5,
    "max_positive_vertical_g": 2.5,
    "max_negative_vertical_g": -1.25,
    "max_lateral_g": 1.75,
    "total_air_time_seconds": 6.5,
    "drop_count": 3,
    "lift_hill_count": 1,
    "highest_drop_height_units": 28.5,
    "inversion_count": 2,
    "ride_category": "rollercoaster",
}
RIDE_REQUIRED = (
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
# The values sent as read when the game has no real value: unrated, unmeasured, no item.
RIDE_PLACEHOLDERS: dict[str, object] = {
    "excitement_hundredths": -1,
    "intensity_hundredths": -1,
    "nausea_hundredths": -1,
    "satisfaction_pct": 1_275,
    "shop_item": 255,
    "shop_item_secondary": 255,
}
# The statement for month 0 of year 1: income positive, spending negative, a refund positive.
FINANCE_PAYLOAD: dict[str, object] = {
    "statement_year": 1,
    "statement_month": 0,
    **{name: -(index + 1) * 10 for index, name in enumerate(LEDGER)},
    "park_entrance_tickets_tenths": 2_500_000_000_000,
    "land_purchase_tenths": 40,
    "cash_tenths": -12345,
    "bank_loan_tenths": 100000,
}


def typed_event(session: str, seq: int, event_type: str, payload: dict[str, object]) -> str:
    """One raw line of ``event_type``: the envelope from ``event`` plus ``payload``."""
    line = json.loads(event(session, seq))
    for name in SNAPSHOT_PAYLOAD:
        del line[name]
    line.update(event_type=event_type, plugin_version="0.2.0", **payload)
    return json.dumps(line)


def ride_row(raw: Path, out: Path, payload: dict[str, object]) -> tuple[object, ...]:
    """Convert one ``ride_snapshot`` line and return its row, columns in file order."""
    land(raw, typed_event("sa", 1, "ride_snapshot", payload))

    assert convert(raw, out).ok
    assert not any(check_all(out).values())
    rows = query(out / "v1" / "ride_snapshot.parquet", "SELECT * FROM '{p}'")
    assert len(rows) == 1
    return rows[0]


def types(path: Path) -> list[tuple[object, object]]:
    return [(row[0], row[1]) for row in query(path, "DESCRIBE SELECT * FROM '{p}'")]


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    return tmp_path / "raw"


@pytest.fixture
def out(tmp_path: Path) -> Path:
    return tmp_path / "parquet"


def test_a_type_with_no_events_gets_a_zero_row_file_with_contract_types(
    raw: Path, out: Path
) -> None:
    land(raw, *session_lines("sa", 2))

    result = convert(raw, out)

    assert result.ok
    assert result.row_counts["finance_month"] == 0
    assert result.row_counts["session_start"] == 0
    for name, expected in (("finance_month", FINANCE_TYPES), ("session_start", START_TYPES)):
        path = out / "v1" / f"{name}.parquet"
        assert query(path, "SELECT count(*) FROM '{p}'") == [(0,)]
        assert types(path) == expected


def test_events_from_plugin_0_1_0_convert_with_the_new_counter_null(raw: Path, out: Path) -> None:
    land(raw, *session_lines("sa", 4))

    result = convert(raw, out)

    assert result.ok
    path = out / "v1" / "plugin_stats.parquet"
    assert ("finance_months_unread_total", "BIGINT") in types(path)
    assert query(path, "SELECT finance_months_unread_total FROM '{p}'") == [(None,), (None,)]


def test_session_start_and_finance_month_convert_with_contract_types(raw: Path, out: Path) -> None:
    stats = json.loads(event("sa", 2, "plugin_stats"))
    stats.update(plugin_version="0.2.0", finance_months_unread_total=3)
    finance = json.loads(typed_event("sa", 4, "finance_month", FINANCE_PAYLOAD))
    finance.update(game_month=1, game_day=1)
    land(
        raw,
        typed_event("sa", 1, "session_start", START_PAYLOAD),
        json.dumps(stats),
        event("sa", 3),
        json.dumps(finance),
    )

    result = convert(raw, out)

    assert result.ok
    assert result.row_counts == {
        "finance_month": 1,
        "game_action": 0,
        "guest_arrived": 0,
        "guest_boarded": 0,
        "guest_left": 0,
        "guest_refused": 0,
        "guest_snapshot": 0,
        "park_snapshot": 1,
        "plugin_stats": 1,
        "ride_snapshot": 0,
        "save_written": 0,
        "session_start": 1,
        "weather_change": 0,
    }
    start = out / "v1" / "session_start.parquet"
    assert types(start) == START_TYPES
    assert query(start, "SELECT seq, api_version, park_name, headless FROM '{p}'") == [
        (1, 110, "Test Park", True)
    ]
    statement = out / "v1" / "finance_month.parquet"
    assert types(statement) == FINANCE_TYPES
    assert query(
        statement,
        "SELECT statement_month, park_entrance_tickets_tenths, land_purchase_tenths,"
        " wages_tenths, cash_tenths, new_month_booked_tenths FROM '{p}'",
    ) == [(0, 2_500_000_000_000, 40, -110, -12345, None)]
    counter = "SELECT finance_months_unread_total FROM '{p}'"
    assert query(out / "v1" / "plugin_stats.parquet", counter) == [(3,)]
    assert query(
        out / "audit" / "seq_audit.parquet", "SELECT first_seq, last_seq, missing FROM '{p}'"
    ) == [(1, 4, 0)]
    assert not any(check_all(out).values())


def test_a_statement_with_the_booked_amount_keeps_it(raw: Path, out: Path) -> None:
    payload = {**FINANCE_PAYLOAD, "new_month_booked_tenths": -75}
    finance = json.loads(typed_event("sa", 1, "finance_month", payload))
    finance.update(game_month=1, game_day=1)
    land(raw, json.dumps(finance))

    result = convert(raw, out)

    assert result.ok
    path = out / "v1" / "finance_month.parquet"
    assert query(path, "SELECT new_month_booked_tenths FROM '{p}'") == [(-75,)]


def test_a_ride_snapshot_converts_with_contract_types(raw: Path, out: Path) -> None:
    ride_row(raw, out, RIDE_PAYLOAD)

    path = out / "v1" / "ride_snapshot.parquet"
    by_name = dict(types(path))
    for name in RIDE_PAYLOAD:
        if name.endswith("_tenths") or name == "total_customers":
            assert by_name[name] == "BIGINT", name
    assert by_name["ride_id"] == "INTEGER"
    assert by_name["classification"] == "VARCHAR"
    assert by_name["max_speed_mph"] == by_name["ride_time_seconds"] == "DOUBLE"
    assert by_name["drop_count"] == by_name["inversion_count"] == "INTEGER"
    assert by_name["ride_category"] == "VARCHAR"
    assert list(by_name)[len(ENVELOPE_TYPES) :] == list(RIDE_PAYLOAD)


def test_a_ride_snapshot_with_every_placeholder_converts_as_read(raw: Path, out: Path) -> None:
    ride_row(raw, out, {**RIDE_PAYLOAD, **RIDE_PLACEHOLDERS, "total_profit_tenths": None})

    row = query(
        out / "v1" / "ride_snapshot.parquet",
        "SELECT excitement_hundredths, satisfaction_pct, shop_item_secondary, total_profit_tenths"
        " FROM '{p}'",
    )
    assert row == [(-1, 1_275, 255, None)]


def test_a_ride_snapshot_with_every_optional_field_null_converts(raw: Path, out: Path) -> None:
    nulls = {name: None for name in RIDE_PAYLOAD if name not in RIDE_REQUIRED}

    row = ride_row(raw, out, {**RIDE_PAYLOAD, **nulls})

    values = dict(zip(RIDE_PAYLOAD, row[len(ENVELOPE_TYPES) :], strict=True))
    assert {name for name, value in values.items() if value is None} == set(nulls)
    assert values["station_count"] == 1


def test_plugin_stats_from_plugin_0_3_0_carry_the_work_counters(raw: Path, out: Path) -> None:
    counters = {
        "work_units_total": 5_000_000_000,
        "work_items_skipped_total": 2,
        "work_queue_length": 7,
    }
    land(raw, event("sa", 1, "plugin_stats", **counters), event("sa", 2, "plugin_stats"))

    assert convert(raw, out).ok

    path = out / "v1" / "plugin_stats.parquet"
    by_name = dict(types(path))
    assert [by_name[name] for name in counters] == ["BIGINT", "BIGINT", "INTEGER"]
    assert query(path, "SELECT " + ", ".join(counters) + " FROM '{p}' ORDER BY seq") == [
        (5_000_000_000, 2, 7),
        (None, None, None),
    ]


def test_a_save_written_converts_with_contract_types(raw: Path, out: Path) -> None:
    land(raw, typed_event("sa", 1, "save_written", {"save_id": "v1790000000000-abc"}))

    result = convert(raw, out)

    assert result.ok
    path = out / "v1" / "save_written.parquet"
    assert types(path) == [*ENVELOPE_TYPES, ("save_id", "VARCHAR")]
    assert query(path, "SELECT seq, save_id FROM '{p}'") == [(1, "v1790000000000-abc")]
    assert not any(check_all(out).values())


@pytest.mark.parametrize(
    ("event_type", "payload", "field"),
    [
        ("save_written", {"save_id": "v1790000000000-abc"}, "save_id"),
        ("ride_snapshot", RIDE_PAYLOAD, "ride_id"),
    ],
)
def test_a_line_without_its_key_field_is_a_schema_error(
    raw: Path, out: Path, *, event_type: str, payload: dict[str, object], field: str
) -> None:
    without = {name: value for name, value in payload.items() if name != field}
    land(raw, typed_event("sa", 1, event_type, without))

    result = convert(raw, out)

    assert result.schema_errors == [f"events-2026-09-30.jsonl:1: {field}: missing required field"]
    assert not out.exists()


def test_session_start_and_park_snapshot_convert_from_plugin_0_2_0_and_0_3_0(
    raw: Path, out: Path
) -> None:
    newer_start = typed_event("sb", 1, "session_start", {**START_PAYLOAD, **START_FIELDS_0_3_0})
    land(
        raw,
        typed_event("sa", 1, "session_start", START_PAYLOAD),
        event("sa", 2, plugin_version="0.2.0"),
        json.dumps({**json.loads(newer_start), "plugin_version": "0.3.0"}),
        event("sb", 2, "park_snapshot", plugin_version="0.3.0", **WEATHER_FIELDS),
    )

    assert convert(raw, out).ok

    start = out / "v1" / "session_start.parquet"
    assert types(start) == START_TYPES
    fields = ", ".join(START_FIELDS_0_3_0)
    assert query(start, f"SELECT session_id, {fields} FROM '{{p}}' ORDER BY 1") == [
        ("sa", None, None, None, None, None),
        ("sb", *START_FIELDS_0_3_0.values()),
    ]
    snapshot = out / "v1" / "park_snapshot.parquet"
    assert types(snapshot)[-2:] == [("weather", "VARCHAR"), ("temperature_c", "INTEGER")]
    assert query(snapshot, "SELECT session_id, weather, temperature_c FROM '{p}' ORDER BY 1") == [
        ("sa", None, None),
        ("sb", "heavyRain", -3),
    ]
    assert not any(check_all(out).values())


def test_a_json_integer_is_accepted_in_a_number_field(raw: Path, out: Path) -> None:
    stats = {**STATS_PAYLOAD, "work_ms_total": 0, "worst_tick_ms": 3}
    land(raw, event("sa", 1, "plugin_stats", **stats))

    result = convert(raw, out)

    assert result.ok
    rows = query(
        out / "v1" / "plugin_stats.parquet", "SELECT work_ms_total, worst_tick_ms FROM '{p}'"
    )
    assert rows == [(0.0, 3.0)]
    types = query(out / "v1" / "plugin_stats.parquet", "DESCRIBE SELECT work_ms_total FROM '{p}'")
    assert types[0][1] == "DOUBLE"


def test_a_raw_folder_of_blank_lines_raises_no_input_and_writes_nothing(
    raw: Path, out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (raw / "v1").mkdir(parents=True)
    (raw / "v1" / "events-2026-09-30.jsonl").write_text("\n \n\t\n", encoding="utf-8")

    with pytest.raises(NoInputError, match="holds no events"):
        convert(raw, out)

    assert not out.exists()
    assert main(["--raw-dir", str(raw), "--out-dir", str(out)]) == 1
    assert "holds no events" in capsys.readouterr().out
    assert not out.exists()

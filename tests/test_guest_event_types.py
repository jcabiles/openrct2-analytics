"""Contract and converter cases for the five guest event types and the plugin 0.4.0 stats fields."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from datacontract.data_contract import DataContract

from openrct2_analytics.ingest import contracts
from openrct2_analytics.ingest.convert import convert
from tests.test_contracts import failures, write_data
from tests.test_convert import event, land, query, session_lines
from tests.test_convert_event_types import ENVELOPE_TYPES, typed_event, types

GUEST_TYPES = (
    "guest_arrived",
    "guest_boarded",
    "guest_left",
    "guest_refused",
    "guest_snapshot",
)
GUEST_CONTRACT_FIELDS: dict[str, set[tuple[str, str, bool]]] = {
    "guest_arrived": {
        ("guest_key", "INTEGER", True),
        ("guest_id", "INTEGER", True),
        ("generated_at_ticks", "BIGINT", True),
        ("in_cohort", "BOOLEAN", True),
        ("guest_cash_tenths", "BIGINT", False),
    },
    "guest_left": {
        ("guest_key", "INTEGER", True),
        ("guest_id", "INTEGER", True),
        ("exit_reason", "VARCHAR", True),
        ("entered_park", "BOOLEAN", True),
        ("arrived_in_session", "BOOLEAN", True),
        ("in_cohort", "BOOLEAN", True),
    },
    "guest_refused": {
        ("guest_key", "INTEGER", True),
        ("guest_id", "INTEGER", True),
        ("thought_type", "VARCHAR", True),
        ("ride_id", "INTEGER", True),
    },
    "guest_snapshot": {
        ("guest_key", "INTEGER", True),
        ("guest_id", "INTEGER", True),
        ("happiness", "INTEGER", False),
        ("hunger", "INTEGER", False),
        ("thirst", "INTEGER", False),
        ("nausea", "INTEGER", False),
        ("energy", "INTEGER", False),
        ("guest_cash_tenths", "BIGINT", False),
        ("items_carried", "VARCHAR", True),
        ("thought_type", "VARCHAR", False),
        ("thought_item", "INTEGER", False),
    },
    "guest_boarded": {
        ("guest_id", "INTEGER", True),
        ("guest_key", "INTEGER", False),
        ("ride_id", "INTEGER", True),
        ("detected_at_ticks", "BIGINT", True),
        ("ride_price_listed_tenths", "BIGINT", False),
        ("happiness", "INTEGER", False),
        ("min_intensity", "INTEGER", False),
        ("max_intensity", "INTEGER", False),
        ("nausea_tolerance", "INTEGER", False),
        ("guest_cash_tenths", "BIGINT", False),
    },
}
ENVELOPE_EVENT_TYPES = {
    "session_start",
    "plugin_stats",
    "park_snapshot",
    "finance_month",
    "ride_snapshot",
    "save_written",
    "guest_arrived",
    "guest_left",
    "guest_refused",
    "guest_snapshot",
    "guest_boarded",
    "weather_change",
    "game_action",
}
REFUSAL_TYPES = (
    "cant_afford_ride",
    "bad_value",
    "not_paying",
    "intense",
    "more_thrilling",
    "sickening",
    "not_safe",
    "queuing_ages",
    "not_while_raining",
)
STATS_FIELDS_0_4_0: dict[str, object] = {
    "work_items_failed_total": 0,
    "worst_step_ms": 0.75,
    "worst_step_kind": "ride",
    "worst_tick_kind_ms": "ride:0.750|day_callback:0.500|other:0.250",
    "worst_day_start_tick_ms": 1.5,
    "guest_fields_ms_total": 0.125,
    "continuous_items_pending": 2,
    "lines_queued_max": 40,
    "guests_known": 120,
    "guests_known_in_park": 90,
    "arrivals_recorded_total": 300,
    "boarding_polls_total": 150,
    "boarders_queued_total": 60,
}
PAYLOADS: dict[str, dict[str, object]] = {
    "guest_arrived": {
        "guest_key": 1,
        "guest_id": 40,
        "generated_at_ticks": 7990,
        "in_cohort": True,
        "guest_cash_tenths": 1200,
    },
    "guest_left": {
        "guest_key": 1,
        "guest_id": 40,
        "exit_reason": "id_reused",
        "entered_park": False,
        "arrived_in_session": True,
        "in_cohort": False,
    },
    "guest_refused": {"guest_key": 1, "guest_id": 40, "thought_type": "bad_value", "ride_id": 3},
    "guest_snapshot": {
        "guest_key": 1,
        "guest_id": 40,
        "happiness": 180,
        "energy": 100,
        "guest_cash_tenths": 900,
        "items_carried": "",
    },
    "guest_boarded": {
        "guest_id": 40,
        "ride_id": 3,
        "detected_at_ticks": 8080,
        "ride_price_listed_tenths": 20,
    },
}


def test_write_data_builds_one_row_per_guest_type(tmp_path: Path) -> None:
    root = write_data(tmp_path / "good")

    for name in GUEST_TYPES:
        rows = query(root / "v1" / f"{name}.parquet", "SELECT count(*) FROM '{p}'")
        assert rows == [(1,)], name


def test_guest_contract_payload_fields_match_the_contract_tables() -> None:
    loaded = contracts.load_fields(contracts.CONTRACTS_DIR)
    envelope = DataContract(
        data_contract_str=(contracts.CONTRACTS_DIR / "envelope.odcs.yaml").read_text(
            encoding="utf-8"
        )
    ).get_data_contract()
    envelope_names = {
        prop.name for schema in envelope.schema_ or [] for prop in schema.properties or []
    }

    actual = {
        event_type: {
            (field.name, field.physical, field.required)
            for field in loaded[event_type]
            if field.name not in envelope_names
        }
        for event_type in GUEST_CONTRACT_FIELDS
    }

    assert actual == GUEST_CONTRACT_FIELDS


def test_envelope_event_types_match_contract_files() -> None:
    envelope = DataContract(
        data_contract_str=(contracts.CONTRACTS_DIR / "envelope.odcs.yaml").read_text(
            encoding="utf-8"
        )
    ).get_data_contract()
    event_type = next(
        prop
        for schema in envelope.schema_ or []
        for prop in schema.properties or []
        if prop.name == "event_type"
    )
    assert isinstance(event_type.description, str)
    types_text = event_type.description.split("one of ", 1)[1].split("; text", 1)[0]
    declared_types = {name.strip() for name in types_text.replace(" or ", ", ").split(",")}
    contract_types = {
        path.name.removesuffix(".odcs.yaml")
        for path in contracts.CONTRACTS_DIR.glob("*.odcs.yaml")
        if path.name != "envelope.odcs.yaml"
    }

    assert declared_types == contract_types == ENVELOPE_EVENT_TYPES


def test_zero_row_guest_files_pass(tmp_path: Path) -> None:
    deletes = "; ".join(f"DELETE FROM {table}" for table in GUEST_TYPES)

    assert failures(write_data(tmp_path / "empty", deletes)) == []


def test_every_refusal_type_and_every_optional_null_passes(tmp_path: Path) -> None:
    values = ", ".join(f"({n}, '{t}')" for n, t in enumerate(REFUSAL_TYPES, start=20))
    refusals = (
        "INSERT INTO guest_refused SELECT r.* REPLACE ('sess-' || v.n AS event_id,"
        " v.n::BIGINT AS seq,"
        f" v.t AS thought_type) FROM guest_refused AS r, (VALUES {values}) AS v(n, t)"
    )
    nulls = (
        "UPDATE guest_snapshot SET happiness = NULL, hunger = NULL, thirst = NULL, nausea = NULL,"
        " energy = NULL, guest_cash_tenths = NULL, thought_type = NULL, thought_item = NULL,"
        " items_carried = '';"
        "UPDATE guest_boarded SET guest_key = NULL, ride_price_listed_tenths = NULL,"
        " happiness = NULL, min_intensity = NULL, max_intensity = NULL, nausea_tolerance = NULL,"
        " guest_cash_tenths = NULL;"
        "UPDATE guest_arrived SET guest_cash_tenths = NULL"
    )

    assert failures(write_data(tmp_path / "refusals", refusals)) == []
    assert failures(write_data(tmp_path / "nulls", nulls)) == []


# (case name, SQL that breaks the good data, text of the check that must fail)
BROKEN_CASES = [
    (
        "refusal_type_outside_the_nine",
        "UPDATE guest_refused SET thought_type = 'was_great'",
        "the thought type is one of the nine refusal types",
    ),
    (
        "refusal_without_a_ride_id",
        "UPDATE guest_refused SET ride_id = NULL",
        "field ride_id has no missing values",
    ),
    (
        "exit_reason_outside_its_two_values",
        "UPDATE guest_left SET exit_reason = 'gone'",
        "the exit reason is one of its two values",
    ),
    (
        "guest_key_below_one",
        "UPDATE guest_arrived SET guest_key = 0",
        "a guest key is at least 1",
    ),
    (
        "snapshot_without_items_carried",
        "UPDATE guest_snapshot SET items_carried = NULL",
        "field items_carried has no missing values",
    ),
    (
        "snapshot_happiness_above_255",
        "UPDATE guest_snapshot SET happiness = 256",
        "field happiness has a maximum of 255",
    ),
    (
        "snapshot_energy_below_32",
        "UPDATE guest_snapshot SET energy = 31",
        "field energy has a minimum of 32",
    ),
    (
        "boarding_without_a_ride_id",
        "UPDATE guest_boarded SET ride_id = NULL",
        "field ride_id has no missing values",
    ),
    (
        "boarding_nausea_tolerance_above_3",
        "UPDATE guest_boarded SET nausea_tolerance = 4",
        "field nausea_tolerance has a maximum of 3",
    ),
    (
        "boarding_max_intensity_above_15",
        "UPDATE guest_boarded SET max_intensity = 16",
        "field max_intensity has a maximum of 15",
    ),
    (
        "negative_guests_known",
        "UPDATE stats SET guests_known = -1",
        "field guests_known has a minimum of 0",
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


def test_converter_writes_a_zero_row_file_for_every_guest_type(tmp_path: Path) -> None:
    land(tmp_path / "raw", *session_lines("sa", 2))

    result = convert(tmp_path / "raw", tmp_path / "out")

    assert result.ok
    for name in GUEST_TYPES:
        assert result.row_counts[name] == 0
        assert types(tmp_path / "out" / "v1" / f"{name}.parquet")[: len(ENVELOPE_TYPES)] == (
            ENVELOPE_TYPES
        )


def test_converter_types_each_guest_event(tmp_path: Path) -> None:
    raw, out = tmp_path / "raw", tmp_path / "out"
    land(
        raw,
        *(
            typed_event("sa", seq, name, PAYLOADS[name])
            for seq, name in enumerate(PAYLOADS, start=1)
        ),
    )

    result = convert(raw, out)

    assert result.ok
    assert {name: result.row_counts[name] for name in GUEST_TYPES} == dict.fromkeys(GUEST_TYPES, 1)
    arrived = query(
        out / "v1" / "guest_arrived.parquet",
        "SELECT guest_key, generated_at_ticks, in_cohort, guest_cash_tenths FROM '{p}'",
    )
    assert arrived == [(1, 7990, True, 1200)]
    assert dict(types(out / "v1" / "guest_arrived.parquet"))["generated_at_ticks"] == "BIGINT"
    boarded = out / "v1" / "guest_boarded.parquet"
    assert query(
        boarded, "SELECT guest_key, ride_id, ride_price_listed_tenths, happiness FROM '{p}'"
    ) == [(None, 3, 20, None)]
    assert dict(types(boarded))["ride_price_listed_tenths"] == "BIGINT"
    assert query(
        out / "v1" / "guest_snapshot.parquet",
        "SELECT items_carried, thought_type, thought_item FROM '{p}'",
    ) == [("", None, None)]


@pytest.mark.parametrize("thought_type", REFUSAL_TYPES)
def test_a_refusal_of_each_type_converts(tmp_path: Path, thought_type: str) -> None:
    payload = {**PAYLOADS["guest_refused"], "thought_type": thought_type, "ride_id": 12}
    land(tmp_path / "raw", typed_event("sa", 1, "guest_refused", payload))

    result = convert(tmp_path / "raw", tmp_path / "out")

    assert result.ok
    rows = query(
        tmp_path / "out" / "v1" / "guest_refused.parquet",
        "SELECT * EXCLUDE (received_at) FROM '{p}'",
    )
    assert [(row[-2], row[-1]) for row in rows] == [(thought_type, 12)]


def test_a_refusal_without_a_ride_id_is_a_schema_error(tmp_path: Path) -> None:
    payload = {k: v for k, v in PAYLOADS["guest_refused"].items() if k != "ride_id"}
    land(tmp_path / "raw", typed_event("sa", 1, "guest_refused", payload))

    result = convert(tmp_path / "raw", tmp_path / "out")

    assert result.schema_errors == ["events-2026-09-30.jsonl:1: ride_id: missing required field"]
    assert not (tmp_path / "out").exists()


def test_the_thirteen_new_stats_fields_convert_and_older_stats_leave_them_null(
    tmp_path: Path,
) -> None:
    raw, out = tmp_path / "raw", tmp_path / "out"
    new = json.loads(event("sa", 1, "plugin_stats"))
    new.update(STATS_FIELDS_0_4_0)
    land(raw, json.dumps(new), event("sa", 2, "plugin_stats"))

    result = convert(raw, out)

    assert result.ok
    stats = out / "v1" / "plugin_stats.parquet"
    columns = ", ".join(STATS_FIELDS_0_4_0)
    rows = query(stats, f"SELECT {columns} FROM '{{p}}' ORDER BY seq")
    assert rows == [tuple(STATS_FIELDS_0_4_0.values()), (None,) * len(STATS_FIELDS_0_4_0)]
    assert len(STATS_FIELDS_0_4_0) == 13
    kinds = dict(types(stats))
    assert kinds["worst_step_ms"] == "DOUBLE"
    assert kinds["worst_step_kind"] == "VARCHAR"
    assert kinds["arrivals_recorded_total"] == "BIGINT"

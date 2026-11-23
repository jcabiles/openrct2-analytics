"""Negative control for the contract runner: good Parquet passes, each broken copy fails.

The Parquet is built directly with DuckDB in a temporary folder, one folder per case.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest import contracts

ENVELOPE = """
    1::INTEGER AS schema_version, '{kind}' AS event_type, '0.1.0' AS plugin_version,
    'parkone' AS park_id, 'sess' AS session_id,
    'events-2026-01-01.jsonl' AS _raw_file, {seq}::BIGINT AS _raw_line,
    {seq}::BIGINT AS seq, 'sess-{seq}' AS event_id,
    1::INTEGER AS game_year, 0::INTEGER AS game_month, {day}::INTEGER AS game_day,
    {ticks}::BIGINT AS game_ticks_elapsed,
    TIMESTAMPTZ '2026-01-01 00:00:00+00' AS emitted_at,
    TIMESTAMPTZ '2026-01-01 00:00:01+00' AS received_at
"""
SNAPSHOT = (
    ENVELOPE.format(kind="park_snapshot", seq="{seq}", day="{day}", ticks="{ticks}")
    + """,
    -500::BIGINT AS cash_tenths, 12::INTEGER AS guests_in_park,
    600::INTEGER AS park_rating, 40::BIGINT AS total_admissions,
    'partiallyCloudy' AS weather, -4::INTEGER AS temperature_c
"""
)
STATS = (
    ENVELOPE.format(kind="plugin_stats", seq="{seq}", day="{day}", ticks="{ticks}")
    + """,
    0::BIGINT AS period_start_ticks, 4000::BIGINT AS period_end_ticks,
    4000::BIGINT AS period_ticks, 1.5::DOUBLE AS work_ms_total, 0.5::DOUBLE AS worst_tick_ms,
    2000::BIGINT AS worst_tick_at_ticks, 30::INTEGER AS callbacks, true AS warmup,
    'performance' AS clock, 1::INTEGER AS game_speed, 0::BIGINT AS lines_dropped_total,
    0::BIGINT AS write_partial_total, 0::BIGINT AS write_error_total,
    1::BIGINT AS connect_attempts_total, 0::INTEGER AS queue_length,
    0::INTEGER AS finance_months_unread_total, 12::BIGINT AS work_units_total,
    0::BIGINT AS work_items_skipped_total, 0::INTEGER AS work_queue_length,
    0::BIGINT AS work_items_failed_total, 0.75::DOUBLE AS worst_step_ms,
    'ride' AS worst_step_kind, 'ride:0.500|other:0.250' AS worst_tick_kind_ms,
    0.5::DOUBLE AS worst_day_start_tick_ms, 0.125::DOUBLE AS guest_fields_ms_total,
    2::INTEGER AS continuous_items_pending, 40::INTEGER AS lines_queued_max,
    120::INTEGER AS guests_known, 90::INTEGER AS guests_known_in_park,
    300::BIGINT AS arrivals_recorded_total, 150::BIGINT AS boarding_polls_total,
    60::BIGINT AS boarders_queued_total,
    5::BIGINT AS game_actions_sent_preview_total, 2::BIGINT AS game_actions_sent_prediction_total,
    9::BIGINT AS game_actions_sent_confirmed_total,
    0::BIGINT AS game_actions_dropped_preview_total,
    0::BIGINT AS game_actions_dropped_prediction_total,
    0::BIGINT AS game_actions_dropped_confirmed_total,
    0.25::DOUBLE AS action_query_ms_total, 0.5::DOUBLE AS action_execute_ms_total,
    1::BIGINT AS game_actions_skipped_preview_total,
    0::BIGINT AS game_actions_skipped_prediction_total,
    4::BIGINT AS game_actions_skipped_confirmed_total,
    0::BIGINT AS game_actions_skipped_unknown_total,
    0::BIGINT AS game_actions_skipped_cheat_total
"""
)
START = (
    ENVELOPE.format(kind="session_start", seq="{seq}", day="{day}", ticks="{ticks}")
    + """,
    1::INTEGER AS api_version, 'Park' AS park_name, 'Scenario' AS scenario_name,
    true AS headless, 1::INTEGER AS game_speed, 'coolAndWet' AS climate,
    'v100-a' AS loaded_save_id, 'sprev' AS loaded_save_session_id,
    40::BIGINT AS loaded_save_seq_floor, 2::INTEGER AS loaded_save_lines_waiting
"""
)
SAVE = (
    ENVELOPE.format(kind="save_written", seq="{seq}", day="{day}", ticks="{ticks}")
    + ", 'v200-b' AS save_id"
)
WEATHER = (
    ENVELOPE.format(kind="weather_change", seq="{seq}", day="{day}", ticks="{ticks}")
    + ", 'rain' AS weather, 'sunny' AS previous_weather, 'cloudy' AS upcoming_weather,"
    + " 12::INTEGER AS temperature_c"
)
GAME_ACTION = (
    ENVELOPE.format(kind="game_action", seq="{seq}", day="{day}", ticks="{ticks}")
    + """,
    'execute' AS hook, 'ridesetprice' AS action, 'preview' AS action_label,
    -2147483584::BIGINT AS args_flags, true AS is_client_only, -1::INTEGER AS player,
    2::INTEGER AS type, '{{"ride":3,"price":125}}' AS args_json, 3::INTEGER AS args_ride,
    28::INTEGER AS args_ride_type, 4::INTEGER AS args_ride_object,
    125::BIGINT AS args_price_tenths, 10::INTEGER AS args_x, 11::INTEGER AS args_y,
    12::INTEGER AS args_z, 0::INTEGER AS result_error, 40::BIGINT AS result_cost_tenths,
    3::INTEGER AS result_ride, 8390::BIGINT AS action_at_ticks, 1::INTEGER AS action_game_year,
    1::INTEGER AS action_game_month, 2::INTEGER AS action_game_day
"""
)
RIDE = (
    ENVELOPE.format(kind="ride_snapshot", seq="{seq}", day="{day}", ticks="{ticks}")
    + """,
    3::INTEGER AS ride_id, 'Carousel 1' AS ride_name, 28::INTEGER AS ride_type,
    'rct2.ride.cars' AS ride_object, 'ride' AS classification, 'open' AS status,
    652::INTEGER AS excitement_hundredths, 410::INTEGER AS intensity_hundredths,
    120::INTEGER AS nausea_hundredths, 20::BIGINT AS price_1_tenths, 0::BIGINT AS price_2_tenths,
    255::INTEGER AS shop_item, 255::INTEGER AS shop_item_secondary,
    4800::BIGINT AS total_customers, 2::INTEGER AS build_date_months_elapsed,
    5::INTEGER AS age_months, 960::BIGINT AS running_cost_per_fortnight_tenths,
    1500::BIGINT AS total_profit_tenths, 300::BIGINT AS income_per_game_hour_tenths,
    120::BIGINT AS profit_per_game_hour_tenths, 70::BIGINT AS value_tenths,
    97::INTEGER AS reliability_pct, 3::INTEGER AS downtime_pct, 80::INTEGER AS satisfaction_pct,
    6::INTEGER AS guests_on_ride, 1::INTEGER AS station_count,
    2::INTEGER AS queue_time_max_minutes, 41.5::DOUBLE AS max_speed_mph,
    22.25::DOUBLE AS average_speed_mph, 95::DOUBLE AS ride_time_seconds,
    1040::DOUBLE AS ride_length_meters, 2.5::DOUBLE AS max_positive_vertical_g,
    -1.25::DOUBLE AS max_negative_vertical_g, 1.75::DOUBLE AS max_lateral_g,
    6.5::DOUBLE AS total_air_time_seconds, 3::INTEGER AS drop_count,
    1::INTEGER AS lift_hill_count, 28.5::DOUBLE AS highest_drop_height_units,
    2::INTEGER AS inversion_count, 'rollercoaster' AS ride_category
"""
)
GUEST_ARRIVED = (
    ENVELOPE.format(kind="guest_arrived", seq="{seq}", day="{day}", ticks="{ticks}")
    + """,
    1::INTEGER AS guest_key, 40::INTEGER AS guest_id, 7990::BIGINT AS generated_at_ticks,
    true AS in_cohort, 1200::BIGINT AS guest_cash_tenths
"""
)
GUEST_LEFT = (
    ENVELOPE.format(kind="guest_left", seq="{seq}", day="{day}", ticks="{ticks}")
    + """,
    1::INTEGER AS guest_key, 40::INTEGER AS guest_id, 'left' AS exit_reason,
    true AS entered_park, true AS arrived_in_session, true AS in_cohort
"""
)
GUEST_REFUSED = (
    ENVELOPE.format(kind="guest_refused", seq="{seq}", day="{day}", ticks="{ticks}")
    + """,
    1::INTEGER AS guest_key, 40::INTEGER AS guest_id, 'intense' AS thought_type,
    3::INTEGER AS ride_id
"""
)
GUEST_SNAPSHOT = (
    ENVELOPE.format(kind="guest_snapshot", seq="{seq}", day="{day}", ticks="{ticks}")
    + """,
    1::INTEGER AS guest_key, 40::INTEGER AS guest_id, 180::INTEGER AS happiness,
    30::INTEGER AS hunger, 20::INTEGER AS thirst, 10::INTEGER AS nausea,
    100::INTEGER AS energy, 900::BIGINT AS guest_cash_tenths,
    'balloon|map' AS items_carried, 'intense' AS thought_type, 3::INTEGER AS thought_item
"""
)
GUEST_BOARDED = (
    ENVELOPE.format(kind="guest_boarded", seq="{seq}", day="{day}", ticks="{ticks}")
    + """,
    40::INTEGER AS guest_id, 1::INTEGER AS guest_key, 3::INTEGER AS ride_id,
    8080::BIGINT AS detected_at_ticks, 20::BIGINT AS ride_price_listed_tenths,
    180::INTEGER AS happiness, 4::INTEGER AS min_intensity, 9::INTEGER AS max_intensity,
    2::INTEGER AS nausea_tolerance, 880::BIGINT AS guest_cash_tenths
"""
)
GUEST_TABLES = {
    "guest_arrived": GUEST_ARRIVED,
    "guest_left": GUEST_LEFT,
    "guest_refused": GUEST_REFUSED,
    "guest_snapshot": GUEST_SNAPSHOT,
    "guest_boarded": GUEST_BOARDED,
}
LEDGER = [
    "ride_construction_tenths",
    "ride_runningcosts_tenths",
    "land_purchase_tenths",
    "landscaping_tenths",
    "park_entrance_tickets_tenths",
    "park_ride_tickets_tenths",
    "shop_sales_tenths",
    "shop_stock_tenths",
    "food_drink_sales_tenths",
    "food_drink_stock_tenths",
    "wages_tenths",
    "marketing_tenths",
    "research_tenths",
    "interest_tenths",
]
# The statement for month 0 of year 1, read on day 1 of month 1 (set in write_data).
FINANCE = (
    ENVELOPE.format(kind="finance_month", seq="{seq}", day="{day}", ticks="{ticks}")
    + ", 1::INTEGER AS statement_year, 0::INTEGER AS statement_month, "
    + ", ".join(f"-{i}::BIGINT AS {name}" for i, name in enumerate(LEDGER))
    + ", -500::BIGINT AS cash_tenths, 0::BIGINT AS bank_loan_tenths,"
    + " NULL::BIGINT AS new_month_booked_tenths"
)


def write_data(root: Path, mutation: str = "") -> Path:
    """Write one session's events of all thirteen types under ``root/v1``, after ``mutation``.

    The session starts (seq 1), has two game days of snapshot and stats, then one
    statement on day 1 of the next month, one ride snapshot, one save and one event of each
    guest type, numbered on from the save so the session's seq runs 1 to 13 with no gap (the
    publish sequence audit reads this data); the weather and game_action files have zero rows.
    The mutation is SQL over the in-memory tables ``start``, ``snapshot``, ``stats``, ``finance``,
    ``ride``, ``save``, ``weather``, ``game_action`` and the five tables named for the guest types.
    """
    folder = root / "v1"
    folder.mkdir(parents=True)
    connection = duckdb.connect()
    connection.execute(f"CREATE TABLE start AS SELECT {START.format(seq=1, day=1, ticks=4000)}")
    connection.execute(
        "CREATE TABLE snapshot AS "
        + " UNION ALL ".join(
            f"SELECT {SNAPSHOT.format(seq=seq, day=day, ticks=day * 4000)}"
            for seq, day in ((2, 1), (4, 2))
        )
    )
    connection.execute(
        "CREATE TABLE stats AS "
        + " UNION ALL ".join(
            f"SELECT {STATS.format(seq=seq, day=day, ticks=day * 4000)}"
            for seq, day in ((3, 1), (5, 2))
        )
    )
    connection.execute(
        "CREATE TABLE finance AS SELECT * REPLACE (1::INTEGER AS game_month) FROM (SELECT "
        f"{FINANCE.format(seq=6, day=1, ticks=12000)})"
    )
    connection.execute(f"CREATE TABLE ride AS SELECT {RIDE.format(seq=7, day=2, ticks=8100)}")
    connection.execute(f"CREATE TABLE save AS SELECT {SAVE.format(seq=8, day=2, ticks=8200)}")
    connection.execute(
        f"CREATE TABLE weather AS SELECT {WEATHER.format(seq=14, day=2, ticks=8400)} WHERE false"
    )
    # Seq 15 is outside write_data's gap-free run; the contract runner does not audit seq.
    connection.execute(
        f"CREATE TABLE game_action AS SELECT {GAME_ACTION.format(seq=15, day=2, ticks=8400)}"
        " WHERE false"
    )
    for seq, (table, sql) in enumerate(GUEST_TABLES.items(), start=9):
        connection.execute(
            f"CREATE TABLE {table} AS SELECT {sql.format(seq=seq, day=2, ticks=8300)}"
        )
    if mutation:
        connection.execute(mutation)
    connection.execute(f"COPY snapshot TO '{folder / 'park_snapshot.parquet'}' (FORMAT parquet)")
    connection.execute(f"COPY stats TO '{folder / 'plugin_stats.parquet'}' (FORMAT parquet)")
    connection.execute(f"COPY start TO '{folder / 'session_start.parquet'}' (FORMAT parquet)")
    connection.execute(f"COPY finance TO '{folder / 'finance_month.parquet'}' (FORMAT parquet)")
    connection.execute(f"COPY ride TO '{folder / 'ride_snapshot.parquet'}' (FORMAT parquet)")
    connection.execute(f"COPY save TO '{folder / 'save_written.parquet'}' (FORMAT parquet)")
    connection.execute(f"COPY weather TO '{folder / 'weather_change.parquet'}' (FORMAT parquet)")
    connection.execute(f"COPY game_action TO '{folder / 'game_action.parquet'}' (FORMAT parquet)")
    for table in GUEST_TABLES:
        connection.execute(f"COPY {table} TO '{folder / (table + '.parquet')}' (FORMAT parquet)")
    connection.close()
    return root


def failures(root: Path) -> list[str]:
    """Every problem line the runner reports for ``root``, across all contracts."""
    return [line for lines in contracts.check_all(root).values() for line in lines]


def test_good_data_passes_every_contract(tmp_path: Path) -> None:
    root = write_data(tmp_path / "good")

    assert failures(root) == []
    assert contracts.main(["--data-root", str(root)]) == 0


DUPLICATE_SNAPSHOT_FOR_ONE_DAY = (
    "INSERT INTO snapshot SELECT * REPLACE ('sess-14' AS event_id, 14::BIGINT AS seq)"
    " FROM snapshot WHERE seq = 2"
)

# (case name, SQL that breaks the good data, text of the check that must fail)
BROKEN_CASES = [
    (
        "null_in_required_field",
        "UPDATE snapshot SET park_id = NULL",
        "field park_id has no missing",
    ),
    (
        "column_missing_from_every_file",
        "ALTER TABLE snapshot DROP COLUMN game_day; ALTER TABLE stats DROP COLUMN game_day",
        "field 'game_day' is present",
    ),
    (
        "game_month_out_of_range",
        "UPDATE snapshot SET game_month = 8",
        "field game_month has a maximum of 7",
    ),
    (
        "game_month_out_of_range_in_plugin_stats_only",
        "UPDATE stats SET game_month = 8",
        "field game_month has a maximum of 7",
    ),
    (
        "seq_below_one",
        "UPDATE snapshot SET seq = 0, event_id = 'sess-0' WHERE seq = 2",
        "field seq has a minimum of 1",
    ),
    (
        "park_rating_above_999",
        "UPDATE snapshot SET park_rating = 1000",
        "field park_rating has a maximum of 999",
    ),
    (
        "null_cash_tenths",
        "UPDATE snapshot SET cash_tenths = NULL",
        "field cash_tenths has no missing",
    ),
    (
        "null_plugin_stats_counter",
        "UPDATE stats SET lines_dropped_total = NULL",
        "field lines_dropped_total has no missing",
    ),
    (
        "envelope_column_missing_from_the_first_file_only",
        "ALTER TABLE snapshot DROP COLUMN game_day",
        "field game_day has no missing",
    ),
    (
        "fractional_seq",
        "ALTER TABLE snapshot ALTER seq TYPE DOUBLE; UPDATE snapshot SET seq = 2.5 WHERE seq = 2",
        "seq is a whole number",
    ),
    (
        "fractional_cash_tenths",
        "ALTER TABLE snapshot ALTER cash_tenths TYPE DOUBLE;"
        " UPDATE snapshot SET cash_tenths = 12.5",
        "cash_tenths is a whole number",
    ),
    (
        "fractional_total_admissions",
        "ALTER TABLE snapshot ALTER total_admissions TYPE DOUBLE;"
        " UPDATE snapshot SET total_admissions = 40.5",
        "total_admissions is a whole number",
    ),
    (
        "text_in_number_column",
        "ALTER TABLE snapshot ALTER guests_in_park TYPE VARCHAR;"
        " UPDATE snapshot SET guests_in_park = 'many'",
        "field guests_in_park has type integer",
    ),
    (
        "two_snapshots_for_one_game_day",
        DUPLICATE_SNAPSHOT_FOR_ONE_DAY,
        "primary key (session_id, game_year, game_month, game_day) has no duplicate",
    ),
    (
        "event_id_not_session_and_seq",
        "UPDATE snapshot SET event_id = 'sess-99' WHERE seq = 2",
        "event_id equals session_id-seq",
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


def test_a_failing_rule_downgraded_to_a_warning_still_fails_the_runner(tmp_path: Path) -> None:
    root = write_data(tmp_path / "data")
    contracts_dir = tmp_path / "contracts"
    contracts_dir.mkdir()
    original = (contracts.CONTRACTS_DIR / "park_snapshot.odcs.yaml").read_text(encoding="utf-8")
    # The rule counts the rows, so it fails; severity warning turns that failure into a warning.
    (contracts_dir / "park_snapshot.odcs.yaml").write_text(
        original
        + "    quality:\n"
        + "      - type: sql\n"
        + "        description: rows exist\n"
        + "        severity: warning\n"
        + "        query: SELECT COUNT(*) FROM {object}\n"
        + "        mustBe: 0\n",
        encoding="utf-8",
    )

    problems = contracts.check_all(root, contracts_dir)["park_snapshot.odcs.yaml"]

    assert (
        "test rows exist: warning (Actual custom_sql(park_snapshot) was 2, expected = 0)"
        in problems
    )


def test_the_database_file_is_deleted_after_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path / "scratch"))
    (tmp_path / "scratch").mkdir()
    root = write_data(tmp_path / "data")

    contracts.check_all(root)

    assert list((tmp_path / "scratch").iterdir()) == []


def test_an_environment_variable_cannot_point_the_check_at_another_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good_database = tmp_path / "elsewhere.duckdb"
    contracts.build_views(
        good_database,
        write_data(tmp_path / "good"),
        contracts.view_globs(sorted(contracts.CONTRACTS_DIR.glob("*.odcs.yaml"))),
    )
    broken = write_data(tmp_path / "broken", "UPDATE snapshot SET game_month = 8")
    monkeypatch.setenv("DATACONTRACT_DUCKDB_DATABASE", str(good_database))

    assert contracts.main(["--data-root", str(broken)]) == 1


def test_a_lint_failure_is_reported_as_lint(tmp_path: Path) -> None:
    root = write_data(tmp_path / "data")
    contracts_dir = tmp_path / "contracts"
    contracts_dir.mkdir()
    original = (contracts.CONTRACTS_DIR / "park_snapshot.odcs.yaml").read_text(encoding="utf-8")
    (contracts_dir / "park_snapshot.odcs.yaml").write_text(
        re.sub(r"^version: .*\n", "", original, count=1, flags=re.MULTILINE), encoding="utf-8"
    )

    problems = contracts.check_all(root, contracts_dir)["park_snapshot.odcs.yaml"]

    assert any(line.startswith("lint ") for line in problems), problems


def test_a_contract_that_runs_no_checks_fails_the_runner(tmp_path: Path) -> None:
    root = write_data(tmp_path / "data")
    contracts_dir = tmp_path / "contracts"
    contracts_dir.mkdir()
    (contracts_dir / "park_snapshot.odcs.yaml").write_text(
        """apiVersion: v3.2.0
kind: DataContract
id: park_snapshot
name: park_snapshot
version: 1.0.0
status: active
servers:
  - server: parquet_through_duckdb
    type: duckdb
    database: __DATABASE__
    schema: main
schema:
  - name: park_snapshot
    physicalType: view
""",
        encoding="utf-8",
    )

    problems = contracts.check_all(root, contracts_dir)["park_snapshot.odcs.yaml"]

    assert any("no checks ran" in line for line in problems), problems

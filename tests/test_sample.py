"""Guards on the committed rehearsal extract in `data/sample/rehearsal/`.

The balance check relies on the extract being one straight game timeline: runs 2 and 3 each
continue the previous run's save, so no game month has two statements and, in
`game_ticks_elapsed` order, each statement follows the one before it in game time.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import NamedTuple

import duckdb
import pytest

from openrct2_analytics.ingest.convert import seq_audit

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample" / "rehearsal"
EVENT_FILES = sorted((SAMPLE / "v1").glob("*.parquet"))
FINANCE_FILE = SAMPLE / "v1" / "finance_month.parquet"
SESSION_START_FILE = SAMPLE / "v1" / "session_start.parquet"
SAVE_WRITTEN_FILE = SAMPLE / "v1" / "save_written.parquet"
AUDIT_FILE = SAMPLE / "audit" / "seq_audit.parquet"
MAX_EXTRACT_BYTES = 5 * 1024 * 1024
# Guest types the benchmark park always produces; guest_refused may be empty (benchmark rule 10).
REQUIRED_GUEST_TYPES = ("guest_arrived", "guest_left", "guest_snapshot", "guest_boarded")
# Read by name: the audit may carry more columns than these.
AUDIT_COLUMNS = "session_id, first_seq, last_seq, row_count, missing, duplicates"
# plugin_stats.parquet before the 1.8.0 migration: row count and md5 over the old columns.
STATS_ROWS = 108
STATS_OLD_COLUMNS_FINGERPRINT = "d2275edbcbcdbd4bea002f351faea352"
SKIPPED_FIELDS = (
    "game_actions_skipped_preview_total",
    "game_actions_skipped_prediction_total",
    "game_actions_skipped_confirmed_total",
    "game_actions_skipped_unknown_total",
    "game_actions_skipped_cheat_total",
)
# The game year has 8 months, 0 (March) to 7 (October).
MONTHS_PER_YEAR = 8
LEDGER_LINES = tuple(
    f"{line}_tenths"
    for line in (
        "ride_construction",
        "ride_runningcosts",
        "land_purchase",
        "landscaping",
        "park_entrance_tickets",
        "park_ride_tickets",
        "shop_sales",
        "shop_stock",
        "food_drink_sales",
        "food_drink_stock",
        "wages",
        "marketing",
        "research",
        "interest",
    )
)


@dataclass(frozen=True)
class Statement:
    """One finance_month row: its park, session and every integer column."""

    park_id: str
    session_id: str
    values: dict[str, int]
    new_month_booked_tenths: int | None


class Balance(NamedTuple):
    pairs: int
    mismatches: int
    repeated_months: int

    @property
    def passed(self) -> bool:
        return self.pairs > 0 and self.mismatches == 0 and self.repeated_months == 0


class SessionStart(NamedTuple):
    session_id: str
    loaded_save_id: str | None
    loaded_save_session_id: str | None
    loaded_save_seq_floor: int | None


class SaveWritten(NamedTuple):
    session_id: str
    save_id: str
    seq: int


def parquet_list(paths: list[Path]) -> str:
    return "[" + ", ".join(f"'{path.as_posix()}'" for path in paths) + "]"


def assert_clean(audit: duckdb.DuckDBPyRelation) -> None:
    """Each of the three sessions' seq starts at 1 and runs without a gap or a repeat."""
    rows = audit.select(AUDIT_COLUMNS).fetchall()
    assert len(rows) == 3
    for session_id, first_seq, last_seq, row_count, missing, duplicates in rows:
        assert (first_seq, missing, duplicates) == (1, 0, 0), session_id
        assert row_count == last_seq, session_id


def month_of(statement: Statement) -> tuple[str, int]:
    months = (
        statement.values["statement_year"] * MONTHS_PER_YEAR + statement.values["statement_month"]
    )
    return statement.park_id, months


def consecutive_pairs(statements: list[Statement]) -> list[tuple[Statement, Statement]]:
    """Neighbours in game_ticks_elapsed order, within one park, whose month rises by exactly 1."""
    ordered = sorted(statements, key=lambda s: (s.park_id, s.values["game_ticks_elapsed"]))
    return [
        (earlier, later)
        for earlier, later in zip(ordered, ordered[1:], strict=False)
        if month_of(later) == (earlier.park_id, month_of(earlier)[1] + 1)
    ]


def balance_check(statements: list[Statement]) -> Balance:
    """Per consecutive pair, (cash - loan - booked to the new month) moves by the later 14-line sum.

    A statement without `new_month_booked_tenths` (null or absent) counts it as 0.
    """

    def net(statement: Statement) -> int:
        return (
            statement.values["cash_tenths"]
            - statement.values["bank_loan_tenths"]
            - (statement.new_month_booked_tenths or 0)
        )

    pairs = consecutive_pairs(statements)
    mismatches = sum(
        1
        for earlier, later in pairs
        if net(later) - net(earlier) != sum(later.values[line] for line in LEDGER_LINES)
    )
    months = [month_of(statement) for statement in statements]
    return Balance(len(pairs), mismatches, len(months) - len(set(months)))


def lineage_breaks(starts: list[SessionStart], saves: list[SaveWritten]) -> list[str]:
    """Sessions after the first, in timeline order, not reporting the save the one before wrote.

    A session reports a save when its `loaded_save_id` and `loaded_save_session_id` are that
    save's ID and session, and its `loaded_save_seq_floor` is below the save event's `seq`.
    """
    breaks = []
    for earlier, later in zip(starts, starts[1:], strict=False):
        written = [save for save in saves if save.session_id == earlier.session_id]
        reported = len(written) == 1 and (
            later.loaded_save_id == written[0].save_id
            and later.loaded_save_session_id == written[0].session_id
            and later.loaded_save_seq_floor is not None
            and later.loaded_save_seq_floor < written[0].seq
        )
        if not reported:
            breaks.append(later.session_id)
    return breaks


@pytest.fixture
def connection() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = duckdb.connect(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def events(connection: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyRelation:
    """Every committed event, all types together, as the converter audits them."""
    return connection.sql(
        f"SELECT park_id, session_id, seq FROM read_parquet({parquet_list(EVENT_FILES)}, "
        "union_by_name = true)"
    )


@pytest.fixture
def statements(connection: duckdb.DuckDBPyConnection) -> list[Statement]:
    """Every column of every statement: the controls below plant on the file's lines."""
    relation = connection.read_parquet(FINANCE_FILE.as_posix())
    rows = [dict(zip(relation.columns, row, strict=True)) for row in relation.fetchall()]
    return [
        Statement(
            park_id=str(row["park_id"]),
            session_id=str(row["session_id"]),
            values={
                name: value
                for name, value in row.items()
                if name != "new_month_booked_tenths" and isinstance(value, int)
            },
            new_month_booked_tenths=(
                row["new_month_booked_tenths"]
                if isinstance(row["new_month_booked_tenths"], int)
                else None
            ),
        )
        for row in rows
    ]


@pytest.fixture
def starts(connection: duckdb.DuckDBPyConnection) -> list[SessionStart]:
    """Each session's start, in game-time order: the sessions form one straight timeline."""
    relation = connection.read_parquet(SESSION_START_FILE.as_posix())
    rows = relation.order("game_ticks_elapsed").select(", ".join(SessionStart._fields)).fetchall()
    return [SessionStart(*row) for row in rows]


@pytest.fixture
def saves(connection: duckdb.DuckDBPyConnection) -> list[SaveWritten]:
    relation = connection.read_parquet(SAVE_WRITTEN_FILE.as_posix())
    return [SaveWritten(*row) for row in relation.select(", ".join(SaveWritten._fields)).fetchall()]


def test_extract_is_at_most_5_mb() -> None:
    files = [path for path in SAMPLE.rglob("*") if path.is_file()]

    assert [path.stem for path in EVENT_FILES] == [
        "finance_month",
        "game_action",
        "guest_arrived",
        "guest_boarded",
        "guest_left",
        "guest_refused",
        "guest_snapshot",
        "park_snapshot",
        "plugin_stats",
        "ride_snapshot",
        "save_written",
        "session_start",
        "weather_change",
    ]
    assert all(path in files for path in [*EVENT_FILES, AUDIT_FILE])
    assert sum(path.stat().st_size for path in files) <= MAX_EXTRACT_BYTES


def test_game_action_file_is_empty_and_the_new_plugin_stats_fields_are_null(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """The sample predates plugin 0.7.0: no player action was recorded, so no stats field is set."""
    new_fields = [
        f"game_actions_{kind}_{label}_total"
        for kind in ("sent", "dropped")
        for label in ("preview", "prediction", "confirmed")
    ] + ["action_query_ms_total", "action_execute_ms_total", *SKIPPED_FIELDS]
    set_in_any_row = " OR ".join(f"{field} IS NOT NULL" for field in new_fields)
    actions = connection.read_parquet((SAMPLE / "v1" / "game_action.parquet").as_posix())
    stats = connection.read_parquet((SAMPLE / "v1" / "plugin_stats.parquet").as_posix())

    assert actions.aggregate("count(*)").fetchall() == [(0,)]
    assert stats.filter(set_in_any_row).aggregate("count(*)").fetchall() == [(0,)]


def test_plugin_stats_keeps_its_108_rows_and_old_values_after_the_column_migration(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Converted at contract 1.7.0, then migrated to 1.8.0 by adding five null columns."""
    file = (SAMPLE / "v1" / "plugin_stats.parquet").as_posix()
    old_columns = f"(select * exclude ({', '.join(SKIPPED_FIELDS)}) from '{file}')"
    row = connection.execute(
        "select count(*), md5(string_agg(cast(t as varchar), '|' order by cast(t as varchar))) "
        f"from {old_columns} t"
    ).fetchone()
    types = connection.execute(
        f"select column_name, column_type from (describe select * from '{file}')"
    ).fetchall()

    assert row == (STATS_ROWS, STATS_OLD_COLUMNS_FINGERPRINT)
    assert types[-5:] == [(name, "BIGINT") for name in SKIPPED_FIELDS]


def test_each_required_guest_type_has_at_least_one_row(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    empty = [
        event_type
        for event_type in REQUIRED_GUEST_TYPES
        if connection.read_parquet((SAMPLE / "v1" / f"{event_type}.parquet").as_posix())
        .aggregate("count(*)")
        .fetchall()
        == [(0,)]
    ]

    assert empty == []


def test_one_park_across_three_sessions(events: duckdb.DuckDBPyRelation) -> None:
    counts = events.aggregate("count(DISTINCT park_id), count(DISTINCT session_id)").fetchone()

    assert counts == (1, 3)


def test_sample_parks_are_registered_for_rehearsal(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Protect the publish audit's unregistered-park check."""
    feed_files = sorted((SAMPLE / "registry" / "v1").glob("park_registry_*.csv"))
    assert feed_files
    registry: dict[str, str] = {}
    for feed_file in feed_files:
        with feed_file.open(newline="", encoding="utf-8") as feed:
            registry.update({row["park_id"]: row["data_set"] for row in csv.DictReader(feed)})

    sample_park_ids = {
        row[0]
        for row in connection.sql(
            f"SELECT DISTINCT park_id FROM read_parquet({parquet_list(EVENT_FILES)}, "
            "union_by_name = true)"
        ).fetchall()
    }

    assert all(registry.get(park_id) == "rehearsal" for park_id in sample_park_ids)


def test_seq_audit_rerun_on_committed_events_is_clean(events: duckdb.DuckDBPyRelation) -> None:
    assert_clean(seq_audit(events))


def test_committed_audit_matches_a_recomputation_from_the_committed_events(
    connection: duckdb.DuckDBPyConnection, events: duckdb.DuckDBPyRelation
) -> None:
    recomputed = seq_audit(events).fetchall()
    committed = connection.read_parquet(AUDIT_FILE.as_posix())
    ordered = committed.order("session_id").select(", ".join(seq_audit(events).columns))

    assert ordered.fetchall() == recomputed


def test_committed_audit_is_clean(connection: duckdb.DuckDBPyConnection) -> None:
    assert_clean(connection.read_parquet(AUDIT_FILE.as_posix()))


def test_each_sessions_seq_1_is_its_session_start(connection: duckdb.DuckDBPyConnection) -> None:
    all_events = connection.sql(
        f"SELECT session_id, seq, event_type FROM read_parquet({parquet_list(EVENT_FILES)}, "
        "union_by_name = true)"
    )
    sessions = {row[0] for row in all_events.select("session_id").distinct().fetchall()}
    firsts = all_events.filter("seq = 1").select("session_id, event_type").fetchall()

    assert len(sessions) == 3
    assert sorted(firsts) == sorted((session, "session_start") for session in sessions)


def test_each_session_has_a_monthly_statement(
    events: duckdb.DuckDBPyRelation, statements: list[Statement]
) -> None:
    sessions = {row[0] for row in events.select("session_id").distinct().fetchall()}

    assert {statement.session_id for statement in statements} == sessions


def test_sessions_2_and_3_each_report_the_save_the_session_before_wrote(
    starts: list[SessionStart], saves: list[SaveWritten]
) -> None:
    assert len(starts) == 3
    # Session 1 loaded the fixture copy, which no plugin 0.3.0 session has saved.
    assert starts[0].loaded_save_id is None
    assert lineage_breaks(starts, saves) == []


def test_a_planted_wrong_save_session_or_floor_breaks_the_lineage(
    starts: list[SessionStart], saves: list[SaveWritten]
) -> None:
    session_1_save = next(save for save in saves if save.session_id == starts[0].session_id)
    session_2_save = next(save for save in saves if save.session_id == starts[1].session_id)
    skipped_a_save = [*starts[:2], starts[2]._replace(loaded_save_id=session_1_save.save_id)]
    wrong_session = [*starts[:2], starts[2]._replace(loaded_save_session_id=starts[0].session_id)]
    floor_at_the_cut = [*starts[:2], starts[2]._replace(loaded_save_seq_floor=session_2_save.seq)]

    assert lineage_breaks(skipped_a_save, saves) == [starts[2].session_id]
    assert lineage_breaks(wrong_session, saves) == [starts[2].session_id]
    assert lineage_breaks(floor_at_the_cut, saves) == [starts[2].session_id]


def test_consecutive_statements_balance_exactly(statements: list[Statement]) -> None:
    result = balance_check(statements)

    assert result.pairs >= 1
    assert result.mismatches == 0
    assert result.repeated_months == 0
    assert result.passed


def planted_balance(statements: list[Statement], column: str) -> Balance:
    """The balance check after +1 tenth on `column` of the later statement of the first pair."""
    planted = list(statements)
    _, later = consecutive_pairs(planted)[0]
    if column == "new_month_booked_tenths":
        planted_statement = replace(
            later, new_month_booked_tenths=(later.new_month_booked_tenths or 0) + 1
        )
    else:
        values = {**later.values, column: later.values[column] + 1}
        planted_statement = replace(later, values=values)
    planted[planted.index(later)] = planted_statement
    return balance_check(planted)


def test_a_planted_tenth_on_any_ledger_line_fails_the_balance(
    statements: list[Statement],
) -> None:
    # The lines come from the file's columns, so a helper that omits a line cannot also
    # omit its control. Seven lines are 0 in every committed statement; only this covers them.
    lines = [
        column
        for column in statements[0].values
        if column.endswith("_tenths") and column not in ("cash_tenths", "bank_loan_tenths")
    ]
    undetected = [line for line in lines if planted_balance(statements, line).passed]

    assert len(lines) == 14
    assert undetected == []
    assert all(planted_balance(statements, line).mismatches >= 1 for line in lines)


def test_a_planted_tenth_on_the_loan_fails_the_balance(statements: list[Statement]) -> None:
    # The loan is 0 in every committed statement; only this control covers the loan side.
    result = planted_balance(statements, "bank_loan_tenths")

    assert result.mismatches >= 1
    assert not result.passed


def test_a_planted_tenth_on_the_booked_amount_fails_the_balance(
    statements: list[Statement],
) -> None:
    # The amount is 0 in the committed sample (null in older captures); the control plants +1 on it,
    # counting null as 0.
    result = planted_balance(statements, "new_month_booked_tenths")

    assert result.mismatches >= 1
    assert not result.passed


def test_a_repeated_statement_month_fails_the_balance(statements: list[Statement]) -> None:
    last = max(statements, key=lambda statement: statement.values["game_ticks_elapsed"])
    later_values = {**last.values, "game_ticks_elapsed": last.values["game_ticks_elapsed"] + 1}
    repeated = [*statements, replace(last, values=later_values)]

    result = balance_check(repeated)

    assert result.repeated_months == 1
    assert not result.passed

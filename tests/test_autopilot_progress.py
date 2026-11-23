"""Autopilot progress lines (spec R11, R12), the run summary (R14) and the dollar display."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from openrct2_analytics.ingest import autopilot_progress as ap
from openrct2_analytics.ingest.autopilot_progress import AutopilotProgress, display_usd, summarize

FINANCE_TS = Path(__file__).resolve().parents[1] / "plugin" / "src" / "finance.ts"


class Fixture:
    """A progress watch on a fake clock that records every line it says."""

    def __init__(self, planned_days: int = 9, limit_seconds: float = 1200.0) -> None:
        self.now = 0.0
        self.lines: list[str] = []
        self.progress = AutopilotProgress(
            "7", planned_days, limit_seconds, self.lines.append, clock=lambda: self.now
        )

    def land(self, at: float, event: dict[str, object]) -> None:
        self.now = at
        self.progress.on_landed(event)
        self.progress.tick()  # the listener thread only queues lines; the main thread says them

    def tick(self, at: float) -> None:
        self.now = at
        self.progress.tick()


def snapshot(year: int, month: int, day: int, **changes: object) -> dict[str, object]:
    event: dict[str, object] = {
        "event_type": "park_snapshot",
        "game_year": year,
        "game_month": month,
        "game_day": day,
        "guests_in_park": 10,
    }
    event.update(changes)
    return event


def statement(year: int, month: int, **tenths: int) -> dict[str, object]:
    event: dict[str, object] = {
        "event_type": "finance_month",
        "statement_year": year,
        "statement_month": month,
    }
    event.update({f"{name}_tenths": value for name, value in tenths.items()})
    return event


def test_first_snapshot_says_the_month_line_with_estimating_time_left() -> None:
    f = Fixture()

    f.land(0.0, {"event_type": "session_start"})
    f.land(5.0, snapshot(2, 0, 1))

    assert f.lines == [
        "autopilot: park 7 · March 1, year 2 · 2 events · 0 min 5 s elapsed · estimating time left"
    ]


def test_new_month_says_a_line_with_the_time_left_rounded_up() -> None:
    f = Fixture(planned_days=9)

    f.land(0.0, snapshot(2, 0, 1))
    f.land(30.0, snapshot(2, 0, 2))  # same month: no line
    f.land(90.0, snapshot(2, 1, 1))  # three dates seen, two full days done in 90 s

    # 90 s / 2 days * (9 - 2) days = 315 s, which is 5.25 min, so 6 min
    assert f.lines[1:] == [
        "autopilot: park 7 · April 1, year 2 · 3 events · 1 min 30 s elapsed · about 6 min left"
    ]


def test_time_left_is_zero_when_the_planned_days_are_done() -> None:
    f = Fixture(planned_days=1)

    f.land(0.0, snapshot(2, 0, 1))
    f.land(60.0, snapshot(2, 1, 1))

    assert f.lines[1].endswith("· 1 min 0 s elapsed · about 0 min left")


def test_a_non_snapshot_event_says_no_month_line() -> None:
    f = Fixture()

    f.land(0.0, {"event_type": "plugin_stats", "game_year": 2, "game_month": 0, "game_day": 1})

    assert f.lines == []


def test_no_stall_line_before_the_first_event() -> None:
    f = Fixture()

    f.tick(10_000.0)

    assert f.lines == []


def test_stall_line_at_60_seconds_but_not_at_59_9() -> None:
    f = Fixture(limit_seconds=1200.0)
    f.land(100.0, snapshot(2, 1, 5))
    f.lines.clear()

    f.tick(159.9)
    assert f.lines == []

    f.tick(160.0)
    assert f.lines == [
        "autopilot: no events for 60 s; the last game date seen was April 5, year 2. "
        "The run stops by itself at its time limit, 20 min after it started."
    ]


def test_stall_limit_rounds_up_to_whole_minutes() -> None:
    f = Fixture(limit_seconds=1201.0)
    f.land(0.0, snapshot(2, 0, 1))
    f.lines.clear()

    f.tick(60.0)

    assert "time limit, 21 min after" in f.lines[0]


def test_stall_before_any_game_date_says_none_seen() -> None:
    f = Fixture()
    f.land(0.0, {"event_type": "session_start"})

    f.tick(60.0)

    assert f.lines[0].startswith("autopilot: no events for 60 s; no game date has been seen yet. ")


def test_one_stall_line_per_stall_then_recovery_then_a_new_stall_may_warn() -> None:
    f = Fixture()
    f.land(0.0, snapshot(2, 0, 1))
    f.lines.clear()

    f.tick(60.0)
    f.tick(120.0)
    assert len(f.lines) == 1

    f.land(130.0, {"event_type": "plugin_stats"})
    assert f.lines[1:] == ["autopilot: events are arriving again."]

    f.tick(189.9)
    assert len(f.lines) == 2
    f.tick(190.0)
    assert len(f.lines) == 3


def test_stall_is_measured_from_the_clock_not_from_emitted_at() -> None:
    f = Fixture()

    f.land(0.0, {"event_type": "plugin_stats", "emitted_at": "2020-01-01T00:00:00Z"})
    f.tick(59.0)

    assert f.lines == []


@pytest.mark.parametrize(
    "bad",
    [
        {"game_month": None},
        {"game_month": "3"},
        {"game_month": True},
        {"game_month": 8},
        {"game_year": 2.5},
        {"game_day": None},
    ],
)
def test_a_snapshot_with_a_missing_or_mistyped_date_field_is_counted_but_says_no_line(
    bad: dict[str, object],
) -> None:
    f = Fixture()
    event = snapshot(2, 0, 1)
    event.update(bad)

    f.land(0.0, event)
    f.land(1.0, snapshot(2, 0, 1))  # a valid line after it lands as usual

    assert len(f.lines) == 1
    assert "· 2 events ·" in f.lines[0]


def test_a_snapshot_with_a_removed_date_key_does_not_raise() -> None:
    f = Fixture()
    event = snapshot(2, 0, 1)
    del event["game_month"]

    f.land(0.0, event)
    f.land(1.0, {})
    f.land(2.0, {"event_type": ["park_snapshot"]})

    assert f.lines == []


def test_summarize_one_year_sums_the_statements_and_reads_the_guests() -> None:
    events = [
        snapshot(2, 0, 1, guests_in_park=40),
        statement(2, 0, shop_sales=500, wages=-200),
        statement(2, 1, shop_sales=300, wages=-200, interest=-5),
        snapshot(2, 2, 1, guests_in_park=90),
    ]

    result = summarize(events)

    assert result.profit_tenths == 395
    assert result.statement_count == 2
    assert result.first_statement == (2, 0)
    assert result.last_statement == (2, 1)
    assert (result.guests_start, result.guests_end) == (40, 90)


def test_summarize_two_years_names_both_ends() -> None:
    result = summarize([statement(2, 7, shop_sales=10), statement(3, 0, shop_sales=10)])

    assert result.first_statement == (2, 7)
    assert result.last_statement == (3, 0)
    assert result.profit_tenths == 20


def test_summarize_with_no_statement_and_no_snapshot() -> None:
    result = summarize([{"event_type": "plugin_stats"}])

    assert result.profit_tenths == 0
    assert result.statement_count == 0
    assert result.first_statement is None
    assert result.last_statement is None
    assert result.guests_start is None
    assert result.guests_end is None


def test_an_expense_line_arriving_negative_lowers_the_profit() -> None:
    income_only = summarize([statement(2, 0, shop_sales=1000)])
    with_wages = summarize([statement(2, 0, shop_sales=1000, wages=-400)])

    assert income_only.profit_tenths == 1000
    assert with_wages.profit_tenths == 600


def test_summarize_skips_mistyped_money_and_guests() -> None:
    bad = statement(2, 0, shop_sales=100)
    bad["wages_tenths"] = "-50"
    bad["marketing_tenths"] = True
    snap = snapshot(2, 0, 1, guests_in_park="many")

    result = summarize([snap, bad])

    assert result.profit_tenths == 100
    assert result.guests_start is None


def test_statement_without_a_year_counts_but_gives_no_range() -> None:
    event = statement(2, 0, shop_sales=5)
    del event["statement_year"]

    result = summarize([event])

    assert result.statement_count == 1
    assert result.first_statement is None
    assert result.profit_tenths == 5


def test_the_field_list_is_the_plugins_expenditure_types_with_tenths_added() -> None:
    text = FINANCE_TS.read_text(encoding="utf-8")
    block = re.search(r"EXPENDITURE_TYPES[^=]*=\s*\[(.*?)\]", text, re.DOTALL)
    assert block is not None
    plugin_types = re.findall(r'"([a-z_]+)"', block.group(1))

    assert len(plugin_types) == 14
    assert [f"{name}_tenths" for name in ap.EXPENDITURE_TYPES] == [
        f"{name}_tenths" for name in plugin_types
    ]


@pytest.mark.parametrize(
    ("tenths", "text"),
    [
        (-1234, "-$123.40"),
        (0, "$0.00"),
        (1234567, "$123,456.70"),
        (5, "$0.50"),
        (-5, "-$0.50"),
    ],
)
def test_display_usd(tenths: int, text: str) -> None:
    assert display_usd(tenths) == text


def test_summarize_adds_every_one_of_the_14_statement_lines() -> None:
    lines = {
        "ride_construction": -1,
        "ride_runningcosts": -2,
        "land_purchase": -4,
        "landscaping": -8,
        "park_entrance_tickets": 16,
        "park_ride_tickets": 32,
        "shop_sales": 64,
        "shop_stock": -128,
        "food_drink_sales": 256,
        "food_drink_stock": -512,
        "wages": -1024,
        "marketing": -2048,
        "research": -4096,
        "interest": -8192,
    }

    # each line is a different power of two, so leaving any one out changes the total
    assert summarize([statement(2, 0, **lines)]).profit_tenths == -15647


def test_time_left_never_goes_below_zero_after_the_planned_days() -> None:
    f = Fixture(planned_days=1)

    f.land(0.0, snapshot(2, 0, 1))
    f.land(30.0, snapshot(2, 0, 2))
    f.land(60.0, snapshot(2, 0, 3))
    f.land(90.0, snapshot(2, 1, 1))  # three full days done against one planned

    assert f.lines[-1].endswith("· 1 min 30 s elapsed · about 0 min left")


def test_on_landed_never_calls_say_and_tick_says_the_queued_lines() -> None:
    lines: list[str] = []
    progress = AutopilotProgress("7", 9, 1200.0, lines.append, clock=lambda: 0.0)

    progress.on_landed(snapshot(1, 0, 1))

    assert lines == []
    progress.tick()
    assert lines == [
        "autopilot: park 7 \u00b7 March 1, year 1 \u00b7 1 events \u00b7 0 min 0 s elapsed "
        "\u00b7 estimating time left"
    ]
    progress.tick()
    assert len(lines) == 1  # said once, not again

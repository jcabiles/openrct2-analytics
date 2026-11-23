"""Capture report tests, on real Parquet from the real converter over synthetic raw lines."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openrct2_analytics.ingest.capture_report import CostRow, judge_cost, render, summarize
from openrct2_analytics.ingest.convert import convert
from tests.test_convert import PARK, event, land
from tests.test_convert_event_types import FINANCE_PAYLOAD, START_PAYLOAD, typed_event

SINCE = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
OLD = "2026-09-29T08:00:00.000Z"
NEW = "2026-09-30T13:00:00.000Z"


def stamp(line: str, received_at: str) -> str:
    """The raw line with its ``received_at`` replaced."""
    doc = json.loads(line)
    doc["received_at"] = received_at
    return json.dumps(doc)


def stats(session: str, seq: int, *, received_at: str = NEW, **fields: object) -> str:
    """A judged-by-default ``plugin_stats`` line; fields override the converter test's payload."""
    judged: dict[str, object] = {"warmup": False}
    judged.update(fields)
    return stamp(event(session, seq, "plugin_stats", **judged), received_at)


def start(session: str, name: str, *, headless: bool, received_at: str = NEW) -> str:
    payload = {**START_PAYLOAD, "park_name": name, "headless": headless}
    return stamp(typed_event(session, 1, "session_start", payload), received_at)


def finance(session: str, seq: int) -> str:
    return stamp(typed_event(session, seq, "finance_month", FINANCE_PAYLOAD), NEW)


def snapshot(session: str, seq: int, received_at: str = NEW) -> str:
    return stamp(event(session, seq), received_at)


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    return tmp_path / "raw"


@pytest.fixture
def out(tmp_path: Path) -> Path:
    return tmp_path / "out"


def make_run(raw: Path, out: Path) -> None:
    """Session sa (with start, excluded rows, a drop count) and sb (no start), plus old sessions."""
    land(
        raw,
        start("sa-aaaaaaaa", "Dusty Greens", headless=True),
        # Excluded: warm-up, clock date, and game speed 2 all carry a bigger worst tick.
        stats("sa-aaaaaaaa", 2, warmup=True, period_ticks=100, work_ms_total=50, worst_tick_ms=30),
        stats(
            "sa-aaaaaaaa",
            3,
            period_ticks=1000,
            work_ms_total=500,
            worst_tick_ms=4,
            worst_tick_at_ticks=777,
            lines_dropped_total=2,
        ),
        stats(
            "sa-aaaaaaaa",
            4,
            period_ticks=3000,
            work_ms_total=1000,
            worst_tick_ms=2,
            lines_dropped_total=5,
        ),
        stats("sa-aaaaaaaa", 5, clock="date", worst_tick_ms=99, work_ms_total=9999),
        stats("sa-aaaaaaaa", 6, game_speed=2, worst_tick_ms=88, work_ms_total=8888),
        finance("sa-aaaaaaaa", 7),
        snapshot("sa-aaaaaaaa", 8),
        stats(
            "sb-bbbbbbbb",
            1,
            period_ticks=1000,
            work_ms_total=200,
            worst_tick_ms=6,
            worst_tick_at_ticks=321,
        ),
        # An earlier session: judged-looking rows that must not count.
        snapshot("so-oooooooo", 1, OLD),
        stats("so-oooooooo", 2, received_at=OLD, worst_tick_ms=500, lines_dropped_total=77),
    )
    assert convert(raw, out).ok


def test_two_sessions_are_summarized_and_the_earlier_one_is_left_out(raw: Path, out: Path) -> None:
    make_run(raw, out)

    summary = summarize(out, SINCE)

    assert [s.session_id for s in summary.sessions] == ["sa-aaaaaaaa", "sb-bbbbbbbb"]
    assert summary.events_by_type == {
        "finance_month": 1,
        "park_snapshot": 1,
        "plugin_stats": 6,
        "session_start": 1,
    }
    assert summary.total_events == 9
    assert summary.finance_months == 1
    assert summary.earlier_violations == []
    first = summary.sessions[0]
    assert (first.park_id, first.park_name, first.headless) == (PARK, "Dusty Greens", True)
    assert (first.first_seq, first.last_seq, first.seq_problem) == (1, 8, None)


def test_warmup_date_clock_and_other_game_speeds_are_not_judged(raw: Path, out: Path) -> None:
    make_run(raw, out)

    cost = summarize(out, SINCE).cost

    assert cost is not None
    assert cost.judged_ticks == 5000
    assert cost.worst_tick_ms == 6
    assert (cost.worst_tick_session_id, cost.worst_tick_at_ticks) == ("sb-bbbbbbbb", 321)
    assert cost.mean_tick_ms == pytest.approx(1700 / 5000)
    assert cost.worst_within_limit
    assert cost.mean_within_limit


def test_limits_are_inclusive(raw: Path, out: Path) -> None:
    land(raw, stats("sa", 1, period_ticks=100, work_ms_total=125, worst_tick_ms=10))
    convert(raw, out)

    cost = summarize(out, SINCE).cost

    assert cost is not None
    assert (cost.worst_tick_ms, cost.mean_tick_ms) == (10.0, 1.25)
    assert cost.worst_within_limit
    assert cost.mean_within_limit
    assert "OVER" not in render(summarize(out, SINCE), 0)


def test_exceeding_the_limits_is_flagged(raw: Path, out: Path) -> None:
    land(
        raw,
        stats("sa", 1, period_ticks=100, work_ms_total=125, worst_tick_ms=10),
        stats("sa", 2, period_ticks=100, work_ms_total=126, worst_tick_ms=10.5),
    )
    convert(raw, out)

    cost = summarize(out, SINCE).cost

    assert cost is not None
    assert cost.mean_tick_ms == pytest.approx(1.255)
    assert not cost.worst_within_limit
    assert not cost.mean_within_limit
    assert "OVER the limit" in render(summarize(out, SINCE), 0)


def test_judged_rows_that_sum_to_zero_ticks_carry_no_numbers(raw: Path, out: Path) -> None:
    land(raw, stats("sa", 1, period_ticks=0, work_ms_total=0, worst_tick_ms=0))
    convert(raw, out)

    assert summarize(out, SINCE).cost is None


def test_a_parquet_folder_with_an_apostrophe_is_read(tmp_path: Path) -> None:
    folder = tmp_path / "o'brien"
    land(folder / "raw", snapshot("sa", 1))
    assert convert(folder / "raw", folder / "out").ok

    assert summarize(folder / "out", SINCE).total_events == 1


def test_no_judged_rows_says_so_and_carries_no_numbers(raw: Path, out: Path) -> None:
    land(
        raw,
        stats("sa", 1, warmup=True),
        stats("sa", 2, clock="date"),
        stats("sa", 3, game_speed=3),
        snapshot("sa", 4),
    )
    convert(raw, out)

    summary = summarize(out, SINCE)

    assert summary.cost is None
    text = render(summary, 0)
    assert "no judged rows" in text
    assert "worst tick" not in text
    assert "per tick" not in text


def test_a_session_without_session_start_is_marked(raw: Path, out: Path) -> None:
    make_run(raw, out)

    second = summarize(out, SINCE).sessions[1]

    assert not second.has_session_start
    assert (second.park_name, second.headless) == (None, None)
    assert "session sb-bbbbb" in render(summarize(out, SINCE), 0)
    assert "no session_start" in render(summarize(out, SINCE), 0)


def test_largest_lines_dropped_total_is_reported_per_session(raw: Path, out: Path) -> None:
    make_run(raw, out)

    sessions = summarize(out, SINCE).sessions

    assert sessions[0].lines_dropped_total == 5
    assert sessions[1].lines_dropped_total == 0
    assert "5 lines dropped" in render(summarize(out, SINCE), 0)


def test_a_session_with_no_plugin_stats_has_no_drop_count(raw: Path, out: Path) -> None:
    land(raw, snapshot("sa", 1))
    convert(raw, out)

    assert summarize(out, SINCE).sessions[0].lines_dropped_total is None


def test_an_earlier_session_with_a_seq_gap_is_only_a_warning(raw: Path, out: Path) -> None:
    land(
        raw,
        snapshot("sold-oooooooo", 1, OLD),
        snapshot("sold-oooooooo", 3, OLD),
        snapshot("snew-nnnnnnnn", 1),
        snapshot("snew-nnnnnnnn", 2),
    )
    assert not convert(raw, out).ok

    summary = summarize(out, SINCE)

    assert [s.session_id for s in summary.sessions] == ["snew-nnnnnnnn"]
    assert summary.sessions[0].seq_problem is None
    assert summary.total_events == 2
    assert len(summary.earlier_violations) == 1
    assert "sold-ooo" in summary.earlier_violations[0]
    assert "1 seq number(s) missing" in summary.earlier_violations[0]
    assert "WARNING, earlier run: session sold-ooo" in render(summary, 0)


def test_a_seq_violation_in_this_run_is_on_the_session_not_a_warning(raw: Path, out: Path) -> None:
    land(raw, snapshot("sa", 1), snapshot("sa", 3))
    convert(raw, out)

    summary = summarize(out, SINCE)

    assert summary.sessions[0].seq_problem == "1 seq number(s) missing"
    assert summary.earlier_violations == []
    assert "seq audit FAILED (1 seq number(s) missing)" in render(summary, 0)


def test_an_event_received_exactly_at_the_start_time_is_in_this_run(raw: Path, out: Path) -> None:
    land(raw, snapshot("sa", 1, "2026-09-30T12:00:00.000Z"), snapshot("sb", 1, OLD))
    convert(raw, out)

    assert [s.session_id for s in summarize(out, SINCE).sessions] == ["sa"]


def test_a_start_time_without_a_time_zone_is_refused(raw: Path, out: Path) -> None:
    land(raw, snapshot("sa", 1))
    convert(raw, out)

    with pytest.raises(ValueError, match="time zone"):
        summarize(out, datetime(2026, 9, 30, 12, 0))  # noqa: DTZ001


def test_render_states_the_key_numbers_with_units(raw: Path, out: Path) -> None:
    make_run(raw, out)

    text = render(summarize(out, SINCE), 0)

    assert "Events landed this run: 9" in text
    assert "Sessions this run: 2" in text
    assert "session sa-aaaaaaaa, park kpark1: Dusty Greens, headless yes" in text
    assert "seq 1 to 8; seq audit ok" in text
    assert "Plugin cost over 5000 judged ticks" in text
    assert "worst tick 6.000 ms (limit 10 ms, within the limit)" in text
    assert "in session sb-bbbbbbbb at game tick 321" in text
    assert "mean 0.3400 ms per tick (limit 1.25 ms per tick, within the limit)" in text
    assert "Monthly statements (finance_month) received: 1" in text
    assert "WARNING" not in text
    assert "removed" not in text


def test_render_prints_the_malformed_line_count(raw: Path, out: Path) -> None:
    land(raw, snapshot("sa", 1))
    convert(raw, out)

    text = render(summarize(out, SINCE), 3)

    assert "Malformed raw lines in the whole raw folder (not converted): 3" in text


def test_session_ids_are_printed_in_full_and_stay_distinct(raw: Path, out: Path) -> None:
    first, second = "s1790808448200-ysgwg2", "s1790808944922-mnvwio"
    land(raw, snapshot(first, 1), snapshot(second, 1))
    convert(raw, out)

    text = render(summarize(out, SINCE), 0)

    assert f"session {first}, park {PARK}" in text
    assert f"session {second}, park {PARK}" in text


def test_judge_cost_returns_none_without_judged_ticks() -> None:
    assert judge_cost([]) is None
    assert judge_cost([CostRow("sa", 0, 3.0, 4.0, 5)]) is None


def test_judge_cost_sums_ticks_and_work() -> None:
    cost = judge_cost(
        [
            CostRow("sa", 3, 1.5, 2.0, 30),
            CostRow("sb", 5, 6.5, 4.0, 50),
        ]
    )

    assert cost is not None
    assert cost.judged_ticks == 8
    assert cost.mean_tick_ms == 1.0


def test_judge_cost_limits_are_inclusive() -> None:
    within = judge_cost([CostRow("sa", 4, 5.0, 10.0, 40)])
    over = judge_cost([CostRow("sb", 4, 5.004, 10.001, 40)])

    assert within is not None
    assert within.worst_within_limit
    assert within.mean_within_limit
    assert over is not None
    assert not over.worst_within_limit
    assert not over.mean_within_limit


def test_judge_cost_breaks_worst_tick_ties_by_session_then_tick() -> None:
    cost = judge_cost(
        [
            CostRow("sb", 1, 1.0, 8.0, 1),
            CostRow("sa", 1, 1.0, 8.0, 99),
            CostRow("sa", 1, 1.0, 8.0, 9),
        ]
    )

    assert cost is not None
    assert (cost.worst_tick_session_id, cost.worst_tick_at_ticks) == ("sa", 9)

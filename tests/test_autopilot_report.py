"""The success report's three finish lines (spec R13) and their order, at function level."""

from __future__ import annotations

from pathlib import Path

import pytest

from openrct2_analytics.ingest.autopilot_progress import RunSummary
from openrct2_analytics.ingest.autopilot_report import ReportFacts, report

STARTED = "Started from: park-a-2026-11-12.park (game date October 20, year 3)."
GUESTS = "Guests in the park: 120 at the start, 340 at the end."
REFURBISH = "To refurbish the park, load save/Park A-last-plugin-save-2026-11-14.park."


def summary(**changes: object) -> RunSummary:
    base: dict[str, object] = {
        "profit_tenths": 395,
        "statement_count": 2,
        "first_statement": (2, 0),
        "last_statement": (2, 1),
        "guests_start": 120,
        "guests_end": 340,
    }
    return RunSummary(**{**base, **changes})  # type: ignore[arg-type]


def said(tmp_path: Path, capsys: pytest.CaptureFixture[str], run: RunSummary) -> list[str]:
    work = tmp_path / "work"
    work.mkdir()
    bench = tmp_path / "bench"
    bench.mkdir()
    report(
        ReportFacts(
            park_id="park-a",
            work_dir=work,
            bench_dir=bench,
            ready_ignored=None,
            dated="Park A-last-plugin-save-2026-11-14.park",
            source_year=3,
            target_year=2003,
            session_id="s-1",
            event_count=50,
            source_file="park-a-2026-11-12.park",
            source_date=(3, 7, 20),
            summary=run,
        )
    )
    return capsys.readouterr().out.splitlines()


def test_the_three_lines_come_in_order_before_the_refurbish_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = said(tmp_path, capsys, summary())

    assert lines[:4] == [
        STARTED,
        "Profit: $39.50 from 2 monthly statements (March to April, year 2), the game's total "
        "of all 14 statement lines, shown in dollars for display.",
        GUESTS,
        REFURBISH,
    ]


def test_statements_across_two_game_years_name_both(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = said(
        tmp_path,
        capsys,
        summary(profit_tenths=-1234, first_statement=(3, 7), last_statement=(4, 0)),
    )

    assert lines[1] == (
        "Profit: -$123.40 from 2 monthly statements (October, year 3 to March, year 4), the "
        "game's total of all 14 statement lines, shown in dollars for display."
    )


def test_no_statement_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    lines = said(
        tmp_path,
        capsys,
        summary(profit_tenths=0, statement_count=0, first_statement=None, last_statement=None),
    )

    assert lines[1] == "Profit: no monthly statement closed during this run."


def test_unknown_guests_are_said_as_unknown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = said(tmp_path, capsys, summary(guests_start=None, guests_end=None))

    assert lines[2] == "Guests in the park: unknown at the start, unknown at the end."

"""An interrupt during the warehouse reads after a filing ends the run at exit 130.

Each case sends a real SIGINT to this process while DuckDB runs a deliberately slow query; DuckDB
ends that query with ``RuntimeError('Query interrupted')``, which must come out as the interrupt.
"""

from __future__ import annotations

import os
import signal
import threading
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest import play_status, previous_park
from tests.auto_file_support import BEFORE, _run
from tests.auto_file_support import data as data  # noqa: F401  (pytest fixture)
from tests.test_auto_file_answers import Registering
from tests.test_auto_file_park_number import PARK_2_NEW
from tests.test_auto_file_previous_park import YEAR_2000, _later_park

SLOW = "(SELECT count(*) FROM range(20000000000)) > 0"


def _slow_view(tmp_path: Path, name: str, columns: str, row: str) -> None:
    """Replace ``marts.<name>`` with a view that takes far longer than the test waits."""
    with duckdb.connect(str(tmp_path / play_status.WAREHOUSE)) as connection:
        connection.execute(f"DROP TABLE IF EXISTS marts.{name}")
        connection.execute(
            f"CREATE VIEW marts.{name} AS SELECT * FROM (VALUES {row}) AS t({columns}) WHERE {SLOW}"
        )


def _sigint_after_call(
    monkeypatch: pytest.MonkeyPatch, module: object, name: str
) -> list[threading.Timer]:
    """Send SIGINT to this process 0.3 s after ``module.<name>`` starts, to hit its query."""
    timers: list[threading.Timer] = []
    real = getattr(module, name)

    def call_then_signal(*args: object, **kwargs: object) -> object:
        timer = threading.Timer(0.3, os.kill, [os.getpid(), signal.SIGINT])
        timers.append(timer)
        timer.start()
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, call_then_signal)
    return timers


def test_a_real_interrupt_during_the_note_query_ends_at_130(
    data: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _later_park(data, tmp_path, [])
    _slow_view(
        tmp_path,
        "obt_park_year",
        "park_id, company_year, close_status, operating_profit, capital_spending, interest_costs",
        "('park-1', 2000, 'complete', 1::DECIMAL(18,2), 0::DECIMAL(18,2), 0::DECIMAL(18,2))",
    )
    timers = _sigint_after_call(monkeypatch, previous_park, "read_previous")

    code, _, _ = _run(tmp_path, "company", filed=Registering(0))

    timers[0].join()
    captured = capsys.readouterr()
    assert code == 130
    assert captured.out == PARK_2_NEW
    assert "Traceback" not in captured.err
    assert not (tmp_path / BEFORE).exists()


def test_a_real_interrupt_during_the_park_number_query_ends_at_130(
    data: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _later_park(data, tmp_path, YEAR_2000)
    _slow_view(
        tmp_path,
        "dim_park",
        "park_id, park_number, company_start_year, park_name",
        "('park-2', 2, 2001, 'park-2')",
    )
    timers = _sigint_after_call(monkeypatch, play_status, "dim_park_numbers")

    code, _, _ = _run(tmp_path, "company", filed=Registering(0))

    timers[0].join()
    captured = capsys.readouterr()
    assert code == 130
    assert captured.out == (
        PARK_2_NEW
        + "auto-file interrupted.\n"
        + "auto-file: already registered by this run: park park-2 (first played Nov 12) as "
        "company park, "
        "start year 2001.\n"
        "To file the rest, run: make auto-file DATA_SET=company COUNT_AS=company "
        "(run it here; the launcher starts a new play)\n"
    )
    assert "Traceback" not in captured.err


def test_a_runtime_error_from_the_note_query_is_not_an_interrupt(
    data: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _later_park(data, tmp_path, YEAR_2000)

    def broken(project_dir: Path, park_ids: object) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(previous_park, "read_previous", broken)

    with pytest.raises(RuntimeError, match="boom"):
        _run(tmp_path, "company", filed=Registering(0))

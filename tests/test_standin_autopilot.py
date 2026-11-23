"""The stand-in game's year stop: a start date, ``finance_month`` rows and the target-year save.

Each test runs ``tests/bench_standin_game.py`` as a child process against a listener of its own,
as the rehearsal tests do through the benchmark, and reads the lines it sent. Helper texts are
written by hand in the form ``var TARGET_YEAR = <year>;``.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

from tests.bench_standin_game import HELPER_FILE
from tests.test_bench_run import REPO_ROOT

Date = tuple[int, int, int]


def helper(target_year: int | None) -> str:
    lines = ['var SAVE_FILENAME = "autopilot-save";']
    if target_year is not None:
        lines.append(f"var TARGET_YEAR = {target_year};")
    return "\n".join(lines) + "\n"


def run_standin(
    tmp_path: Path, entry: dict[str, object], helper_text: str, park: bytes = b"PARK"
) -> list[dict[str, object]]:
    """Run one launch with ``exit_early`` and return the lines it sent, in order."""
    user = tmp_path / "user"
    (user / "plugin").mkdir(parents=True)
    (user / "save").mkdir()
    (user / "plugin" / HELPER_FILE).write_text(helper_text, encoding="utf-8")
    park_file = tmp_path / "park.park"
    park_file.write_bytes(park)
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        script = tmp_path / "script.json"
        launch = {"save": True, "exit_early": True, **entry}
        script.write_text(
            json.dumps({"listener_port": server.getsockname()[1], "launches": [launch]}),
            encoding="utf-8",
        )
        received = bytearray()

        def read() -> None:
            connection, _ = server.accept()
            with connection:
                while chunk := connection.recv(65536):
                    received.extend(chunk)

        reader = threading.Thread(target=read)
        reader.start()
        env = {**os.environ, "BENCH_STANDIN_SCRIPT": str(script), "PYTHONPATH": str(REPO_ROOT)}
        argv = ["host", str(park_file), "--headless", "--port", "1", "--user-data-path", str(user)]
        subprocess.run(
            [sys.executable, "-m", "tests.bench_standin_game", *argv],
            cwd=REPO_ROOT,
            env=env,
            check=True,
            timeout=60,
        )
        reader.join(timeout=30)
    return [json.loads(line) for line in received.decode("utf-8").splitlines()]


def date(line: dict[str, object]) -> Date:
    return (line["game_year"], line["game_month"], line["game_day"])  # type: ignore[return-value]


def dates_of(lines: list[dict[str, object]], event_type: str) -> list[Date]:
    return [date(line) for line in lines if line["event_type"] == event_type]


def test_target_year_saves_on_1_march_of_that_year_and_not_the_earlier_one(tmp_path: Path) -> None:
    # Starts 10 September (month 6) of year 1, so 1 March of year 2 passes before the target.
    entry = {"start_date": [1, 6, 10], "stats": 600}

    lines = run_standin(tmp_path, entry, helper(3))

    assert dates_of(lines, "save_written") == [(3, 0, 1)]
    assert dates_of(lines, "finance_month").count((2, 0, 1)) == 1
    assert (tmp_path / "user" / "save" / "autopilot-save.park").exists()


def test_a_start_on_31_october_plays_1_march_of_the_next_year_first(tmp_path: Path) -> None:
    lines = run_standin(tmp_path, {"start_date": [1, 7, 31], "stats": 50}, helper(2))

    assert dates_of(lines, "session_start") == [(1, 7, 31)]
    assert dates_of(lines, "park_snapshot") == [(2, 0, 1)]
    assert dates_of(lines, "save_written") == [(2, 0, 1)]


def test_a_start_on_1_march_does_not_save_on_its_own_1_march(tmp_path: Path) -> None:
    lines = run_standin(tmp_path, {"start_date": [1, 0, 1], "stats": 300}, helper(2))

    assert dates_of(lines, "session_start") == [(1, 0, 1)]
    assert dates_of(lines, "save_written") == [(2, 0, 1)]


def test_a_helper_without_a_target_year_saves_after_the_last_day(tmp_path: Path) -> None:
    entry = {"start_date": [1, 7, 28], "stats": 8}

    lines = run_standin(tmp_path, entry, helper(None))

    assert dates_of(lines, "park_snapshot")[-1] == (2, 0, 5)
    assert dates_of(lines, "save_written") == [(2, 0, 5)]
    assert lines[-1]["event_type"] == "save_written"


def test_a_launch_without_a_start_date_keeps_its_fixed_dates_and_end_save(tmp_path: Path) -> None:
    lines = run_standin(tmp_path, {"stats": 3}, helper(2))

    assert [line["event_type"] for line in lines].count("save_written") == 1
    assert lines[-1]["event_type"] == "save_written"
    assert all(line["game_year"] == 1 for line in lines)


def test_finance_month_rows_come_on_each_day_1_from_the_start_date(tmp_path: Path) -> None:
    entry = {"start_date": [1, 7, 28], "stats": 70}

    lines = run_standin(tmp_path, entry, helper(None))

    finance = [line for line in lines if line["event_type"] == "finance_month"]
    assert [date(line) for line in finance] == [(2, 0, 1), (2, 1, 1), (2, 2, 1)]
    assert [(line["statement_year"], line["statement_month"]) for line in finance] == [
        (1, 7),
        (2, 0),
        (2, 1),
    ]


def test_session_start_lineage_comes_from_the_loaded_parks_marker(tmp_path: Path) -> None:
    entry = {"start_date": [1, 7, 31], "stats": 1}

    lines = run_standin(tmp_path, entry, helper(None), park=b"PARK+standin-4+standin-7")

    assert lines[0]["event_type"] == "session_start"
    assert lines[0]["loaded_save_id"] == "save-standin-7"
    assert lines[0]["loaded_save_session_id"] == "standin-7"


def test_session_start_without_a_marker_has_no_lineage(tmp_path: Path) -> None:
    lines = run_standin(tmp_path, {"start_date": [1, 7, 31], "stats": 1}, helper(None))

    assert "loaded_save_id" not in lines[0]
    assert "loaded_save_session_id" not in lines[0]


def test_nothing_is_dated_after_the_target_save(tmp_path: Path) -> None:
    entry = {"start_date": [1, 7, 28], "stats": 40}

    lines = run_standin(tmp_path, entry, helper(2))

    assert dates_of(lines, "save_written") == [(2, 0, 1)]
    assert max(date(line) for line in lines) == (2, 0, 1)
    assert lines[-1]["event_type"] == "save_written"
    assert dates_of(lines, "park_snapshot") == [(1, 7, 29), (1, 7, 30), (1, 7, 31), (2, 0, 1)]

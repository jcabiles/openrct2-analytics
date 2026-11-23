"""The autopilot run's October check against the stop save's ``seq`` (spec section 6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from openrct2_analytics.ingest.bench_setup import RunFolder
from tests.test_autopilot_run import Runner, rewrite
from tests.test_bench_run import make_bench


@pytest.fixture(name="runner")
def _runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Runner:
    return Runner(make_bench(tmp_path, monkeypatch), monkeypatch)


def test_an_october_statement_after_the_save_fails(runner: Runner) -> None:
    # October's row and the save swap seq: the kept timeline is cut at the save, so it is lost.
    def swap(folder: RunFolder) -> None:
        seqs: dict[object, object] = {}

        def note(event: dict[str, object]) -> dict[str, object]:
            seqs[event["event_type"]] = event["seq"]
            return event

        def exchange(event: dict[str, object]) -> dict[str, object]:
            other = {"finance_month": "save_written", "save_written": "finance_month"}
            if event["event_type"] in other:
                event["seq"] = seqs[other[str(event["event_type"])]]
                event["event_id"] = f"{event['session_id']}-{event['seq']}"
            return event

        rewrite(folder, note)
        rewrite(folder, exchange)

    result = runner.run(tamper=swap)

    assert result.reached_stop is True
    assert result.problems == [
        "No finance_month row for October of game year 3 before the save_written row."
    ]

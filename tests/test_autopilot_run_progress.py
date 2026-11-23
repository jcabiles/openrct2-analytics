"""Autopilot progress lines that land after the run's last poll are still printed."""

from __future__ import annotations

import pytest

import tests.test_autopilot_run as run_tests
from openrct2_analytics.ingest.bench_play import play as real_play
from tests.test_autopilot_run import PARK, Runner, _runner  # noqa: F401  # _runner is the fixture

LATE = {"event_type": "park_snapshot", "game_year": 9, "game_month": 4, "game_day": 2}


def test_a_line_queued_after_the_last_poll_is_still_printed(
    runner: Runner, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def play_then_land_late(*args: object, **kwargs: object) -> str | None:
        problem = real_play(*args, **kwargs)  # type: ignore[arg-type]
        kwargs["watch"].on_landed(LATE)  # type: ignore[attr-defined]  # after the last poll
        return problem

    monkeypatch.setattr(run_tests, "real_play", play_then_land_late)

    runner.run()

    assert any(
        line.startswith(f"autopilot: park {PARK} \u00b7 July 2, year 9 \u00b7 ")
        for line in capsys.readouterr().out.splitlines()
    )

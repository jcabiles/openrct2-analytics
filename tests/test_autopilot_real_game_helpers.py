"""The planting helper of the by-hand real-game test, run offline in ``make check``.

``plant_second_park_day`` adds a second park's rows beside step 1's. It must leave the source
proof (``find_source``) able to pair the first park's real save, or the by-hand run would stop
on a refusal instead of testing the product.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openrct2_analytics.ingest.autopilot_source import SourceFound
from tests.autopilot_fixtures import event_row, plant_park_snapshot, plant_session_start
from tests.test_autopilot_real_game import plant_second_park_day
from tests.test_autopilot_source import World


def test_planting_a_second_park_day_keeps_the_first_parks_source_found(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.copy("Beta", datetime(2026, 11, 12, 21, 0, 0))
    plant_session_start(world.parquet, [event_row(1, park_name="Crazy Castle")])
    plant_park_snapshot(world.parquet, [event_row(2, cash_tenths=500, guests_in_park=3)])
    before = world.find()
    assert isinstance(before, SourceFound)
    assert before.event_id == "sess-1-42"

    plant_second_park_day(world.parquet, "park-a")

    after = world.find()
    assert after == before

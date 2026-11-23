// A closed, untested coaster reports zero statistics; after its first test, the next daily snapshot reports them.
import assert from "node:assert/strict";
import { test } from "node:test";

import { createGame } from "./fake-game.mjs";

const DAY_TICKS = 520;
const ZERO_STATISTICS = {
  maxSpeed: 0,
  averageSpeed: 0,
  rideTime: 0,
  rideLength: 0,
  maxPositiveVerticalGs: 0,
  maxNegativeVerticalGs: 0,
  maxLateralGs: 0,
  totalAirTime: 0,
  numDrops: 0,
  numLiftHills: 0,
  highestDropHeight: 0,
};
const TESTED_STATISTICS = {
  maxSpeed: 62.5,
  averageSpeed: 34.25,
  rideTime: 95.5,
  rideLength: 1205.25,
  maxPositiveVerticalGs: 3.875,
  maxNegativeVerticalGs: -1.625,
  maxLateralGs: 2.375,
  totalAirTime: 7.75,
  numDrops: 5,
  numLiftHills: 3,
  highestDropHeight: 39.5,
};
const STATISTIC_FIELDS = [
  ["max_speed_mph", "maxSpeed"],
  ["average_speed_mph", "averageSpeed"],
  ["ride_time_seconds", "rideTime"],
  ["ride_length_meters", "rideLength"],
  ["max_positive_vertical_g", "maxPositiveVerticalGs"],
  ["max_negative_vertical_g", "maxNegativeVerticalGs"],
  ["max_lateral_g", "maxLateralGs"],
  ["total_air_time_seconds", "totalAirTime"],
  ["drop_count", "numDrops"],
  ["lift_hill_count", "numLiftHills"],
  ["highest_drop_height_units", "highestDropHeight"],
];

function captureDay(game) {
  game.day(game.date.ticksElapsed + DAY_TICKS);
  game.tick();
}

test("a closed untested coaster sends zero statistics before its test and values the next day", () => {
  const game = createGame().load().start();
  const ride = game.addRide({
    type: 3,
    status: "closed",
    ...ZERO_STATISTICS,
    track: {
      segments: [
        { countsAsInversion: false },
        { countsAsInversion: true },
        { countsAsInversion: true },
        { countsAsInversion: false },
      ],
      startIndex: 0,
      closed: true,
    },
  });
  game.socket.accept();

  captureDay(game);
  const untested = game.eventsOfType("ride_snapshot").find((event) => event.ride_id === ride.id);
  assert.ok(untested);
  assert.strictEqual(untested.status, "closed");
  for (const [field] of STATISTIC_FIELDS) {
    assert.strictEqual(untested[field], 0, `${field} before the first test`);
  }
  assert.strictEqual(untested.inversion_count, 2);

  ride.status = "testing";
  Object.assign(ride, TESTED_STATISTICS);
  captureDay(game);

  const snapshots = game.eventsOfType("ride_snapshot").filter((event) => event.ride_id === ride.id);
  assert.strictEqual(snapshots.length, 2);
  const tested = snapshots[1];
  assert.strictEqual(tested.status, "testing");
  for (const [field, statistic] of STATISTIC_FIELDS) {
    assert.strictEqual(tested[field], TESTED_STATISTICS[statistic], `${field} after the first test`);
  }
  assert.strictEqual(tested.inversion_count, 2);
  assert.notStrictEqual(untested.game_ticks_elapsed, tested.game_ticks_elapsed);
});

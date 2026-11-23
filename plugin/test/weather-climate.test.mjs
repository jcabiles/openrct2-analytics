// Tests for the weather and climate fields, driven through the stand-in game in fake-game.mjs.
import assert from "node:assert/strict";
import { test } from "node:test";

import { createGame } from "./fake-game.mjs";

const DAY_TICKS = 520;

test("each park_snapshot carries the weather and temperature read in its day callback", () => {
  const game = createGame().load().start();
  game.socket.accept();
  game.climateValues.current = { weather: "heavyRain", temperature: 12 };
  game.day(1520);
  game.climateValues.current = { weather: "blizzard", temperature: -7 };
  game.day(1520 + DAY_TICKS);
  const snapshots = game.eventsOfType("park_snapshot");
  assert.deepEqual(
    snapshots.map((event) => [event.weather, event.temperature_c]),
    [["heavyRain", 12], ["blizzard", -7]],
  );
});

test("session_start carries the climate read once at plugin start", () => {
  const game = createGame().load();
  game.climateValues.type = "hotAndDry";
  game.start();
  game.climateValues.type = "cold";
  game.socket.accept();
  game.day(1520);
  const [sessionStart] = game.received;
  assert.deepEqual([sessionStart.event_type, sessionStart.seq, sessionStart.climate], ["session_start", 1, "hotAndDry"]);
});

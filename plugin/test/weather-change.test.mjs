// Tests for the weather_change event, driven through the stand-in game in fake-game.mjs. Each tick fires the
// plugin's tick hook, which checks climate.current first.
import assert from "node:assert/strict";
import { test } from "node:test";

import { createGame } from "./fake-game.mjs";

function startGame() {
  const game = createGame().load().start();
  game.socket.accept();
  return game;
}

// Sets the current weather, runs one tick, and returns the tick it ran on.
function changeTo(game, weather, temperature = 18) {
  game.climateValues.current = { weather, temperature };
  game.tick();
  return game.date.ticksElapsed;
}

// Enough further ticks, at no fake cost, to hand every queued line off.
function settle(game) {
  game.tick(3);
}

function changes(game) {
  return game.eventsOfType("weather_change");
}

test("no weather_change is sent at start or on unchanged ticks", () => {
  const game = startGame();
  game.tick(5);
  settle(game);
  assert.equal(changes(game).length, 0);
});

test("one weather_change per change, stamped with the tick that observed it", () => {
  const game = startGame();
  game.tick(4);
  game.climateValues.future = { weather: "thunder", temperature: 9 };
  const tick = changeTo(game, "heavyRain", 12);
  game.tick(4);
  settle(game);
  const [change, ...rest] = changes(game);
  assert.equal(rest.length, 0);
  assert.deepEqual(
    [change.weather, change.previous_weather, change.upcoming_weather, change.temperature_c, change.game_ticks_elapsed],
    ["heavyRain", "sunny", "thunder", 12, tick],
  );
});

test("previous_weather is the weather before each change", () => {
  const game = startGame();
  changeTo(game, "heavyRain");
  changeTo(game, "thunder");
  changeTo(game, "sunny");
  settle(game);
  assert.deepEqual(
    changes(game).map((event) => [event.previous_weather, event.weather]),
    [["sunny", "heavyRain"], ["heavyRain", "thunder"], ["thunder", "sunny"]],
  );
});

test("a temperature-only change sends nothing", () => {
  const game = startGame();
  changeTo(game, "sunny", 30);
  changeTo(game, "sunny", -4);
  settle(game);
  assert.equal(changes(game).length, 0);
});

test("an unchanged tick reads climate.current once and never reads the upcoming weather", () => {
  const game = startGame();
  game.calls["climate.current"] = 0;
  game.tick();
  assert.deepEqual([game.calls["climate.current"], game.calls["climate.future"] ?? 0], [1, 0]);
});

test("a change tick reads climate.current once and climate.future once, the temperature coming from that one read", () => {
  const game = startGame();
  game.climateValues.future = { weather: "thunder", temperature: 9 };
  game.climateValues.current = { weather: "heavyRain", temperature: 12 };
  game.calls["climate.current"] = 0;
  game.calls["climate.future"] = 0;
  game.tick();
  assert.deepEqual([game.calls["climate.current"], game.calls["climate.future"]], [1, 1]);
  settle(game);
  assert.equal(changes(game)[0].temperature_c, 12);
});

test("a current weather that is not a string sends nothing and leaves the stored weather", () => {
  const game = startGame();
  changeTo(game, undefined);
  changeTo(game, null);
  changeTo(game, 7);
  // Back to the stored weather: no change. A later real change names the stored weather as the previous one.
  changeTo(game, "sunny");
  changeTo(game, "snow");
  settle(game);
  assert.deepEqual(changes(game).map((event) => [event.previous_weather, event.weather]), [["sunny", "snow"]]);
});

test("a seed that is not a string is replaced by the first string read, which sends nothing", () => {
  const game = createGame().load();
  game.climateValues.current = { weather: undefined, temperature: 18 };
  game.start();
  game.socket.accept();
  changeTo(game, "sunny");
  changeTo(game, "rain");
  settle(game);
  assert.deepEqual(changes(game).map((event) => [event.previous_weather, event.weather]), [["sunny", "rain"]]);
});

test("an upcoming weather that is not a string is sent as null", () => {
  const game = startGame();
  game.climateValues.future = { weather: undefined, temperature: 18 };
  changeTo(game, "rain");
  settle(game);
  assert.equal(changes(game)[0].upcoming_weather, null);
});

test("a climate read that throws still lets the work queue run, and its error reaches the game", () => {
  const game = startGame();
  game.addRide();
  game.day(1520);
  // No tick has run yet, so the first seat poll is due on the throwing tick; each poll reads the cars once.
  const before = game.calls["map.rides"] ?? 0;
  const carReadsBefore = game.calls["map.getAllEntities"] ?? 0;
  game.throwing.add("climate.current");
  assert.throws(() => game.tick(), /stand-in climate\.current throws/);
  game.throwing.delete("climate.current");
  assert.ok(game.calls["map.rides"] > before, "the ride list step ran on the throwing tick");
  assert.ok(game.calls["map.getAllEntities"] > carReadsBefore, "the seat poll ran on the throwing tick");
});

test("a weather check that uses the allowance leaves the queue one step on that tick", () => {
  const game = createGame().load().start();
  game.socket.accept();
  for (let i = 0; i < 5; i += 1) game.addRide();
  game.tick();
  game.day(game.date.ticksElapsed + 2);
  const before = game.calls["map.getRide"] ?? 0;
  // 5 ms is past the 4 ms allowance (WORK_ALLOWANCE_MS, work.ts:16), so the queue runs its one guaranteed step and stops.
  game.costs["climate.current"] = 5;
  game.tick();
  game.costs["climate.current"] = 0;
  assert.equal((game.calls["map.getRide"] ?? 0) - before, 0, "only the ride_list step ran");
  assert.ok(game.calls["map.rides"] >= 1);
});

test("a costed weather check is the weather tick part, not a work step", () => {
  const game = startGame();
  // Every period holds the seat poll or a day's queued steps, so no period is free of work steps. The check's
  // 1.5 ms is the largest time on its tick: were it a step, it would be worst_step_kind and worst_step_ms.
  game.tick();
  game.day(game.date.ticksElapsed + 2);
  game.costs["climate.current"] = 1.5;
  game.tick();
  game.costs["climate.current"] = 0;
  game.day(game.date.ticksElapsed + 2);
  const stats = game.eventsOfType("plugin_stats").pop();
  assert.equal(stats.worst_tick_kind_ms, "weather:1.500");
  assert.deepEqual([stats.worst_step_kind, stats.worst_step_ms], ["ride_list", 0]);
});

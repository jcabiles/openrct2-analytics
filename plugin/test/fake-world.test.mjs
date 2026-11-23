// Tests for the stand-in game's own hooks and world (fake-world.mjs, fake-game.mjs): the parts the plugin tests
// for the work queue, ride snapshots, climate and save lineage rely on.
import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import { createGame } from "./fake-game.mjs";

// Runs code in the game's script context, as the plugin's own code would run.
function inGame(game, code) {
  return vm.runInContext(code, game.context);
}

test("tick(n) fires the tick hooks n times and adds n to ticksElapsed, costing msPerTick each", () => {
  const game = createGame({ msPerTick: 2 }).load();
  game.date.ticksElapsed = 100;
  const start = game.wallMs;
  inGame(game, "globalThis.fired = 0; context.subscribe('interval.tick', () => { fired += 1; });");
  game.tick(3);
  assert.equal(inGame(game, "fired"), 3);
  assert.equal(game.date.ticksElapsed, 103);
  assert.equal(game.wallMs - start, 6);
  game.tick();
  assert.equal(game.date.ticksElapsed, 104);
});

test("subscribe still rejects a hook the stand-in lacks", () => {
  const game = createGame().load();
  assert.throws(() => inGame(game, "context.subscribe('unknown.hook', () => {})"), /no hook/);
});

test("a ride read costs the fake time set for its API", () => {
  const game = createGame().load();
  game.addRide();
  game.costs["map.getRide"] = 5;
  game.costs["map.rides"] = 7;
  const start = game.wallMs;
  inGame(game, "map.getRide(0); map.rides;");
  assert.equal(game.wallMs - start, 12);
});

test("save() runs the map.save hooks, copies storage, and loadSave restores it in a fresh context", () => {
  const game = createGame().load();
  inGame(
    game,
    "globalThis.saves = 0; " +
      "context.subscribe('map.save', () => { saves += 1; context.getParkStorage().set('k', { n: 1 }); });",
  );
  const saved = game.save();
  assert.equal(inGame(game, "saves"), 1);
  game.storage.values.k.n = 2;
  assert.deepEqual(saved.storage.k, { n: 1 });
  const oldContext = game.context;
  game.loadSave(saved);
  assert.notEqual(game.context, oldContext);
  assert.deepEqual(game.storage.values.k, { n: 1 });
  assert.equal(inGame(game, "typeof saves"), "undefined");
});

test("a ride has 255 station slots with only the chosen ones used; demolishing removes it", () => {
  const game = createGame().load();
  const ride = game.addRide({ usedStations: [{ queueTime: 30 }, { queueTime: 45 }] });
  const other = game.addRide({ status: "closed" });
  assert.equal(ride.stations.length, 255);
  assert.deepEqual(ride.stations.filter((s) => s.start !== null).map((s) => s.queueTime), [30, 45]);
  const unused = ride.stations[2];
  assert.deepEqual([unused.start, unused.length, unused.queueTime], [null, 0, 0]);
  assert.equal(inGame(game, "map.rides.length"), 2);
  game.demolishRide(ride.id);
  assert.equal(inGame(game, "map.getRide(0)"), null);
  assert.equal(inGame(game, "map.getRide(1).status"), other.status);
  assert.equal(inGame(game, "map.rides.length"), 1);
});

test("climate starts with a valid type and weather and a test can set them", () => {
  const game = createGame().load();
  assert.equal(inGame(game, "climate.type"), "coolAndWet");
  game.climateValues.current = { weather: "thunder", temperature: 25 };
  game.climateValues.type = "hotAndDry";
  assert.equal(inGame(game, "climate.current.weather"), "thunder");
  assert.equal(inGame(game, "climate.type"), "hotAndDry");
});

test("daysPerMonth wraps day() into the next month, and with it off day() only counts days", () => {
  const off = createGame().load();
  for (let i = 0; i < 40; i += 1) off.day(1000 + i);
  assert.equal(off.date.day, 41);
  assert.equal(off.date.monthsElapsed, 0);

  const game = createGame({ daysPerMonth: 3 }).load();
  game.date.month = 7;
  const fired = [];
  game.dayHooks.push(() => fired.push(game.date.day));
  game.day(1);
  game.day(2);
  assert.equal(game.date.day, 3);
  game.day(3);
  assert.deepEqual([game.date.year, game.date.month, game.date.day, game.date.monthsElapsed], [2, 0, 1, 1]);
  assert.equal(game.expenditures.wages[0], 0);
  assert.deepEqual(fired, [2, 3, 1]);
});

test("map.rides is a new array on every read, so clearing or sorting it leaves the world alone", () => {
  const game = createGame().load();
  game.addRide();
  game.addRide();
  assert.equal(inGame(game, "map.rides === map.rides"), false);
  inGame(game, "map.rides.splice(0); map.rides.reverse();");
  assert.equal(inGame(game, "map.rides.length"), 2);
  assert.equal(game.rides.length, 2);
});

test("a ride's stations are built fresh on every read, and each read charges costs['ride.stations']", () => {
  const game = createGame().load();
  game.costs["ride.stations"] = 3;
  game.addRide();
  const start = game.wallMs;
  assert.equal(inGame(game, "map.getRide(0).stations === map.getRide(0).stations"), false);
  assert.equal(game.wallMs - start, 6);
  assert.equal(inGame(game, "map.getRide(0).stations.length"), 255);
  inGame(game, "map.getRide(0).stations[0].queueTime = 99;");
  assert.equal(inGame(game, "map.getRide(0).stations[0].queueTime"), 0);
});

test("addRide reuses the lowest free ride id, as OpenRCT2 reuses a demolished ride's slot", () => {
  const game = createGame().load();
  for (let i = 0; i < 3; i += 1) game.addRide();
  game.demolishRide(1);
  assert.equal(game.addRide().id, 1);
  game.demolishRide(0);
  game.demolishRide(2);
  assert.equal(game.addRide().id, 0);
  assert.equal(game.addRide().id, 2);
  assert.equal(game.addRide().id, 3);
});

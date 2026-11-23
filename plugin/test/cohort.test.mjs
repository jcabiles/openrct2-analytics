// Tests for the followed cohort: the random pick on arrival, the cap of 100, replacement on departure and the
// once-a-game-day guest_snapshot, driven through the stand-in game with scripted Math.random draws. The expected
// field names are written out here, never derived from the plugin or the contracts.
import assert from "node:assert/strict";
import { test } from "node:test";

import { createGame } from "./fake-game.mjs";

const SNAPSHOT_FIELDS = [
  "guest_key", "guest_id", "happiness", "hunger", "thirst", "nausea", "energy", "guest_cash_tenths",
  "items_carried", "thought_type", "thought_item",
];
const DAY_TICKS = 520;
const JOIN = 0.1;
const NO_JOIN = 0.5;

function startGame(draws = [], seed = () => {}) {
  const game = createGame().load();
  seed(game);
  game.start();
  game.socket.accept();
  // After start(), so the park ID's and session ID's Math.random draws have been taken.
  game.draws.push(...draws);
  return game;
}

function captureDay(game) {
  game.day(game.date.ticksElapsed + DAY_TICKS);
  game.tick(3);
}

function pick(event, fields) {
  return fields.map((field) => event[field]);
}

function inCohort(game) {
  return game.eventsOfType("guest_arrived").map((event) => event.in_cohort);
}

test("an arrival joins when its draw is below 0.5 and not at 0.5 or above, one draw per arrival", () => {
  const game = startGame([0.1, 0.5, 0.49, 0.9, 0]);
  for (let i = 0; i < 5; i++) game.generateGuest();
  game.tick(3);
  assert.deepEqual(inCohort(game), [true, false, true, false, true]);
  assert.deepEqual(game.draws, [], "every scripted draw was used, in arrival order");
});

test("guests seeded at session start never join the cohort and use no draw", () => {
  const game = createGame().load();
  game.addGuest();
  // Pushed before start(): the minted park ID and the session ID take one draw each, so a seeding draw would
  // take the JOIN and the seeded guest would join.
  game.draws.push(NO_JOIN, NO_JOIN, JOIN);
  game.start();
  game.socket.accept();
  assert.deepEqual(game.draws, [JOIN], "start() drew only for the two IDs");
  captureDay(game);
  assert.equal(game.eventsOfType("guest_snapshot").length, 0);
  assert.deepEqual(game.draws, [JOIN]);
});

test("a full cohort of 100 admits no one and draws nothing for the next arrival", () => {
  const game = startGame(new Array(101).fill(JOIN));
  for (let i = 0; i < 101; i++) game.generateGuest();
  game.tick(3);
  const flags = inCohort(game);
  assert.equal(flags.length, 101);
  assert.equal(flags.filter(Boolean).length, 100);
  assert.equal(flags[100], false);
  assert.deepEqual(game.draws, [JOIN], "the 101st arrival drew nothing while the cohort was full");
});

test("an exit frees a place that a later arrival can take, and the exit says in_cohort", () => {
  const game = startGame(new Array(100).fill(JOIN));
  for (let i = 0; i < 100; i++) game.generateGuest({ isInPark: false });
  game.tick(3);
  game.draws.push(JOIN, JOIN);
  game.generateGuest(); // slot 100: the cohort is full, no draw
  game.tick();
  assert.equal(inCohort(game)[100], false);
  assert.equal(game.draws.length, 2);
  game.replaceEntity(0); // the first member goes
  captureDay(game);
  const left = game.eventsOfType("guest_left");
  assert.deepEqual(left.map((event) => [event.guest_id, event.in_cohort]), [[0, true]]);
  game.generateGuest(); // slot 0 again: takes the freed place
  game.tick();
  assert.equal(inCohort(game)[101], true);
  game.generateGuest(); // full again
  game.tick();
  assert.equal(inCohort(game)[102], false);
  assert.equal(game.draws.length, 1, "the arrival into the full cohort drew nothing");
});

test("a reused ID's earlier member frees its place before the new arrival draws", () => {
  const game = startGame(new Array(100).fill(JOIN));
  for (let i = 0; i < 100; i++) game.generateGuest();
  game.tick(3);
  game.draws.push(JOIN);
  game.replaceEntity(7);
  game.generateGuest({}, 7);
  game.tick();
  assert.deepEqual(game.eventsOfType("guest_left").map((event) => [event.exit_reason, event.in_cohort]), [["id_reused", true]]);
  assert.equal(inCohort(game)[100], true);
  assert.deepEqual(game.draws, []);
});

test("each member gets one guest_snapshot a game day with the guest's values, items joined by | and the newest thought", () => {
  const game = startGame([JOIN, JOIN, JOIN, NO_JOIN]);
  game.generateGuest({
    happiness: 200, hunger: 10, thirst: 20, nausea: 30, energy: 40, cash: 1234,
    items: [{ type: "balloon" }, { type: "umbrella" }],
    thoughts: [{ type: "intense", item: 6 }, { type: "good_value", item: 2 }],
  });
  game.generateGuest({ items: [{ type: "map" }], thoughts: [] });
  game.generateGuest({ items: [] });
  game.generateGuest(); // not in the cohort
  game.tick(3);
  for (let day = 0; day < 3; day++) captureDay(game);
  const snapshots = game.eventsOfType("guest_snapshot");
  assert.equal(snapshots.length, 9, "three members, three days");
  assert.deepEqual(Object.keys(snapshots[0]).filter((key) => !SNAPSHOT_FIELDS.includes(key)).sort(), [
    "emitted_at", "event_id", "event_type", "game_day", "game_month", "game_ticks_elapsed", "game_year",
    "park_id", "plugin_version", "schema_version", "seq", "session_id",
  ]);
  assert.deepEqual(pick(snapshots[0], SNAPSHOT_FIELDS), [1, 0, 200, 10, 20, 30, 40, 1234, "balloon|umbrella", "intense", 6]);
  assert.deepEqual(pick(snapshots[1], SNAPSHOT_FIELDS), [2, 1, 128, 64, 64, 0, 96, 500, "map", null, null]);
  assert.deepEqual(pick(snapshots[2], SNAPSHOT_FIELDS).slice(8), ["", null, null], "no items is the empty string");
  const perDay = {};
  for (const event of snapshots) {
    const key = `${event.game_day}:${event.guest_key}`;
    perDay[key] = (perDay[key] ?? 0) + 1;
  }
  assert.deepEqual(Object.values(perDay), new Array(9).fill(1));
  assert.ok(snapshots.every((event) => event.guest_key !== 4), "the guest that did not join is never snapshotted");
});

test("items_carried joins each item's type, also for a photo that carries more fields", () => {
  const game = startGame([JOIN]);
  game.generateGuest({ items: [{ type: "balloon" }, { type: "photo1", rideId: 3 }] });
  game.tick(3);
  captureDay(game);
  assert.deepEqual(game.eventsOfType("guest_snapshot").map((event) => event.items_carried), ["balloon|photo1"]);
});

test("snapshot() refuses a guest key or ID that is not a JSON-safe integer", () => {
  const game = createGame().load();
  const guest = game.addGuest();
  const cohort = game.context.createCohort();
  assert.throws(() => cohort.snapshot(1.5, 0, guest, []), /guest_key is not a JSON-safe integer: 1\.5/);
  assert.throws(() => cohort.snapshot(1, 2.5, guest, []), /guest_id is not a JSON-safe integer: 2\.5/);
  assert.equal(cohort.snapshot(1, 0, guest, []).guest_id, 0, "whole values pass");
});

test("a member that left gets no further snapshots", () => {
  const game = startGame([JOIN, JOIN]);
  game.generateGuest();
  game.generateGuest();
  game.tick(3);
  captureDay(game);
  assert.equal(game.eventsOfType("guest_snapshot").length, 2);
  game.received.length = 0;
  game.replaceEntity(0);
  captureDay(game);
  assert.deepEqual(game.eventsOfType("guest_snapshot").map((event) => event.guest_key), [2]);
});

test("a member's snapshot waits behind the day's ride items on the day callback's tick", () => {
  const game = startGame([JOIN]);
  game.costs["map.getRide"] = 2;
  for (let i = 0; i < 3; i++) game.addRide();
  game.generateGuest();
  game.tick(3);
  game.received.length = 0;
  game.day(game.date.ticksElapsed + DAY_TICKS);
  assert.equal(game.eventsOfType("guest_snapshot").length, 0, "none on the day callback's tick");
  for (const hook of game.tickHooks) hook(); // the ride list and rides 0 and 1
  game.tick(); // ride 2 alone
  const rideTicks = game.eventsOfType("ride_snapshot").map((event) => event.game_ticks_elapsed);
  assert.equal(game.eventsOfType("guest_snapshot").length, 0, "still none while ride items are pending");
  game.tick();
  const [snapshot] = game.eventsOfType("guest_snapshot");
  assert.ok(snapshot.game_ticks_elapsed > rideTicks[rideTicks.length - 1]);
  assert.equal(game.eventsOfType("guest_snapshot").length, 1);
});

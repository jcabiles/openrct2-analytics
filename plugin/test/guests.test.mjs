// Tests for guest tracking: seeding, arrivals from the guest.generation hook, the daily exit check and refusal
// thoughts, driven through the stand-in game in fake-game.mjs. The expected field names are written out here,
// never derived from the plugin or the contracts, so a misspelled field cannot pass.
import assert from "node:assert/strict";
import { test } from "node:test";
import vm from "node:vm";

import { createGame } from "./fake-game.mjs";

const ENVELOPE = [
  "schema_version", "event_type", "plugin_version", "park_id", "session_id", "game_year", "game_month",
  "game_day", "game_ticks_elapsed", "emitted_at", "seq", "event_id",
];
const ARRIVED_FIELDS = ["guest_key", "guest_id", "generated_at_ticks", "in_cohort", "guest_cash_tenths"];
const LEFT_FIELDS = ["guest_key", "guest_id", "exit_reason", "entered_park", "arrived_in_session", "in_cohort"];
const REFUSED_FIELDS = ["guest_key", "guest_id", "thought_type", "ride_id"];
// The nine ride-refusal thought types, written out here, never read from the plugin.
const REFUSALS = [
  "cant_afford_ride", "bad_value", "not_paying", "intense", "more_thrilling", "sickening", "not_safe",
  "queuing_ages", "not_while_raining",
];
const DAY_TICKS = 520;

// Loads the plugin, lets `seed` place the guests main() will find, starts it and accepts the socket.
function startGame(seed = () => {}, options = {}) {
  const game = createGame(options).load();
  // Every arrival draws for the cohort: these tests are about tracking, so no draw joins it (cohort.test.mjs).
  game.draws.push(...new Array(200).fill(0.99));
  seed(game);
  game.start();
  game.socket.accept();
  return game;
}

// One day callback, then enough ticks (at no fake cost) for the ride items, the held guest steps and the lines.
function captureDay(game) {
  game.day(game.date.ticksElapsed + DAY_TICKS);
  game.tick(3);
}

function lastStats(game) {
  const stats = game.eventsOfType("plugin_stats");
  return stats[stats.length - 1];
}

function guestEvents(game) {
  return game.received.filter((event) => event.event_type.startsWith("guest_"));
}

function pick(event, fields) {
  return fields.map((field) => event[field]);
}

function guestCounts(stats) {
  return [stats.guests_known, stats.guests_known_in_park, stats.arrivals_recorded_total];
}

test("seeding reads all guests once and emits nothing, and no later tick reads all guests", () => {
  let guestReads = 0;
  const game = startGame((g) => {
    // Only the all-guest reads are counted: the seat poll reads map.getAllEntities("car") every 20 ticks.
    const getAllEntities = g.context.map.getAllEntities;
    g.context.map.getAllEntities = (type) => {
      if (type === "guest") guestReads += 1;
      return getAllEntities(type);
    };
    g.addGuest();
    g.addGuest();
    g.addGuest({ isInPark: false });
  });
  assert.equal(guestReads, 1);
  for (let day = 0; day < 3; day++) captureDay(game);
  game.day(game.date.ticksElapsed + DAY_TICKS);
  assert.equal(guestReads, 1, "the only all-guest read is the seeding");
  assert.deepEqual(guestEvents(game), []);
  assert.deepEqual(guestCounts(lastStats(game)), [3, 2, 0]);
});

test("an arrival emits guest_arrived with a new key and the hook's tick, and adds 1 to arrivals_recorded_total", () => {
  const game = startGame((g) => {
    g.addGuest();
    g.addGuest();
  });
  captureDay(game);
  game.generateGuest({ cash: 777, isInPark: false }); // slot 2, on tick 1523
  assert.equal(game.eventsOfType("guest_arrived").length, 0, "the hook only records the arrival");
  game.tick();
  const [arrived] = game.eventsOfType("guest_arrived");
  assert.deepEqual(Object.keys(arrived).sort(), [...ENVELOPE, ...ARRIVED_FIELDS].sort());
  assert.deepEqual(pick(arrived, ARRIVED_FIELDS), [3, 2, 1523, false, 777]);
  assert.equal(arrived.game_ticks_elapsed, 1524, "the arrival step emits it on a later tick");
  game.day(game.date.ticksElapsed + DAY_TICKS);
  assert.deepEqual(guestCounts(lastStats(game)), [3, 2, 1], "an arrival starts outside the park");
});

test("a reused ID emits guest_left (id_reused) for its earlier occupant before the new arrival", () => {
  const game = startGame((g) => g.addGuest());
  captureDay(game); // the seeded guest is checked in the park
  game.replaceEntity(0);
  game.generateGuest(); // the engine reuses slot 0 before the next daily check
  game.tick();
  const events = guestEvents(game);
  assert.deepEqual(events.map((event) => event.event_type), ["guest_left", "guest_arrived"]);
  assert.deepEqual(pick(events[0], LEFT_FIELDS), [1, 0, "id_reused", true, false, false]);
  assert.deepEqual(pick(events[1], ["guest_key", "guest_id"]), [2, 0]);
  assert.ok(events[0].seq < events[1].seq);
});

test("a guest that goes emits guest_left (left) at the next daily check, with entered_park and arrived_in_session right", () => {
  const game = startGame((g) => {
    g.addGuest(); // 0: seeded, will leave its slot empty
    g.addGuest(); // 1: seeded, its slot will hold a money_effect
    g.addGuest(); // 2: seeded, stays
  });
  captureDay(game);
  game.generateGuest({ isInPark: false }); // 3: never enters
  const inside = game.generateGuest({ isInPark: false }); // 4: enters, then walks out
  game.tick(); // both arrival steps
  inside.values.isInPark = true;
  captureDay(game); // the check sees 4 in the park
  game.replaceEntity(0);
  game.replaceEntity(1, "money_effect");
  game.replaceEntity(3);
  inside.values.isInPark = false;
  game.tick(10);
  assert.equal(game.eventsOfType("guest_left").length, 0, "exits are found by the daily check");
  captureDay(game);
  const left = game.eventsOfType("guest_left").map((event) => pick(event, LEFT_FIELDS));
  assert.deepEqual(left.sort((a, b) => a[0] - b[0]), [
    [1, 0, "left", true, false, false],
    [2, 1, "left", true, false, false],
    [4, 3, "left", false, true, false],
    [5, 4, "left", true, true, false],
  ]);
  for (const event of game.eventsOfType("guest_left")) {
    assert.deepEqual(Object.keys(event).sort(), [...ENVELOPE, ...LEFT_FIELDS].sort());
  }
  game.day(game.date.ticksElapsed + DAY_TICKS);
  assert.deepEqual(guestCounts(lastStats(game)), [1, 1, 2]);
});

test("the daily check skips a guest whose arrival is pending: the arrival step reports the reuse", () => {
  const game = startGame((g) => {
    for (let i = 0; i < 6; i++) g.addGuest();
  });
  game.costs["map.getEntity"] = 2;
  game.day(1520);
  game.tick(2); // 1521: the ride list read; 1522: the guest list read, then guests 0 and 1 reach 4 ms
  const entityReads = game.calls["map.getEntity"];
  assert.equal(entityReads, 2);
  game.replaceEntity(5);
  game.generateGuest({ isInPark: false }); // slot 5 again: its arrival is newer than the day's guest items
  game.tick(3); // guests 2 and 3; guest 4, guest 5 skipped, then the arrival step
  assert.equal(game.calls["map.getEntity"], entityReads + 3 + 1, "guests 2 to 4 and the arrival's cash read");
  const events = guestEvents(game);
  assert.deepEqual(
    events.map((event) => [event.event_type, event.guest_key]),
    [["guest_left", 6], ["guest_arrived", 7]],
  );
  assert.equal(events[0].exit_reason, "id_reused");
});

test("guests_known_in_park counts known guests last read in the park and leaves out a generated guest not yet in", () => {
  const game = startGame((g) => {
    g.addGuest();
    g.addGuest();
    g.addGuest({ isInPark: false });
  });
  captureDay(game);
  const arrival = game.generateGuest({ isInPark: false });
  game.tick();
  game.day(game.date.ticksElapsed + DAY_TICKS);
  assert.deepEqual(guestCounts(lastStats(game)), [4, 2, 1]);
  arrival.values.isInPark = true;
  game.tick(3); // this day's check reads the arrival in the park
  game.day(game.date.ticksElapsed + DAY_TICKS);
  assert.deepEqual(guestCounts(lastStats(game)), [4, 3, 1]);
});

test("each refusal type newly present emits one guest_refused with its ride; repeats and other thoughts emit none", () => {
  const thoughts = (types, first) => types.map((type, i) => ({ type, item: first + i }));
  const game = startGame((g) => g.addGuest({ thoughts: thoughts(["intense"], 40) }));
  captureDay(game);
  const one = game.generateGuest({ thoughts: thoughts(REFUSALS.slice(0, 5), 10) });
  const two = game.generateGuest({
    thoughts: [...thoughts(REFUSALS.slice(5), 20), { type: "good_value", item: 30 }],
  });
  game.tick();
  assert.deepEqual(game.eventsOfType("guest_refused"), [], "arrived guests start with no keys and are checked daily");
  captureDay(game);
  const refused = game.eventsOfType("guest_refused");
  assert.deepEqual(refused.map((event) => pick(event, REFUSED_FIELDS)), [
    ...REFUSALS.slice(0, 5).map((type, i) => [2, one.id, type, 10 + i]),
    ...REFUSALS.slice(5).map((type, i) => [3, two.id, type, 20 + i]),
  ]);
  for (const event of refused) assert.deepEqual(Object.keys(event).sort(), [...ENVELOPE, ...REFUSED_FIELDS].sort());
  captureDay(game);
  assert.equal(game.eventsOfType("guest_refused").length, 9, "the same thoughts the next day emit nothing");
  // The seeded guest's first check stored its thought without emitting; a new refusal of the same type for
  // another ride is a new key.
  game.entities[0].values.thoughts.unshift({ type: "intense", item: 41 });
  captureDay(game);
  assert.deepEqual(pick(game.eventsOfType("guest_refused")[9], REFUSED_FIELDS), [1, 0, "intense", 41]);
});

// A refused ride's item JSON cannot carry, or one missing.
for (const bad of [1.5, undefined]) {
  test(`a refusal whose ride ID is ${bad} fails its step: no guest_refused, one failed step, the error reaches the game`, () => {
    const game = startGame();
    captureDay(game);
    const guest = game.generateGuest();
    game.tick(); // the arrival step: the guest starts with no refusal keys
    guest.values.thoughts = [{ type: "intense", item: 7 }, { type: "not_safe", item: bad }];
    game.day(game.date.ticksElapsed + DAY_TICKS);
    assert.throws(() => game.tick(3), /ride_id is not a JSON-safe integer/);
    assert.deepEqual(game.eventsOfType("guest_refused"), [], "the good refusal beside it is not sent either");
    game.day(game.date.ticksElapsed + DAY_TICKS);
    assert.equal(lastStats(game).work_items_failed_total, 1);
    // No keys were stored, so once the bad thought expires the good one is sent, once.
    guest.values.thoughts = [{ type: "intense", item: 7 }];
    game.tick(3);
    captureDay(game);
    const refused = game.eventsOfType("guest_refused").map((event) => pick(event, REFUSED_FIELDS));
    assert.deepEqual(refused, [[1, guest.id, "intense", 7]]);
    assert.equal(game.malformed.length, 0);
  });
}

test("guest steps wait from the day callback's tick until the day's ride items are done", () => {
  const game = startGame((g) => {
    g.addGuest();
    g.addGuest();
  });
  game.costs["map.getRide"] = 2;
  for (let i = 0; i < 3; i++) game.addRide();
  game.generateGuest(); // slot 2: recorded before the day's ride items, and still held behind them
  game.replaceEntity(0);
  game.replaceEntity(1);
  game.day(1520);
  for (const hook of game.tickHooks) hook(); // 1520: the ride list read and rides 0 and 1
  game.tick(2); // 1521: ride 2 alone, as a tick that starts with ride items pending holds guest steps; 1522: guests
  const rideTicks = game.eventsOfType("ride_snapshot").map((event) => event.game_ticks_elapsed);
  assert.deepEqual(rideTicks, [1520, 1520, 1521]);
  assert.deepEqual(
    guestEvents(game).map((event) => [event.event_type, event.game_ticks_elapsed]),
    [["guest_arrived", 1522], ["guest_left", 1522], ["guest_left", 1522]],
  );
});

test("the stand-in's seams for later tickets: scripted draws, cars, and a read that throws after its cost", () => {
  const game = startGame();
  game.draws.length = 0; // startGame's no-join draws
  game.draws.push(0.25, 0.75);
  const random = () => vm.runInContext("Math.random()", game.context);
  assert.deepEqual([random(), random()], [0.25, 0.75]);
  const draw = random();
  assert.ok(draw >= 0 && draw < 1 && draw !== 0.75, "real random numbers once the draws run out");
  const car = game.addCar({ ride: 3, guests: [null, 7] });
  const cars = vm.runInContext('map.getAllEntities("car")', game.context);
  assert.deepEqual([cars.length, cars[0].ride, cars[0].guests], [1, 3, [null, 7]]);
  assert.equal(vm.runInContext(`map.getEntity(${car.id}).type`, game.context), "car");
  const guest = game.addGuest();
  game.costs["guest.read"] = 1;
  game.throwing.add("guest.read");
  const before = game.wallMs;
  assert.throws(() => guest.cash, /stand-in guest\.read throws/);
  assert.equal(game.wallMs, before + 1);
});

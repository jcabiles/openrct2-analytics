// Tests for boardings: the seat poll the tick hook runs every 20 ticks, its failed-poll rule, the reads at the
// poll and the boarder step, driven through the stand-in game in fake-game.mjs. The expected field names are
// written out here, never derived from the plugin or the contracts, so a misspelled field cannot pass.
import assert from "node:assert/strict";
import { test } from "node:test";

import { createGame } from "./fake-game.mjs";

const ENVELOPE = [
  "schema_version", "event_type", "plugin_version", "park_id", "session_id", "game_year", "game_month",
  "game_day", "game_ticks_elapsed", "emitted_at", "seq", "event_id",
];
const BOARDED_FIELDS = [
  "guest_id", "guest_key", "ride_id", "detected_at_ticks", "ride_price_listed_tenths", "happiness",
  "min_intensity", "max_intensity", "nausea_tolerance", "guest_cash_tenths",
];
const POLL_TICKS = 20;
const DAY_TICKS = 520;

// Loads the plugin, lets `seed` place the guests main() will find, starts it and accepts the socket.
function startGame(seed = () => {}) {
  const game = createGame().load();
  seed(game);
  game.start();
  game.socket.accept();
  return game;
}

// Fires the tick hooks on the current tick, without moving the game date. After game.day() this is the
// stand-in's order, day hook first; the engine runs the tick hook first (docs/FINDINGS.md), which
// dayChangeInEngineOrder() follows.
function tickHooksNow(game) {
  for (const hook of game.tickHooks) hook();
}

// The engine's order on the tick a new game day starts: the date moves, the tick hooks run, then the day hook.
function dayChangeInEngineOrder(game, tick) {
  game.date.ticksElapsed = tick;
  game.date.day += 1;
  tickHooksNow(game);
  for (const hook of game.dayHooks) hook();
}

function boarded(game) {
  return game.eventsOfType("guest_boarded").map((event) => BOARDED_FIELDS.map((field) => event[field]));
}

// The day callback's plugin_stats row, which closes the period.
function statsAfterDay(game) {
  game.day(game.date.ticksElapsed + DAY_TICKS);
  const stats = game.eventsOfType("plugin_stats");
  return stats[stats.length - 1];
}

function boardingCounters(stats) {
  return [stats.boarding_polls_total, stats.boarders_queued_total, stats.work_items_failed_total];
}

test("a guest newly seated emits one guest_boarded with the poll's tick, its fields and the listed price", () => {
  const game = startGame((g) => {
    g.addGuest({ happiness: 200, minIntensity: 3, maxIntensity: 8, nauseaTolerance: 1, cash: 450 }); // slot 0, key 1
  });
  game.addRide({ price: [35] }); // ride 0
  game.addRide({ price: [70] }); // ride 1
  const car = game.addCar({ ride: 0, guests: [null, null] });
  const other = game.addCar({ ride: 1, guests: [null] });
  game.tick(); // 1001: the first poll
  car.values.guests = [null, 0];
  game.tick(POLL_TICKS - 1); // 1002 to 1020: no poll
  assert.deepEqual(boarded(game), []);
  game.tick(); // 1021: the poll finds the guest, and the boarder step sends it on the same tick
  const [event] = game.eventsOfType("guest_boarded");
  assert.deepEqual(Object.keys(event).sort(), [...ENVELOPE, ...BOARDED_FIELDS].sort());
  assert.deepEqual(boarded(game), [[0, 1, 0, 1021, 35, 200, 3, 8, 1, 450]]);
  assert.equal(event.game_ticks_elapsed, 1021);
  game.tick(POLL_TICKS); // 1041: still seated
  car.values.guests = [];
  game.tick(5);
  car.values.guests = [null, 0];
  game.tick(POLL_TICKS - 5); // 1061: left and took the same seat again between polls, the stated limit
  assert.equal(boarded(game).length, 1, "a guest in the same seat at the next poll emits nothing");
  car.values.guests = [];
  other.values.guests = [0];
  game.tick(POLL_TICKS); // 1081: seated on another ride is a new boarding
  assert.deepEqual(boarded(game)[1], [0, 1, 1, 1081, 70, 200, 3, 8, 1, 450]);
  assert.deepEqual(boardingCounters(statsAfterDay(game)), [5, 2, 0]);
});

test("the first poll records the seats without emitting", () => {
  const game = startGame((g) => g.addGuest());
  game.addRide();
  game.addCar({ ride: 0, guests: [0] });
  game.tick(); // 1001: the first poll finds the guest already seated
  game.tick(POLL_TICKS); // 1021: still seated
  assert.deepEqual(boarded(game), []);
  assert.deepEqual(boardingCounters(statsAfterDay(game)), [2, 0, 0]);
});

test("a guest still listed in a car it left and seated in an earlier car of another ride emits one boarding, not one per poll", () => {
  const game = startGame((g) => g.addGuest()); // slot 0
  game.addRide(); // ride 0
  game.addRide(); // ride 1
  const seated = game.addCar({ ride: 1 }); // slot 1
  game.addCar({ ride: 0, guests: [0] }); // slot 2: the guest's ID left in its seat, as 0.5.5 leaves it
  game.tick(); // 1001: the first poll
  seated.values.guests = [0];
  game.tick(4 * POLL_TICKS); // 1021 finds the boarding; 1041 to 1081: still seated, still listed
  assert.deepEqual(boarded(game).map((row) => [row[0], row[2], row[3]]), [[0, 1, 1021]]);
  assert.deepEqual(boardingCounters(statsAfterDay(game)), [5, 1, 0]);
});

test("a guest listed in two seats on one poll emits one boarding", () => {
  const game = startGame((g) => g.addGuest()); // slot 0
  game.addRide();
  const first = game.addCar({ ride: 0 }); // slot 1
  const second = game.addCar({ ride: 0 }); // slot 2
  game.tick(); // 1001: the first poll
  first.values.guests = [0, null];
  second.values.guests = [null, 0];
  game.tick(2 * POLL_TICKS); // 1021 finds the boarding; 1041: still listed in both
  assert.deepEqual(boarded(game).map((row) => [row[0], row[2], row[3]]), [[0, 0, 1021]]);
  assert.deepEqual(boardingCounters(statsAfterDay(game)), [3, 1, 0]);
});

test("a leftover listing in a later car is not a boarding when the guest's earlier seat is taken by another", () => {
  const game = startGame((g) => {
    g.addGuest(); // slot 0
    g.addGuest(); // slot 1
  });
  game.addRide(); // ride 0
  game.addRide(); // ride 1
  const seated = game.addCar({ ride: 1 }); // slot 2
  game.addCar({ ride: 0, guests: [0] }); // slot 3: guest 0's ID left in its seat, as 0.5.5 leaves it
  game.tick(); // 1001: the first poll
  seated.values.guests = [0];
  game.tick(POLL_TICKS); // 1021: guest 0 boards ride 1
  seated.values.guests = [1];
  game.tick(POLL_TICKS); // 1041: guest 1 takes that seat; guest 0's listing on ride 0 is unchanged
  assert.deepEqual(boarded(game).map((row) => [row[0], row[2], row[3]]), [[0, 1, 1021], [1, 1, 1041]]);
  assert.deepEqual(boardingCounters(statsAfterDay(game)), [3, 2, 0]);
});

test("a guest taking the seat that still lists them is missed, and another seat of the same ride is found, the stated limit", () => {
  const game = startGame((g) => g.addGuest()); // slot 0
  game.addRide();
  const car = game.addCar({ ride: 0, guests: [null, null] }); // slot 1
  game.tick(); // 1001: the first poll
  car.values.guests = [0, null];
  game.tick(POLL_TICKS); // 1021: the boarding is found
  // The guest leaves (0.5.5 keeps its ID in the seat) and rides again in the same seat: the poll sees no change.
  game.tick(2 * POLL_TICKS); // 1041, 1061
  assert.deepEqual(boarded(game).map((row) => [row[0], row[2], row[3]]), [[0, 0, 1021]]);
  car.values.guests = [0, 0]; // rides again in the other seat; the first still lists it
  game.tick(POLL_TICKS); // 1081
  assert.deepEqual(boarded(game).map((row) => [row[0], row[2], row[3]]), [[0, 0, 1021], [0, 0, 1081]]);
  assert.deepEqual(boardingCounters(statsAfterDay(game)), [5, 2, 0]);
});

test("a seat that lists the same guest at both polls is missed even when another guest sat there between them, the stated limit", () => {
  const game = startGame((g) => {
    g.addGuest(); // slot 0, guest X
    g.addGuest(); // slot 1, guest Y
  });
  game.addRide();
  const car = game.addCar({ ride: 0, guests: [null] }); // slot 2
  game.tick(); // 1001: the first poll
  car.values.guests = [0];
  game.tick(POLL_TICKS); // 1021: X boards
  car.values.guests = [1];
  game.tick(5); // Y takes the seat
  car.values.guests = [0];
  game.tick(POLL_TICKS - 5); // 1041: X sits there again; the seat lists X at both polls
  assert.deepEqual(boarded(game).map((row) => [row[0], row[2], row[3]]), [[0, 0, 1021]]);
  assert.deepEqual(boardingCounters(statsAfterDay(game)), [3, 1, 0]);
});

test("a car absent for one poll that returns in the same slot is compared with nothing, not with its older seats", () => {
  const game = startGame((g) => g.addGuest()); // slot 0
  game.addRide();
  const car = game.addCar({ ride: 0, guests: [0] }); // slot 1
  game.tick(); // 1001: the first poll records guest 0 seated
  car.values.guests = [null];
  game.tick(POLL_TICKS); // 1021: the seat is empty
  game.replaceEntity(1);
  game.tick(POLL_TICKS); // 1041: the car is absent
  game.entities[1] = car;
  car.values.guests = [0];
  game.tick(POLL_TICKS); // 1061: the car is back and lists guest 0, who is new against the last completed poll
  assert.deepEqual(boarded(game).map((row) => [row[0], row[2], row[3]]), [[0, 0, 1061]]);
  assert.deepEqual(boardingCounters(statsAfterDay(game)), [4, 1, 0]);
});

test("a guest seated and gone between two polls emits nothing, the stated limit", () => {
  const game = startGame((g) => g.addGuest());
  game.addRide();
  const car = game.addCar({ ride: 0 });
  game.tick(); // 1001: the first poll
  game.tick(5);
  car.values.guests = [0];
  game.tick(10);
  car.values.guests = [];
  game.tick(5); // 1021: the next poll
  assert.deepEqual(boarded(game), []);
  assert.deepEqual(boardingCounters(statsAfterDay(game)), [2, 0, 0]);
});

test("polls run at most once per 20 ticks", () => {
  const game = startGame();
  game.addCar({ ride: 0 });
  const carReads = () => game.calls["car.read"] ?? 0;
  game.tick(); // 1001: the first poll reads the car's ride and seats
  assert.equal(carReads(), 2);
  game.tick(POLL_TICKS - 1);
  assert.equal(carReads(), 2, "no poll within 20 ticks of the last");
  game.tick(); // 1021
  assert.equal(carReads(), 4);
  game.tick(POLL_TICKS + 5); // 1041 only
  assert.equal(carReads(), 6);
});

test("a getter that throws midway fails the poll; the queue's steps still run and the next poll compares with the last completed one", () => {
  const game = startGame((g) => {
    g.addGuest(); // slot 0, key 1
    g.addGuest(); // slot 1, key 2
  });
  game.addRide();
  const car = game.addCar({ ride: 0, guests: [0, null] });
  game.tick(); // 1001: the first poll records guest 0 seated
  car.values.guests = [0, 1];
  game.day(1520);
  game.throwing.add("guest.read");
  // 1520: the poll lists guest 1 as new, then its first guest-field read throws; the ride items still run.
  assert.throws(() => tickHooksNow(game), /stand-in guest\.read throws/);
  game.throwing.delete("guest.read");
  assert.deepEqual(boarded(game), [], "the failed poll emits no boarding");
  assert.deepEqual(game.eventsOfType("ride_snapshot").map((event) => event.game_ticks_elapsed), [1520]);
  game.tick(POLL_TICKS); // 1540: guest 1 is new against the 1001 poll, guest 0 is not
  assert.deepEqual(boarded(game), [[1, 2, 0, 1540, 100, 128, 2, 9, 2, 500]]);
  assert.deepEqual(boardingCounters(statsAfterDay(game)), [2, 1, 1]);
});

test("a boarder unreadable as a guest at the poll still gets its event, with null key, guest fields and gone ride's price", () => {
  const game = startGame();
  game.addRide({ price: [40] }); // ride 0; ride 9 does not exist
  const known = game.addCar({ ride: 0 }); // slot 0
  const gone = game.addCar({ ride: 9 }); // slot 1
  game.replaceEntity(2, "money_effect");
  game.tick(); // 1001: the first poll
  known.values.guests = [7]; // an empty slot
  gone.values.guests = [2];
  game.tick(POLL_TICKS); // 1021
  assert.deepEqual(boarded(game), [
    [7, null, 0, 1021, 40, null, null, null, null, null],
    [2, null, 9, 1021, null, null, null, null, null, null],
  ]);
});

test("a guest replaced in its slot or a price changed after the poll leaves the boarding with what the poll read", () => {
  const game = startGame((g) => {
    g.addGuest({ happiness: 210, minIntensity: 4, maxIntensity: 11, nauseaTolerance: 3, cash: 990 }); // key 1
  });
  const ride = game.addRide({ price: [60] });
  const car = game.addCar({ ride: 0 });
  game.tick(); // 1001: the first poll
  car.values.guests = [0];
  game.day(1520);
  tickHooksNow(game); // 1520: the poll reads the boarder; its step waits, as the day's ride work starts
  assert.deepEqual(boarded(game), []);
  // Another guest, outside the park, takes slot 0, so the day's check (older than the boarder) removes key 1.
  game.replaceEntity(0);
  game.addGuest({ happiness: 5, minIntensity: 0, maxIntensity: 1, nauseaTolerance: 0, cash: 1, isInPark: false }, 0);
  ride.price = [90];
  game.tick(); // 1521
  const [left] = game.eventsOfType("guest_left");
  const [event] = game.eventsOfType("guest_boarded");
  assert.ok(left.guest_key === 1 && left.seq < event.seq, "key 1 was gone before the boarder step ran");
  assert.deepEqual(boarded(game), [[0, 1, 0, 1520, 60, 210, 4, 11, 3, 990]]);
  assert.equal(event.game_ticks_elapsed, 1521);
});

test("boarder steps wait from the day callback's tick until the day's ride items are done", () => {
  const game = startGame((g) => g.addGuest());
  game.costs["map.getRide"] = 2;
  for (let i = 0; i < 3; i++) game.addRide();
  const car = game.addCar({ ride: 0 });
  game.tick(); // 1001: the first poll
  car.values.guests = [0];
  game.day(1520);
  tickHooksNow(game); // 1520: the poll's price read (2 ms), the ride list and ride 0 reach 4 ms
  game.tick(2); // 1521: rides 1 and 2, a day-start tick as ride items were pending; 1522: the boarder
  assert.deepEqual(game.eventsOfType("ride_snapshot").map((event) => event.game_ticks_elapsed), [1520, 1521, 1521]);
  assert.deepEqual(game.eventsOfType("guest_boarded").map((event) => event.game_ticks_elapsed), [1522]);
  assert.equal(boarded(game)[0][3], 1520, "detected at the poll's tick");
});

test("in the engine's order, a poll on a new day's tick records the boarder, holds it behind the ride items and counts as day-start time", () => {
  const game = startGame((g) => g.addGuest()); // slot 0
  for (let i = 0; i < 3; i++) game.addRide();
  const car = game.addCar({ ride: 0 }); // slot 1
  game.tick(); // 1001: the first poll, at no cost
  car.values.guests = [0];
  game.costs["car.read"] = 1.5;
  // 1520: the poll (3 ms of car reads) records the boarder before runTick() sees the new day; then the day
  // callback queues the ride items.
  dayChangeInEngineOrder(game, 1520);
  assert.deepEqual(boarded(game), [], "held on the new day's tick");
  game.tick(2); // 1521: the ride list and rides 0 to 2, a day-start tick as ride items were pending; 1522: the boarder
  assert.deepEqual(game.eventsOfType("ride_snapshot").map((event) => event.game_ticks_elapsed), [1521, 1521, 1521]);
  assert.deepEqual(game.eventsOfType("guest_boarded").map((event) => event.game_ticks_elapsed), [1522]);
  assert.equal(boarded(game)[0][3], 1520, "detected at the poll's tick");
  const stats = statsAfterDay(game);
  assert.deepEqual(
    [stats.worst_day_start_tick_ms, stats.worst_tick_at_ticks, stats.worst_tick_kind_ms],
    [3, 1520, "poll:3.000"],
    "the poll's time is the new day's tick's day-start time",
  );
});

test("a boarder with a non-integer ride or seat ID sends no guest_boarded, fails its step and the error reaches the game", () => {
  for (const [ride, seat, field] of [[1.5, 0, "ride_id"], [0, 2.5, "guest_id"]]) {
    const game = startGame((g) => g.addGuest()); // slot 0
    game.addRide();
    const car = game.addCar({ ride }); // slot 1
    game.tick(); // 1001: the first poll
    car.values.guests = [seat];
    // 1021: the poll lists the boarder; its step on the same tick refuses the value.
    assert.throws(() => game.tick(POLL_TICKS), new RegExp(`${field} is not a JSON-safe integer`));
    assert.deepEqual(boarded(game), [], field);
    assert.deepEqual(boardingCounters(statsAfterDay(game)), [2, 1, 1], field);
  }
});

test("the boarder arrays are written from index 0 again each time the boarder task drains", () => {
  const game = createGame().load();
  let poll = null;
  const createBoardingPoll = game.context.createBoardingPoll;
  game.context.createBoardingPoll = (...args) => (poll = createBoardingPoll(...args));
  for (let i = 0; i < 6; i++) game.addGuest(); // slots 0 to 5
  game.start();
  game.socket.accept();
  game.addRide();
  const car = game.addCar({ ride: 0 }); // slot 6
  game.tick(); // 1001: the first poll
  const headOrders = [];
  for (let p = 0; p < 3; p++) {
    car.values.guests = [2 * p, 2 * p + 1];
    game.tick(POLL_TICKS); // the poll lists 2 boarders, and their steps drain the task on the same tick
    assert.equal(poll.boarderTask.pending(), 0);
    // The order stored at the head index; with the arrays reset, the head is index 0, which this poll wrote.
    headOrders.push(poll.boarderTask.headOrder());
  }
  assert.equal(boarded(game).length, 6);
  assert.ok(headOrders.every(Number.isInteger), `head orders ${headOrders}`);
  assert.ok(headOrders[0] < headOrders[1] && headOrders[1] < headOrders[2], `head orders ${headOrders}`);
});

test("a boarder's lookups are timed as boarder_read and its five field reads as guest_fields, the ride read once", () => {
  const game = startGame((g) => {
    g.addGuest();
    g.addGuest();
  });
  game.addRide();
  const car = game.addCar({ ride: 0 });
  game.tick(); // 1001: the first poll, at no cost
  Object.assign(game.costs, { "car.read": 0.25, "map.getEntity": 0.5, "map.getRide": 1, "guest.read": 0.25 });
  car.values.guests = [0, 1];
  game.tick(POLL_TICKS); // 1021: car reads 0.5 ms; boarder 0: 1.5 ms of lookups; boarder 1: 0.5 ms; fields 1.25 ms each
  assert.equal(game.calls["map.getRide"], 1, "the price is read once per ride per poll");
  const stats = statsAfterDay(game);
  assert.deepEqual([stats.worst_tick_ms, stats.worst_tick_at_ticks], [5, 1021]);
  assert.equal(stats.worst_tick_kind_ms, "poll:0.500|boarder_read:2.000|guest_fields:2.500");
  assert.deepEqual([stats.worst_step_ms, stats.worst_step_kind], [1.5, "boarder_read"]);
  assert.equal(stats.guest_fields_ms_total, 2.5);
});

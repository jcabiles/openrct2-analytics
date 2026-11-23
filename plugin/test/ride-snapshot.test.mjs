// Tests for the daily ride_snapshot, driven through the stand-in game in fake-game.mjs. The expected field
// names are written out here, never derived from the plugin or the stand-in, so a misspelled field cannot pass.
import assert from "node:assert/strict";
import { test } from "node:test";

import { createGame } from "./fake-game.mjs";

const ENVELOPE = [
  "schema_version", "event_type", "plugin_version", "park_id", "session_id", "game_year", "game_month",
  "game_day", "game_ticks_elapsed", "emitted_at", "seq", "event_id",
];
const RIDE_FIELDS = [
  "ride_id", "ride_name", "ride_type", "ride_object", "classification", "status", "excitement_hundredths",
  "intensity_hundredths", "nausea_hundredths", "price_1_tenths", "price_2_tenths", "shop_item",
  "shop_item_secondary", "total_customers", "build_date_months_elapsed", "age_months",
  "running_cost_per_fortnight_tenths", "total_profit_tenths", "income_per_game_hour_tenths",
  "profit_per_game_hour_tenths", "value_tenths", "reliability_pct", "downtime_pct", "satisfaction_pct",
  "guests_on_ride", "station_count", "queue_time_max_minutes",
  "max_speed_mph", "average_speed_mph", "ride_time_seconds", "ride_length_meters", "max_positive_vertical_g",
  "max_negative_vertical_g", "max_lateral_g", "total_air_time_seconds", "drop_count", "lift_hill_count",
  "highest_drop_height_units", "inversion_count", "ride_category",
];
// The 0.5.5 value a never-opened stall reads in its profit fields: -2^63, past JSON's safe integers.
const NEVER_OPENED_PROFIT = -9223372036854775808;
const DAY_TICKS = 520;

function startGame(options) {
  return createGame(options).load().start();
}

// One day callback, then enough ticks (at no fake cost) to run every ride step and hand off every line.
function captureDay(game) {
  game.day(game.date.ticksElapsed + DAY_TICKS);
  game.tick();
}

function snapshotOf(game, rideId) {
  return game.eventsOfType("ride_snapshot").find((event) => event.ride_id === rideId);
}

test("one ride_snapshot per ride, stall and facility per day, with every field read from the game", () => {
  const game = startGame();
  game.addRide({
    type: 52, status: "testing", price: [100, 50], excitement: 652, intensity: 551, nausea: 302,
    totalCustomers: 1203, buildDate: 4, age: 5, runningCost: 806, totalProfit: 5007, incomePerHour: 2008,
    profit: 409, value: 30010, reliability: 91, downtime: 12, satisfaction: 73, guestCount: 14,
    object: { identifier: "rct2.ride.rcadv", shopItem: 255, shopItemSecondary: 254 },
    usedStations: [{ queueTime: 9 }],
  });
  // Unrated, unmeasured and itemless placeholders are sent as read.
  game.addRide({
    name: "Burger Bar", classification: "stall", status: "closed", price: [15, 0], excitement: -1,
    intensity: -1, nausea: -1, satisfaction: 1275, object: { identifier: "rct2.ride.burgb", shopItem: 1,
      shopItemSecondary: 255 },
  });
  game.addRide({ name: "Toilets", classification: "facility", status: "simulating" });
  game.socket.accept();
  captureDay(game);
  captureDay(game);

  const snapshots = game.eventsOfType("ride_snapshot");
  assert.deepEqual(snapshots.map((event) => [event.game_day, event.ride_id]), [
    [2, 0], [2, 1], [2, 2], [3, 0], [3, 1], [3, 2],
  ]);
  for (const event of snapshots) {
    assert.deepEqual(Object.keys(event).sort(), [...ENVELOPE, ...RIDE_FIELDS].sort());
  }
  const [ride, stall, facility] = snapshots;
  assert.deepEqual(Object.fromEntries(RIDE_FIELDS.map((field) => [field, ride[field]])), {
    ride_id: 0, ride_name: "Ride 0", ride_type: 52, ride_object: "rct2.ride.rcadv", classification: "ride",
    status: "testing", excitement_hundredths: 652, intensity_hundredths: 551, nausea_hundredths: 302,
    price_1_tenths: 100, price_2_tenths: 50, shop_item: 255, shop_item_secondary: 254, total_customers: 1203,
    build_date_months_elapsed: 4, age_months: 5, running_cost_per_fortnight_tenths: 806,
    total_profit_tenths: 5007, income_per_game_hour_tenths: 2008, profit_per_game_hour_tenths: 409,
    value_tenths: 30010, reliability_pct: 91, downtime_pct: 12, satisfaction_pct: 73, guests_on_ride: 14,
    station_count: 1, queue_time_max_minutes: 9,
    max_speed_mph: 61.5, average_speed_mph: 33.25, ride_time_seconds: 94.5, ride_length_meters: 1204.25,
    max_positive_vertical_g: 3.75, max_negative_vertical_g: -1.5, max_lateral_g: 2.25, total_air_time_seconds: 7.5,
    drop_count: 4, lift_hill_count: 2, highest_drop_height_units: 38.5, inversion_count: null,
    ride_category: "thrill",
  });
  assert.deepEqual(
    [stall.ride_name, stall.classification, stall.status, stall.price_1_tenths, stall.price_2_tenths],
    ["Burger Bar", "stall", "closed", 15, 0],
  );
  assert.deepEqual(
    [stall.excitement_hundredths, stall.intensity_hundredths, stall.nausea_hundredths, stall.satisfaction_pct],
    [-1, -1, -1, 1275],
  );
  assert.deepEqual([stall.ride_object, stall.shop_item, stall.shop_item_secondary], ["rct2.ride.burgb", 1, 255]);
  assert.deepEqual([facility.classification, facility.status], ["facility", "simulating"]);
  // The envelope's date is the moment the ride's step ran: the tick after the day callback.
  assert.equal(ride.game_ticks_elapsed, game.eventsOfType("plugin_stats")[0].game_ticks_elapsed + 1);
});

test("station_count counts the slots with a start, and queue_time_max_minutes is their largest queue time", () => {
  const game = startGame();
  game.addRide({ usedStations: [{ queueTime: 12 }, { queueTime: 7 }] });
  game.addRide({ usedStations: [{ queueTime: 7 }, { queueTime: 12 }] });
  game.addRide({ usedStations: [] });
  assert.equal(game.rides[0].stations.length, 255);
  const stationReads = [];
  const spend = game.spend.bind(game);
  game.spend = (api) => {
    if (api === "ride.stations") stationReads.push(game.date.ticksElapsed);
    spend(api);
  };
  game.socket.accept();
  captureDay(game);
  assert.deepEqual(
    [0, 1, 2].map((id) => [snapshotOf(game, id).station_count, snapshotOf(game, id).queue_time_max_minutes]),
    [[2, 12], [2, 12], [0, null]],
  );
  assert.equal(stationReads.length, 3, "each ride's 255 slots are read once");
});

test("a used slot whose length is 0, as on flat rides and mazes, still counts as a station", () => {
  const game = startGame();
  const unused = { start: null, length: 0, entrance: null, exit: null, queueTime: 0 };
  const slots = Array.from({ length: 255 }, () => ({ ...unused }));
  slots[0] = { start: { x: 32, y: 64, z: 14 }, length: 0, entrance: null, exit: null, queueTime: 5 };
  game.addRide({ stations: slots });
  game.socket.accept();
  captureDay(game);
  const flat = snapshotOf(game, 0);
  assert.deepEqual([flat.station_count, flat.queue_time_max_minutes], [1, 5]);
});

test("a value outside JSON's safe integers is sent as null; one inside is sent as read", () => {
  const game = startGame();
  game.addRide({
    classification: "stall", totalProfit: NEVER_OPENED_PROFIT, profit: NEVER_OPENED_PROFIT,
    value: 9007199254740991, runningCost: -9007199254740991, incomePerHour: 9007199254740992,
  });
  game.socket.accept();
  captureDay(game);
  assert.equal(game.malformed.length, 0);
  const stall = snapshotOf(game, 0);
  assert.deepEqual(
    [stall.total_profit_tenths, stall.profit_per_game_hour_tenths, stall.income_per_game_hour_tenths],
    [null, null, null],
  );
  assert.deepEqual(
    [stall.value_tenths, stall.running_cost_per_fortnight_tenths],
    [9007199254740991, -9007199254740991],
  );
});

test("a price array shorter than two sends null for each missing price", () => {
  const game = startGame();
  game.addRide({ name: "Cash Machine", classification: "facility", price: [] });
  game.addRide({ classification: "stall", price: [25] });
  game.socket.accept();
  captureDay(game);
  const atm = snapshotOf(game, 0);
  assert.deepEqual([atm.ride_name, atm.price_1_tenths, atm.price_2_tenths], ["Cash Machine", null, null]);
  const stall = snapshotOf(game, 1);
  assert.deepEqual([stall.price_1_tenths, stall.price_2_tenths], [25, null]);
});

test("a ride demolished after the list read and before its step sends nothing and is not skipped", () => {
  const game = createGame();
  game.costs["map.rides"] = 4; // the list read alone fills tick 1521
  game.load().start();
  for (let i = 0; i < 3; i++) game.addRide();
  game.socket.accept();
  game.day(1520);
  game.tick();
  assert.equal(game.eventsOfType("ride_snapshot").length, 0);
  game.demolishRide(1);
  game.tick(3);
  assert.deepEqual(game.eventsOfType("ride_snapshot").map((event) => event.ride_id), [0, 2]);
  game.day(2040);
  const stats = game.eventsOfType("plugin_stats")[1];
  // The list read, three ride steps (the demolished ride's included) and the day's guest list read.
  assert.deepEqual([stats.work_units_total, stats.work_items_skipped_total, stats.work_queue_length], [5, 0, 0]);
});

test("an empty slot before a used one is walked past: the used slot counts, from one stations read per snapshot", () => {
  const game = startGame();
  game.addRide({ usedStations: [null, { queueTime: 6 }] });
  const slots = game.rides[0].stations;
  assert.deepEqual([slots[0].start, slots[1].start === null], [null, false]);
  const stationReads = [];
  const spend = game.spend.bind(game);
  game.spend = (api) => {
    if (api === "ride.stations") stationReads.push(game.date.ticksElapsed);
    spend(api);
  };
  game.socket.accept();
  captureDay(game);
  captureDay(game);
  const snapshots = game.eventsOfType("ride_snapshot");
  assert.deepEqual(snapshots.map((event) => [event.station_count, event.queue_time_max_minutes]), [[1, 6], [1, 6]]);
  assert.equal(stationReads.length, 2, "one stations read per snapshot");
});

// The five required integers, each given a value JSON cannot carry exactly.
const REQUIRED_INTEGERS = [
  ["ride_id", { id: 0.5 }],
  ["ride_type", { type: 2 ** 53 }],
  ["total_customers", { totalCustomers: NEVER_OPENED_PROFIT }],
  ["build_date_months_elapsed", { buildDate: Number.NaN }],
  ["age_months", { age: 1.5 }],
];

for (const [field, bad] of REQUIRED_INTEGERS) {
  test(`a ${field} JSON cannot carry fails its step: no event, one failed step, the error reaches the game`, () => {
    const game = startGame();
    game.addRide();
    game.addRide(bad);
    game.addRide();
    game.socket.accept();
    game.day(1520);
    // Tick 1521: the list read and the first ride run, then the bad ride's step throws out of the tick hook.
    assert.throws(() => game.tick(), new RegExp(`${field} is not a JSON-safe integer`));
    game.tick(); // the step after the bad ride: it is not run again; the day's guest list read is still held
    const goodIds = [game.rides[0].id, game.rides[2].id];
    assert.deepEqual(game.eventsOfType("ride_snapshot").map((event) => event.ride_id), goodIds);
    game.day(2040);
    const stats = game.eventsOfType("plugin_stats")[1];
    assert.deepEqual(
      [stats.work_units_total, stats.work_items_skipped_total, stats.work_queue_length, stats.work_items_failed_total],
      [4, 0, 1, 1],
    );
    assert.equal(game.malformed.length, 0);
  });
}

// A track of segments, each flagged as an inversion (1) or not (0); a null entry is a segment the game cannot
// describe. `opts`: startIndex (default 0), closed, noElement, nullIterator.
function track(flags, opts = {}) {
  return {
    segments: flags.map((flag) => (flag === null ? null : { countsAsInversion: flag === 1 })),
    startIndex: 0,
    closed: false,
    ...opts,
  };
}

const COASTER_TYPE = 3;
const STATISTICS = [
  "max_speed_mph", "average_speed_mph", "ride_time_seconds", "ride_length_meters", "max_positive_vertical_g",
  "max_negative_vertical_g", "max_lateral_g", "total_air_time_seconds", "drop_count", "lift_hill_count",
  "highest_drop_height_units",
];

// The inversion_count and ride_category of the one coaster a game holds, after one day.
function coasterCount(coasterTrack, ride = {}) {
  const game = startGame();
  game.addRide({ type: COASTER_TYPE, track: coasterTrack, ...ride });
  game.socket.accept();
  captureDay(game);
  return [snapshotOf(game, 0).inversion_count, snapshotOf(game, 0).ride_category];
}

test("a coaster's snapshot carries all 13 new fields: the statistics as read and the track's inversion count", () => {
  const game = startGame();
  game.addRide(); // so the coaster's ride ID, 1, is not its ride type
  game.addRide({ type: COASTER_TYPE, track: track([0, 1, 1, 0, 1], { closed: true }) });
  game.socket.accept();
  captureDay(game);
  const coaster = snapshotOf(game, 1);
  assert.deepEqual(Object.fromEntries([...STATISTICS, "inversion_count", "ride_category"].map((f) => [f, coaster[f]])), {
    max_speed_mph: 61.5, average_speed_mph: 33.25, ride_time_seconds: 94.5, ride_length_meters: 1204.25,
    max_positive_vertical_g: 3.75, max_negative_vertical_g: -1.5, max_lateral_g: 2.25, total_air_time_seconds: 7.5,
    drop_count: 4, lift_hill_count: 2, highest_drop_height_units: 38.5, inversion_count: 3,
    ride_category: "rollercoaster",
  });
});

test("ride_category comes from either research list; a type in neither has a null category and a null count", () => {
  const game = startGame();
  game.addRide({ type: 7, track: track([1], { closed: true }) }); // researched later: in the uninvented list
  game.addRide({ type: 99, usedStations: [null, { queueTime: 0 }], track: track([1], { closed: true }) });
  game.addRide({ type: 0 });
  game.socket.accept();
  captureDay(game);
  assert.deepEqual(
    [0, 1, 2].map((id) => [snapshotOf(game, id).ride_category, snapshotOf(game, id).inversion_count]),
    [["rollercoaster", 1], [null, null], ["gentle", null]],
  );
  assert.equal(game.calls["map.getTrackIterator"], 1, "only the coaster is walked");
});

test("a non-coaster ride, a stall and a facility carry the statistics and a category, and are not walked", () => {
  const game = startGame();
  game.addRide({ type: 52, track: track([1, 1], { closed: true }) });
  game.addRide({ classification: "stall", type: 0 });
  game.addRide({ classification: "facility", type: 0 });
  game.socket.accept();
  captureDay(game);
  for (const id of [0, 1, 2]) {
    const event = snapshotOf(game, id);
    assert.deepEqual([event.max_speed_mph, event.drop_count, event.highest_drop_height_units], [61.5, 4, 38.5]);
    assert.equal(event.inversion_count, null);
  }
  assert.deepEqual([0, 1, 2].map((id) => snapshotOf(game, id).ride_category), ["thrill", "gentle", "gentle"]);
  assert.equal(game.calls["map.getTrackIterator"] ?? 0, 0);
  assert.equal(game.calls["map.getTile"] ?? 0, 0);
});

test("a closed circuit counts each segment once, the start included", () => {
  assert.deepEqual(coasterCount(track([1, 0, 1, 1], { closed: true, startIndex: 2 })), [3, "rollercoaster"]);
});

test("an open track the station sits at the start of is counted forward; at the end, backward", () => {
  assert.deepEqual(coasterCount(track([1, 0, 1, 0, 1])), [3, "rollercoaster"]);
  assert.deepEqual(coasterCount(track([1, 0, 1, 0, 1], { startIndex: 4 })), [3, "rollercoaster"]);
});

test("a shuttle layout, whose forward walk dead-ends mid-track, adds the backward leg to the forward leg", () => {
  // Forward from index 3: the start, then 4, 5 and 6 (dead end). Backward from 3: 2, 1 and 0.
  const flags = [1, 1, 0, 1, 0, 1, 1];
  assert.deepEqual(coasterCount(track(flags, { startIndex: 3 })), [5, "rollercoaster"]);
});

test("a walk that takes 5,000 moves is counted; one that would take a 5,001st gives null", () => {
  const circuit = (length) => track(new Array(length).fill(1), { closed: true });
  assert.deepEqual(coasterCount(circuit(5000)), [5000, "rollercoaster"]);
  assert.deepEqual(coasterCount(circuit(5001)), [null, "rollercoaster"]);
  // The cap covers both legs together: 2,500 forward moves and 2,501 backward ones.
  assert.deepEqual(coasterCount(track(new Array(5002).fill(0), { startIndex: 2500 })), [null, "rollercoaster"]);
});

test("a missing track element, a null iterator, a null segment or no used station gives a null count", () => {
  const flags = [1, 0, 1];
  assert.deepEqual(coasterCount(track(flags, { noElement: true })), [null, "rollercoaster"]);
  assert.deepEqual(coasterCount(track(flags, { nullIterator: true })), [null, "rollercoaster"]);
  assert.deepEqual(coasterCount(track([1, null, 1], { closed: true })), [null, "rollercoaster"]);
  assert.deepEqual(coasterCount(track([null, 1, 1])), [null, "rollercoaster"], "a null start segment");
  assert.deepEqual(coasterCount(track([1, null, 1], { startIndex: 2 })), [null, "rollercoaster"], "null on the backward leg");
  assert.deepEqual(coasterCount(undefined, { usedStations: [] }), [null, "rollercoaster"]);
});

test("the category table is read once per session, not on each day's ride_list step", () => {
  const game = startGame();
  game.addRide({ type: COASTER_TYPE, track: track([1], { closed: true }) });
  game.socket.accept();
  for (let day = 0; day < 3; day++) captureDay(game);
  assert.equal(game.eventsOfType("ride_snapshot").length, 3);
  assert.equal(game.calls["park.research"], 1);
  game.load().start(); // a new session reads it again
  assert.equal(game.calls["park.research"], 1, "main() does not read it; the first ride_list step does");
  game.socket.accept();
  captureDay(game);
  assert.equal(game.calls["park.research"], 2);
});

test("a measurement that is not finite is sent as null, a fractional one and a zero as read; a non-whole count is null", () => {
  const game = startGame();
  game.addRide({
    maxSpeed: Number.NaN, averageSpeed: Number.POSITIVE_INFINITY, rideTime: Number.NEGATIVE_INFINITY,
    rideLength: 0, maxPositiveVerticalGs: 2.125, maxNegativeVerticalGs: -0.5, totalAirTime: 0.1,
    numDrops: 2.5, numLiftHills: 2 ** 53, highestDropHeight: 17.75,
  });
  game.socket.accept();
  captureDay(game);
  assert.equal(game.malformed.length, 0);
  const event = snapshotOf(game, 0);
  assert.deepEqual(
    [event.max_speed_mph, event.average_speed_mph, event.ride_time_seconds, event.drop_count, event.lift_hill_count],
    [null, null, null, null, null],
  );
  assert.deepEqual(
    [event.ride_length_meters, event.max_positive_vertical_g, event.max_negative_vertical_g, event.total_air_time_seconds],
    [0, 2.125, -0.5, 0.1],
  );
  assert.equal(event.highest_drop_height_units, 17.75);
});

test("a research read that throws part way sends no ride_snapshot that step; the next clean read sends them with categories", () => {
  const game = startGame();
  game.addRide({ type: COASTER_TYPE, track: track([1], { closed: true }) });
  game.socket.accept();
  const research = game.research;
  const uninvented = research.uninventedItems;
  // The invented list reads fine, then the uninvented one throws: a partial category table.
  Object.defineProperty(research, "uninventedItems", {
    configurable: true,
    get() {
      throw new Error("stand-in uninventedItems throws");
    },
  });
  assert.throws(() => captureDay(game), /stand-in uninventedItems throws/);
  game.tick();
  assert.equal(game.eventsOfType("ride_snapshot").length, 0);
  Object.defineProperty(research, "uninventedItems", { configurable: true, value: uninvented });
  captureDay(game);
  assert.equal(game.eventsOfType("ride_snapshot").length, 1);
  assert.deepEqual([snapshotOf(game, 0).ride_category, snapshotOf(game, 0).inversion_count], ["rollercoaster", 1]);
});

test("a day whose ride pass is cut short shows its leftover items first in the stats row before the second following park_snapshot", () => {
  const game = startGame();
  for (let i = 0; i < 3; i++) game.addRide();
  game.socket.accept();
  game.day(1520);
  game.tick(); // the list read and the first ride step; two ride steps and the guest list read are left
  game.day(2040); // cut short: the leftover items are counted when this day is queued, after its stats row
  game.day(2560);
  const stats = game.eventsOfType("plugin_stats");
  const parks = game.eventsOfType("park_snapshot");
  assert.equal(stats.length, 3);
  assert.equal(parks.length, 3);
  assert.equal(stats[1].work_items_skipped_total, 0, "the stats row before the first following park_snapshot");
  assert.ok(stats[2].work_items_skipped_total > 0, "the stats row before the second following park_snapshot");
  assert.ok(stats[2].seq < parks[2].seq);
});

// Tests that the plugin builds no payload per event and keeps no object per work item or per day, driven
// through the stand-in game in fake-game.mjs. Payloads are recorded where the plugin hands them to its emitter,
// which copies each into its own queued event, so every line must still keep its own values.
import assert from "node:assert/strict";
import { readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import v8 from "node:v8";
import vm from "node:vm";

import { createGame } from "./fake-game.mjs";
import { fireAction } from "./fake-actions.mjs";

const DAY_TICKS = 520;
const POLL_TICKS = 20;
// Four full 32-seat trains on rides 0 to 3, reseated with other guests each day.
const CARS = 4;
const SEATS = 32;

// Loads the plugin with its emitter's emit() wrapped to record each payload object by event type, and each
// named factory wrapped to count its calls and keep what it last made, lets `seed` place the guests main()
// will find, then starts it.
function startRecording(factories = [], seed = () => {}) {
  const game = createGame().load();
  const payloads = {};
  const calls = {};
  const made = {};
  const createEmitter = game.context.createEmitter;
  game.context.createEmitter = (...args) => {
    const emitter = createEmitter(...args);
    const emit = emitter.emit;
    emitter.emit = (eventType, payload) => {
      (payloads[eventType] ??= []).push(payload);
      emit(eventType, payload);
    };
    return emitter;
  };
  for (const name of factories) {
    const factory = game.context[name];
    calls[name] = 0;
    game.context[name] = (...args) => {
      calls[name] += 1;
      made[name] = factory(...args);
      return made[name];
    };
  }
  seed(game);
  game.start();
  return { game, payloads, calls, made };
}

// One day callback, then enough ticks (at no fake cost) to run every ride step and hand off every line.
function captureDay(game) {
  game.day(game.date.ticksElapsed + DAY_TICKS);
  game.tick();
}

test("every ride_snapshot reuses one payload, for 2 rides and then 29, while each line keeps its own ride", () => {
  const { game, payloads, calls } = startRecording(["createRideTask", "createRideSnapshotBuilder"]);
  game.addRide({ totalCustomers: 100 });
  game.addRide({ totalCustomers: 101, type: 3, track: { segments: [{ countsAsInversion: true }, { countsAsInversion: true }], startIndex: 0, closed: true } });
  game.socket.accept();
  captureDay(game);
  for (let i = 2; i < 29; i++) game.addRide({ totalCustomers: 100 + i, usedStations: [] });
  captureDay(game);
  assert.equal(payloads.ride_snapshot.length, 31);
  assert.equal(new Set(payloads.ride_snapshot).size, 1);
  const lines = game.eventsOfType("ride_snapshot");
  const expected = [0, 1].map((id) => [2, id, 100 + id, 1]);
  for (let id = 0; id < 29; id++) expected.push([3, id, 100 + id, id < 2 ? 1 : 0]);
  assert.deepEqual(lines.map((line) => [line.game_day, line.ride_id, line.total_customers, line.station_count]), expected);
  // A field the payload held from the previous ride is written again: a stationless ride has no queue time.
  assert.deepEqual([lines[3].queue_time_max_minutes, lines[4].queue_time_max_minutes], [0, null]);
  // The coaster's count and category are written again for the ride after it, which has neither a walk nor a coaster type.
  assert.deepEqual(
    [lines[3], lines[4]].map((line) => [line.inversion_count, line.ride_category]),
    [[2, "rollercoaster"], [null, "gentle"]],
  );
  assert.deepEqual(calls, { createRideTask: 1, createRideSnapshotBuilder: 1 }, "the task is one object for the session");
});

test("plugin_stats and park_snapshot each reuse one payload across days, while each queued line keeps its day", () => {
  const { game, payloads, calls } = startRecording(["createDayPayloads"]);
  for (const cash of [1000, 2000, 3000]) {
    game.parkValues.cash = cash;
    game.day(game.date.ticksElapsed + DAY_TICKS); // disconnected: the lines stay queued
  }
  game.interval(); // reconnect
  game.socket.accept();
  game.interval(); // flush
  assert.equal(new Set(payloads.plugin_stats).size, 1);
  assert.equal(new Set(payloads.park_snapshot).size, 1);
  assert.equal(payloads.plugin_stats.length, 3);
  assert.deepEqual(game.eventsOfType("park_snapshot").map((line) => line.cash_tenths), [1000, 2000, 3000]);
  assert.deepEqual(game.eventsOfType("plugin_stats").map((line) => line.period_start_ticks), [1000, 1520, 2040]);
  assert.deepEqual(calls, { createDayPayloads: 1 });
});

test("every save_written reuses one payload, while each line keeps its own save ID", () => {
  const { game, payloads, calls } = startRecording(["createSavePayloads"]);
  game.socket.accept();
  game.day(game.date.ticksElapsed + DAY_TICKS);
  const SAVE_DRAWS = [0.25, 0.5, 0.75]; // distinct, scripted after start(); the random part of each save ID is its own draw
  game.draws.push(...SAVE_DRAWS);
  const saves = [game.save()];
  game.socket.fail();
  saves.push(game.save(), game.save()); // disconnected: the two lines stay queued
  game.interval(); // reconnect
  game.socket.accept();
  game.interval(); // flush
  assert.equal(payloads.save_written.length, 3);
  assert.equal(new Set(payloads.save_written).size, 1);
  const ids = game.eventsOfType("save_written").map((line) => line.save_id);
  assert.deepEqual(ids, saves.map((saved) => saved.storage.save_id));
  ids.forEach((id, i) => {
    assert.ok(id.endsWith("-" + Math.floor(SAVE_DRAWS[i] * 2176782336).toString(36)), `save ${i} has its own draw: ${id}`);
  });
  assert.equal(new Set(ids).size, 3);
  assert.deepEqual(calls, { createSavePayloads: 1 });
});

test("action sends reuse their payload and preallocated field arrays while lines keep their values", () => {
  const game = createGame().load();
  game.draws.push(0.2, 0.4, 0.6);
  const payloads = [];
  const fieldArrays = [];
  const createWorkQueue = game.context.createWorkQueue;
  game.context.createWorkQueue = (...args) => {
    const work = createWorkQueue(...args);
    const emitter = args[1];
    const emit = emitter.emit;
    emitter.emit = (type, payload) => {
      if (type === "game_action") payloads.push(payload);
      emit(type, payload);
    };
    return work;
  };
  const createActionRecorder = game.context.createActionRecorder;
  game.context.createActionRecorder = (...args) => {
    const OriginalArray = vm.runInContext("Array", game.context);
    game.context.Array = function (length) {
      const array = new OriginalArray(length);
      if (length === 2048) fieldArrays.push(array);
      return array;
    };
    try {
      return createActionRecorder(...args);
    } finally {
      game.context.Array = OriginalArray;
    }
  };
  game.start();
  game.socket.accept();
  for (let i = 0; i < 3; i++) fireAction(game, { action: "ridesetprice", args: { ride: i } });
  game.tick();
  game.interval();
  assert.equal(payloads.length, 3);
  assert.equal(new Set(payloads).size, 1);
  assert.equal(fieldArrays.length, 23);
  assert.equal(new Set(fieldArrays).size, 23);
  assert.deepEqual(game.eventsOfType("game_action").map((row) => [row.action, row.args_ride]),
    [["ridesetprice", 0], ["ridesetprice", 1], ["ridesetprice", 2]]);
});

test("skipped action calls keep the one name table and sub-type arrays and call no constructor or stringify", () => {
  const game = createGame().load().start();
  game.socket.accept();
  const tables = () => vm.runInContext("[ACTION_NAME_CODES, RIDE_SET_SETTING_KEPT, RIDE_SET_VEHICLE_KEPT]", game.context);
  const before = tables();
  const beforeKeys = Object.keys(before[0]);
  const beforeArrays = before.slice(1).map((array) => [array.length, Array.from(array)]);
  const calls = [];
  for (const name of ["Array", "Object", "String"]) {
    const original = vm.runInContext(name, game.context);
    game.context[name] = function (...args) { calls.push(name); return original(...args); };
  }
  const json = vm.runInContext("JSON", game.context);
  const stringify = json.stringify;
  json.stringify = (...args) => { calls.push("JSON.stringify"); return stringify(...args); };
  try {
    for (const action of ["trackplace", "notanaction", "cheatset", "ridesetsetting", "ridesetvehicle"]) {
      for (const flags of [0, 64]) {
        fireAction(game, { action, args: { flags, setting: 6, type: 2 } });
      }
    }
    fireAction(game, { action: "ridesetprice", args: { flags: 64 } });
  } finally {
    json.stringify = stringify;
  }
  const after = tables();
  assert.deepEqual(calls, []);
  assert.deepEqual([0, 1, 2].map((i) => after[i] === before[i]), [true, true, true]);
  assert.deepEqual(Object.keys(after[0]), beforeKeys);
  assert.deepEqual(after.slice(1).map((array) => [array.length, Array.from(array)]), beforeArrays);
});

test("every guest_boarded reuses one payload, while each line keeps its own boarder", () => {
  const { game, payloads, calls } = startRecording(["createBoardingPoll"], (g) => {
    for (let i = 0; i < 3; i++) g.addGuest({ cash: 100 + i });
  });
  game.addRide();
  const car = game.addCar({ ride: 0 });
  game.socket.accept();
  game.tick(); // 1001: the first poll
  car.values.guests = [0, 1];
  game.tick(POLL_TICKS); // 1021
  car.values.guests = [2];
  game.tick(POLL_TICKS); // 1041
  assert.equal(payloads.guest_boarded.length, 3);
  assert.equal(new Set(payloads.guest_boarded).size, 1);
  assert.deepEqual(
    game.eventsOfType("guest_boarded").map((line) => [line.guest_id, line.guest_cash_tenths, line.detected_at_ticks]),
    [[0, 100, 1021], [1, 101, 1021], [2, 102, 1041]],
  );
  assert.deepEqual(calls, { createBoardingPoll: 1 }, "the poll and its boarder task are one object for the session");
});

// The planted control: a day-scoped guest task built inside the plugin's context, so its objects count as the
// plugin's, that keeps one new object per item it runs.
const CONTEXT_HOLDING_TASK = `(function (count) {
  var left = 0, order = 0, held = [];
  return {
    pending: function () { return left; },
    headOrder: function () { return order; },
    headKind: function () { return "guest"; },
    runOne: function () { left -= 1; held.push({}); },
    startDay: function (dayOrder) { var dropped = left; left = count; order = dayOrder; return dropped; }
  };
})`;

// The IDs of the objects, arrays and closures alive in the whole heap. A heap snapshot collects garbage first
// and keeps each object's ID across snapshots. v8.queryObjects cannot serve: it counts only objects created in
// the calling context, never those of the plugin's vm context.
function liveObjectIds() {
  const file = v8.writeHeapSnapshot(join(tmpdir(), `allocation-${process.pid}.heapsnapshot`));
  const text = readFileSync(file, "utf8");
  rmSync(file);
  const { nodes, snapshot } = JSON.parse(text);
  const fields = snapshot.meta.node_fields;
  const counted = ["object", "array", "closure"].map((type) => snapshot.meta.node_types[0].indexOf(type));
  const typeAt = fields.indexOf("type");
  const idAt = fields.indexOf("id");
  const ids = new Set();
  for (let i = 0; i < nodes.length; i += fields.length) {
    if (counted.includes(nodes[i + typeAt])) ids.add(nodes[i + idAt]);
  }
  return ids;
}

// How many objects alive right after day 10's callback were not alive right after day 1's, with 29 rides,
// 2,000 known guests checked each day and 128 new boarders found by each day's first poll from day 2; with
// `hold`, the planted control's 2,000 items a day as well. The stand-in's received lines are cleared each day,
// so its own copies do not count.
function liveObjectGrowth(hold) {
  const { game, made } = startRecording(["createWorkQueue"], (g) => {
    for (let i = 0; i < 2000; i++) g.addGuest();
  });
  if (hold) made.createWorkQueue.addDayTask(vm.runInContext(CONTEXT_HOLDING_TASK, game.context)(2000));
  for (let i = 0; i < 29; i++) game.addRide();
  const cars = [];
  for (let c = 0; c < CARS; c++) cars.push(game.addCar({ ride: c }));
  game.socket.accept();
  let dayOne = new Set();
  let snapshots = 0;
  let boardings = 0;
  for (let day = 1; day <= 10; day++) {
    game.day(game.date.ticksElapsed + DAY_TICKS);
    snapshots += game.eventsOfType("ride_snapshot").length;
    boardings += game.eventsOfType("guest_boarded").length;
    game.received.length = 0;
    cars.forEach((car, c) => {
      car.values.guests = Array.from({ length: SEATS }, (_, s) => (day * CARS * SEATS + c * SEATS + s) % 2000);
    });
    if (day === 1) dayOne = liveObjectIds();
    game.tick(3); // the poll, the ride items, then the guest checks (and control items), the boarders, the lines
  }
  game.received.length = 0;
  assert.equal(snapshots, 9 * 29);
  assert.equal(boardings, 8 * CARS * SEATS, "days 2 to 9 each sent a poll's 128 boarders");
  assert.equal(
    game.calls["map.getEntity"],
    10 * 2000 + 9 * CARS * SEATS,
    "every known guest is checked each day, and each boarder is read at its poll",
  );
  let grown = 0;
  for (const id of liveObjectIds()) if (!dayOne.has(id)) grown += 1;
  return grown;
}

test("no task, payload, poll or queue keeps an object per item, boarder or day: live objects stay flat over 10 days", () => {
  const growth = liveObjectGrowth(false);
  assert.ok(growth < 100, `grew by ${growth}`);
  const control = liveObjectGrowth(true);
  assert.ok(control >= 2000, `the planted control keeps one object per guest item, yet grew by ${control}`);
});

test("every guest_snapshot reuses one payload for 2 members, then 100, and keeps no object per guest per day", () => {
  const { game, payloads } = startRecording();
  game.socket.accept();
  game.draws.push(...new Array(100).fill(0.1)); // after start(), so the park ID's and session ID's draws are taken
  const arrive = (from, to) => {
    for (let i = from; i < to; i++) {
      game.generateGuest({ items: [{ type: "balloon" }], thoughts: [{ type: "intense", item: i }] });
    }
    game.tick(3);
  };
  arrive(0, 2);
  game.day(game.date.ticksElapsed + DAY_TICKS);
  game.tick(3);
  assert.equal(payloads.guest_snapshot.length, 2, "2 members for a day");
  arrive(2, 100);
  let dayOne = new Set();
  for (let day = 1; day <= 10; day++) {
    game.day(game.date.ticksElapsed + DAY_TICKS);
    game.tick(3);
    game.received.length = 0; // the stand-in's own copies of the lines do not count
    if (day === 1) dayOne = liveObjectIds(); // after the first day's 100 snapshots, so lazy set-up is not growth
  }
  assert.equal(payloads.guest_snapshot.length, 2 + 1000, "2 members for a day, then 100 for 10 days");
  assert.equal(new Set(payloads.guest_snapshot).size, 1, "one object served 2 members and then 100");
  let grown = 0;
  for (const id of liveObjectIds()) if (!dayOne.has(id)) grown += 1;
  assert.ok(grown < 100, `grew by ${grown}`);
});

test("every weather_change reuses one payload, which has no game_ticks_elapsed key, while each line keeps its own change", () => {
  const { game, payloads } = startRecording();
  game.socket.accept();
  for (const weather of ["rain", "thunder", "sunny"]) {
    game.climateValues.current = { weather, temperature: 18 };
    game.tick();
  }
  game.tick(3);
  assert.equal(payloads.weather_change.length, 3);
  assert.equal(new Set(payloads.weather_change).size, 1);
  assert.equal("game_ticks_elapsed" in payloads.weather_change[0], false);
  assert.deepEqual(
    game.eventsOfType("weather_change").map((line) => [line.previous_weather, line.weather]),
    [["sunny", "rain"], ["rain", "thunder"], ["thunder", "sunny"]],
  );
});

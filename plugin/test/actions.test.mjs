import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import { createGame } from "./fake-game.mjs";
import { fireAction } from "./fake-actions.mjs";

function startActions() {
  const game = createGame().load();
  game.draws.push(0.2, 0.4, 0.6);
  const seenPayloads = [];
  const actionOrders = [];
  let recorder;
  const createWorkQueue = game.context.createWorkQueue;
  game.context.createWorkQueue = (...args) => {
    const work = createWorkQueue(...args);
    const emitter = args[1];
    const emit = emitter.emit;
    emitter.emit = (type, payload) => {
      if (type === "game_action") seenPayloads.push(payload);
      emit(type, payload);
    };
    return work;
  };
  const createActionRecorder = game.context.createActionRecorder;
  game.context.createActionRecorder = (...args) => {
    const nextOrder = args[1];
    recorder = createActionRecorder(args[0], () => {
      const order = nextOrder();
      actionOrders.push(order);
      return order;
    });
    return recorder;
  };
  game.start();
  game.socket.accept();
  return { game, recorder, seenPayloads, actionOrders };
}

function flushAll(game, times = 1) {
  for (let i = 0; i < times; i++) game.interval();
}

test("one row per hook copies all raw and flat values with its action clock and envelope", () => {
  const { game } = startActions();
  const args = { flags: 0, ride: 11, rideType: 12, rideObject: 13, price: 145, x: 21, y: 22, z: 23 };
  const result = { error: 7, cost: 345, ride: 14 };
  fireAction(game, { hook: "query", player: -3, type: 6, action: "ridesetstatus", args, result });
  fireAction(game, { hook: "execute", player: -2, type: 2, action: "ridesetprice", args, result });
  game.tick();
  flushAll(game);
  const rows = game.eventsOfType("game_action");
  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map((row) => [row.hook, row.player, row.type, row.action]),
    [["query", -3, 6, "ridesetstatus"], ["execute", -2, 2, "ridesetprice"]]);
  const row = rows[0];
  assert.deepEqual([row.is_client_only, row.args_flags, row.action_label, row.args_json],
    [false, 0, "confirmed", JSON.stringify(args)]);
  assert.deepEqual(JSON.parse(row.args_json), args);
  assert.deepEqual([row.args_ride, row.args_ride_type, row.args_ride_object, row.args_price_tenths,
    row.args_x, row.args_y, row.args_z, row.result_error, row.result_cost_tenths, row.result_ride],
  [11, 12, 13, 145, 21, 22, 23, 7, 345, 14]);
  assert.deepEqual([row.action_at_ticks, row.action_game_year, row.action_game_month, row.action_game_day],
    [1000, 1, 0, 1]);
  for (const key of ["park_id", "session_id", "seq", "event_id", "game_year", "game_month", "game_day", "emitted_at"]) {
    assert.ok(row[key] !== undefined, key);
  }
  assert.equal(row.schema_version, 1);
  assert.equal(rows[0].event_id, rows[0].session_id + "-" + rows[0].seq);
});

test("preview bit wins for client only and negative flags; missing and nonnumeric flags stay null", () => {
  const { game, recorder } = startActions();
  const cases = [
    [{ flags: 64 }, false, "preview", 64],
    [{ flags: -2147483584 }, false, "preview", -2147483584],
    [{ flags: 64 }, true, "preview", 64],
    [{ flags: 0 }, true, "prediction", 0],
    [{ flags: 0 }, false, "confirmed", 0],
    [{}, false, "confirmed", null],
    [{ flags: "64" }, false, "confirmed", null],
  ];
  for (const [args, isClientOnly] of cases) fireAction(game, { args, isClientOnly });
  game.tick();
  flushAll(game);
  // The three previews are skipped before the buffer; the other four calls are sent.
  assert.deepEqual(game.eventsOfType("game_action").map((row) => [row.action_label, row.args_flags]),
    cases.filter(([, , label]) => label !== "preview").map(([, , label, flags]) => [label, flags]));
  assert.deepEqual([recorder.totals().game_actions_sent_preview_total,
    recorder.totals().game_actions_sent_prediction_total,
    recorder.totals().game_actions_sent_confirmed_total,
    recorder.totals().game_actions_skipped_preview_total], [0, 1, 3, 3]);
});

test("action rows preserve falsy player and client-only values", () => {
  const { game } = startActions();
  fireAction(game, { player: 0, isClientOnly: false, args: { flags: 0 } });
  fireAction(game, { player: 0, isClientOnly: true, args: { flags: 0 } });
  game.tick();
  flushAll(game);
  const rows = game.eventsOfType("game_action");
  assert.deepEqual(rows.map((row) => [row.action_label, row.player, row.is_client_only]),
    [["confirmed", 0, false], ["prediction", 0, true]]);
  for (const row of rows) {
    assert.ok(Object.prototype.hasOwnProperty.call(row, "player"));
    assert.ok(Object.prototype.hasOwnProperty.call(row, "is_client_only"));
  }
});

test("hook copies values before the game mutates arguments or result and nulls every absent flat field", () => {
  const { game } = startActions();
  const args = { flags: 0, ride: 8, nested: { value: 9 } };
  const result = { error: 0, cost: 99, ride: 10 };
  fireAction(game, { args, result });
  args.ride = 80;
  args.nested.value = 90;
  result.error = 4;
  result.cost = 999;
  result.ride = 100;
  fireAction(game, { args: {}, result: {}, type: null });
  game.tick();
  flushAll(game);
  const rows = game.eventsOfType("game_action");
  assert.deepEqual([rows[0].args_ride, rows[0].result_error, rows[0].result_cost_tenths, rows[0].result_ride],
    [8, 0, 99, 10]);
  assert.deepEqual(JSON.parse(rows[0].args_json), { flags: 0, ride: 8, nested: { value: 9 } });
  assert.deepEqual([rows[1].args_flags, rows[1].args_ride, rows[1].args_ride_type, rows[1].args_ride_object,
    rows[1].args_price_tenths, rows[1].args_x, rows[1].args_y, rows[1].args_z,
    rows[1].result_error, rows[1].result_cost_tenths, rows[1].result_ride],
  [null, null, null, null, null, null, null, null, null, null, null]);
  assert.equal(rows[1].type, null);
});

test("action sends refill one payload object while each emitted row keeps its own values", () => {
  const { game, seenPayloads } = startActions();
  fireAction(game, { action: "ridesetprice", args: { ride: 1 } });
  fireAction(game, { action: "ridesetstatus", args: { ride: 2 } });
  game.tick();
  flushAll(game);
  assert.equal(seenPayloads.length, 2);
  assert.equal(seenPayloads[0], seenPayloads[1]);
  assert.deepEqual(game.eventsOfType("game_action").map((row) => [row.action, row.args_ride]),
    [["ridesetprice", 1], ["ridesetstatus", 2]]);
});

test("action items keep creation order beside a guest arrival", () => {
  const { game } = startActions();
  fireAction(game, { action: "ridesetprice" });
  game.generateGuest();
  fireAction(game, { action: "ridesetstatus" });
  game.tick();
  flushAll(game);
  assert.deepEqual(game.received.filter((row) => row.event_type === "game_action" || row.event_type === "guest_arrived")
    .map((row) => row.event_type === "game_action" ? row.action : row.event_type),
  ["ridesetprice", "guest_arrived", "ridesetstatus"]);
});

test("action clock remains at the hook day when the send occurs after day change", () => {
  const { game } = startActions();
  fireAction(game);
  game.day(1520);
  game.tick();
  flushAll(game);
  const [row] = game.eventsOfType("game_action");
  assert.deepEqual([row.action_at_ticks, row.action_game_day, row.game_ticks_elapsed, row.game_day],
    [1000, 1, 1521, 2]);
});

test("buffer overflow counts each dropped label and save sends all retained items in order", () => {
  const { game, recorder } = startActions();
  for (let i = 0; i < 2048; i++) {
    fireAction(game, { action: "ridesetprice", isClientOnly: i % 2 === 1, args: { ride: i, flags: 0 } });
  }
  fireAction(game, { action: "ridesetprice", args: { flags: 64 } });
  fireAction(game, { action: "ridesetprice", isClientOnly: true, args: { flags: 0 } });
  fireAction(game, { action: "ridesetprice", args: { flags: 0 } });
  assert.equal(recorder.task.pending(), 2048);
  // A preview never reaches the buffer, so it is skipped, not dropped.
  assert.deepEqual([recorder.totals().game_actions_dropped_preview_total,
    recorder.totals().game_actions_dropped_prediction_total,
    recorder.totals().game_actions_dropped_confirmed_total,
    recorder.totals().game_actions_skipped_preview_total], [0, 1, 1, 1]);
  game.save();
  assert.equal(recorder.task.pending(), 0);
  flushAll(game, 206);
  const rows = game.eventsOfType("game_action");
  assert.equal(rows.length, 2048);
  assert.deepEqual(rows.map((row) => row.args_ride), Array.from({ length: 2048 }, (_, i) => i));
  assert.deepEqual([recorder.totals().game_actions_sent_preview_total,
    recorder.totals().game_actions_sent_prediction_total,
    recorder.totals().game_actions_sent_confirmed_total], [0, 1024, 1024]);
});

test("session without hooks sends no action rows and stats expose running totals", () => {
  const { game, recorder } = startActions();
  game.day(1520);
  flushAll(game);
  assert.equal(game.eventsOfType("game_action").length, 0);
  let stats = game.eventsOfType("plugin_stats").at(-1);
  assert.deepEqual([stats.game_actions_sent_preview_total, stats.game_actions_sent_prediction_total,
    stats.game_actions_sent_confirmed_total, stats.game_actions_dropped_preview_total,
    stats.game_actions_dropped_prediction_total, stats.game_actions_dropped_confirmed_total,
    stats.action_query_ms_total, stats.action_execute_ms_total], [0, 0, 0, 0, 0, 0, 0, 0]);
  fireAction(game, { isClientOnly: true, args: { flags: 0 } });
  game.save();
  game.day(2040);
  flushAll(game);
  stats = game.eventsOfType("plugin_stats").at(-1);
  assert.equal(stats.game_actions_sent_prediction_total, 1);
});

// ---- Skip path: non-business calls leave before anything is copied or ordered (R2-R7) ----

const KEPT_NAMES = [
  "parksetentrancefee", "ridesetprice", "ridesetstatus", "ridesetsetting", "ridesetvehicle", "parksetparameter",
  "parkmarketing", "parksetloan", "parksetresearchfunding", "staffhire", "stafffire", "staffsetorders",
  "staffsetpatrolarea",
];

function skipped(recorder) {
  const totals = recorder.totals();
  return [totals.game_actions_skipped_preview_total, totals.game_actions_skipped_prediction_total,
    totals.game_actions_skipped_confirmed_total, totals.game_actions_skipped_unknown_total,
    totals.game_actions_skipped_cheat_total];
}

// One call with every read counted: the event's own properties and every key read from args.
function fireSpied(game, { action = "ridesetprice", isClientOnly = false, args = {} } = {}) {
  const reads = { event: {}, args: {}, resultEvaluated: 0, toJSON: 0, enumerated: 0 };
  const count = (bucket, key) => { bucket[key] = (bucket[key] || 0) + 1; };
  const spiedArgs = new Proxy(args, {
    get(target, key) {
      if (key === "toJSON") reads.toJSON += 1;
      count(reads.args, String(key));
      return target[key];
    },
    ownKeys(target) {
      reads.enumerated += 1;
      return Reflect.ownKeys(target);
    },
  });
  const event = {
    player: -1,
    type: 2,
    get action() { count(reads.event, "action"); return action; },
    get isClientOnly() { count(reads.event, "isClientOnly"); return isClientOnly; },
    get args() { count(reads.event, "args"); return spiedArgs; },
    get result() { reads.resultEvaluated += 1; return {}; },
  };
  for (const callback of game.actionExecuteHooks) callback(event);
  return reads;
}

test("burst 1: skipped trackplace calls on both hooks never fill the buffer or raise the drop counters", () => {
  const { game, recorder } = startActions();
  for (let i = 0; i < 400; i++) {
    for (const hook of ["query", "execute"]) {
      fireAction(game, { hook, action: "trackplace", args: { flags: 64 } });
      fireAction(game, { hook, action: "trackplace", isClientOnly: true, args: { flags: 0 } });
      fireAction(game, { hook, action: "trackplace", args: { flags: 0 } });
    }
    fireAction(game, { action: "ridesetprice", args: { flags: 0, ride: i } });
  }
  fireAction(game, { action: "ridesetprice", args: { flags: 0, ride: 400 } });
  assert.equal(recorder.task.pending(), 401);
  const totals = recorder.totals();
  assert.equal(totals.game_actions_dropped_confirmed_total, 0);
  assert.deepEqual(skipped(recorder), [800, 800, 800, 0, 0]);
  game.save();
  flushAll(game, 50);
  const rows = game.eventsOfType("game_action");
  assert.equal(rows.length, 401);
  assert.ok(rows.every((row) => row.action === "ridesetprice"));
});

test("burst 1 is larger than the buffer: more skipped calls than 2048 do not touch the drop counters", () => {
  const { game, recorder } = startActions();
  for (let i = 0; i < 2400; i++) fireAction(game, { action: "trackplace", args: { flags: i % 2 ? 64 : 0 } });
  for (let i = 0; i < 1000; i++) fireAction(game, { action: "ridesetprice", args: { flags: 0 } });
  const totals = recorder.totals();
  assert.deepEqual([totals.game_actions_dropped_preview_total, totals.game_actions_dropped_prediction_total,
    totals.game_actions_dropped_confirmed_total], [0, 0, 0]);
  assert.deepEqual(skipped(recorder), [1200, 0, 1200, 0, 0]);
  assert.equal(recorder.task.pending(), 1000);
});

test("burst 2: more than 2048 kept confirmed calls in one tick are dropped by label and skip nothing", () => {
  const { game, recorder } = startActions();
  for (let i = 0; i < 2100; i++) fireAction(game, { action: "ridesetprice", args: { flags: 0 } });
  const totals = recorder.totals();
  assert.deepEqual([totals.game_actions_dropped_preview_total, totals.game_actions_dropped_prediction_total,
    totals.game_actions_dropped_confirmed_total], [0, 0, 52]);
  assert.deepEqual(skipped(recorder), [0, 0, 0, 0, 0]);
  assert.equal(recorder.task.pending(), 2048);
});

test("seq stays gapless across every event when kept and skipped calls are mixed", () => {
  const { game } = startActions();
  for (let i = 0; i < 30; i++) {
    fireAction(game, { action: i % 3 === 0 ? "ridesetprice" : "trackplace", args: { flags: i % 2 ? 64 : 0, ride: i } });
    if (i % 5 === 0) game.generateGuest();
  }
  game.save();
  flushAll(game, 10);
  const seqs = game.received.map((row) => row.seq);
  assert.ok(game.eventsOfType("game_action").length > 0);
  assert.deepEqual(seqs, Array.from({ length: seqs.length }, (_, i) => i + 1));
});

test("skipped calls take no work-queue orders between kept actions", () => {
  const { game, actionOrders } = startActions();
  fireAction(game, { action: "ridesetprice", args: { flags: 0 } });
  fireAction(game, { action: "trackplace", args: { flags: 0 } });
  fireAction(game, { action: "ridesetstatus", args: { flags: 0 } });
  fireAction(game, { action: "ridesetprice", args: { flags: 64 } });
  fireAction(game, { action: "ridesetvehicle", args: { flags: 0, type: 2 } });
  fireAction(game, { action: "ridesetprice", args: { flags: 0 } });
  assert.equal(actionOrders.length, 3);
  assert.deepEqual(actionOrders.slice(1), actionOrders.slice(0, -1).map((order) => order + 1));
});

test("per label: a skipped call raises only its own label's counter; previews of kept names are skipped", () => {
  const { game, recorder } = startActions();
  fireAction(game, { action: "trackplace", args: { flags: 64 } });
  assert.deepEqual(skipped(recorder), [1, 0, 0, 0, 0]);
  fireAction(game, { action: "trackplace", isClientOnly: true, args: { flags: 0 } });
  assert.deepEqual(skipped(recorder), [1, 1, 0, 0, 0]);
  fireAction(game, { action: "trackplace", args: { flags: 0 } });
  assert.deepEqual(skipped(recorder), [1, 1, 1, 0, 0]);
  fireAction(game, { action: "ridesetprice", args: { flags: 64 } });
  fireAction(game, { action: "ridesetprice", args: { flags: -2147483584 } });
  assert.deepEqual(skipped(recorder), [3, 1, 1, 0, 0]);
  assert.equal(recorder.task.pending(), 0);
  fireAction(game, { action: "ridesetprice", isClientOnly: true, args: { flags: 0 } });
  assert.equal(recorder.task.pending(), 1);
  assert.deepEqual(skipped(recorder), [3, 1, 1, 0, 0]);
  game.save();
  flushAll(game, 2);
  assert.deepEqual(game.eventsOfType("game_action").map((row) => row.action_label), ["prediction"]);
});

test("unknown names are dropped and counted by label and as unknown; a known dropped name is not unknown", () => {
  const { game, recorder } = startActions();
  fireAction(game, { action: "notanaction", args: { flags: 0 } });
  fireAction(game, { action: "constructor", isClientOnly: true, args: { flags: 0 } });
  fireAction(game, { action: "__proto__", args: { flags: 64 } });
  assert.deepEqual(skipped(recorder), [1, 1, 1, 3, 0]);
  fireAction(game, { action: "trackplace", args: { flags: 0 } });
  assert.deepEqual(skipped(recorder), [1, 1, 2, 3, 0]);
  assert.equal(recorder.task.pending(), 0);
});

test("cheatset raises its label's counter and the cheat counter; other names do not", () => {
  const { game, recorder } = startActions();
  fireAction(game, { action: "cheatset", args: { flags: 0, type: 1, param1: 1 } });
  fireAction(game, { action: "cheatset", isClientOnly: true, args: { flags: 0 } });
  fireAction(game, { action: "cheatset", args: { flags: 64 } });
  assert.deepEqual(skipped(recorder), [1, 1, 1, 0, 3]);
  fireAction(game, { action: "trackplace", args: { flags: 0 } });
  fireAction(game, { action: "notanaction", args: { flags: 0 } });
  assert.equal(recorder.totals().game_actions_skipped_cheat_total, 3);
  assert.equal(recorder.task.pending(), 0);
});

test("ridefreezerating raises its label's counter and the cheat counter for every label", () => {
  const { game, recorder } = startActions();
  fireAction(game, { action: "ridefreezerating", args: { flags: 0 } });
  assert.deepEqual(skipped(recorder), [0, 0, 1, 0, 1]);
  assert.equal(recorder.totals().game_actions_skipped_cheat_total, 1);
  fireAction(game, { action: "ridefreezerating", isClientOnly: true, args: { flags: 0 } });
  assert.deepEqual(skipped(recorder), [0, 1, 1, 0, 2]);
  assert.equal(recorder.totals().game_actions_skipped_cheat_total, 2);
  fireAction(game, { action: "ridefreezerating", args: { flags: 64 } });
  assert.deepEqual(skipped(recorder), [1, 1, 1, 0, 3]);
  assert.equal(recorder.totals().game_actions_skipped_cheat_total, 3);
  assert.equal(recorder.task.pending(), 0);
  assert.deepEqual(game.eventsOfType("game_action"), []);

  const combined = startActions();
  fireAction(combined.game, { action: "cheatset", args: { flags: 0 } });
  fireAction(combined.game, { action: "ridefreezerating", args: { flags: 0 } });
  assert.deepEqual(skipped(combined.recorder), [0, 0, 2, 0, 2]);
  assert.equal(combined.recorder.totals().game_actions_skipped_cheat_total, 2);
  fireAction(combined.game, { action: "guestsetflags", args: { flags: 0 } });
  assert.deepEqual(skipped(combined.recorder), [0, 0, 3, 0, 2]);
  assert.equal(combined.recorder.totals().game_actions_skipped_cheat_total, 2);
  assert.equal(combined.recorder.task.pending(), 0);
  assert.deepEqual(combined.game.eventsOfType("game_action"), []);
});

test("sub-types: kept ride settings and vehicle types are sent; others are dropped with only the sub-type read", () => {
  const { game, recorder } = startActions();
  for (const setting of [0, 1, 2, 3, 4, 5, 8, 9]) fireAction(game, { action: "ridesetsetting", args: { flags: 0, setting } });
  for (const type of [0, 1]) fireAction(game, { action: "ridesetvehicle", args: { flags: 0, type } });
  assert.equal(recorder.task.pending(), 10);
  assert.deepEqual(skipped(recorder), [0, 0, 0, 0, 0]);
  const dropped = [
    ["ridesetsetting", { setting: 6 }], ["ridesetsetting", { setting: 7 }], ["ridesetsetting", { setting: 10 }],
    ["ridesetsetting", { setting: 99 }], ["ridesetsetting", { setting: -1 }], ["ridesetsetting", { setting: 1.5 }],
    ["ridesetsetting", {}], ["ridesetsetting", { setting: "0" }],
    ["ridesetvehicle", { type: 2 }], ["ridesetvehicle", { type: 99 }], ["ridesetvehicle", { type: -1 }],
    ["ridesetvehicle", { type: 0.5 }], ["ridesetvehicle", {}],
    // The other filtered name's field is not the sub-type.
    ["ridesetsetting", { type: 0 }], ["ridesetvehicle", { setting: 0 }],
  ];
  for (const [action, args] of dropped) {
    const reads = fireSpied(game, { action, args: { flags: 0, ...args } });
    const subtype = action === "ridesetsetting" ? "setting" : "type";
    assert.deepEqual(Object.keys(reads.args).sort(), ["flags", subtype].sort(), JSON.stringify([action, args]));
    assert.equal(reads.resultEvaluated, 0);
  }
  assert.equal(recorder.task.pending(), 10);
  assert.deepEqual(skipped(recorder), [0, 0, dropped.length, 0, 0]);
});

test("all 81 names: the 13 kept names are sent, the 68 dropped names are not", () => {
  const { game, recorder } = startActions();
  const table = vm.runInContext("ACTION_NAME_CODES", game.context);
  const names = Object.keys(table);
  assert.equal(names.length, 81);
  assert.ok(KEPT_NAMES.every((name) => names.includes(name)));
  for (const action of names) {
    fireAction(game, { action, args: { flags: 0, setting: 0, type: 0 } });
  }
  assert.equal(recorder.task.pending(), 13);
  game.save();
  flushAll(game, 3);
  assert.deepEqual(game.eventsOfType("game_action").map((row) => row.action).sort(), [...KEPT_NAMES].sort());
  assert.deepEqual(skipped(recorder), [0, 0, 68, 0, 2]);
});

test("skipped calls read nothing extra, copy nothing and never evaluate event.result", () => {
  const { game, recorder } = startActions();
  const stringify = vm.runInContext("JSON.stringify", game.context);
  let stringifyCalls = 0;
  vm.runInContext("JSON", game.context).stringify = (...args) => { stringifyCalls += 1; return stringify(...args); };
  const everyArg = { flags: 0, ride: 1, rideType: 2, rideObject: 3, price: 4, x: 5, y: 6, z: 7, setting: 99, type: 99 };
  const skippedCalls = [
    { action: "trackplace", args: everyArg },
    { action: "ridesetprice", args: { ...everyArg, flags: 64 } },
    { action: "notanaction", args: everyArg },
    { action: "cheatset", args: everyArg },
    { action: "ridesetsetting", args: { ...everyArg, setting: 6 } },
    { action: "ridesetvehicle", args: { ...everyArg, type: 2 } },
  ];
  for (const call of skippedCalls) {
    const reads = fireSpied(game, call);
    const filtered = call.action === "ridesetsetting" ? ["flags", "setting"]
      : call.action === "ridesetvehicle" ? ["flags", "type"] : ["flags"];
    assert.deepEqual(Object.keys(reads.args).sort(), filtered.sort(), call.action);
    assert.deepEqual(reads.event, { action: 1, isClientOnly: 1, args: 1 }, call.action);
    assert.equal(reads.resultEvaluated, 0, call.action);
    assert.equal(reads.toJSON, 0, call.action);
    assert.equal(reads.enumerated, 0, call.action);
  }
  assert.equal(stringifyCalls, 0);
  assert.equal(recorder.task.pending(), 0);
});

test("a kept call evaluates event.result once and copies its arguments", () => {
  const { game } = startActions();
  const reads = fireSpied(game, { action: "ridesetprice", args: { flags: 0, ride: 3 } });
  assert.equal(reads.resultEvaluated, 1);
  assert.ok(reads.toJSON > 0, "the kept path serialises the arguments");
});

test("the compiled plugin is ES5: no arrow functions, let, const, classes or template strings", () => {
  const compiled = readFileSync(fileURLToPath(new URL("../dist/openrct2-analytics.js", import.meta.url)), "utf8");
  const source = compiled.split("\n").map((line) => line.replace(/\/\/.*$/, "")).join("\n");
  assert.ok(source.includes("ACTION_NAME_CODES"));
  assert.doesNotMatch(source, /=>|\b(let|const|class)\s|`/);
});

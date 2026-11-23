// Tests for the work queue, driven through the stand-in game in fake-game.mjs. Fake costs per game API call
// give each step a known duration; game.tick() fires the tick hook on a new tick, and calling game.tickHooks
// directly fires it again on the current tick, as when the engine runs it after the day hook.
//
// The later tests add the test tasks in queue-tasks.mjs to the queue main() created, and report to it the steps
// that run outside the queue.
import assert from "node:assert/strict";
import { test } from "node:test";

import { createGame } from "./fake-game.mjs";
import { continuousTask, dayTask, startCapturingQueue } from "./queue-tasks.mjs";

const DAY_TICKS = 520;

function startGame(options) {
  return createGame(options).load().start();
}

function addRides(game, count) {
  for (let i = 0; i < count; i++) game.addRide();
}

// Fires the tick hooks on the current tick, without moving the game date.
function tickHooksNow(game) {
  for (const hook of game.tickHooks) hook();
}

function nextDay(game) {
  game.day(game.date.ticksElapsed + DAY_TICKS);
}

function lastStats(game) {
  const stats = game.eventsOfType("plugin_stats");
  return stats[stats.length - 1];
}

// The game tick of each ride_snapshot: the tick its step ran on.
function snapshotTicks(game) {
  return game.eventsOfType("ride_snapshot").map((event) => event.game_ticks_elapsed);
}

function assertContiguous(events) {
  assert.deepEqual(events.map((event) => event.seq), events.map((_, i) => i + 1));
  for (const event of events) assert.equal(event.event_id, `${event.session_id}-${event.seq}`);
}

function workCounters(stats) {
  return [stats.work_units_total, stats.work_items_skipped_total, stats.work_queue_length];
}

test("steps stop once the plugin's time in the tick reaches the 4 ms allowance", () => {
  const game = createGame();
  game.costs["map.getRide"] = 1;
  game.load().start();
  addRides(game, 10);
  game.socket.accept();
  game.day(1520);
  game.tick(3);
  // Tick 1521: the list read (0 ms) and four 1 ms rides reach 4 ms; tick 1523 finishes and hands off the lines.
  assert.deepEqual(snapshotTicks(game), [1521, 1521, 1521, 1521, 1522, 1522, 1522, 1522, 1523, 1523]);
});

test("a step is never cut short, so a tick overshoots the allowance by at most one step", () => {
  const game = createGame();
  game.costs["map.getRide"] = 3;
  game.load().start();
  addRides(game, 4);
  game.socket.accept();
  game.day(1520);
  game.tick(3);
  assert.deepEqual(snapshotTicks(game), [1521, 1521, 1522, 1522]);
  nextDay(game);
  const stats = lastStats(game);
  // 3 ms, then 6 ms: the second step started under 4 ms and ran to its end; 6 < 4 + 3.
  assert.deepEqual([stats.worst_tick_ms, stats.worst_tick_at_ticks, stats.work_ms_total], [6, 1521, 12]);
});

test("time another callback spent in the same tick counts toward the allowance", () => {
  const game = createGame();
  game.costs["park.cash"] = 3; // the day callback reads it once: 3 ms on tick 1520
  game.costs["map.getRide"] = 1;
  game.load().start();
  addRides(game, 6);
  game.socket.accept();
  game.day(1520);
  tickHooksNow(game); // 3 ms already spent: the list read, then one ride reaches 4 ms
  game.tick(2);
  assert.deepEqual(snapshotTicks(game), [1520, 1521, 1521, 1521, 1521, 1522]);
});

test("at least one step runs per tick, even past the allowance and when one step costs more than it", () => {
  const game = createGame();
  game.costs["park.cash"] = 10;
  game.costs["map.rides"] = 10;
  game.costs["map.getRide"] = 10;
  game.load().start();
  addRides(game, 3);
  game.socket.accept();
  game.day(1520);
  tickHooksNow(game); // 10 ms already spent on this tick: the list read still runs
  assert.equal(lastStats(game).work_queue_length, 0, "built before the day's work was queued");
  game.tick(4);
  assert.deepEqual(snapshotTicks(game), [1521, 1522, 1523]);
  nextDay(game);
  assert.deepEqual(workCounters(lastStats(game)), [5, 0, 0], "the list read, three rides and the guest list read");
});

test("each step serves the oldest line or task, and a task's lines follow all of its items", () => {
  const game = createGame();
  game.costs["socket.write"] = 2;
  game.costs["map.rides"] = 2;
  game.costs["map.getRide"] = 2;
  game.load().start(); // session_start queued: order 1
  addRides(game, 3);
  game.day(1520); // disconnected: plugin_stats and park_snapshot wait (orders 2 and 3); the ride task is 4
  game.socket.accept();
  const types = () => game.received.map((event) => event.event_type);

  game.tick(); // 1521: two 2 ms hand-offs
  assert.deepEqual(types(), ["session_start", "plugin_stats"]);
  game.tick(); // 1522: the last older line, then the task's list read
  assert.deepEqual(types(), ["session_start", "plugin_stats", "park_snapshot"]);
  game.tick(); // 1523: rides 0 and 1; their lines are newer than the task's last item
  assert.equal(game.received.length, 3);
  game.tick(); // 1524: ride 2, then the first ride line
  game.tick(); // 1525: the other two ride lines
  assert.deepEqual(types().slice(3), ["ride_snapshot", "ride_snapshot", "ride_snapshot"]);
  assert.deepEqual(snapshotTicks(game), [1523, 1523, 1524]);
  assertContiguous(game.received);
});

test("seq stays gap-free through tick hand-offs, a throw and a partial send", () => {
  const game = startGame();
  addRides(game, 4);
  game.socket.accept();
  game.day(1520); // seq 1-3 handed off by the day callback's flush
  game.writeBehavior = "throw";
  game.tick(); // the four ride items run; the first ride line's hand-off throws and ends line steps
  assert.equal(game.received.length, 3);
  assert.equal(game.socket.writes, 4, "no line step after the throw");

  game.interval(); // reconnect
  game.socket.accept();
  game.tick(); // the kept line goes first, with the seq the throw left unused
  assert.deepEqual(
    game.eventsOfType("ride_snapshot").map((event) => [event.seq, event.ride_id]),
    [[4, 0], [5, 1], [6, 2], [7, 3]],
  );

  game.writeBehavior = "partial"; // day 2's plugin_stats (seq 8) is cut and runs into park_snapshot (seq 9)
  game.day(2040);
  game.tick();
  game.day(2560);
  assert.equal(game.malformed.length, 1);
  const expected = [1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 13, 14, 15];
  assert.deepEqual(game.received.map((event) => event.seq), expected);
  for (const event of game.received) assert.equal(event.event_id, `${event.session_id}-${event.seq}`);
  const stats = lastStats(game);
  assert.deepEqual([stats.write_error_total, stats.write_partial_total], [1, 1]);
});

test("while disconnected, task items still run and their lines wait for the reconnect flush", () => {
  const game = startGame();
  addRides(game, 3);
  game.day(1520);
  game.tick();
  assert.equal(game.received.length, 0);
  game.interval(); // reconnect
  game.socket.accept();
  game.interval(); // flush: session_start, plugin_stats, park_snapshot and the three ride lines
  assert.deepEqual(snapshotTicks(game), [1521, 1521, 1521]);
  assertContiguous(game.received);
});

test("a day whose ride work does not finish counts the skipped items, and the next day reads a fresh list", () => {
  const game = createGame();
  game.costs["map.getRide"] = 2;
  game.load().start();
  addRides(game, 5);
  game.socket.accept();
  game.day(1520); // game day 2
  assert.deepEqual(workCounters(lastStats(game)), [0, 0, 0]);
  game.tick(); // the list read and rides 0 and 1; rides 2 to 4 are still pending
  game.addRide(); // ride 5, built before the next day's list read
  game.day(2040); // game day 3: day 2's three unreached rides are dropped
  // Three rides and the held guest list read are pending.
  assert.deepEqual(workCounters(lastStats(game)), [3, 0, 4], "pending work is read before the day's work is queued");
  game.tick(5);
  game.day(2560);
  assert.deepEqual(workCounters(lastStats(game)), [11, 4, 0]);
  const idsOnDay = (day) =>
    game.eventsOfType("ride_snapshot").filter((event) => event.game_day === day).map((event) => event.ride_id);
  assert.deepEqual(idsOnDay(2), [0, 1]);
  assert.deepEqual(idsOnDay(3), [0, 1, 2, 3, 4, 5]);
});

test("plugin_stats then park_snapshot stay consecutive on the same tick while work lines are queued", () => {
  const game = createGame();
  game.costs["socket.write"] = 1;
  game.costs["map.getRide"] = 1;
  game.load().start();
  addRides(game, 20);
  game.socket.accept();
  for (let day = 0; day < 4; day++) {
    nextDay(game); // the day callback's flush hands off older ride lines first
    tickHooksNow(game);
    game.tick(3);
  }
  game.tick(40);
  nextDay(game);
  game.tick(40);
  assertContiguous(game.received);
  const stats = game.eventsOfType("plugin_stats");
  assert.equal(stats.length, 5);
  for (const row of stats) {
    const next = game.received[row.seq]; // received[i] has seq i + 1
    assert.deepEqual(
      [next.event_type, next.seq, next.game_ticks_elapsed],
      ["park_snapshot", row.seq + 1, row.game_ticks_elapsed],
    );
  }
  assert.ok(lastStats(game).work_items_skipped_total > 0, "some days' work was cut off by the next day");
});

test("the tick callback is timed: its time shows in plugin_stats", () => {
  const game = createGame();
  game.costs["map.getRide"] = 3;
  game.load().start();
  addRides(game, 4);
  game.socket.accept();
  game.day(1520);
  game.tick(3); // 1521: 6 ms, 1522: 6 ms, 1523: the ride lines at 0 ms
  nextDay(game);
  const stats = lastStats(game);
  // The day callback on 1520 and three tick callbacks.
  assert.deepEqual(
    [stats.work_ms_total, stats.worst_tick_ms, stats.worst_tick_at_ticks, stats.callbacks],
    [12, 6, 1521, 4],
  );
  assert.deepEqual(workCounters(stats), [6, 0, 0]);
});

test("weather and action hooks keep separate tick parts without becoming work steps", () => {
  const game = createGame().load();
  const { work } = startCapturingQueue(game);
  work.noteTickPart("weather", 0, 1);
  work.noteTickPart("action_query", 0, 2);
  work.noteTickPart("action_execute", 0, 3);
  work.keepTickRecord(6);

  const counters = work.closePeriod();
  assert.equal(counters.worst_tick_kind_ms, "weather:1.000|action_query:2.000|action_execute:3.000");
  assert.deepEqual(
    [counters.action_query_ms_total, counters.action_execute_ms_total, counters.worst_step_kind],
    [2, 3, null],
  );
});

test("restarting in the same script context starts a clean work queue", () => {
  const game = createGame();
  game.costs["map.getRide"] = 2;
  game.load().start();
  addRides(game, 5);
  game.day(1520); // disconnected: lines wait
  game.tick(); // rides 0 and 1 read, three pending
  assert.equal(game.received.length, 0);

  game.restartInSameContext();
  game.socket.accept();
  nextDay(game);
  const stats = lastStats(game);
  assert.deepEqual(workCounters(stats), [0, 0, 0]);
  assert.equal(stats.queue_length, 1, "only the new session's session_start waits");
  game.tick(10);
  assertContiguous(game.received);
  const sessions = new Set(game.received.map((event) => event.session_id));
  assert.equal(sessions.size, 1);
  assert.deepEqual(game.eventsOfType("ride_snapshot").map((event) => event.ride_id), [0, 1, 2, 3, 4]);
});

test("guest steps wait from the day callback's tick until the day's ride items are done, then all run", () => {
  const game = createGame();
  game.costs["park.cash"] = 1;
  game.costs["map.getRide"] = 2;
  game.load();
  const { work, nextOrder } = startCapturingQueue(game);
  const guests = dayTask(game, "guest", 3, 3);
  const arrivals = continuousTask(game, "arrival", nextOrder, 3);
  work.addDayTask(guests);
  work.addContinuousTask(arrivals);
  addRides(game, 5);
  game.socket.accept();
  arrivals.feed(2); // older than the day's ride items, and still held
  game.day(1520); // 1 ms
  tickHooksNow(game); // 1520: the list read and rides 0 and 1, 5 ms in all
  game.tick(2); // 1521: rides 2 and 3, 4 ms; 1522: ride 4, the day's last ride item, 2 ms
  assert.deepEqual(snapshotTicks(game), [1520, 1520, 1521, 1521, 1522]);
  assert.deepEqual([arrivals.ran, guests.ran], [[], []], "no guest step on a day-start tick");
  game.tick(3); // 1523: both arrivals, 6 ms; 1524: two guest items; 1525: the last one
  assert.deepEqual([arrivals.ran, guests.ran], [[1523, 1523], [1524, 1524, 1525]]);
  nextDay(game);
  const stats = lastStats(game);
  assert.deepEqual(
    [stats.work_items_skipped_total, stats.work_queue_length, stats.continuous_items_pending],
    [0, 0, 0],
    "none dropped or skipped",
  );
  // The highest whole day-start tick is the day callback's (its own 1 ms included); the worst tick is a guest tick.
  assert.deepEqual([stats.worst_day_start_tick_ms, stats.worst_tick_ms, stats.worst_tick_at_ticks], [5, 6, 1523]);
  assert.equal(stats.worst_tick_kind_ms, "arrival:6.000");
});

test("at a new day, day-scoped items left are skipped and counted; continuous items stay pending and run", () => {
  const game = createGame().load();
  const { work, nextOrder } = startCapturingQueue(game);
  const guests = dayTask(game, "guest", 4, 0);
  const arrivals = continuousTask(game, "arrival", nextOrder, 0);
  work.addDayTask(guests);
  work.addContinuousTask(arrivals);
  game.socket.accept();
  game.day(1520); // the ride and guest tasks' list reads and four guest items
  arrivals.feed(3);
  game.day(2040); // nothing ran
  game.day(2560);
  const queueCounts = (stats) =>
    [stats.work_queue_length, stats.continuous_items_pending, stats.work_items_skipped_total];
  assert.deepEqual(queueCounts(lastStats(game)), [6, 3, 6]);
  // 2561: the ride list read (no rides); 2562: the three arrivals, the guest list read and the four guest items
  game.tick(2);
  nextDay(game);
  assert.deepEqual(queueCounts(lastStats(game)), [0, 0, 12]);
  assert.deepEqual([arrivals.ran.length, guests.ran.length], [3, 4]);
});

test("many cheap guest steps make guest the worst tick's largest part, though a ride step is the longest", () => {
  const game = createGame();
  game.costs["map.getRide"] = 3;
  game.load();
  const { work } = startCapturingQueue(game);
  work.addDayTask(dayTask(game, "guest", 6, 0.75));
  addRides(game, 1);
  game.socket.accept();
  game.day(1520);
  tickHooksNow(game); // 1520: the list read and the 3 ms ride step; the guest items wait
  game.tick(); // 1521: six 0.75 ms guest items reach 4.5 ms
  nextDay(game);
  const stats = lastStats(game);
  assert.deepEqual([stats.worst_tick_ms, stats.worst_tick_at_ticks, stats.worst_tick_kind_ms], [4.5, 1521, "guest:4.500"]);
  assert.deepEqual([stats.worst_step_ms, stats.worst_step_kind], [3, "ride"]);
});

test("the day callback's time is its own part, other callbacks' time is other, and the parts sum to the tick", () => {
  const game = createGame();
  game.costs["park.cash"] = 2;
  game.costs["map.getRide"] = 2;
  game.load().start();
  addRides(game, 1);
  game.day(1520); // disconnected: the day callback's 2 ms
  tickHooksNow(game); // the list read and the 2 ms ride step
  game.costs["network.createSocket"] = 1;
  game.interval(1520); // a 1 ms reconnect on the same tick
  game.socket.accept();
  nextDay(game);
  const stats = lastStats(game);
  assert.deepEqual([stats.worst_tick_ms, stats.worst_tick_at_ticks], [5, 1520]);
  assert.equal(stats.worst_tick_kind_ms, "ride:2.000|day_callback:2.000|other:1.000");
  const parts = stats.worst_tick_kind_ms.split("|").map((part) => Number(part.split(":")[1]));
  assert.equal(parts.reduce((sum, ms) => sum + ms, 0), stats.worst_tick_ms);
});

test("a day callback that throws still reports its time as day_callback", () => {
  const game = createGame();
  game.costs["park.cash"] = 2;
  game.load().start();
  game.socket.accept();
  game.throwing.add("park.cash"); // the park snapshot's cash read costs 2 ms, then throws
  assert.throws(() => game.day(1520), /stand-in park\.cash throws/);
  game.throwing.delete("park.cash");
  nextDay(game);
  const stats = lastStats(game);
  assert.deepEqual([stats.worst_tick_ms, stats.worst_tick_at_ticks], [2, 1520]);
  assert.equal(stats.worst_tick_kind_ms, "day_callback:2.000");
});

test("lines_queued_max reports each period's highest emitter queue length", () => {
  const game = startGame();
  addRides(game, 3);
  game.day(1520); // disconnected: session_start, plugin_stats and park_snapshot wait
  game.tick(); // the three ride lines join them: 6
  game.interval(); // reconnect
  game.socket.accept();
  game.interval(); // flush all six
  nextDay(game); // two day lines, flushed at once
  game.tick(); // three ride lines at most
  nextDay(game);
  assert.deepEqual(game.eventsOfType("plugin_stats").map((stats) => stats.lines_queued_max), [1, 6, 3]);
});

test("in the engine's order, the tick hook on a new day's tick, before the day callback, already holds guest steps", () => {
  const game = createGame().load();
  const { work } = startCapturingQueue(game);
  const guests = dayTask(game, "guest", 2, 0);
  work.addDayTask(guests);
  addRides(game, 1);
  game.socket.accept();
  game.day(1520);
  game.tick(3); // 1521: the ride items; 1522: both guest items
  assert.deepEqual(guests.ran, [1522, 1522]);
  guests.startDay(0); // plant two guest items, older than anything queued
  // Tick 2040 starts game day 3: the date moves, then the tick hook runs, then the day callback.
  game.date.ticksElapsed = 2040;
  game.date.day += 1;
  tickHooksNow(game);
  assert.deepEqual(guests.ran, [1522, 1522], "held on the new day's tick before its day callback");
  for (const hook of game.dayHooks) hook();
  game.tick(2); // 2041: the ride items; 2042: the day's guest items
  assert.deepEqual(guests.ran, [1522, 1522, 2042, 2042]);
});

test("a later tick that starts with ride items pending is a day-start tick, and can be the worst one", () => {
  const game = createGame();
  game.costs["park.cash"] = 1;
  game.costs["map.getRide"] = 3;
  game.load();
  const { work } = startCapturingQueue(game);
  const guests = dayTask(game, "guest", 1, 7);
  work.addDayTask(guests);
  addRides(game, 3);
  game.socket.accept();
  game.day(1520); // the day callback's tick: 1 ms
  game.tick(3); // 1521: the list read and rides 0 and 1, 6 ms; 1522: ride 2, 3 ms; 1523: the 7 ms guest item
  assert.deepEqual([snapshotTicks(game), guests.ran], [[1521, 1521, 1522], [1523]]);
  nextDay(game);
  const stats = lastStats(game);
  // 1521 started with ride items pending, so it is a day-start tick, costlier than the day callback's; 1523 is not.
  assert.deepEqual([stats.worst_day_start_tick_ms, stats.worst_tick_ms, stats.worst_tick_at_ticks], [6, 7, 1523]);
});

// Reports a step that runs outside the queue, costing `ms` of fake time, from a timed callback on the current tick.
function reportStep(game, captured, kind, ms) {
  captured.timer.timed(() => {
    const msBefore = captured.timer.tickMsSoFar();
    game.wallMs += ms;
    captured.work.noteStep(kind, msBefore, captured.timer.tickMsSoFar());
  });
}

test("steps reported from outside the queue join the tick's parts, and their failures and guest_fields time count", () => {
  const game = createGame();
  game.costs["map.getRide"] = 2;
  game.load();
  const captured = startCapturingQueue(game);
  addRides(game, 2);
  game.socket.accept();
  game.day(1520);
  game.tick(); // 1521: the list read and two 2 ms ride steps, then the three reported steps
  reportStep(game, captured, "poll", 0.25);
  reportStep(game, captured, "boarder_read", 0.5);
  reportStep(game, captured, "guest_fields", 0.25);
  reportStep(game, captured, "action", 0.75);
  game.tick(); // 1522: the ride lines, then a second guest_fields step
  reportStep(game, captured, "guest_fields", 0.25);
  captured.work.noteFailure();
  nextDay(game);
  const stats = lastStats(game);
  assert.deepEqual([stats.worst_tick_ms, stats.worst_tick_at_ticks], [5.75, 1521]);
  assert.equal(stats.worst_tick_kind_ms, "ride:4.000|poll:0.250|boarder_read:0.500|guest_fields:0.250|action:0.750");
  const parts = stats.worst_tick_kind_ms.split("|").map((part) => Number(part.split(":")[1]));
  assert.equal(parts.reduce((sum, ms) => sum + ms, 0), stats.worst_tick_ms);
  assert.deepEqual([stats.worst_step_ms, stats.worst_step_kind], [2, "ride"]);
  assert.deepEqual([stats.guest_fields_ms_total, stats.work_items_failed_total], [0.5, 1]);
});

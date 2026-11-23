// Tests for the action hooks wired in main.ts, driven through the stand-in game: the save drains buffered
// actions before it reads the seq floor and waiting count, and the hook time counts as a tick part.
import assert from "node:assert/strict";
import { test } from "node:test";

import { createGame } from "./fake-game.mjs";
import { fireAction } from "./fake-actions.mjs";

function startGame(options) {
  return createGame(options).load().start();
}

test("an action followed at once by a save takes a lower seq than save_written, which the stored keys predict", () => {
  const game = startGame();
  game.socket.accept();
  game.day(1520);
  game.socket.fail();
  fireAction(game, { hook: "query", action: "ridesetprice" });
  fireAction(game, { hook: "execute", action: "ridesetstatus" });

  const saved = game.save();

  game.interval(); // reconnect
  game.socket.accept();
  game.interval(); // flush
  const actions = game.eventsOfType("game_action");
  const [written] = game.eventsOfType("save_written");
  assert.deepEqual(actions.map((row) => row.action), ["ridesetprice", "ridesetstatus"]);
  for (const row of actions) {
    assert.ok(row.seq < written.seq, `action seq ${row.seq} is below save_written seq ${written.seq}`);
  }
  const { save_seq_floor: floor, save_lines_waiting: waiting } = saved.storage;
  assert.equal(floor + waiting + 1, written.seq);
  assert.ok(waiting >= actions.length, "the waiting count includes the drained actions");
});

// Lines handed off by one tick hook run, with the hooks and the tick in the same game tick.
function linesHandedOffInOneTick(cost) {
  const game = startGame();
  game.socket.accept();
  for (let i = 0; i < 131; i++) fireAction(game, { hook: "execute", action: "ridesetprice", cost });
  const before = game.received.length;
  for (const hook of game.tickHooks) hook();
  return { game, handedOff: game.received.length - before };
}

test("131 hook calls with a set cost in one tick are that tick's action_execute part and stop the queue's steps", () => {
  assert.ok(linesHandedOffInOneTick(0).handedOff > 1, "without hook time the queue runs more than one step");

  const { game, handedOff } = linesHandedOffInOneTick(0.125);
  assert.equal(handedOff, 1, "one step ran: the 16.375 ms of hooks passed the allowance");
  game.tick();
  game.day(game.date.ticksElapsed + 520);
  game.interval();
  const stats = game.eventsOfType("plugin_stats").at(-1);
  assert.match(stats.worst_tick_kind_ms, /(^|\|)action_execute:16\.375(\||$)/);
  assert.equal(stats.action_execute_ms_total, 16.375);
  assert.equal(stats.action_query_ms_total, 0);
});

test("the save's drain times each sent action as an action step on the save tick and counts it as a unit", () => {
  const game = createGame().load();
  const createActionRecorder = game.context.createActionRecorder;
  game.context.createActionRecorder = (emitter, nextOrder) => {
    const emit = emitter.emit;
    emitter.emit = (type, payload) => {
      if (type === "game_action") game.wallMs += 2;
      emit(type, payload);
    };
    return createActionRecorder(emitter, nextOrder);
  };
  game.start();
  game.socket.accept();
  game.day(1520);
  game.interval();
  const unitsBefore = game.eventsOfType("plugin_stats").at(-1).work_units_total;
  fireAction(game, { hook: "query", action: "ridesetprice" });
  fireAction(game, { hook: "execute", action: "ridesetstatus" });
  fireAction(game, { hook: "execute", action: "ridesetprice" });

  game.save();
  game.day(game.date.ticksElapsed + 520);
  game.interval();

  const stats = game.eventsOfType("plugin_stats").at(-1);
  assert.match(stats.worst_tick_kind_ms, /(^|\|)action:6\.000(\||$)/);
  assert.equal(stats.work_units_total - unitsBefore, 3);
});

test("query hooks with a set cost are the action_query part, with its own total", () => {
  const game = startGame();
  game.socket.accept();
  game.day(1520);
  for (let i = 0; i < 4; i++) fireAction(game, { hook: "query", action: "ridesetprice", cost: 0.5 });
  game.tick();
  game.day(game.date.ticksElapsed + 520);
  game.interval();

  const stats = game.eventsOfType("plugin_stats").at(-1);
  assert.match(stats.worst_tick_kind_ms, /(^|\|)action_query:\d/);
  assert.equal(stats.action_query_ms_total, 2);
  assert.equal(stats.action_execute_ms_total, 0);
});

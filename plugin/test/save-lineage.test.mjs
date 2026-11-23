// Tests for save lineage, driven through the stand-in game in fake-game.mjs: the save hook writes four keys to
// park storage and sends save_written; the next session reports the keys of the save it loaded. Random IDs are
// checked by format, never by value.
import assert from "node:assert/strict";
import { test } from "node:test";

import { createGame, createParkStorage } from "./fake-game.mjs";

const SAVE_ID = /^v\d+-[0-9a-z]{1,6}$/;
const SAVE_KEYS = ["save_id", "save_session_id", "save_seq_floor", "save_lines_waiting"];
const LOADED_FIELDS = [
  "loaded_save_id", "loaded_save_session_id", "loaded_save_seq_floor", "loaded_save_lines_waiting",
];
const DAY_TICKS = 520;

function startGame(options) {
  return createGame(options).load().start();
}

function loaded(event) {
  return LOADED_FIELDS.map((field) => event[field]);
}

function stored(values) {
  return SAVE_KEYS.map((key) => values[key]);
}

// The first session_start of the session the game is running now, once its socket is accepted and flushed.
function sessionStartAfterLoad(game) {
  const before = game.received.length;
  game.socket.accept();
  game.interval();
  return game.received[before];
}

// A session that hands off its first three lines, loses the listener, queues two ride snapshots and a day's
// two lines, then saves: four lines wait behind the save's own event.
function saveWhileDisconnected(game) {
  game.addRide();
  game.addRide();
  game.socket.accept();
  game.day(1520);
  assert.equal(game.received.length, 3);
  game.socket.fail();
  game.tick(3);
  game.day(1520 + DAY_TICKS);
  return game.save();
}

test("a save writes the four keys and hands off save_written inside the save callback", () => {
  const game = startGame();
  game.socket.accept();
  game.day(1520);
  const sessionId = game.received[0].session_id;

  const saved = game.save();

  assert.equal(game.received.length, 4, "the save's bounded flush hands off its event at once");
  const written = game.received[3];
  assert.deepEqual([written.event_type, written.seq, written.session_id], ["save_written", 4, sessionId]);
  assert.match(written.save_id, SAVE_ID);
  assert.deepEqual(Object.keys(written).filter((field) => field.startsWith("save")), ["save_id"]);
  // Three lines were handed off and none waited, so the event's seq is floor + waiting + 1.
  assert.deepEqual(stored(game.storage.values), [written.save_id, sessionId, 3, 0]);
  assert.deepEqual(stored(saved.storage), stored(game.storage.values), "the keys reach the saved file");

  game.save();
  const second = game.received[4];
  assert.deepEqual([second.event_type, second.seq], ["save_written", 5]);
  assert.match(second.save_id, SAVE_ID);
  assert.notEqual(second.save_id, written.save_id, "every save mints its own ID");
  assert.deepEqual(stored(game.storage.values), [second.save_id, sessionId, 4, 0]);
});

test("loading a save reports its four keys in session_start at seq 1", () => {
  const game = startGame();
  game.socket.accept();
  game.day(1520);
  const saved = game.save();
  const written = game.eventsOfType("save_written")[0];

  game.loadSave(saved);
  const sessionStart = sessionStartAfterLoad(game);

  assert.deepEqual([sessionStart.event_type, sessionStart.seq], ["session_start", 1]);
  assert.notEqual(sessionStart.session_id, written.session_id);
  assert.equal(sessionStart.park_id, written.park_id);
  assert.deepEqual(loaded(sessionStart), [written.save_id, written.session_id, 3, 0]);
});

test("a save lost with its session still places its event's seq: floor + waiting + 1", () => {
  // The quit: the session ends with save_written still queued, so it never lands.
  const quit = startGame();
  const saved = saveWhileDisconnected(quit);
  assert.deepEqual(stored(quit.storage.values).slice(2), [3, 4]);
  quit.loadSave(saved);
  const sessionStart = sessionStartAfterLoad(quit);
  assert.equal(quit.eventsOfType("save_written").length, 0);
  assert.equal(sessionStart.seq, 1);
  const [, , floor, waiting] = loaded(sessionStart);
  assert.deepEqual([floor, waiting], [3, 4]);

  // The same session, had the listener come back before the quit: the event takes exactly that seq.
  const twin = startGame();
  saveWhileDisconnected(twin);
  twin.interval(); // reconnect
  twin.socket.accept();
  twin.interval(); // flush
  const written = twin.eventsOfType("save_written");
  assert.equal(written.length, 1);
  assert.equal(written[0].seq, floor + waiting + 1);
  assert.deepEqual(twin.received.map((event) => event.seq), [1, 2, 3, 4, 5, 6, 7, 8]);
});

test("a park never saved by the plugin reports null for all four", () => {
  const game = startGame();
  const sessionStart = sessionStartAfterLoad(game);
  // Sent as JSON null, not left out: a missing field would read back as undefined.
  assert.deepEqual(loaded(sessionStart), [null, null, null, null]);
});

test("a stored save key of the wrong type or out of range reads as null, and only that one", () => {
  const good = { save_id: "v1-a", save_session_id: "s1-b", save_seq_floor: 0, save_lines_waiting: 0 };
  const wrong = [
    ["save_id", ""], ["save_id", 42], ["save_id", null],
    ["save_session_id", ""], ["save_session_id", { id: "s1-b" }],
    ["save_seq_floor", -1], ["save_seq_floor", 2.5], ["save_seq_floor", "3"],
    // Past what the converter stores: a floor beyond JSON's safe integers (BIGINT), a count beyond INTEGER.
    ["save_seq_floor", 9007199254740992],
    ["save_lines_waiting", -2], ["save_lines_waiting", true], ["save_lines_waiting", 2147483648],
  ];
  // The smallest and largest counts the converter stores read back as stored.
  const largest = { save_seq_floor: 9007199254740991, save_lines_waiting: 2147483647 };
  const kept = [
    [good, ["v1-a", "s1-b", 0, 0]],
    [{ ...good, ...largest }, ["v1-a", "s1-b", 9007199254740991, 2147483647]],
  ];
  for (const [values, expected] of kept) {
    const baseline = createParkStorage();
    Object.assign(baseline.values, values);
    assert.deepEqual(loaded(sessionStartAfterLoad(startGame({ storage: baseline }))), expected);
  }
  for (const [key, value] of wrong) {
    const storage = createParkStorage();
    Object.assign(storage.values, good, { [key]: value });
    const expected = stored(good).map((goodValue, i) => (SAVE_KEYS[i] === key ? null : goodValue));
    assert.deepEqual(loaded(sessionStartAfterLoad(startGame({ storage }))), expected, `${key} = ${String(value)}`);
  }
});

test("a park storage failure in the save hook reaches the game and sends no save_written", () => {
  const game = startGame();
  game.socket.accept();
  game.day(1520);
  const set = game.storage.set;
  game.storage.set = () => {
    throw new Error("storage unavailable");
  };
  assert.throws(() => game.save(), /storage unavailable/);
  game.storage.set = set;
  game.interval();
  game.day(1520 + DAY_TICKS);
  assert.equal(game.eventsOfType("save_written").length, 0);
});

test("the save callback is timed: its time shows in plugin_stats", () => {
  const game = startGame(); // tick 1000
  game.socket.accept();
  game.day(1520); // 0 ms: writes cost nothing yet
  game.costs["socket.write"] = 6;
  game.date.ticksElapsed = 1600;
  game.save(); // one write: 6 ms on tick 1600
  game.costs["socket.write"] = 0;
  game.day(1520 + DAY_TICKS);
  const stats = game.eventsOfType("plugin_stats")[1];
  // The day callback on 1520 and the save callback on 1600.
  assert.deepEqual(
    [stats.work_ms_total, stats.worst_tick_ms, stats.worst_tick_at_ticks, stats.callbacks],
    [6, 6, 1600, 2],
  );
});

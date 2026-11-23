// Tests for the compiled plugin, driven through the stand-in game in fake-game.mjs. Random IDs are
// checked by format, never by value.
import assert from "node:assert/strict";
import { test } from "node:test";

import { createGame, createParkStorage } from "./fake-game.mjs";

const PARK_ID = /^k\d+-[0-9a-z]{1,6}$/;
const SESSION_ID = /^s\d+-[0-9a-z]{1,6}$/;
const ISO_MS = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;
const ENVELOPE = [
  "schema_version", "event_type", "plugin_version", "park_id", "session_id", "game_year", "game_month",
  "game_day", "game_ticks_elapsed", "emitted_at", "seq", "event_id",
];
const SNAPSHOT_FIELDS = [
  "cash_tenths", "guests_in_park", "park_rating", "total_admissions", "weather", "temperature_c",
];
const STATS_FIELDS = [
  "period_start_ticks", "period_end_ticks", "period_ticks", "work_ms_total", "worst_tick_ms",
  "worst_tick_at_ticks", "callbacks", "warmup", "clock", "game_speed", "lines_dropped_total",
  "write_partial_total", "write_error_total", "connect_attempts_total", "queue_length",
  "finance_months_unread_total", "work_units_total", "work_items_skipped_total", "work_queue_length",
  "work_items_failed_total", "worst_step_ms", "worst_step_kind", "worst_tick_kind_ms", "worst_day_start_tick_ms",
  "guest_fields_ms_total", "action_query_ms_total", "action_execute_ms_total", "game_actions_sent_preview_total",
  "game_actions_sent_prediction_total", "game_actions_sent_confirmed_total",
  "game_actions_dropped_preview_total", "game_actions_dropped_prediction_total",
  "game_actions_dropped_confirmed_total", "game_actions_skipped_preview_total",
  "game_actions_skipped_prediction_total", "game_actions_skipped_confirmed_total",
  "game_actions_skipped_unknown_total", "game_actions_skipped_cheat_total",
  "continuous_items_pending", "lines_queued_max", "guests_known", "guests_known_in_park",
  "arrivals_recorded_total", "boarding_polls_total", "boarders_queued_total",
];
const SESSION_FIELDS = [
  "api_version", "park_name", "scenario_name", "headless", "game_speed", "climate", "loaded_save_id",
  "loaded_save_session_id", "loaded_save_seq_floor", "loaded_save_lines_waiting",
];
const DAY_TICKS = 520;

function startGame(options) {
  return createGame(options).load().start();
}

// Fires `count` day callbacks, one game day apart, after the current tick.
function runDays(game, count) {
  for (let i = 0; i < count; i++) game.day(game.date.ticksElapsed + DAY_TICKS);
}

// seq runs 1..n in arrival order, with event_id derived from it.
function assertContiguous(events) {
  assert.deepEqual(events.map((event) => event.seq), events.map((_, i) => i + 1));
  for (const event of events) assert.equal(event.event_id, `${event.session_id}-${event.seq}`);
}

// session_start is created in main(), before any day callback: seq 1, at main()'s game date and tick.
function assertSessionStartAtMain(event, [year, month, day, ticks]) {
  assert.equal(event.event_type, "session_start");
  assert.equal(event.seq, 1);
  assert.deepEqual(
    [event.game_year, event.game_month, event.game_day, event.game_ticks_elapsed],
    [year, month, day, ticks],
  );
}

function lastStats(game) {
  const stats = game.eventsOfType("plugin_stats");
  return stats[stats.length - 1];
}

test("registers under its frozen name with the shared version", () => {
  const game = startGame();
  assert.equal(game.metadata.name, "openrct2-analytics");
  assert.equal(game.metadata.version, "0.9.0");
  game.socket.accept();
  game.day(1520);
  for (const event of game.received) assert.equal(event.plugin_version, game.metadata.version);
});

test("every event carries the full v1 envelope and nothing else", () => {
  const game = startGame();
  game.socket.accept();
  game.day(1520);
  const [sessionStart, stats, snapshot] = game.received;
  assert.deepEqual(Object.keys(sessionStart).sort(), [...ENVELOPE, ...SESSION_FIELDS].sort());
  assert.deepEqual(Object.keys(stats).sort(), [...ENVELOPE, ...STATS_FIELDS].sort());
  assert.deepEqual(Object.keys(snapshot).sort(), [...ENVELOPE, ...SNAPSHOT_FIELDS].sort());
  // session_start carries the same envelope, stamped when main() ran.
  assert.equal(sessionStart.schema_version, 1);
  assert.match(sessionStart.park_id, PARK_ID);
  assert.match(sessionStart.session_id, SESSION_ID);
  assert.match(sessionStart.emitted_at, ISO_MS);
  assertSessionStartAtMain(sessionStart, [1, 0, 1, 1000]);
  for (const event of [stats, snapshot]) {
    assert.equal(event.schema_version, 1);
    assert.match(event.park_id, PARK_ID);
    assert.match(event.session_id, SESSION_ID);
    assert.match(event.emitted_at, ISO_MS);
    assert.deepEqual(
      [event.game_year, event.game_month, event.game_day, event.game_ticks_elapsed],
      [game.date.year, game.date.month, game.date.day, 1520],
    );
  }
  // Money stays in the game's tenths of a dollar.
  assert.deepEqual(
    SNAPSHOT_FIELDS.map((field) => snapshot[field]),
    [
      game.parkValues.cash, game.parkValues.guests, game.parkValues.rating, game.parkValues.totalAdmissions,
      game.climateValues.current.weather, game.climateValues.current.temperature,
    ],
  );
});

test("outside normal mode the plugin mints no ID and sends nothing", () => {
  for (const mode of ["title", "scenario_editor", "track_designer", "track_manager"]) {
    const game = startGame({ mode });
    assert.equal(game.sockets.length, 0, mode);
    assert.equal(game.dayHooks.length, 0, mode);
    assert.equal(game.intervals.length, 0, mode);
    assert.deepEqual(game.storage.values, {}, mode);
    assert.equal(game.storage.sets, 0, mode);
  }
});

test("a park storage failure makes main() throw before anything connects", () => {
  const storage = createParkStorage();
  storage.get = () => {
    throw new Error("storage unavailable");
  };
  const game = createGame({ storage }).load();
  assert.throws(() => game.start(), /storage unavailable/);
  assert.equal(game.sockets.length, 0);
  assert.equal(game.dayHooks.length, 0);
});

test("a stored park ID that is not a non-empty string is replaced by a minted one", () => {
  for (const stored of [null, "", 42]) {
    const storage = createParkStorage();
    storage.values.park_id = stored;
    const game = startGame({ storage });
    game.socket.accept();
    game.day(1520);
    assert.match(storage.values.park_id, PARK_ID, String(stored));
    assert.equal(storage.sets, 1, String(stored));
    for (const event of game.received) assert.equal(event.park_id, storage.values.park_id);
  }
});

// Leaves a first session with delivered lines, drops, a partial send, a write error and a backlog, so a
// restart that kept any of it would show.
// Its first day callback is a day 1 whose ledger history is too short (the month counter reads 0, as after
// a cheat reset it), so the session also holds one unread month.
function runBusyFirstSession(game) {
  game.date.day = 0;
  runDays(game, 2501); // session_start and 5,002 lines into a 5,000-line queue while disconnected: 3 dropped
  game.socket.accept();
  game.interval();
  assert.equal(game.received.length, 10);
  assert.equal(game.received[0].seq, 1);
  assert.equal(game.eventsOfType("finance_month").length, 0);
  assert.equal(lastStats(game).finance_months_unread_total, 1);
  game.writeBehavior = "partial";
  game.interval();
  game.writeBehavior = "throw";
  game.interval();
  assert.equal(game.malformed.length, 1);
}

const RESTARTS = [
  ["calling main() again in the same context", (game) => game.restartInSameContext()],
  ["loading into a fresh context with the same park storage", (game) => startGame({ storage: game.storage })],
];

for (const [how, restart] of RESTARTS) {
  test(`restart by ${how}: same park ID, new session, fresh state, seq from 1`, () => {
    const first = startGame();
    runBusyFirstSession(first);
    const parkId = first.storage.values.park_id;
    const firstSession = first.received[0].session_id;
    assert.match(parkId, PARK_ID);
    assert.equal(first.received[0].park_id, parkId);

    const second = restart(first);
    const newEvents = second.received.length;
    assert.equal(second.storage.sets, 1, "the park ID is minted once and read back");
    second.socket.accept();
    second.day(second.date.ticksElapsed + DAY_TICKS);
    const events = second.received.slice(newEvents);

    assert.equal(events.length, 3);
    assertContiguous(events);
    assert.equal(events[0].event_type, "session_start");
    for (const event of events) {
      assert.equal(event.park_id, parkId);
      assert.match(event.session_id, SESSION_ID);
      assert.notEqual(event.session_id, firstSession);
    }
    const stats = events[1];
    assert.equal(stats.event_type, "plugin_stats");
    assert.equal(stats.warmup, true);
    assert.equal(stats.lines_dropped_total, 0);
    assert.equal(stats.write_partial_total, 0);
    assert.equal(stats.write_error_total, 0);
    assert.equal(stats.connect_attempts_total, 1);
    assert.equal(stats.queue_length, 1, "only the new session's session_start waits in the queue");
    assert.equal(stats.finance_months_unread_total, 0);
  });
}

test("seq has no gaps through an outage, a reconnect and a bounded flush", () => {
  const game = startGame();
  assert.deepEqual(game.socket.target, { port: 8765, host: "127.0.0.1" });
  assert.deepEqual(game.intervals.map((entry) => entry.delay), [5000]);
  game.socket.accept();
  game.day(1520);
  assert.equal(game.received.length, 3);

  game.socket.fail(); // the listener goes down
  const deadSocket = game.socket;
  runDays(game, 7);
  assert.equal(game.received.length, 3, "flush does nothing while disconnected");
  assert.equal(deadSocket.writes, 3);

  game.interval(); // reconnect: the old socket is destroyed with an argument
  assert.equal(game.sockets.length, 2);
  assert.equal(deadSocket.destroyed, true);
  assert.equal(typeof deadSocket.destroyArgument, "object");
  game.interval(); // no connect callback yet, so it is still disconnected and tries again
  assert.equal(game.sockets.length, 3);
  runDays(game, 1);
  assert.equal(game.socket.writes, 0, "not connected until the connect callback fires");

  game.socket.accept();
  game.sockets[1].close(); // a late close from a replaced socket changes nothing
  assert.equal(game.received.length, 3, "connecting alone sends nothing");
  game.interval();
  assert.equal(game.received.length, 13, "one flush hands off at most 10 lines");
  game.interval();
  assert.equal(game.received.length, 19);

  game.day(game.date.ticksElapsed + DAY_TICKS);
  assert.equal(game.received.length, 21);
  assertContiguous(game.received);
  const stats = lastStats(game);
  assert.equal(stats.connect_attempts_total, 3);
  assert.equal(stats.lines_dropped_total, 0);
  assert.equal(stats.queue_length, 0);
  assertSessionStartAtMain(game.received[0], [1, 0, 1, 1000]);
  // Each day's pair: plugin_stats at seq n, park_snapshot at n + 1, same game tick.
  const dayEvents = game.received.slice(1);
  for (let i = 0; i < dayEvents.length; i += 2) {
    assert.equal(dayEvents[i].event_type, "plugin_stats");
    assert.equal(dayEvents[i + 1].event_type, "park_snapshot");
    assert.equal(dayEvents[i].game_ticks_elapsed, dayEvents[i + 1].game_ticks_elapsed);
  }
});

test("a line queued through an outage keeps its creation-time game date and emitted_at", () => {
  const game = startGame();
  game.socket.fail(); // the listener is down
  game.day(1520);
  const created = [game.date.year, game.date.month, game.date.day, new Date(game.wallMs).toISOString()];
  game.date.year += 1;
  game.date.month = 3;
  game.date.day = 9;
  game.wallMs += 3600000;
  game.interval(); // reconnect
  game.socket.accept();
  game.interval(); // flush
  assert.equal(game.received.length, 3);
  // session_start keeps main()'s date: day 1, before the day callback moved it to day 2.
  const [sessionStart, ...dayEvents] = game.received;
  assertSessionStartAtMain(sessionStart, [1, 0, 1, 1000]);
  assert.equal(sessionStart.emitted_at, created[3]);
  for (const event of dayEvents) {
    assert.deepEqual([event.game_year, event.game_month, event.game_day, event.emitted_at], created);
  }
});

test("late events from a replaced socket change neither the connection state nor delivery", () => {
  const game = startGame();
  game.day(1520); // queued: nothing is connected
  game.interval(); // reconnect: socket 0 is replaced by socket 1
  game.sockets[0].accept(); // a late connect callback from the replaced socket
  game.interval(); // still disconnected, so it reconnects again instead of flushing
  assert.equal(game.sockets.length, 3);
  assert.equal(game.received.length, 0);
  assert.deepEqual(game.logs, []);

  game.socket.accept();
  game.sockets[1].fail(); // a late error and close from a replaced socket
  game.interval(); // still connected, so it flushes
  assert.equal(game.sockets.length, 3);
  assert.equal(game.received.length, 3);
  assertContiguous(game.received);
  assert.deepEqual(game.logs, ["[openrct2-analytics] connected to 127.0.0.1:8765"]);
});

test("reconnect replaces the socket before destroying it, so the old socket's close is ignored", () => {
  const game = createGame();
  game.costs["network.createSocket"] = 3;
  game.load().start(); // tick 1000
  game.socket.accept();
  game.writeBehavior = "throw";
  game.day(1520); // the first write throws: the plugin marks down a socket that is still open
  const old = game.socket;
  game.interval(1600); // reconnect: destroying the open socket raises its close at once
  assert.equal(old.destroyed, true);
  game.socket.accept();
  game.day(2040);
  assertContiguous(game.received);
  const stats = lastStats(game);
  // Day 1, the reconnect and the accept: the close raised inside the reconnect is neither a callback of its
  // own nor time counted twice.
  assert.deepEqual([stats.callbacks, stats.work_ms_total, stats.worst_tick_ms], [3, 3, 3]);
  assert.equal(game.logs.filter((line) => line.includes("disconnected")).length, 1);
});

test("a partial send (write returns true) is counted, never resent; a full send (false) is not counted", () => {
  const game = startGame();
  game.socket.accept();
  game.writeBehavior = "partial"; // the first line handed off, session_start: only its first half is sent
  game.day(1520);
  game.day(2040);
  game.day(2560);
  assert.equal(game.malformed.length, 1, "the cut line runs into the next one");
  assert.deepEqual(game.received.map((event) => event.seq), [3, 4, 5, 6, 7]);
  assert.equal(lastStats(game).write_partial_total, 1);
  assert.equal(lastStats(game).write_error_total, 0);
});

test("seq does not advance when write throws, and the line is sent again", () => {
  const game = startGame();
  game.socket.accept();
  game.day(1520);
  game.writeBehavior = "throw"; // the next write throws once
  game.day(2040);
  assert.equal(game.received.length, 3);
  assert.equal(game.socket.writes, 4, "the socket is marked down after the throw");

  game.interval(); // reconnect
  game.socket.accept();
  game.interval(); // flush the kept line and its pair
  const [stats, snapshot] = game.received.slice(3);
  assert.deepEqual([stats.seq, stats.event_type, stats.game_ticks_elapsed], [4, "plugin_stats", 2040]);
  assert.deepEqual([snapshot.seq, snapshot.event_type], [5, "park_snapshot"]);

  game.day(2560);
  assertContiguous(game.received);
  assert.equal(lastStats(game).write_error_total, 1);
  assert.equal(lastStats(game).connect_attempts_total, 2);
});

test("queue overflow drops the oldest lines and counts every drop", () => {
  const game = startGame();
  runDays(game, 2501); // session_start and 5,002 lines emitted while the listener is down
  game.socket.accept();
  for (let i = 0; i < 500; i++) game.interval();
  assert.equal(game.received.length, 5000);
  assertContiguous(game.received);
  // session_start and day 1 were dropped, so the first line handed off is day 2's plugin_stats, with seq 1.
  assert.deepEqual(
    [game.received[0].event_type, game.received[0].game_ticks_elapsed],
    ["plugin_stats", 1000 + 2 * DAY_TICKS],
  );
  // Day 2,501's stats were built after day 2,500's one drop, with a full queue.
  assert.equal(lastStats(game).lines_dropped_total, 1);
  assert.equal(lastStats(game).queue_length, 5000);

  game.day(game.date.ticksElapsed + DAY_TICKS);
  assert.equal(lastStats(game).lines_dropped_total, 3);
  assert.equal(lastStats(game).queue_length, 0);
  assertContiguous(game.received);
});

test("plugin_stats timing matches the fake clock", () => {
  const game = createGame();
  game.costs["network.createSocket"] = 3;
  game.costs["socket.write"] = 5;
  game.load().start(); // tick 1000: startup, 3 ms
  game.date.ticksElapsed = 1010;
  game.socket.accept(); // 0 ms
  game.day(1520); // day 1: session_start and two day lines written, 15 ms
  game.date.ticksElapsed = 1600;
  game.socket.fail(); // error and close, 0 ms
  // Tick 1700: five callbacks, two of them reconnects at 8 ms each, share one 16 ms tick. The reconnect
  // cost is set so this mid-period tick still beats day 1's 15 ms, which includes session_start's write.
  game.costs["network.createSocket"] = 8;
  game.interval(1700);
  game.socket.fail();
  game.interval(1700);
  game.socket.accept();
  game.costs["park.cash"] = 7;
  game.gameSpeed = 4; // sampled once, at the day callback
  game.day(2040); // day 2: 7 ms reading the park plus two writes, 17 ms
  game.gameSpeed = 1;
  game.interval(2100); // flush with nothing queued, 0 ms
  game.day(2560);

  const stats = game.eventsOfType("plugin_stats");
  const timing = (row) => ({
    start: row.period_start_ticks,
    end: row.period_end_ticks,
    ticks: row.period_ticks,
    work: row.work_ms_total,
    worst: row.worst_tick_ms,
    worstAt: row.worst_tick_at_ticks,
    callbacks: row.callbacks,
    warmup: row.warmup,
  });
  // The first period starts at main() and includes startup; ticks without work add 0 ms to the 520.
  assert.deepEqual(timing(stats[0]), {
    start: 1000, end: 1520, ticks: 520, work: 3, worst: 3, worstAt: 1000, callbacks: 2, warmup: true,
  });
  // Day 1's own 15 ms lands in period 2, not in the period it closed; the mid-period tick 1700 is its worst.
  assert.deepEqual(timing(stats[1]), {
    start: 1520, end: 2040, ticks: 520, work: 31, worst: 16, worstAt: 1700, callbacks: 8, warmup: false,
  });
  // Day 2 was given 17 ms; it appears as the next period's worst tick.
  assert.deepEqual(timing(stats[2]), {
    start: 2040, end: 2560, ticks: 520, work: 17, worst: 17, worstAt: 2040, callbacks: 2, warmup: false,
  });
  assert.deepEqual(stats.map((row) => row.game_speed), [1, 4, 1]);
  for (const row of stats) assert.equal(row.clock, "performance");
});

test("a period with no timed work reports 0 ms at its start tick", () => {
  const game = startGame(); // tick 1000
  game.socket.accept();
  game.day(1000); // the first day callback on main()'s own tick: no bucket has been folded yet
  const stats = lastStats(game);
  assert.deepEqual(
    [stats.period_start_ticks, stats.period_ticks, stats.callbacks, stats.worst_tick_ms, stats.worst_tick_at_ticks],
    [1000, 0, 0, 0, 1000],
  );
});

test("while paused, reconnects on one frozen tick are timed apart and the outage is logged once", () => {
  const game = startGame(); // tick 1000
  game.socket.accept();
  game.socket.fail(); // the listener goes down
  game.costs["network.createSocket"] = 3;
  for (let i = 0; i < 10; i++) {
    game.wallMs += 5000; // the reconnect interval keeps firing while the tick stands still
    game.interval(1100);
    game.socket.fail();
  }
  game.day(1620);
  game.interval(); // reconnect
  game.socket.accept();
  game.interval(); // flush
  const stats = game.eventsOfType("plugin_stats")[0];
  assert.deepEqual([stats.work_ms_total, stats.worst_tick_ms, stats.worst_tick_at_ticks], [30, 3, 1100]);
  assert.deepEqual(game.logs, [
    "[openrct2-analytics] connected to 127.0.0.1:8765",
    "[openrct2-analytics] disconnected: error ECONNREFUSED",
    "[openrct2-analytics] connected to 127.0.0.1:8765",
  ]);
});

test("timing falls back to Date.now() and says so when performance is absent", () => {
  const game = startGame({ withPerformance: false });
  game.socket.accept();
  game.day(1520);
  assert.equal(lastStats(game).clock, "date");
});

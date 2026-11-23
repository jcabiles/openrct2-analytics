// Tests for the session start and the monthly statement, driven through the stand-in game in fake-game.mjs.
// The expected field names are written out here, never derived from the plugin or the stand-in, so a
// misspelled type cannot pass.
import assert from "node:assert/strict";
import { test } from "node:test";

import { createGame, EXPENDITURE_TYPES } from "./fake-game.mjs";

const ENVELOPE = [
  "schema_version", "event_type", "plugin_version", "park_id", "session_id", "game_year", "game_month",
  "game_day", "game_ticks_elapsed", "emitted_at", "seq", "event_id",
];
const SESSION_FIELDS = [
  "api_version", "park_name", "scenario_name", "headless", "game_speed", "climate", "loaded_save_id",
  "loaded_save_session_id", "loaded_save_seq_floor", "loaded_save_lines_waiting",
];
const LEDGER_FIELDS = [
  "ride_construction_tenths", "ride_runningcosts_tenths", "land_purchase_tenths", "landscaping_tenths",
  "park_entrance_tickets_tenths", "park_ride_tickets_tenths", "shop_sales_tenths", "shop_stock_tenths",
  "food_drink_sales_tenths", "food_drink_stock_tenths", "wages_tenths", "marketing_tenths", "research_tenths",
  "interest_tenths",
];
const STATEMENT_FIELDS = [
  "statement_year", "statement_month", ...LEDGER_FIELDS, "cash_tenths", "bank_loan_tenths",
  "new_month_booked_tenths",
];
const DAY_TICKS = 520;

function startGame(options) {
  return createGame(options).load().start();
}

function nextDay(game) {
  game.day(game.date.ticksElapsed + DAY_TICKS);
}

function nextMonth(game, bookedAfterShift) {
  game.nextMonth(game.date.ticksElapsed + DAY_TICKS, bookedAfterShift);
}

function statsAt(game, index) {
  return game.eventsOfType("plugin_stats")[index];
}

test("session_start is the first event, at seq 1, with the game's values", () => {
  const game = startGame();
  game.socket.accept();
  nextDay(game);
  const [first] = game.received;
  assert.deepEqual(Object.keys(first).sort(), [...ENVELOPE, ...SESSION_FIELDS].sort());
  assert.deepEqual([first.event_type, first.seq, first.plugin_version], ["session_start", 1, "0.9.0"]);
  assert.deepEqual(
    [first.game_year, first.game_month, first.game_day, first.game_ticks_elapsed],
    [1, 0, 1, 1000],
    "stamped when main() ran, before the day callback",
  );
  assert.deepEqual(
    SESSION_FIELDS.map((field) => first[field]),
    [110, "Stand-in Park", "Stand-in Scenario", true, 1, "coolAndWet", null, null, null, null],
  );
  assert.equal(game.eventsOfType("session_start").length, 1);
});

test("session_start never sends the scenario's filename", () => {
  const game = startGame();
  game.socket.accept();
  game.interval();
  const line = JSON.stringify(game.received[0]);
  assert.equal(line.includes(game.scenarioValues.filename), false);
  assert.equal(line.includes("stand-in.park"), false);
});

test("headless is true without ui and false with it", () => {
  for (const [withUi, headless] of [[false, true], [true, false]]) {
    const game = startGame({ withUi });
    game.socket.accept();
    game.interval();
    assert.equal(game.received[0].headless, headless, `withUi ${withUi}`);
  }
});

test("session_start reports the game speed at start", () => {
  const game = createGame();
  game.gameSpeed = 3;
  game.load().start();
  game.socket.accept();
  game.interval();
  assert.equal(game.received[0].game_speed, 3);
});

const RESTARTS = [
  ["calling main() again in the same context", (game) => game.restartInSameContext()],
  ["loading into a fresh context with the same park storage", (game) => startGame({ storage: game.storage })],
];

for (const [how, restart] of RESTARTS) {
  test(`restart by ${how}: one session_start per start, at seq 1 of its session`, () => {
    const first = startGame();
    first.socket.accept();
    nextDay(first);
    const second = restart(first);
    second.socket.accept();
    nextDay(second);
    const all = second === first ? first.received : [...first.received, ...second.received];
    const starts = all.filter((event) => event.event_type === "session_start");
    assert.equal(starts.length, 2);
    assert.notEqual(starts[0].session_id, starts[1].session_id);
    for (const start of starts) {
      const session = all.filter((event) => event.session_id === start.session_id);
      assert.equal(session[0], start);
      assert.equal(start.seq, 1);
    }
  });

  test(`restart by ${how}: the unread-month counter starts at 0 in the new session`, () => {
    const first = startGame();
    first.socket.accept();
    first.date.day = 0; // a day 1 with the month counter at 0: the history is too short
    nextDay(first);
    nextDay(first);
    assert.equal(statsAt(first, 1).finance_months_unread_total, 1);
    const second = restart(first);
    const before = second.received.length;
    second.socket.accept();
    nextDay(second);
    const stats = second.received.slice(before).filter((event) => event.event_type === "plugin_stats");
    assert.equal(stats.length, 1);
    assert.equal(stats[0].finance_months_unread_total, 0);
  });
}

test("outside normal mode no session_start is created", () => {
  for (const mode of ["title", "scenario_editor", "track_designer", "track_manager"]) {
    const game = startGame({ mode });
    assert.equal(game.sockets.length, 0, mode);
    assert.equal(game.received.length, 0, mode);
  }
});

test("finance_month is sent only on day-1 callbacks", () => {
  const game = startGame();
  game.socket.accept();
  for (let i = 0; i < 30; i++) nextDay(game);
  assert.equal(game.eventsOfType("finance_month").length, 0);
  nextMonth(game);
  nextDay(game);
  nextDay(game);
  nextMonth(game);
  const statements = game.eventsOfType("finance_month");
  assert.equal(statements.length, 2);
  for (const statement of statements) assert.equal(statement.game_day, 1);
});

test("a statement carries index 1 of every history, cash and loan, under the 14 field names verbatim", () => {
  const game = createGame();
  // Late in month 4 of year 1, four months in: after the month-end the history has 6 entries, so index 1
  // differs from index 0 and from the last entry.
  Object.assign(game.date, { month: 4, day: 31, monthsElapsed: 4 });
  game.load().start();
  game.socket.accept();
  // The month being closed: index 0 now, index 1 after the month-end. Every line differs, and
  // ride_construction is positive, as a demolition refund can make it.
  const booked = EXPENDITURE_TYPES.map((_, i) => (i === 0 ? 4321 : -(i + 1) * 111));
  EXPENDITURE_TYPES.forEach((type, i) => {
    game.expenditures[type][0] = booked[i];
  });
  game.parkValues.cash = 987650;
  game.parkValues.bankLoan = 300000;
  nextMonth(game);
  const [statement] = game.eventsOfType("finance_month");
  assert.deepEqual(Object.keys(statement).sort(), [...ENVELOPE, ...STATEMENT_FIELDS].sort());
  assert.deepEqual(LEDGER_FIELDS.map((field) => statement[field]), booked);
  assert.deepEqual([statement.cash_tenths, statement.bank_loan_tenths], [987650, 300000]);
});

test("the statement covers the month before the envelope date, wrapping month 0 to month 7 of last year", () => {
  const game = startGame();
  game.socket.accept();
  const closed = [];
  for (let i = 0; i < 9; i++) {
    closed.push([game.date.year, game.date.month]);
    nextMonth(game);
  }
  const statements = game.eventsOfType("finance_month");
  assert.deepEqual(statements.map((s) => [s.statement_year, s.statement_month]), closed);
  // Month 7 of year 1 closes on day 1 of month 0 of year 2.
  const wrap = statements[7];
  assert.deepEqual([wrap.game_year, wrap.game_month, wrap.game_day], [2, 0, 1]);
  assert.deepEqual([wrap.statement_year, wrap.statement_month], [1, 7]);
});

test("on day 1, plugin_stats, park_snapshot and finance_month take seq n, n + 1, n + 2 on one tick", () => {
  const game = startGame();
  game.socket.accept();
  nextDay(game);
  nextMonth(game);
  const dayOne = game.received.slice(-3);
  assert.deepEqual(dayOne.map((event) => event.event_type), ["plugin_stats", "park_snapshot", "finance_month"]);
  const n = dayOne[0].seq;
  assert.deepEqual(dayOne.map((event) => event.seq), [n, n + 1, n + 2]);
  assert.equal(n, 4);
  for (const event of dayOne) assert.equal(event.game_ticks_elapsed, game.date.ticksElapsed);
  // Read in the same callback, so the statement's cash equals the snapshot's.
  assert.equal(dayOne[2].cash_tenths, dayOne[1].cash_tenths);
});

test("a session whose first day callback is day 1 sends that month's statement", () => {
  const game = createGame();
  // A save loaded on the last day of month 4 of year 1, four months into the park.
  Object.assign(game.date, { month: 4, day: 31, monthsElapsed: 4 });
  game.load().start();
  game.socket.accept();
  nextMonth(game);
  const statements = game.eventsOfType("finance_month");
  assert.equal(statements.length, 1);
  assert.deepEqual([statements[0].statement_year, statements[0].statement_month], [1, 4]);
});

test("a save loaded mid-month with a readable history sends no statement until the next month's day 1", () => {
  const game = createGame();
  Object.assign(game.date, { month: 3, day: 14, monthsElapsed: 3 });
  game.load().start();
  game.socket.accept();
  nextDay(game);
  nextDay(game);
  assert.equal(game.eventsOfType("finance_month").length, 0);
  assert.equal(statsAt(game, 1).finance_months_unread_total, 0);
  nextMonth(game);
  const statements = game.eventsOfType("finance_month");
  assert.equal(statements.length, 1);
  assert.deepEqual([statements[0].statement_year, statements[0].statement_month], [1, 3]);
});

test("a short history sends no statement, does not throw, and counts one unread month", () => {
  const game = startGame();
  game.socket.accept();
  game.date.day = 0; // the next callback is a day 1 while the month counter reads 0
  assert.doesNotThrow(() => nextDay(game));
  assert.equal(game.eventsOfType("finance_month").length, 0);
  // The counter is emitted before that day's statement is tried, so the increment shows the next day.
  assert.equal(statsAt(game, 0).finance_months_unread_total, 0);
  nextDay(game);
  assert.equal(statsAt(game, 1).finance_months_unread_total, 1);
  // A later month with a full history is read, and the count stays.
  nextMonth(game);
  nextDay(game);
  assert.equal(game.eventsOfType("finance_month").length, 1);
  assert.equal(statsAt(game, 3).finance_months_unread_total, 1);
});

test("successive monthly statements reuse one payload while each queued finance_month keeps its own month", () => {
  const game = createGame().load();
  const statements = [];
  const createFinanceReader = game.context.createFinanceReader;
  game.context.createFinanceReader = () => {
    const reader = createFinanceReader();
    const statementForToday = reader.statementForToday;
    reader.statementForToday = () => {
      const statement = statementForToday();
      if (statement !== null) statements.push(statement);
      return statement;
    };
    return reader;
  };
  game.start();
  nextMonth(game, { park_ride_tickets: 40 }); // disconnected: the first statement waits in the queue
  game.parkValues.cash = 555;
  nextMonth(game, { shop_stock: -7, wages: 3 }); // the second fill of the same payload
  assert.equal(statements.length, 2);
  assert.equal(statements[0], statements[1]);
  game.interval(); // reconnect
  game.socket.accept();
  game.interval(); // flush: the first line was queued before the second fill
  const lines = game.eventsOfType("finance_month");
  // Cash includes what each month-end booked. Month 0 closes with wages from the starting history; month 1
  // with the 0 the month-end booked.
  assert.deepEqual(
    lines.map((line) => [line.statement_year, line.statement_month, line.cash_tenths, line.wages_tenths]),
    [[1, 0, 123490, -11000], [1, 1, 551, 0]],
  );
  assert.deepEqual(lines.map((line) => line.new_month_booked_tenths), [40, -4]);
});

test("new_month_booked_tenths is the sum of index 0 of the 14 histories after the month shift", () => {
  const game = startGame();
  game.socket.accept();
  const booked = Object.fromEntries(
    EXPENDITURE_TYPES.map((type, index) => [type, (index % 2 === 0 ? -1 : 1) * 2 ** index]),
  );
  game.parkValues.cash = 987650;
  nextMonth(game, booked);
  const [statement] = game.eventsOfType("finance_month");
  assert.equal(statement.new_month_booked_tenths, 5461);
  assert.equal(statement.cash_tenths, 993111);
});

test("a month with nothing booked after the shift sends new_month_booked_tenths of 0", () => {
  const game = startGame();
  game.socket.accept();
  nextMonth(game);
  const [statement] = game.eventsOfType("finance_month");
  assert.equal(statement.new_month_booked_tenths, 0);
});

test("(cash - loan) - booked moves between two statements by exactly the later statement's 14 lines", () => {
  const game = startGame();
  game.socket.accept();
  nextMonth(game, { park_ride_tickets: 80, food_drink_sales: 25, shop_stock: -30 });
  // More money arrives during the month; the stand-in's cash follows the ledger.
  game.expenditures.wages[0] -= 400;
  game.parkValues.cash -= 400;
  nextMonth(game, { park_ride_tickets: 10, marketing: -60 });
  const [first, second] = game.eventsOfType("finance_month");
  const open = (s) => s.cash_tenths - s.bank_loan_tenths - s.new_month_booked_tenths;
  const lines = LEDGER_FIELDS.reduce((sum, field) => sum + second[field], 0);
  assert.equal(second.new_month_booked_tenths, -50);
  assert.equal(lines, 75 - 400);
  assert.equal(open(second) - open(first), lines);
});

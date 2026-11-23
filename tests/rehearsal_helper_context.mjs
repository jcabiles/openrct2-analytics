// Runs the rehearsal speed helper under Node and prints what it called, as JSON.
// Usage: node tests/rehearsal_helper_context.mjs <helper file> [later-year | first-counted-day | target-from-30-october-save | target-march-first | target-31-october-save]
// It imports plugin/test/fake-game.mjs and uses that stand-in's globals (date, hooks, subscribe).
// fake-game.mjs cannot load an arbitrary plugin file (load() reads only the compiled analytics
// plugin) and has no executeAction or saveGame, so this file evaluates the helper in its own
// node:vm context built from the stand-in's globals and adds those two calls, recording them.
// The "pausetoggle" action pauses as in the game: while paused, no tick or day callback runs.
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { createGame } from "../plugin/test/fake-game.mjs";

const helperFile = process.argv[2];
const scenario = process.argv[3] ?? "later-year";
const game = createGame();
const calls = [];
const days = [];
let now = 0;
let paused = false;

const globals = game.globals();
globals.context.executeAction = (action, args) => {
  calls.push({ api: "executeAction", action, args, at: now });
  if (action === "pausetoggle") paused = !paused;
};
globals.context.saveGame = (options) => calls.push({ api: "saveGame", options, at: now });
vm.runInContext(readFileSync(helperFile, "utf8"), vm.createContext(globals), { filename: helperFile });
game.metadata.main();

function tick(count) {
  for (let i = 0; i < count; i += 1) {
    if (paused) return;
    now += 1;
    game.tick(1);
  }
}

function day(month, dayOfMonth) {
  if (paused) return;
  game.date.month = month;
  game.date.day = dayOfMonth;
  days.push([month, dayOfMonth]);
  for (const hook of game.dayHooks) hook();
}

const checkpoints = {};
const mark = (name) => {
  checkpoints[name] = calls.length;
};

tick(1);
mark("afterFirstTick");
tick(4);
// The first day() call below is the first day callback after the load, so the saved date is the day before.
if (scenario === "target-from-30-october-save") {
  day(7, 31); // the session's first day callback, on 31 October of game year 1 (a 30 October save)
  tick(300);
  game.date.year = 2; // the night passes; the next 1 March is in game year 2
} else if (scenario === "target-31-october-save") {
  game.date.year = 2; // the target year
  day(0, 1); // the session's first day callback, on 1 March of the target year (a 31 October save)
} else if (scenario === "target-march-first") {
  day(0, 1); // the session's first day callback, on 1 March of game year 1: not the target year
  tick(500);
  mark("afterFirstDay");
  game.date.year = 2;
} else if (scenario === "first-counted-day") {
  day(7, 31); // the session's first day callback, on 31 October: ignored
  tick(300);
} else {
  day(0, 1); // the session's first day callback, on 1 March: ignored
  tick(500);
  mark("afterFirstDay");
  day(3, 1); // a later day that is not 1 March
  tick(300);
  mark("afterOtherDay");
  day(0, 2); // a March day that is not the 1st: does not arm
  tick(300);
  mark("afterMarchSecond");
}
if (scenario !== "target-31-october-save") day(0, 1); // the next 1 March: arms
const armedAt = now;
tick(199);
mark("before200");
tick(1);
mark("at200");
tick(300);
day(0, 2); // the days after the save: never played once the helper has paused the game
tick(300);
day(0, 3);
tick(300);

console.log(
  JSON.stringify({
    hooks: { day: game.dayHooks.length, tick: game.tickHooks.length },
    armedAt,
    checkpoints,
    calls,
    days,
    paused,
  }),
);

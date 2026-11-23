"""The rehearsal capture's speed helper plugin: its text and its rendering.

The helper is written only into each rehearsal run's own plugin folder, beside the built
plugin. It stays an embedded string, as ``bench_setup.SAVE_HELPER`` does, so nothing is
added under ``plugin/``; ``tests/rehearsal_helper_context.mjs`` runs it under Node.
"""

from __future__ import annotations

import json

HELPER_FILE = "openrct2-analytics-rehearsal-helper.js"

# ES5 only (no let, const, arrow functions or template strings): the game's plugin engine
# runs this text as is. In the game's date, month 0 is March.
REHEARSAL_HELPER = """// Rehearsal speed helper, written only into a rehearsal run's plugin folder.
// It sets game speed on its first tick, arms on a 1 March, saves once SAVE_DELAY_TICKS ticks
// after that and then pauses the game, so no day after the save is played before the harness
// stops the game. Without a TARGET_YEAR line it ignores the session's first day callback and
// arms on a later 1 March; with one it arms only on 1 March of that game year.
var SAVE_FILENAME = __SAVE_FILENAME__;
__TARGET_YEAR_LINE__var GAME_SPEED = 8;
var SAVE_DELAY_TICKS = 200;
var MARCH = 0;
var HAS_TARGET = typeof TARGET_YEAR !== "undefined";

function main() {
  var ticks = 0;
  var speedSet = false;
  var firstDayIgnored = false;
  var armedAtTick = -1;
  var saved = false;

  context.subscribe("interval.tick", function () {
    ticks += 1;
    if (!speedSet) {
      speedSet = true;
      context.executeAction("gamesetspeed", { speed: GAME_SPEED });
    }
    if (armedAtTick >= 0 && !saved && ticks - armedAtTick >= SAVE_DELAY_TICKS) {
      saved = true;
      context.saveGame({ filename: SAVE_FILENAME });
      // context.paused is read-only on a headless host, so the pause goes through the action.
      context.executeAction("pausetoggle", {});
    }
  });

  context.subscribe("interval.day", function () {
    if (!HAS_TARGET && !firstDayIgnored) {
      firstDayIgnored = true;
      return;
    }
    if (HAS_TARGET && date.year !== TARGET_YEAR) {
      return;
    }
    if (armedAtTick < 0 && date.month === MARCH && date.day === 1) {
      armedAtTick = ticks;
    }
  });
}

registerPlugin({
  name: "openrct2-analytics-rehearsal-helper",
  version: "0.1.0",
  authors: ["John Cabiles"],
  type: "local",
  licence: "MIT",
  targetApiVersion: 122,
  main: main
});
"""


def rehearsal_helper(filename: str, target_year: int | None = None) -> str:
    """Return the helper's plugin text, saving as ``filename`` (the stem, without ``.park``).

    With ``target_year`` (a game year), the text holds one ``var TARGET_YEAR = <year>;`` line
    and the helper arms only on 1 March of that year; without it, the helper keeps its rule of
    ignoring the first day callback and arming on a later 1 March.
    """
    target_line = "" if target_year is None else f"var TARGET_YEAR = {int(target_year)};\n"
    return REHEARSAL_HELPER.replace("__SAVE_FILENAME__", json.dumps(filename)).replace(
        "__TARGET_YEAR_LINE__", target_line
    )

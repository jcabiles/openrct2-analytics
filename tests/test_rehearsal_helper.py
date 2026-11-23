"""The rehearsal speed helper: its text, the config line it needs, and its behavior under Node."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from openrct2_analytics.ingest.bench_setup import AUTOSAVE_NEVER, config_ini
from openrct2_analytics.ingest.rehearsal_helper import rehearsal_helper

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTEXT_SCRIPT = REPO_ROOT / "tests" / "rehearsal_helper_context.mjs"
SAVE_NAME = "rehearsal-step-3"
GAME_PATH = Path("/game/path")


def run_helper(
    tmp_path: Path, save_name: str = SAVE_NAME, scenario: str = "later-year"
) -> dict[str, Any]:
    node = shutil.which("node")
    assert node is not None, "node is required to run the helper test"
    helper = tmp_path / "helper.js"
    helper.write_text(rehearsal_helper(save_name), encoding="utf-8")
    done = subprocess.run(
        [node, str(CONTEXT_SCRIPT), str(helper), scenario],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert done.returncode == 0, done.stderr
    result: dict[str, Any] = json.loads(done.stdout)
    return result


def run_target_helper(tmp_path: Path, scenario: str, target_year: int) -> dict[str, Any]:
    # Kept apart from run_helper so the no-target tests stay byte-for-byte as they were.
    node = shutil.which("node")
    assert node is not None, "node is required to run the helper test"
    helper = tmp_path / "helper.js"
    helper.write_text(rehearsal_helper(SAVE_NAME, target_year), encoding="utf-8")
    done = subprocess.run(
        [node, str(CONTEXT_SCRIPT), str(helper), scenario],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert done.returncode == 0, done.stderr
    result: dict[str, Any] = json.loads(done.stdout)
    return result


def test_text_holds_token_speed_delay_and_no_es2015_syntax() -> None:
    text = rehearsal_helper(SAVE_NAME)
    assert f'var SAVE_FILENAME = "{SAVE_NAME}";' in text
    assert "var GAME_SPEED = 8;" in text
    assert "var SAVE_DELAY_TICKS = 200;" in text
    assert "__SAVE_FILENAME__" not in text
    assert not re.search(r"\b(let|const)\b", text)
    assert "=>" not in text
    assert "`" not in text


def test_config_ini_adds_exactly_one_line_under_general() -> None:
    default = config_ini(GAME_PATH, AUTOSAVE_NEVER)
    with_tools = config_ini(GAME_PATH, AUTOSAVE_NEVER, debugging_tools=True)
    assert default == config_ini(GAME_PATH, AUTOSAVE_NEVER, debugging_tools=False)
    assert "debugging_tools" not in default
    default_lines = default.splitlines()
    tools_lines = with_tools.splitlines()
    assert len(tools_lines) == len(default_lines) + 1
    assert [line for line in tools_lines if line not in default_lines] == ["debugging_tools = true"]
    general_end = tools_lines.index("") if "" in tools_lines else len(tools_lines)
    assert tools_lines.index("debugging_tools = true") < general_end
    assert tools_lines[0] == "[general]"


def test_speed_is_set_once_on_the_first_tick(tmp_path: Path) -> None:
    result = run_helper(tmp_path)
    assert result["hooks"] == {"day": 1, "tick": 1}
    speed_calls = [c for c in result["calls"] if c.get("action") == "gamesetspeed"]
    assert speed_calls == [
        {"api": "executeAction", "action": "gamesetspeed", "args": {"speed": 8}, "at": 1}
    ]
    assert result["checkpoints"]["afterFirstTick"] == 1


def test_first_day_callback_is_ignored_even_on_march_first(tmp_path: Path) -> None:
    result = run_helper(tmp_path)
    assert result["checkpoints"]["afterFirstDay"] == 1
    assert result["checkpoints"]["afterOtherDay"] == 1


def test_a_march_day_that_is_not_the_first_does_not_arm(tmp_path: Path) -> None:
    result = run_helper(tmp_path)
    assert result["checkpoints"]["afterMarchSecond"] == 1


def test_save_name_with_quote_and_backslash_is_saved_exactly(tmp_path: Path) -> None:
    name = 'a"b\\c'
    result = run_helper(tmp_path, name)
    saves = [c for c in result["calls"] if c["api"] == "saveGame"]
    assert [c["options"]["filename"] for c in saves] == [name]


def test_one_save_200_ticks_after_the_next_march_first(tmp_path: Path) -> None:
    result = run_helper(tmp_path)
    assert result["checkpoints"]["before200"] == 1
    assert result["checkpoints"]["at200"] == 3  # the save, then the pause
    saves = [c for c in result["calls"] if c["api"] == "saveGame"]
    assert saves == [
        {"api": "saveGame", "options": {"filename": SAVE_NAME}, "at": result["armedAt"] + 200}
    ]


def test_nothing_else_is_called(tmp_path: Path) -> None:
    result = run_helper(tmp_path)
    assert [c["api"] for c in result["calls"]] == ["executeAction", "saveGame", "executeAction"]


# Spec R2: the run stops on 1 March, "before any day of the next year is played, and saves there".
# The context arms at tick 1105 (1 + 4 + 500 + 300 + 300) and offers 2 and 3 March after the save.
def test_the_game_is_paused_on_the_save_tick_right_after_the_save(tmp_path: Path) -> None:
    result = run_helper(tmp_path)
    assert result["calls"] == [
        {"api": "executeAction", "action": "gamesetspeed", "args": {"speed": 8}, "at": 1},
        {"api": "saveGame", "options": {"filename": SAVE_NAME}, "at": 1305},
        {"api": "executeAction", "action": "pausetoggle", "args": {}, "at": 1305},
    ]
    assert result["paused"] is True


def test_no_day_after_the_march_first_save_is_played(tmp_path: Path) -> None:
    result = run_helper(tmp_path)
    assert result["days"] == [[0, 1], [3, 1], [0, 2], [0, 1]]


def test_days_keep_advancing_while_the_save_has_not_happened(tmp_path: Path) -> None:
    result = run_helper(tmp_path)
    speed = {"api": "executeAction", "action": "gamesetspeed", "args": {"speed": 8}, "at": 1}
    assert result["calls"][: result["checkpoints"]["before200"]] == [speed]
    assert result["days"][:3] == [[0, 1], [3, 1], [0, 2]]


# Edge case: 1 March is the first day callback the helper counts (the one after the ignored
# first callback, here 31 October). It arms at tick 305 (1 + 4 + 300).
def test_a_save_on_the_first_counted_day_also_stops_the_next_day(tmp_path: Path) -> None:
    result = run_helper(tmp_path, scenario="first-counted-day")
    assert result["days"] == [[7, 31], [0, 1]]
    assert result["calls"] == [
        {"api": "executeAction", "action": "gamesetspeed", "args": {"speed": 8}, "at": 1},
        {"api": "saveGame", "options": {"filename": SAVE_NAME}, "at": 505},
        {"api": "executeAction", "action": "pausetoggle", "args": {}, "at": 505},
    ]


# With a target year (game year 2), the helper arms only on 1 March of that year. The context
# arms at tick 305 (1 + 4 + 300) after 31 October, and at tick 505 (1 + 4 + 500) in the
# march-first scenario, whose first day callback is 1 March of game year 1.
def test_a_target_year_is_rendered_as_one_plain_line() -> None:
    text = rehearsal_helper(SAVE_NAME, 2)
    assert text.count("var TARGET_YEAR = 2;") == 1
    assert re.search(r"TARGET_YEAR = (\d+);", text) is not None
    assert not re.search(r"\b(let|const)\b", text)
    assert "=>" not in text
    assert "`" not in text


def test_no_target_year_leaves_no_target_line() -> None:
    assert "var TARGET_YEAR" not in rehearsal_helper(SAVE_NAME)
    assert "var TARGET_YEAR" not in rehearsal_helper(SAVE_NAME, None)


def test_with_a_target_year_a_start_on_31_october_arms_on_the_next_1_march(tmp_path: Path) -> None:
    result = run_target_helper(tmp_path, "target-from-30-october-save", 2)
    assert result["days"] == [[7, 31], [0, 1]]
    assert result["armedAt"] == 305
    assert result["calls"] == [
        {"api": "executeAction", "action": "gamesetspeed", "args": {"speed": 8}, "at": 1},
        {"api": "saveGame", "options": {"filename": SAVE_NAME}, "at": 505},
        {"api": "executeAction", "action": "pausetoggle", "args": {}, "at": 505},
    ]
    assert result["paused"] is True


def test_with_a_target_year_a_31_october_source_arms_on_its_first_day_callback(
    tmp_path: Path,
) -> None:
    result = run_target_helper(tmp_path, "target-31-october-save", 2)
    assert result["days"] == [[0, 1]]
    assert result["armedAt"] == 5
    assert result["calls"] == [
        {"api": "executeAction", "action": "gamesetspeed", "args": {"speed": 8}, "at": 1},
        {"api": "saveGame", "options": {"filename": SAVE_NAME}, "at": 205},
        {"api": "executeAction", "action": "pausetoggle", "args": {}, "at": 205},
    ]
    assert result["paused"] is True


def test_with_a_target_year_1_march_of_the_source_year_does_not_arm(tmp_path: Path) -> None:
    result = run_target_helper(tmp_path, "target-march-first", 2)
    assert result["checkpoints"]["afterFirstDay"] == 1  # only the speed call; no save yet
    assert result["days"] == [[0, 1], [0, 1]]
    assert result["armedAt"] == 505
    assert result["calls"] == [
        {"api": "executeAction", "action": "gamesetspeed", "args": {"speed": 8}, "at": 1},
        {"api": "saveGame", "options": {"filename": SAVE_NAME}, "at": 705},
        {"api": "executeAction", "action": "pausetoggle", "args": {}, "at": 705},
    ]


def test_with_a_target_year_no_day_is_played_after_the_save(tmp_path: Path) -> None:
    result = run_target_helper(tmp_path, "target-from-30-october-save", 2)
    assert result["days"][-1] == [0, 1]  # 2 and 3 March are offered but never played
    assert [c["action"] for c in result["calls"] if c["api"] == "executeAction"] == [
        "gamesetspeed",
        "pausetoggle",
    ]

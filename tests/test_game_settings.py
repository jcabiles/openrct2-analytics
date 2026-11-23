"""Game settings are found from the environment, then local/game-settings.env, then defaults.

Every test builds a stand-in OpenRCT2 folder under ``tmp_path`` and points the settings file at
a path there; nothing reads the real home folder, the real settings file or the real game.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path

import pytest

from openrct2_analytics import config
from openrct2_analytics.ingest import bench_setup
from openrct2_analytics.ingest.bench_setup import load_settings
from openrct2_analytics.ingest.capture import Refused
from openrct2_analytics.ingest.game_settings import read_settings_file

NAMES = ("OPENRCT2_BINARY", "OPENRCT2_BENCH_PARK", "OPENRCT2_GAME_PATH")

PARK_REFUSAL = (
    "OPENRCT2_BENCH_PARK is not set. Add a line OPENRCT2_BENCH_PARK=<path to the benchmark "
    ".park file> to local/game-settings.env, or export it. Nothing was written."
)
GAME_PATH_REFUSAL = (
    "OPENRCT2_GAME_PATH is not set and was not found in OpenRCT2's own settings. Add a line "
    "OPENRCT2_GAME_PATH=<path to the RollerCoaster Tycoon 2 folder> to local/game-settings.env, "
    "or export it. Nothing was written."
)
BINARY_REFUSAL = (
    "OPENRCT2_BINARY is not set. Add a line OPENRCT2_BINARY=<path to the OpenRCT2 executable> "
    "to local/game-settings.env, or export it. Nothing was written."
)


COMMENT_REFUSAL_TAIL = (
    "put comments on their own line, or put the value in quotes if the path really contains "
    "a space and a #. Nothing was written."
)


class World:
    """A stand-in OpenRCT2 folder, game folders, a binary and a park, all under one folder."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = root
        self.monkeypatch = monkeypatch
        self.user_dir = root / "user"
        self.user_dir.mkdir()
        self.env_game = root / "rct2-env"
        self.file_game = root / "rct2-file"
        self.ini_game = root / "rct2-ini"
        for folder in (self.env_game, self.file_game, self.ini_game):
            folder.mkdir()
        self.env_binary = root / "bin-env"
        self.file_binary = root / "bin-file"
        for binary in (self.env_binary, self.file_binary):
            binary.write_text("#!/bin/sh\n", encoding="utf-8")
            binary.chmod(0o755)
        self.park = root / "park.park"
        self.park.write_bytes(b"park")
        self.file_park = root / "file.park"
        self.file_park.write_bytes(b"park")
        self.settings_file = root / "game-settings.env"
        monkeypatch.setattr(bench_setup, "SETTINGS_FILE", self.settings_file)
        monkeypatch.setenv("HOME", str(root))
        monkeypatch.setenv("OPENRCT2_USER_DIR", str(self.user_dir))
        monkeypatch.setenv("OPENRCT2_BENCH_DIR", str(root / "bench"))
        for name in NAMES:
            monkeypatch.delenv(name, raising=False)

    def export(self, **values: Path) -> None:
        for name, value in values.items():
            self.monkeypatch.setenv(name, str(value))

    def write_file(self, *lines: str) -> None:
        self.settings_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_ini(self, text: str) -> None:
        (self.user_dir / "config.ini").write_text(text, encoding="utf-8")

    def export_all_but(self, *skipped: str) -> None:
        """Export a complete valid environment, minus the named settings."""
        values = {
            "OPENRCT2_BINARY": self.env_binary,
            "OPENRCT2_BENCH_PARK": self.park,
            "OPENRCT2_GAME_PATH": self.env_game,
        }
        self.export(**{k: v for k, v in values.items() if k not in skipped})


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return World(tmp_path, monkeypatch)


def test_an_exported_game_path_beats_the_settings_file(world: World) -> None:
    world.export_all_but()
    world.write_file(f"OPENRCT2_GAME_PATH={world.file_game}")

    assert load_settings(platform.system()).game_path == world.env_game


def test_the_settings_file_game_path_is_used_when_nothing_is_exported(world: World) -> None:
    world.export_all_but("OPENRCT2_GAME_PATH")
    world.write_file(f"OPENRCT2_GAME_PATH={world.file_game}")

    assert load_settings(platform.system()).game_path == world.file_game


def test_the_settings_file_game_path_beats_the_openrct2_config_ini(world: World) -> None:
    world.export_all_but("OPENRCT2_GAME_PATH")
    world.write_file(f"OPENRCT2_GAME_PATH={world.file_game}")
    world.write_ini(f"[general]\ngame_path = {world.ini_game}\n")

    assert load_settings(platform.system()).game_path == world.file_game


def test_the_openrct2_config_ini_game_path_is_used_when_env_and_file_are_silent(
    world: World,
) -> None:
    world.export_all_but("OPENRCT2_GAME_PATH")
    world.write_ini(f'[general]\ngame_path = "{world.ini_game}"\n')

    assert load_settings(platform.system()).game_path == world.ini_game


def test_an_exported_game_path_beats_the_openrct2_config_ini(world: World) -> None:
    world.export_all_but()
    world.write_ini(f"[general]\ngame_path = {world.ini_game}\n")

    assert load_settings(platform.system()).game_path == world.env_game


def test_a_missing_config_ini_refuses_naming_the_file_and_openrct2_settings(world: World) -> None:
    world.export_all_but("OPENRCT2_GAME_PATH")

    with pytest.raises(Refused) as caught:
        load_settings(platform.system())

    assert str(caught.value) == GAME_PATH_REFUSAL


def test_a_config_ini_without_the_game_path_key_refuses(world: World) -> None:
    world.export_all_but("OPENRCT2_GAME_PATH")
    world.write_ini("[general]\nlanguage = en-GB\n")

    with pytest.raises(Refused) as caught:
        load_settings(platform.system())

    assert str(caught.value) == GAME_PATH_REFUSAL


def test_a_config_ini_game_path_that_is_not_a_folder_refuses(world: World) -> None:
    world.export_all_but("OPENRCT2_GAME_PATH")
    world.write_ini(f"[general]\ngame_path = {world.root / 'no-such-folder'}\n")

    with pytest.raises(Refused) as caught:
        load_settings(platform.system())

    assert str(caught.value) == GAME_PATH_REFUSAL


def test_a_game_path_only_under_default_in_config_ini_is_ignored(world: World) -> None:
    world.export_all_but("OPENRCT2_GAME_PATH")
    world.write_ini(f"[DEFAULT]\ngame_path = {world.ini_game}\n[general]\nlanguage = en-GB\n")

    with pytest.raises(Refused) as caught:
        load_settings(platform.system())

    assert str(caught.value) == GAME_PATH_REFUSAL


def test_an_exported_park_beats_the_settings_file(world: World) -> None:
    world.export_all_but()
    world.write_file(f"OPENRCT2_BENCH_PARK={world.file_park}")

    assert load_settings(platform.system()).park == world.park


def test_the_settings_file_park_is_used_when_nothing_is_exported(world: World) -> None:
    world.export_all_but("OPENRCT2_BENCH_PARK")
    world.write_file(f"OPENRCT2_BENCH_PARK={world.file_park}")

    assert load_settings(platform.system()).park == world.file_park


def test_a_bench_park_found_nowhere_refuses_with_the_fix(world: World) -> None:
    world.export_all_but("OPENRCT2_BENCH_PARK")

    with pytest.raises(Refused) as caught:
        load_settings(platform.system())

    assert str(caught.value) == PARK_REFUSAL


def test_an_exported_binary_beats_the_settings_file(world: World) -> None:
    world.export_all_but()
    world.write_file(f"OPENRCT2_BINARY={world.file_binary}")

    assert load_settings(platform.system()).binary == world.env_binary


def test_the_settings_file_binary_beats_the_automatic_default(world: World) -> None:
    world.export_all_but("OPENRCT2_BINARY")
    world.write_file(f"OPENRCT2_BINARY={world.file_binary}")

    assert load_settings(platform.system()).binary == world.file_binary


def test_a_binary_found_nowhere_refuses_where_no_default_exists(world: World) -> None:
    world.export_all_but("OPENRCT2_BINARY")
    world.monkeypatch.setattr(config, "DEFAULT_BINARIES", {})

    with pytest.raises(Refused) as caught:
        load_settings("Linux")

    assert str(caught.value) == BINARY_REFUSAL


def test_an_unknown_key_in_the_settings_file_is_refused_with_file_and_line(world: World) -> None:
    world.export_all_but()
    world.write_file("# comment", f"OPENRCT2_GAME_PATH={world.file_game}", "SOMETHING_ELSE=1")

    with pytest.raises(Refused) as caught:
        load_settings(platform.system())

    assert str(caught.value) == (
        "local/game-settings.env line 3: SOMETHING_ELSE is not accepted here. Only "
        "OPENRCT2_BINARY, OPENRCT2_GAME_PATH, OPENRCT2_BENCH_PARK are read from this file; "
        "data-set choices such as DATA_SET, PARKS and START_YEAR stay on the command line. "
        "Nothing was written."
    )


@pytest.mark.parametrize(("key", "line"), [("DATA_SET", 1), ("PARKS", 1), ("START_YEAR", 1)])
def test_a_data_set_choice_in_the_settings_file_is_refused(
    world: World, key: str, line: int
) -> None:
    world.export_all_but()
    world.write_file(f"{key}=company")

    with pytest.raises(Refused) as caught:
        load_settings(platform.system())

    assert str(caught.value).startswith(
        f"local/game-settings.env line {line}: {key} is not accepted"
    )
    assert "stay on the command line" in str(caught.value)


def test_a_line_without_an_equals_sign_is_refused_with_its_line(world: World) -> None:
    world.export_all_but()
    world.write_file("", "OPENRCT2_BENCH_PARK")

    with pytest.raises(Refused) as caught:
        load_settings(platform.system())

    assert (
        str(caught.value)
        == "local/game-settings.env line 2: expected KEY=value. Nothing was written."
    )


def test_a_leading_tilde_slash_in_the_settings_file_is_expanded(world: World) -> None:
    world.export_all_but("OPENRCT2_GAME_PATH")
    world.write_file("OPENRCT2_GAME_PATH=~/rct2-file")

    assert load_settings(platform.system()).game_path == world.root / "rct2-file"


def test_comments_and_blank_lines_in_the_settings_file_are_ignored(world: World) -> None:
    world.export_all_but("OPENRCT2_GAME_PATH")
    world.write_file(
        "# the game folder",
        "",
        f"  OPENRCT2_GAME_PATH = {world.file_game}  ",
        "   ",
        "# end",
    )

    assert load_settings(platform.system()).game_path == world.file_game


def test_a_missing_settings_file_is_fine(world: World) -> None:
    world.export_all_but()

    assert not world.settings_file.exists()
    assert load_settings(platform.system()).park == world.park


def test_every_test_starts_off_the_real_settings_file_and_player_folder(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    base = tmp_path_factory.getbasetemp()
    user_dir = Path(os.environ["OPENRCT2_USER_DIR"])

    assert bench_setup.SETTINGS_FILE.parent.parent == base
    assert bench_setup.SETTINGS_FILE.parent.name.startswith("isolated")
    assert bench_setup.SETTINGS_FILE.parent != tmp_path
    assert not bench_setup.SETTINGS_FILE.exists()
    assert user_dir.parent == bench_setup.SETTINGS_FILE.parent
    assert list(user_dir.iterdir()) == []


def test_an_empty_value_in_the_settings_file_is_refused_with_its_line(world: World) -> None:
    world.export_all_but("OPENRCT2_GAME_PATH")
    world.write_file("# the game folder", "OPENRCT2_GAME_PATH=")

    with pytest.raises(Refused) as caught:
        load_settings(platform.system())

    assert str(caught.value) == (
        "local/game-settings.env line 2: OPENRCT2_GAME_PATH must not be empty. Nothing was written."
    )


@pytest.mark.parametrize("quote", ["'", '"'], ids=["single", "double"])
def test_one_pair_of_matching_quotes_around_a_settings_file_value_is_removed(
    world: World, quote: str
) -> None:
    spaced = world.root / "Roller Coaster Tycoon 2"
    spaced.mkdir()
    world.export_all_but("OPENRCT2_GAME_PATH")
    world.write_file(f"OPENRCT2_GAME_PATH={quote}{spaced}{quote}")

    assert load_settings(platform.system()).game_path == spaced


def test_an_unmatched_quote_stays_in_the_value_and_the_refusal_names_the_line(
    world: World,
) -> None:
    world.export_all_but("OPENRCT2_GAME_PATH")
    world.write_file(f'OPENRCT2_GAME_PATH="{world.file_game}')

    with pytest.raises(Refused) as caught:
        load_settings(platform.system())

    assert str(caught.value) == (
        "OPENRCT2_GAME_PATH does not name a folder (from local/game-settings.env line 1). "
        "Nothing was written."
    )


def test_a_comment_after_an_unquoted_value_is_refused_with_its_line(world: World) -> None:
    world.export_all_but("OPENRCT2_GAME_PATH")
    world.write_file("", f"OPENRCT2_GAME_PATH={world.file_game}  # my game")

    with pytest.raises(Refused) as caught:
        load_settings(platform.system())

    assert str(caught.value) == (
        "local/game-settings.env line 2: OPENRCT2_GAME_PATH has a # comment after the value; "
        + COMMENT_REFUSAL_TAIL
    )


def test_a_tab_before_a_comment_after_an_unquoted_value_is_refused(world: World) -> None:
    world.export_all_but("OPENRCT2_GAME_PATH")
    world.write_file(f"OPENRCT2_GAME_PATH={world.file_game}\t# my game")

    with pytest.raises(Refused) as caught:
        load_settings(platform.system())

    assert str(caught.value) == (
        "local/game-settings.env line 1: OPENRCT2_GAME_PATH has a # comment after the value; "
        + COMMENT_REFUSAL_TAIL
    )


def test_a_settings_path_that_is_a_folder_is_refused(world: World) -> None:
    world.export_all_but("OPENRCT2_GAME_PATH")
    world.settings_file.mkdir()

    with pytest.raises(Refused) as caught:
        load_settings(platform.system())

    assert str(caught.value) == "local/game-settings.env is not a file. Nothing was written."


def test_a_settings_path_that_does_not_exist_holds_no_settings(world: World) -> None:
    assert not world.settings_file.exists()

    assert read_settings_file(world.settings_file) == {}


def test_a_hash_inside_a_quoted_value_is_part_of_the_value(world: World) -> None:
    hashed = world.root / "rct2 #2"
    hashed.mkdir()
    world.export_all_but("OPENRCT2_GAME_PATH")
    world.write_file(f'OPENRCT2_GAME_PATH="{hashed}"')

    assert load_settings(platform.system()).game_path == hashed


def test_a_repeated_key_is_refused_naming_both_lines(world: World) -> None:
    world.export_all_but("OPENRCT2_GAME_PATH")
    world.write_file(
        f"OPENRCT2_GAME_PATH={world.file_game}", "# again", f"OPENRCT2_GAME_PATH={world.ini_game}"
    )

    with pytest.raises(Refused) as caught:
        load_settings(platform.system())

    assert str(caught.value) == (
        "local/game-settings.env line 3: OPENRCT2_GAME_PATH is already set on line 1. "
        "Nothing was written."
    )


def test_a_settings_file_that_is_not_utf8_is_refused_naming_the_file(world: World) -> None:
    world.export_all_but()
    world.settings_file.write_bytes(b"OPENRCT2_GAME_PATH=\xff\xfe\n")

    with pytest.raises(Refused) as caught:
        load_settings(platform.system())

    assert str(caught.value) == (
        "local/game-settings.env could not be read (UnicodeDecodeError). Nothing was written."
    )


def test_a_config_ini_without_a_section_header_is_refused(world: World) -> None:
    world.export_all_but("OPENRCT2_GAME_PATH")
    world.write_ini(f"game_path = {world.ini_game}\n")

    with pytest.raises(Refused) as caught:
        load_settings(platform.system())

    assert str(caught.value) == (
        "OpenRCT2's own settings file could not be read (MissingSectionHeaderError). "
        "Nothing was written."
    )


def test_a_config_ini_that_is_not_utf8_is_refused(world: World) -> None:
    world.export_all_but("OPENRCT2_GAME_PATH")
    (world.user_dir / "config.ini").write_bytes(b"[general]\ngame_path = \xff\n")

    with pytest.raises(Refused) as caught:
        load_settings(platform.system())

    assert str(caught.value) == (
        "OpenRCT2's own settings file could not be read (UnicodeDecodeError). Nothing was written."
    )


def test_a_config_ini_that_cannot_be_opened_is_refused(world: World) -> None:
    world.export_all_but("OPENRCT2_GAME_PATH")
    world.write_ini(f"[general]\ngame_path = {world.ini_game}\n")
    (world.user_dir / "config.ini").chmod(0)

    with pytest.raises(Refused) as caught:
        load_settings(platform.system())

    assert str(caught.value) == (
        "OpenRCT2's own settings file could not be read (PermissionError). Nothing was written."
    )

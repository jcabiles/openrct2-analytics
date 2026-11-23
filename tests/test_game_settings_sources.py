"""Game settings: the source a refused value came from, and the real-game test's helper.

Every test builds the stand-in folders of ``tests/test_game_settings.py`` under ``tmp_path``;
nothing reads the real home folder, the real settings file or the real game.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path

import pytest

from openrct2_analytics.ingest import bench_setup
from openrct2_analytics.ingest.bench_setup import load_settings
from openrct2_analytics.ingest.capture import Refused
from tests.conftest import isolate_game_settings, settings_for_real_run
from tests.test_game_settings import World


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return World(tmp_path, monkeypatch)


SOURCES = ("exported", "file")


def put_setting(world: World, name: str, value: Path, source: str) -> None:
    """Give one setting a value from the exported environment or from line 2 of the file."""
    world.export_all_but(name)
    if source == "exported":
        world.export(**{name: value})
    else:
        world.write_file("# the setting", f"{name}={value}")


def source_label(source: str) -> str:
    return "exported" if source == "exported" else "local/game-settings.env line 2"


@pytest.mark.parametrize("source", SOURCES)
def test_a_binary_that_is_not_a_file_names_where_the_value_came_from(
    world: World, source: str
) -> None:
    put_setting(world, "OPENRCT2_BINARY", world.root / "no-such-binary", source)

    with pytest.raises(Refused) as caught:
        load_settings(platform.system())

    assert str(caught.value) == (
        f"OPENRCT2_BINARY does not name an executable file (from {source_label(source)}). "
        "Nothing was written."
    )


@pytest.mark.parametrize("source", SOURCES)
def test_a_park_that_is_not_a_file_names_where_the_value_came_from(
    world: World, source: str
) -> None:
    put_setting(world, "OPENRCT2_BENCH_PARK", world.root / "no-such.park", source)

    with pytest.raises(Refused) as caught:
        load_settings(platform.system())

    assert str(caught.value) == (
        f"OPENRCT2_BENCH_PARK does not name a file (from {source_label(source)}). "
        "Nothing was written."
    )


@pytest.mark.parametrize("source", SOURCES)
def test_a_game_path_that_is_not_a_folder_names_where_the_value_came_from(
    world: World, source: str
) -> None:
    put_setting(world, "OPENRCT2_GAME_PATH", world.root / "no-such-folder", source)

    with pytest.raises(Refused) as caught:
        load_settings(platform.system())

    assert str(caught.value) == (
        f"OPENRCT2_GAME_PATH does not name a folder (from {source_label(source)}). "
        "Nothing was written."
    )


def test_the_real_game_settings_come_from_the_real_sources_and_the_run_gets_its_own_folder(
    world: World, tmp_path: Path
) -> None:
    world.export_all_but("OPENRCT2_BINARY", "OPENRCT2_BENCH_PARK", "OPENRCT2_GAME_PATH")
    world.write_file(
        f"OPENRCT2_BINARY={world.file_binary}", f"OPENRCT2_BENCH_PARK={world.file_park}"
    )
    world.write_ini(f"[general]\ngame_path = {world.ini_game}\n")
    run_user = tmp_path / "run-user"
    run_user.mkdir()

    settings = settings_for_real_run(platform.system(), world.monkeypatch, run_user)

    assert settings.game_path == world.ini_game
    assert settings.park == world.file_park
    assert settings.binary == world.file_binary
    assert settings.user_dir == run_user
    assert os.environ["OPENRCT2_USER_DIR"] == str(run_user)
    assert os.environ["OPENRCT2_GAME_PATH"] == str(world.ini_game)
    assert load_settings(platform.system()).game_path == world.ini_game


REAL_FILE = "test_autopilot_real_game.py"
FLAG = {"OPENRCT2_AUTOPILOT_REAL_GAME": "1"}


def isolation_result(
    tmp_path: Path, environ: dict[str, str], test_file: str
) -> tuple[Path, str, Path, str]:
    """Run the isolation decision; return SETTINGS_FILE and OPENRCT2_USER_DIR before, then after."""
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    before = (bench_setup.SETTINGS_FILE, os.environ["OPENRCT2_USER_DIR"])
    with pytest.MonkeyPatch.context() as inner:
        isolate_game_settings(isolated, inner, environ, test_file)
        after = (bench_setup.SETTINGS_FILE, os.environ["OPENRCT2_USER_DIR"])
    return (*before, *after)


def test_the_real_game_test_with_the_flag_keeps_the_real_sources(tmp_path: Path) -> None:
    file_before, user_before, file_after, user_after = isolation_result(tmp_path, FLAG, REAL_FILE)

    assert file_after == file_before
    assert user_after == user_before


def test_another_test_with_the_flag_stays_isolated(tmp_path: Path) -> None:
    file_before, user_before, file_after, user_after = isolation_result(
        tmp_path, FLAG, "test_bench_run.py"
    )

    assert file_after == tmp_path / "isolated" / "settings.cfg"
    assert user_after == str(tmp_path / "isolated" / "openrct2-user")
    assert file_after != file_before
    assert user_after != user_before


def test_the_real_game_test_without_the_flag_stays_isolated(tmp_path: Path) -> None:
    file_before, user_before, file_after, user_after = isolation_result(tmp_path, {}, REAL_FILE)

    assert file_after == tmp_path / "isolated" / "settings.cfg"
    assert user_after == str(tmp_path / "isolated" / "openrct2-user")
    assert file_after != file_before
    assert user_after != user_before


def test_a_settings_file_that_cannot_be_read_is_refused(world: World) -> None:
    world.write_file("OPENRCT2_BINARY=x")
    world.settings_file.chmod(0)
    try:
        with pytest.raises(Refused) as caught:
            load_settings(platform.system())
    finally:
        world.settings_file.chmod(0o600)

    assert str(caught.value) == (
        "local/game-settings.env could not be read (PermissionError). Nothing was written."
    )

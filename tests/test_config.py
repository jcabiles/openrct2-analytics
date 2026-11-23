"""Behavioral tests for the settings module, on the real process environment."""
# WEAKENED-OK: the Config.raw_dir/parquet_dir defaults and OPENRCT2_RAW_DIR/OPENRCT2_PARQUET_DIR
# overrides were removed on purpose; tests/test_data_set_refusals.py covers their replacement tests.

from __future__ import annotations

import platform
from pathlib import Path

import pytest

from openrct2_analytics.config import DEFAULT_BINARIES, BenchConfig, Config, ConfigError

VARIABLES = (
    "OPENRCT2_LISTENER_HOST",
    "OPENRCT2_LISTENER_PORT",
    "OPENRCT2_DATA_DIR",
    "OPENRCT2_USER_DIR",
    "OPENRCT2_CAPTURE_DIR",
    "XDG_CONFIG_HOME",
    "USERPROFILE",
    "OPENRCT2_BINARY",
    "OPENRCT2_BENCH_PARK",
    "OPENRCT2_GAME_PATH",
    "OPENRCT2_BENCH_DIR",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_defaults_need_no_environment() -> None:
    config = Config.from_env()

    assert config.listener_host == "127.0.0.1"
    assert config.listener_port == 8765
    assert config.openrct2_user_dir is None
    assert config.capture_dir == Path("data/capture")
    assert config.xdg_config_home is None
    assert config.userprofile is None
    assert config.home == Path.home()


def test_environment_overrides_every_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENRCT2_LISTENER_HOST", "127.0.0.2")
    monkeypatch.setenv("OPENRCT2_LISTENER_PORT", "9000")
    monkeypatch.setenv("OPENRCT2_USER_DIR", "/fake/user")
    monkeypatch.setenv("OPENRCT2_CAPTURE_DIR", "elsewhere/capture")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/fake/xdg")
    monkeypatch.setenv("USERPROFILE", "C:/fake/profile")

    config = Config.from_env()

    assert config.listener_host == "127.0.0.2"
    assert config.listener_port == 9000
    assert config.openrct2_user_dir == Path("/fake/user")
    assert config.capture_dir == Path("elsewhere/capture")
    assert config.xdg_config_home == Path("/fake/xdg")
    assert config.userprofile == Path("C:/fake/profile")


@pytest.mark.parametrize("port", ["abc", "", "8765.5", "-1", "65536"])
def test_invalid_port_raises(monkeypatch: pytest.MonkeyPatch, port: str) -> None:
    monkeypatch.setenv("OPENRCT2_LISTENER_PORT", port)

    with pytest.raises(ConfigError, match="OPENRCT2_LISTENER_PORT"):
        Config.from_env()


def test_empty_path_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENRCT2_CAPTURE_DIR", " ")

    with pytest.raises(ConfigError, match="OPENRCT2_CAPTURE_DIR"):
        Config.from_env()


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "127.255.255.254", "::1"])
def test_loopback_hosts_are_accepted(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    monkeypatch.setenv("OPENRCT2_LISTENER_HOST", host)

    assert Config.from_env().listener_host == host


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.5", "example.com", "128.0.0.1"])
def test_non_loopback_host_raises(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    monkeypatch.setenv("OPENRCT2_LISTENER_HOST", host)

    with pytest.raises(ConfigError, match="OPENRCT2_LISTENER_HOST"):
        Config.from_env()


def test_user_dir_is_expanded_and_made_absolute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OPENRCT2_USER_DIR", "~/game")
    assert Config.from_env().openrct2_user_dir == tmp_path / "game"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENRCT2_USER_DIR", "relative/game")
    assert Config.from_env().openrct2_user_dir == tmp_path / "relative" / "game"


def test_home_comes_from_the_home_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    assert Config.from_env().home == tmp_path


@pytest.mark.parametrize("name", ["OPENRCT2_USER_DIR", "OPENRCT2_CAPTURE_DIR"])
@pytest.mark.parametrize("value", ["", "   "])
def test_empty_user_or_capture_dir_raises(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ConfigError, match=name):
        Config.from_env()


@pytest.mark.parametrize("name", ["XDG_CONFIG_HOME", "USERPROFILE"])
@pytest.mark.parametrize("value", ["", "  "])
def test_empty_platform_variable_means_unset(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    config = Config.from_env()

    assert config.xdg_config_home is None
    assert config.userprofile is None


def test_bench_settings_default_to_unset_except_the_app_location_and_work_folder() -> None:
    config = BenchConfig.from_env()

    default = DEFAULT_BINARIES.get(platform.system())
    assert config.binary == (None if default is None else Path(default))
    assert config.park is None
    assert config.game_path is None
    assert config.work_dir == Path("data/bench")


def test_bench_settings_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENRCT2_BINARY", "/fake/OpenRCT2")
    monkeypatch.setenv("OPENRCT2_BENCH_PARK", "/fake/park.park")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENRCT2_GAME_PATH", "relative/rct2")
    monkeypatch.setenv("OPENRCT2_BENCH_DIR", "elsewhere/bench")

    config = BenchConfig.from_env()

    assert config.binary == Path("/fake/OpenRCT2")
    assert config.park == Path("/fake/park.park")
    assert config.game_path == tmp_path / "relative" / "rct2"
    assert config.work_dir == Path("elsewhere/bench")


@pytest.mark.parametrize(
    "name", ["OPENRCT2_BINARY", "OPENRCT2_BENCH_PARK", "OPENRCT2_GAME_PATH", "OPENRCT2_BENCH_DIR"]
)
def test_empty_bench_setting_raises(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, " ")

    with pytest.raises(ConfigError, match=name):
        BenchConfig.from_env()


@pytest.mark.parametrize(
    "name", ["OPENRCT2_BINARY", "OPENRCT2_BENCH_PARK", "OPENRCT2_GAME_PATH", "OPENRCT2_BENCH_DIR"]
)
def test_an_empty_bench_setting_does_not_stop_the_other_commands(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv(name, " ")

    assert Config.from_env().listener_port == 8765

"""12-factor configuration: every setting comes from the environment.

Invalid values fail fast at startup with clear errors.

The plugin sends to 127.0.0.1:8765; ``OPENRCT2_LISTENER_PORT`` moves only the listener
for tests, and real capture needs the default.

Benchmark settings (``OPENRCT2_BINARY``, ``OPENRCT2_BENCH_PARK``, ``OPENRCT2_GAME_PATH``,
``OPENRCT2_REHEARSAL_PARK2``) hold private paths; only the macOS app location has a default. bench,
bench-sample and capture-rehearsal refuse one set but empty; other commands ignore them.
"""

from __future__ import annotations

import ipaddress
import os
import platform
from dataclasses import dataclass
from pathlib import Path

MAX_PORT = 65535
DATA_SETS = ("rehearsal", "company")
# None makes capture refuse until the clean start (roadmap step 2d, ADR 0013).
CAPTURE_DEFAULT_DATA_SET: str | None = None
DEFAULT_BENCH_DIR = "data/bench"
DEFAULT_BINARIES = {"Darwin": "/Applications/OpenRCT2.app/Contents/MacOS/OpenRCT2"}


class ConfigError(Exception):
    """Raised when configuration is invalid."""


def _env_port(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        port = int(raw)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {name} must be an integer, got: {raw!r}") from exc
    if not 0 <= port <= MAX_PORT:
        raise ConfigError(f"Environment variable {name} must be 0-{MAX_PORT}, got: {raw!r}")
    return port


def _env_text(name: str, default: str) -> str:
    value = os.environ.get(name, default)
    if not value.strip():
        raise ConfigError(f"Environment variable {name} must not be empty")
    return value


def env_optional_path(name: str, default: str | None = None) -> Path | None:
    """Read a path; unset means ``default`` (or None), but a set value must not be empty."""
    value = os.environ.get(name, default)
    if value is None:
        return None
    if not value.strip():
        raise ConfigError(f"Environment variable {name} must not be empty")
    return Path(value).expanduser().absolute()  # recorded paths must not depend on the cwd


def data_root() -> Path:
    """Return the data folder: ``OPENRCT2_DATA_DIR``, default ``data``, as given (not absolute)."""
    return Path(_env_text("OPENRCT2_DATA_DIR", "data"))


def _env_platform_path(name: str) -> Path | None:
    """Read a platform variable the system may leave unset; unset or empty means None."""
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return Path(value)


def _env_loopback_host(name: str, default: str) -> str:
    """Read a listener host; the listener has no authentication, so only loopback is allowed."""
    value = _env_text(name, default)
    if value == "localhost":
        return value
    try:
        loopback = ipaddress.ip_address(value).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise ConfigError(
            f"Environment variable {name} must be localhost or a loopback address, got: {value!r}"
        )
    return value


@dataclass(frozen=True)
class Config:
    """Runtime configuration loaded from environment variables."""

    listener_host: str
    listener_port: int
    openrct2_user_dir: Path | None
    capture_dir: Path
    backup_dir: Path
    xdg_config_home: Path | None
    userprofile: Path | None
    home: Path

    @classmethod
    def from_env(cls) -> Config:
        """Build a Config from the current process environment.

        Raises:
            ConfigError: if a variable (except ``XDG_CONFIG_HOME`` and ``USERPROFILE``, where
                empty means unset) is empty, the host is not loopback, or the port is not 0-65535.
        """
        return cls(
            listener_host=_env_loopback_host("OPENRCT2_LISTENER_HOST", "127.0.0.1"),
            listener_port=_env_port("OPENRCT2_LISTENER_PORT", 8765),
            openrct2_user_dir=env_optional_path("OPENRCT2_USER_DIR"),
            capture_dir=Path(_env_text("OPENRCT2_CAPTURE_DIR", "data/capture")),
            backup_dir=Path(_env_text("OPENRCT2_BACKUP_DIR", "local/park-backups")),
            xdg_config_home=_env_platform_path("XDG_CONFIG_HOME"),
            userprofile=_env_platform_path("USERPROFILE"),
            home=Path.home(),
        )


@dataclass(frozen=True)
class LandingDirs:
    """The two landing folders of one data set.

    Attributes:
        raw: Folder the listener writes ``v<N>/`` and ``malformed-*`` files to.
        parquet: Folder the converter writes ``v1/`` and ``audit/`` to.
    """

    raw: Path
    parquet: Path


def landing_dirs(data_set: str) -> LandingDirs:
    """Return the raw and Parquet folders of ``data_set`` under ``data`` (or ``OPENRCT2_DATA_DIR``).

    Args:
        data_set: One of ``DATA_SETS``.

    Raises:
        ConfigError: if ``data_set`` is empty or unknown, ``OPENRCT2_DATA_DIR`` is set but empty,
            or any two of the four raw and Parquet folders (or their existing ``v1`` children)
            resolve to one folder or nest (``<root>/company`` as a symlink to ``<root>/rehearsal``).
    """
    if data_set not in DATA_SETS:
        raise ConfigError(f"Data set must be one of {', '.join(DATA_SETS)}, got: {data_set!r}")
    root = data_root()
    folders = [root / name / kind for name in DATA_SETS for kind in ("raw", "parquet")]
    # Each folder's ``v1`` child is checked too, so an alias one level down is refused.
    children = [(folder / "v1", folder) for folder in folders if os.path.lexists(folder / "v1")]
    seen: list[tuple[Path, Path, Path | None]] = []
    for folder, parent in [(f, None) for f in folders] + children:
        resolved = folder.resolve()
        for earlier, earlier_resolved, _ in seen:
            if earlier == parent:
                continue
            if resolved == earlier_resolved:
                raise ConfigError(
                    f"Two landing folders are one folder: {earlier} and {folder} "
                    f"(both resolve to {resolved})"
                )
            if resolved.is_relative_to(earlier_resolved) or earlier_resolved.is_relative_to(
                resolved
            ):
                raise ConfigError(
                    f"Two landing folders nest: {earlier} and {folder} "
                    f"(resolving to {earlier_resolved} and {resolved})"
                )
        seen.append((folder, resolved, parent))
    return LandingDirs(raw=root / data_set / "raw", parquet=root / data_set / "parquet")


@dataclass(frozen=True)
class BenchConfig:
    """The benchmark's settings from the environment; only the benchmark loads them."""

    binary: Path | None
    park: Path | None
    game_path: Path | None
    work_dir: Path
    rehearsal_park2: Path | None = None

    @classmethod
    def from_env(cls) -> BenchConfig:
        """Build a BenchConfig from the current process environment.

        Raises:
            ConfigError: if a benchmark variable is set but empty.
        """
        return cls(
            binary=env_optional_path("OPENRCT2_BINARY", DEFAULT_BINARIES.get(platform.system())),
            park=env_optional_path("OPENRCT2_BENCH_PARK"),
            game_path=env_optional_path("OPENRCT2_GAME_PATH"),
            work_dir=Path(_env_text("OPENRCT2_BENCH_DIR", DEFAULT_BENCH_DIR)),
            rehearsal_park2=env_optional_path("OPENRCT2_REHEARSAL_PARK2"),
        )

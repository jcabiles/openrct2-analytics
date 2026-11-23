"""Shared test fixtures; modules opt in by name, except the run-wide validator reuse."""

import os
import signal
from collections.abc import Callable, Iterator, Mapping
from dataclasses import replace
from datetime import tzinfo
from pathlib import Path

import fastjsonschema
import pytest

from openrct2_analytics.ingest import bench_setup, park_label
from openrct2_analytics.ingest.lock import SIGNAL_NAMES
from tests.test_bench_run import make_bench
from tests.test_rehearsal_capture import RehearsalHarness
from tests.validator_cache import cached_validate


@pytest.fixture(autouse=True, scope="session")
def _reuse_compiled_validators() -> Iterator[None]:
    """Compile each contract schema once per run instead of on every contract read."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(fastjsonschema, "validate", cached_validate)
        yield


@pytest.fixture
def fixed_local_zone(monkeypatch: pytest.MonkeyPatch) -> Callable[[tzinfo], None]:
    """Opt in by name: ``fixed_local_zone(zone)`` makes ``park_label.to_local`` use ``zone``."""

    def use(zone: tzinfo) -> None:
        monkeypatch.setattr(park_label, "to_local", lambda moment: moment.astimezone(zone))

    return use


REAL_GAME_FLAG = "OPENRCT2_AUTOPILOT_REAL_GAME"


REAL_GAME_TEST_FILE = "test_autopilot_real_game.py"


def real_game_opted_in(environ: Mapping[str, str], test_file: str) -> bool:
    """Return whether this is the by-hand real-game test and its flag is on (agents never set it).

    The flag alone is not enough: it may be exported for a whole pytest run, and every other
    test must stay off the real settings file and the player's OpenRCT2 folder.
    """
    return environ.get(REAL_GAME_FLAG) == "1" and test_file == REAL_GAME_TEST_FILE


def isolate_game_settings(
    isolated: Path,
    monkeypatch: pytest.MonkeyPatch,
    environ: Mapping[str, str],
    test_file: str,
) -> None:
    """Keep a test off the real settings file and the player's OpenRCT2 folder.

    Does nothing for the real-game test when its flag is on: that test reads the real sources
    first (``tests/test_autopilot_real_game.py``) and then gives the run its own temporary
    folder. The environment value also reaches any subprocess the test starts. ``isolated``
    sits beside ``tmp_path``, not in it, because tests assert that ``tmp_path`` holds only what
    they wrote.
    """
    if real_game_opted_in(environ, test_file):
        return
    monkeypatch.setattr(bench_setup, "SETTINGS_FILE", isolated / "settings.cfg")
    user_dir = isolated / "openrct2-user"
    user_dir.mkdir()
    monkeypatch.setenv("OPENRCT2_USER_DIR", str(user_dir))


@pytest.fixture(autouse=True)
def _isolate_game_settings(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runs before the test body, so a test that sets its own values still wins."""
    isolate_game_settings(
        tmp_path_factory.mktemp("isolated"), monkeypatch, os.environ, request.node.path.name
    )


@pytest.fixture(autouse=True)
def _no_exported_data_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the default relative data root; a test that needs another sets it itself."""
    monkeypatch.delenv("OPENRCT2_DATA_DIR", raising=False)


def settings_for_real_run(
    system: str, monkeypatch: pytest.MonkeyPatch, user_dir: Path
) -> bench_setup.BenchSettings:
    """Load the settings from the real sources, then give the run a separate user folder.

    The real sources are the exported environment, the settings file and the ``game_path`` in
    the real OpenRCT2 folder's ``config.ini``; they are read before ``OPENRCT2_USER_DIR`` moves
    to ``user_dir``. The three game settings are then exported so that a later ``load_settings``
    (the one inside ``autopilot_year.main``) finds them although the user folder is now empty.
    """
    settings = bench_setup.load_settings(system)
    monkeypatch.setenv("OPENRCT2_BINARY", str(settings.binary))
    monkeypatch.setenv("OPENRCT2_BENCH_PARK", str(settings.park))
    monkeypatch.setenv("OPENRCT2_GAME_PATH", str(settings.game_path))
    monkeypatch.setenv("OPENRCT2_USER_DIR", str(user_dir))
    return replace(settings, user_dir=user_dir)


@pytest.fixture
def landing_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the data root inside ``tmp_path`` and clear machine settings."""
    for name in [key for key in os.environ if key.startswith("OPENRCT2_")]:
        monkeypatch.delenv(name)
    root = tmp_path / "data"
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(root))
    return root


@pytest.fixture(autouse=True)
def handlers() -> Iterator[None]:
    """Restore the signal handlers ``main`` installs, so no SIG_IGN leaks into later tests."""
    numbers = [getattr(signal, n) for n in SIGNAL_NAMES if hasattr(signal, n)]
    previous = {number: signal.getsignal(number) for number in numbers}
    yield
    for number, handler in previous.items():
        signal.signal(number, handler)


@pytest.fixture(name="rh")
def rehearsal_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RehearsalHarness:
    return RehearsalHarness(make_bench(tmp_path, monkeypatch), monkeypatch)


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    (root / "sample").mkdir(parents=True)
    (root / "sample" / "README.md").write_text("untouched\n")
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(root))
    return root

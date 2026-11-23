"""Launch and stop one benchmark session: the shared run options and the game child process.

``bench_run`` (verdict mode) and ``bench_sample`` (sample mode) both run sessions through
``play``: it starts the listener on ``127.0.0.1`` writing to the run's raw folder, launches
the game headless on the run's park copy, waits for the caller's stop condition, then stops
the game and the listener in an order that cuts no line.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Protocol

from openrct2_analytics.ingest.bench_setup import (
    BENCH_PARK_SHA1_PREFIX,
    BenchSettings,
    Clock,
    LoadAverage,
    RunFolder,
    Sleep,
    one_minute_load,
)
from openrct2_analytics.ingest.capture import (
    HANDLER_WAIT_SECONDS,
    PLUGIN_HOST,
    PLUGIN_PORT,
    REPO_ROOT,
    SERVE_POLL_SECONDS,
    stop_listener,
)
from openrct2_analytics.ingest.listener import EventServer, Lander

JUDGED_DAYS = 35
SAMPLE_DAYS = 36
GAME_PORT = 11799
SECONDS_PER_DAY = 30.0  # a run is invalid after N days of this plus the startup allowance
STARTUP_SECONDS = 120.0
STOP_GRACE_SECONDS = 30.0  # after asking the game to quit, before killing it
WAIT_POLL_SECONDS = 0.2
SAMPLE_DIR = REPO_ROOT / "data" / "sample" / "rehearsal"


@dataclass(frozen=True)
class Options:
    """Ports, run lengths and the substituted inputs; tests shrink and replace them.

    Attributes:
        listener_port: Listener port on ``127.0.0.1``; only 8765 reaches the real plugin.
        game_port: The port the game hosts on.
        judged_days: N, the judged game days per verdict run.
        sample_days: Day callbacks per sample session before its save.
        seconds_per_day: Wall-clock allowance per game day for the run timeout.
        startup_seconds: Wall-clock allowance added once per run for the timeout.
        stop_grace_seconds: How long the game may take to quit before it is killed.
        fixture_sha1_prefix: The benchmark park's SHA-1 prefix.
        sample_dir: Where the sample is converted to.
        clock: Wall-clock seconds, for the autosave age and the load-average wait.
        sleep: Sleeps between load-average checks.
        load_average: Returns the one-minute load average.
    """

    listener_port: int = PLUGIN_PORT
    game_port: int = GAME_PORT
    judged_days: int = JUDGED_DAYS
    sample_days: int = SAMPLE_DAYS
    seconds_per_day: float = SECONDS_PER_DAY
    startup_seconds: float = STARTUP_SECONDS
    stop_grace_seconds: float = STOP_GRACE_SECONDS
    fixture_sha1_prefix: str = BENCH_PARK_SHA1_PREFIX
    sample_dir: Path = SAMPLE_DIR
    clock: Clock = time.time
    sleep: Sleep = time.sleep
    load_average: LoadAverage = one_minute_load

    def timeout_seconds(self, days: int) -> float:
        """The wall-clock time a run of ``days`` game days may take before it is invalid."""
        return days * self.seconds_per_day + self.startup_seconds


@dataclass(frozen=True)
class Bench:
    """What every run of one invocation shares, once the refusals have passed.

    Attributes:
        settings: The checked settings.
        options: Ports, run lengths and the substituted inputs.
        built: The plugin built once for this invocation.
        fixture_sha1: The fixture's SHA-1 before the first run; never written anywhere.
        version: The first line of the game's ``--version``.
    """

    settings: BenchSettings
    options: Options
    built: Path
    fixture_sha1: str
    version: str


class Watch(Protocol):
    """What ``play`` tells an observer: each landed event (listener thread), each poll (main)."""

    def on_landed(self, event: dict[str, object]) -> None:
        """Called with the parsed event after its line has landed."""

    def tick(self) -> None:
        """Called once per poll while waiting for the stop condition."""


class CountingLander(Lander):
    """A Lander that also counts landed events by type, so a run can stop on a count.

    ``on_landed``, when given, is called with the parsed event after each line that landed.
    """

    def __init__(
        self, raw_dir: Path, on_landed: Callable[[dict[str, object]], None] | None = None
    ) -> None:
        super().__init__(raw_dir)
        self._on_landed = on_landed
        self._counting = threading.Lock()
        self._counts: Counter[str] = Counter()

    def land(self, line: bytes) -> bool | None:
        """Land one line as the listener does, then count it by ``event_type`` if it landed."""
        landed = super().land(line)
        if landed:
            event = json.loads(line)  # it landed, so it parsed
            with self._counting:
                self._counts[str(event.get("event_type"))] += 1
            if self._on_landed is not None:
                self._on_landed(event)
        return landed

    def count(self, event_type: str) -> int:
        """How many events of ``event_type`` have landed."""
        with self._counting:
            return self._counts[event_type]


StopCondition = Callable[[CountingLander], bool]


def _stop_game(game: subprocess.Popen[bytes], grace_seconds: float) -> None:
    if game.poll() is not None:
        return
    game.terminate()
    try:
        game.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        game.kill()
        game.wait()


def _wait_for_stop(
    game: subprocess.Popen[bytes],
    done: Callable[[], bool],
    timeout_seconds: float,
    tick: Callable[[], None] | None = None,
) -> str | None:
    """Poll until ``done``; return None, or why the run never reached its stop condition."""
    deadline = time.monotonic() + timeout_seconds
    while not done():
        if tick is not None:
            tick()
        code = game.poll()
        if code is not None:
            return f"the game exited (code {code}) before the stop condition"
        if time.monotonic() >= deadline:
            return f"timed out after {timeout_seconds:g} s before the stop condition"
        time.sleep(WAIT_POLL_SECONDS)
    return None


def play(
    bench: Bench,
    folder: RunFolder,
    park_copy: Path,
    *,
    stop: StopCondition,
    days: int,
    watch: Watch | None = None,
) -> str | None:
    """Run the game until ``stop`` holds; return None, or why the run is invalid.

    Stop order: terminate the game (kill it after the grace period), wait for the listener's
    connection to reach end of input, then stop the listener, so no line is cut. A run of
    ``days`` game days that has not stopped after ``Options.timeout_seconds`` is invalid.
    ``watch``, when given, sees each landed event and each poll; it never changes the run.
    """
    options = bench.options
    lander = CountingLander(folder.raw, None if watch is None else watch.on_landed)
    server = EventServer((PLUGIN_HOST, options.listener_port), lander)
    serving = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": SERVE_POLL_SECONDS}, daemon=True
    )
    argv = [str(bench.settings.binary), "host", str(park_copy), "--headless"]
    argv += ["--port", str(options.game_port), "--user-data-path", str(folder.user_data)]
    try:
        serving.start()
        with folder.game_log.open("wb") as log:
            game = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log)  # noqa: S603
        try:
            problem = _wait_for_stop(
                game,
                partial(stop, lander),
                options.timeout_seconds(days),
                None if watch is None else watch.tick,
            )
        finally:
            _stop_game(game, options.stop_grace_seconds)
        still_open = server.wait_for_handlers(HANDLER_WAIT_SECONDS)
    finally:
        stop_listener(server, serving)
    if problem is None and still_open:
        problem = "the game's connection was still open after it stopped; a line may be cut"
    return problem

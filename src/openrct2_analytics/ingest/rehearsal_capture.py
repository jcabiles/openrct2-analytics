"""Capture a two-park rehearsal chain and land it (``make capture-rehearsal DATA_SET=rehearsal``).

Run with ``python -m openrct2_analytics.ingest.rehearsal_capture --data-set rehearsal``. The
command refuses before writing anything when it is unsafe to start (spec R3, in order), builds
the plugin once, plays the nine-session chain headless (``rehearsal_chain``), then proves the
capture in the work folder and lands it into ``data/rehearsal/`` (``rehearsal_land``).
``--skip-process-check`` skips only process listing and relies on the autosave-age check; an
open game with no autosave from the last ten minutes is not detected when this option is used.

Output names files relative to the work folder or the data folder and never prints a private
path; the game's own output stays in each run's ``game.log``. Exit codes: 0 landed, 1 a capture
or landing problem, 2 refused, 130 interrupted. SIGINT, SIGHUP and SIGTERM raise
``Interrupted`` once ``main`` has passed the data-set check (item 1).
"""

from __future__ import annotations

import argparse
import os
import platform
import sys
from collections.abc import Callable, Sequence
from contextlib import chdir
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path

from openrct2_analytics.config import BenchConfig, ConfigError, data_root, landing_dirs
from openrct2_analytics.ingest import plugin_install as pi
from openrct2_analytics.ingest.bench_play import Bench, Options
from openrct2_analytics.ingest.bench_setup import (
    BenchSettings,
    check_fixture,
    check_no_live_game,
    check_ports,
    check_work_folder,
    game_version,
    load_settings,
    wait_for_low_load,
)
from openrct2_analytics.ingest.capture import (
    EXIT_OK,
    EXIT_PROBLEM,
    EXIT_REFUSED,
    REPO_ROOT,
    Build,
    Refused,
    refuse_unless_closed,
    say,
)
from openrct2_analytics.ingest.capture_session import EXIT_INTERRUPTED, NOTHING_CHANGED
from openrct2_analytics.ingest.contracts import LANDING_FOLDER
from openrct2_analytics.ingest.convert import landing_lock_path
from openrct2_analytics.ingest.game_check import GameCheck, platform_game_check
from openrct2_analytics.ingest.game_settings import NOTHING_WRITTEN
from openrct2_analytics.ingest.listener import no_data_set_line
from openrct2_analytics.ingest.lock import Interrupted, raise_interrupted, set_signal_handlers
from openrct2_analytics.ingest.registry_feed import FEED_FOLDER, registry_dir
from openrct2_analytics.ingest.rehearsal_chain import (
    COMBINED,
    CONVERTED,
    SECONDS_PER_DAY,
    STARTUP_SECONDS,
    Sources,
    reserved_names,
    run_chain,
)
from openrct2_analytics.ingest.rehearsal_land import DATA_SET, land

PARK2_SHA1_PREFIX = "644c5e78"  # Park 2's save (ruling 2)
TARGET = "capture-rehearsal"
HALF_LANDED = (
    "data/rehearsal/ is not empty, or an earlier landing stopped half way. Move data/rehearsal/ "
    "(under OPENRCT2_DATA_DIR when set) aside by hand, then run again."
)
LANDING_TAIL = (
    f"Nothing was landed. The captured files stay in {COMBINED}/ and {CONVERTED}/ in the work "
    "folder (OPENRCT2_BENCH_DIR)."
)
INTERRUPTED_LANDING = "Interrupted while landing; the lines above say whether the capture landed."
NEXT_STEPS = (
    "Next: make convert DATA_SET=rehearsal, then make contracts DATA_SET=rehearsal, "
    "then make transform DATA_SET=rehearsal."
)


def _rehearsal_bench_options() -> Options:
    return Options(seconds_per_day=SECONDS_PER_DAY, startup_seconds=STARTUP_SECONDS)


@dataclass(frozen=True)
class RehearsalOptions:
    """The command's substitutable inputs; tests shrink and replace them.

    Attributes:
        bench: Ports, timeout figures, and the clock, sleep and load-average reader the
            load wait uses; the defaults give R5's timeout of 3.0 s per day plus 300 s.
        park2_sha1_prefix: Park 2's SHA-1 prefix; a test seam, as
            ``Options.fixture_sha1_prefix`` is for the fixture.
        game_check: Whether the game process runs (R3 item 9); a test seam.
        skip_process_check: Skip process listing and rely on the autosave-age check alone.
    """

    bench: Options = field(default_factory=_rehearsal_bench_options)
    park2_sha1_prefix: str = PARK2_SHA1_PREFIX
    game_check: GameCheck = field(default_factory=platform_game_check)
    skip_process_check: bool = False


@dataclass
class Progress:
    """Whether landing has begun; ``main`` words a late interrupt from it.

    Attributes:
        landing: True once ``land`` is about to be called.
    """

    landing: bool = False


def _park2() -> Path:
    """R3 item 2's Park 2 part: ``OPENRCT2_REHEARSAL_PARK2`` names a file.

    ``load_settings`` has already raised ``ConfigError`` for a malformed environment.
    """
    park2 = BenchConfig.from_env().rehearsal_park2
    if park2 is None:
        raise Refused(f"OPENRCT2_REHEARSAL_PARK2 is not set. {NOTHING_WRITTEN}")
    if not park2.is_file():
        raise Refused(f"OPENRCT2_REHEARSAL_PARK2 does not name a file. {NOTHING_WRITTEN}")
    return park2


def check_write_boundary(settings: BenchSettings, park2: Path, project: Path, *, tail: str) -> None:
    """R3 item 3: nothing this command writes may lie in a folder that must not be touched.

    It checks the work folder, the data root and each landing target, every one resolved with
    links followed (a path that does not exist yet resolves through its nearest existing parent).
    Rule (a): none equals, contains or lies inside the player's OpenRCT2 folder or the folder of
    either source save. Rule (b): none equals or lies inside ``data/sample/``, ``data/company/``,
    ``plugin/src/`` or ``data/rehearsal/parquet/`` of the ``project`` folder ("contains" passes:
    the default data root ``data`` contains all four).

    Raises:
        Refused: ending ``tail``, which says what was or was not written.
    """
    try:
        # A relative root is against the project folder: ``run`` makes it the working folder.
        root = data_root().resolve()
    except ConfigError as exc:
        raise Refused(f"{exc}. {tail}") from exc
    guarded = {
        "the player's OpenRCT2 folder": settings.user_dir.resolve(),
        "the folder of OPENRCT2_BENCH_PARK": settings.park.parent.resolve(),
        "the folder of OPENRCT2_REHEARSAL_PARK2": park2.parent.resolve(),
    }
    never_written = {
        "data/sample/": (project / "data" / "sample").resolve(),
        "data/company/": (project / "data" / "company").resolve(),
        "plugin/src/": (project / "plugin" / "src").resolve(),
        "data/rehearsal/parquet/": (project / "data" / "rehearsal" / "parquet").resolve(),
    }
    rehearsal = root / DATA_SET
    chosen = {
        "The work folder (OPENRCT2_BENCH_DIR)": settings.bench_dir.resolve(),
        "The data folder (OPENRCT2_DATA_DIR)": root,
        "The landing folder data/rehearsal/": rehearsal.resolve(),
        "The landing folder data/rehearsal/raw/": (rehearsal / "raw").resolve(),
        "The landing folder data/rehearsal/registry/": (rehearsal / FEED_FOLDER).resolve(),
        "The landing folder data/rehearsal/registry/v1/": (
            rehearsal / FEED_FOLDER / LANDING_FOLDER
        ).resolve(),
    }
    for setting, path in chosen.items():
        for name, folder in guarded.items():
            if path.is_relative_to(folder) or folder.is_relative_to(path):
                raise Refused(f"{setting} equals, contains or lies inside {name}. {tail}")
        for name, folder in never_written.items():
            if path.is_relative_to(folder):
                raise Refused(f"{setting} equals or lies inside {name}. {tail}")


def _holds_entries(folder: Path) -> bool:
    return folder.is_dir() and any(folder.iterdir())


def _check_landing_folders() -> None:
    """R3 items 4 and 5: the landing folders are their own folders, and all of them are empty."""
    try:
        folders = landing_dirs(DATA_SET)
        feed = registry_dir(DATA_SET) / LANDING_FOLDER
    except ConfigError as exc:
        raise Refused(
            "The rehearsal landing folders resolve to, or nest inside, another landing folder "
            f"(a link under OPENRCT2_DATA_DIR?). {NOTHING_WRITTEN}"
        ) from exc
    if os.path.lexists(landing_lock_path(folders.parquet)):
        raise Refused(f"{HALF_LANDED} A parquet.lock is present. {NOTHING_WRITTEN}")
    if _holds_entries(folders.raw) or _holds_entries(feed):
        raise Refused(f"{HALF_LANDED} raw/ or registry/v1/ already holds files. {NOTHING_WRITTEN}")


def _capture(bench: Bench, sources: Sources, progress: Progress, guard: Callable[[], None]) -> int:
    """Play the chain, then prove and land it; return the exit code."""
    say(f"Game version: {bench.version}")
    attempts = run_chain(bench, sources)
    if attempts is None:
        return EXIT_PROBLEM
    work = bench.settings.bench_dir
    # From here a signal may fall before, during or after the two renames, so 130 means
    # "landed or not, read the output": land prints what it landed.
    progress.landing = True
    try:
        code = land(attempts, combined=work / COMBINED, converted=work / CONVERTED, guard=guard)
    except Interrupted:
        code = EXIT_INTERRUPTED
    if code == EXIT_OK:
        say(NEXT_STEPS)
    if code == EXIT_INTERRUPTED:
        say(INTERRUPTED_LANDING)
    return code


def run(options: RehearsalOptions, build: Build, progress: Progress, project: Path) -> int:
    """Refuse (R3 items 2 to 11, in order), or play the chain and land it.

    Item 1, the data set, is ``main``'s. Item 2 reads the settings in the folder the command
    started in, so a relative input setting means that folder; items 3 to 11 and the landing run
    with ``project`` as the working folder, so a relative ``OPENRCT2_DATA_DIR`` means the same
    folder to the write-boundary check, the registry alias check and the landing.

    Returns:
        0 landed, 1 a capture or landing problem, 130 interrupted once landing began.

    Raises:
        Refused: before anything is written; the message says why.
        Interrupted: on a signal before ``land`` was called (nothing was landed), or in the
            moment after it returned (``progress.landing`` is then true).
        OSError: any file error; it is never reported as success.
    """
    # Item 2: the settings, then Park 2's file.
    settings: BenchSettings = load_settings(platform.system())
    park2 = _park2()
    with chdir(project):
        return _refuse_or_capture(
            options, build, progress, project=project, settings=settings, park2=park2
        )


def _refuse_or_capture(
    options: RehearsalOptions,
    build: Build,
    progress: Progress,
    *,
    project: Path,
    settings: BenchSettings,
    park2: Path,
) -> int:
    """R3 items 3 to 11, then the capture; ``run`` has put the working folder at the project."""
    # Item 3, then 4 and 5 (the landing folders), 6 (the work folder), 7 (both source saves).
    check_write_boundary(settings, park2, project, tail=NOTHING_WRITTEN)
    _check_landing_folders()
    check_work_folder(settings.bench_dir, reserved_names())
    bench_options = options.bench
    fixture_sha1 = check_fixture(settings.park, bench_options.fixture_sha1_prefix, hint="")
    park2_sha1 = check_fixture(
        park2,
        options.park2_sha1_prefix,
        setting="OPENRCT2_REHEARSAL_PARK2",
        hint="",
        park_name="Park 2's save",
    )
    # Item 8, then 9: process check, autosave age, then the two ports. --skip-process-check skips
    # only the process-list check; a game left open with no autosave in the last ten minutes then
    # goes undetected.
    version = game_version(settings.binary)
    if not options.skip_process_check:
        refuse_unless_closed(
            options.game_check, advice="Quit it, then run this command.", tail=NOTHING_WRITTEN
        )
    check_no_live_game(settings.user_dir, bench_options.clock())
    check_ports(bench_options.listener_port, bench_options.game_port, settings.bench_dir)
    # Item 10: the load average, once (D8).
    wait_for_low_load(bench_options.load_average, bench_options.clock, bench_options.sleep)
    # Item 11: the plugin builds.
    try:
        built = build()
    except pi.BuildError as exc:
        raise Refused(f"{exc}\nThe plugin did not build. {NOTHING_WRITTEN}") from exc
    bench = Bench(settings, bench_options, built, fixture_sha1, version)
    guard = partial(check_write_boundary, settings, park2, project, tail=LANDING_TAIL)
    return _capture(bench, Sources(settings.park, fixture_sha1, park2, park2_sha1), progress, guard)


def main(
    argv: Sequence[str] | None = None,
    *,
    options: RehearsalOptions | None = None,
    build: Build | None = None,
    project_dir: Path = REPO_ROOT,
) -> int:
    """Run the capture; return 0 (landed), 1 (problem), 2 (refused) or 130 (interrupted).

    ``options``, ``build`` and ``project_dir`` are test seams; the command line never sets them.
    A relative input setting (``OPENRCT2_USER_DIR``, ``OPENRCT2_BINARY``, ``OPENRCT2_BENCH_PARK``,
    ``OPENRCT2_GAME_PATH``, ``OPENRCT2_REHEARSAL_PARK2``) means the folder the command started in;
    a relative ``OPENRCT2_DATA_DIR`` means the project folder.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-set", help="Must be rehearsal; the command writes only there")
    parser.add_argument(
        "--skip-process-check",
        action="store_true",
        help="skip the process-list check and rely on the autosave-age check alone",
    )
    args = parser.parse_args(argv)
    # R3 item 1.
    if args.data_set is None:
        print(no_data_set_line(TARGET), file=sys.stderr)
        return EXIT_REFUSED
    if args.data_set != DATA_SET:
        print(
            f"make {TARGET} writes only rehearsal data; DATA_SET must be rehearsal. "
            f"{NOTHING_CHANGED}",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    set_signal_handlers(raise_interrupted)
    progress = Progress()
    base = options if options is not None else RehearsalOptions()
    if args.skip_process_check:
        base = replace(base, skip_process_check=True)
    project = project_dir.resolve()
    try:
        return run(
            base,
            build if build is not None else partial(pi.build_plugin, project),
            progress,
            project,
        )
    except Refused as refusal:
        say(str(refusal))
        return EXIT_REFUSED
    except Interrupted:
        if progress.landing:
            say(INTERRUPTED_LANDING)
        else:
            say("Interrupted before landing began. Nothing was landed.")
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())

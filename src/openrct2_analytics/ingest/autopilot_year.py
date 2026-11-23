"""Play a company park's year on autopilot (``make autopilot-year DATA_SET=company PARK=<id>``).

Run with ``python -m openrct2_analytics.ingest.autopilot_year --data-set company --park <id>
[--ready "<phrase>"]``. It refuses before writing anything (exit 2, "Nothing was written.") with
refusals 1 to 20 of docs/ai-dlc/specs/autopilot-year.md, section 4, in that order; then it plays,
re-checks the registry, lands, and converts, reports and backs up as ``make play`` does. The work
folder is removed after full success and kept after any failure (section 4's exit 1 and 130).
"""

from __future__ import annotations

import argparse
import os
import platform
import signal
import sys
from collections.abc import Sequence
from contextlib import chdir
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from openrct2_analytics.config import Config, ConfigError, landing_dirs
from openrct2_analytics.domain.company_years import Verdict, autopilot_verdict, company_year
from openrct2_analytics.ingest import autopilot_land as al
from openrct2_analytics.ingest import lock
from openrct2_analytics.ingest import managed_years as my
from openrct2_analytics.ingest import plugin_install as pi
from openrct2_analytics.ingest.autopilot_report import ReportFacts, dated_copy, report
from openrct2_analytics.ingest.autopilot_run import (
    COMPANY,
    RunResult,
    autopilot_options,
    run_autopilot,
    work_folder_name,
    write_boundary_problem,
)
from openrct2_analytics.ingest.autopilot_source import SourceFound, SourceRefused, find_source
from openrct2_analytics.ingest.bench_play import Options
from openrct2_analytics.ingest.bench_setup import (
    BenchSettings,
    RunFolder,
    check_no_live_game,
    check_ports,
    check_work_folder,
    game_version,
    load_settings,
    wait_for_low_load,
)
from openrct2_analytics.ingest.capture import REPO_ROOT, refuse_unless_closed
from openrct2_analytics.ingest.capture_report import AUDIT_FILE
from openrct2_analytics.ingest.capture_session import (
    EXIT_INTERRUPTED,
    EXIT_PROBLEM,
    EXIT_REFUSED,
    Build,
    Refused,
    convert_and_report,
    say,
)
from openrct2_analytics.ingest.contracts import LANDING_FOLDER
from openrct2_analytics.ingest.convert import landing_lock_path
from openrct2_analytics.ingest.game_check import GameCheck, platform_game_check
from openrct2_analytics.ingest.game_settings import NOTHING_WRITTEN
from openrct2_analytics.ingest.play_mode_feed import check_feed as check_label_feed
from openrct2_analytics.ingest.play_mode_feed import ready_phrase
from openrct2_analytics.ingest.registry_feed import (
    FILE_GLOB,
    INCOMING,
    check_feed,
    latest_rows,
    registry_dir,
)
from openrct2_analytics.ingest.save_backup import BackupPlan, file_label, is_own_copy
from openrct2_analytics.ingest.save_files import save_files_dir
from openrct2_analytics.ingest.save_watch import watch_folders

# The game's months from March (month 0) to October (month 7); the year has 245 days.
MONTH_DAYS = (31, 30, 31, 30, 31, 31, 30, 31)
LANDING_LOCK_WAIT_S = 120.0  # spec section 6; a module value so tests can shrink it
WRONG_DATA_SET = "autopilot-year runs only on the company data set; give DATA_SET=company."


@dataclass(frozen=True)
class Cleared:
    """What passed every refusal; ``ready_ignored`` is a later run's ``READY`` (decision 4)."""

    settings: BenchSettings
    source: SourceFound
    work_name: str
    target_year: int
    version: str
    plugin: Path
    archive: Path
    ready_confirmation: str | None
    ready_ignored: str | None


def _refused(text: str) -> Refused:
    return Refused(f"{text} {NOTHING_WRITTEN}")


def archive_dir(project: Path) -> Path:
    """Refusal 3's ``OPENRCT2_BACKUP_DIR``; a relative value is against ``project``."""
    try:
        backup = Config.from_env().backup_dir
    except ConfigError as exc:
        raise _refused(f"{exc}.") from exc
    return backup if backup.is_absolute() else project / backup


def _check_folders(work_name: str, settings: BenchSettings, archive: Path, project: Path) -> None:
    """Refusals 4 to 6: the write boundary, staged leftovers, the new work folder's name."""
    problem = write_boundary_problem(
        settings.bench_dir / work_name, settings.user_dir, archive, project
    )
    if problem is not None:
        raise _refused(problem)
    landing = {
        "data/company/raw/v1": landing_dirs(COMPANY).raw,
        "data/company/save_files/v1": save_files_dir(COMPANY),
        "data/company/registry/v1": registry_dir(COMPANY),
    }
    for name, parent in landing.items():
        folder = parent / LANDING_FOLDER
        leftovers = sorted(folder.glob(f"{INCOMING}*")) if folder.is_dir() else []
        if leftovers:
            raise _refused(
                f"Staged file {leftovers[0].name} already exists in {name}; a killed landing "
                "left it."
            )
    # Only the new name: a folder kept by an earlier failed run never blocks (decision 13).
    check_work_folder(settings.bench_dir, [work_name])


def _check_game(settings: BenchSettings, options: Options, game_check: GameCheck) -> str:
    """Refusals 7 to 10; returns the game's version line."""
    version = game_version(settings.binary)
    refuse_unless_closed(game_check, advice="Quit it, then run this command.", tail=NOTHING_WRITTEN)
    check_no_live_game(settings.user_dir, options.clock())
    check_ports(options.listener_port, options.game_port, settings.bench_dir)
    return version


def _check_converted(parquet: Path, raw: Path) -> None:
    """Refusals 11 and 12: no convert or landing runs, and every raw session is converted."""
    if os.path.lexists(landing_lock_path(parquet)):
        raise _refused(
            "data/company/parquet.lock is present: a convert, landing or delete is running, or a "
            "killed run left it."
        )
    if not my.table(parquet, "session_start").is_file() or not (parquet / AUDIT_FILE).is_file():
        raise _refused("No converted data; run make convert DATA_SET=company first.")
    stale = my.unconverted_raw_file(raw, parquet)
    if stale is not None:
        raise _refused(
            f"data/company/raw/{LANDING_FOLDER}/{stale.name} holds a session that was never "
            "converted; run make convert DATA_SET=company first."
        )


def _registration_problem(park_id: str, registry: Path) -> str | None:
    """Refusal 13 and the re-check after the run: a company row that is not a sandbox park.

    The registry and label feeds are checked first, as ``register_parks.registered_parks`` does;
    a failing feed returns its problem lines, so a malformed delivery is a refusal, not a crash.
    """
    if sorted((registry / LANDING_FOLDER).glob(FILE_GLOB)):
        problems = check_feed(registry) + check_label_feed(registry, data_set=COMPANY)
        if problems:
            return "\n".join(problems)
    row = latest_rows(registry / LANDING_FOLDER).get(park_id)
    if row is None or row.data_set != COMPANY:
        return (
            f"Park {park_id} is not a registered company park; register it with make "
            "register-parks DATA_SET=company first."
        )
    if row.practice:
        return (
            f"Park {park_id} is registered as a throwaway sandbox park; autopilot runs only "
            "company parks."
        )
    return None


def _check_year(park_id: str, source: SourceFound, parquet: Path, registry: Path) -> int:
    """Refusals 17a and 17b (spec section 5); returns T, the company year the run plays."""
    row = latest_rows(registry / LANDING_FOLDER)[park_id]
    target = company_year(source.game_year, row.company_start_year, row.game_year_origin)
    verdict = autopilot_verdict(park_id, target, my.company_managed_years(parquet, registry))
    if verdict is Verdict.REFUSAL_17B:
        raise _refused(
            f"Park {park_id} is itself the managed park of company year {target}. Play it by "
            "hand to 1 March of the next game year, save, and quit, with make play "
            "DATA_SET=company."
        )
    if verdict is Verdict.REFUSAL_17A:
        text = (
            f"Park {park_id} would play company year {target}, but no other registered company "
            f"park has a managed day in {target} yet. An autopilot park runs only a company year "
            f"the managed park runs; play the managed park into {target} first."
        )
        waiting = my.waiting_parks(parquet, registry)
        if waiting:
            names = ", ".join(f"{park} ({name})" for park, name in waiting)
            text += f" Waiting to register (they count once registered): {names}."
        raise _refused(text)
    return target


def _refuse(  # noqa: PLR0913  # the seams of main, fixed by spec section 8
    park_id: str,
    ready: str | None,
    *,
    options: Options,
    build: Build,
    project: Path,
    game_check: GameCheck,
) -> Cleared:
    """Refusals 3 to 20, in the order of spec section 4 (``main`` owns 1 and 2).

    Raises ``Refused`` before anything is written; a file that cannot be read raises its error.
    """
    # Refusal 3: the settings, with the park's archive folder (computed, not read) as the park.
    archive = archive_dir(project)
    settings = load_settings(platform.system(), park=archive / file_label(None, park_id))
    work_name = work_folder_name(park_id, datetime.fromtimestamp(options.clock(), UTC))
    with chdir(project):  # a relative OPENRCT2_DATA_DIR means the project folder
        _check_folders(work_name, settings, archive, project)  # 4 to 6
        version = _check_game(settings, options, game_check)  # 7 to 10
        dirs = landing_dirs(COMPANY)
        registry = registry_dir(COMPANY)
        _check_converted(dirs.parquet, dirs.raw)  # 11 and 12
        unregistered = _registration_problem(park_id, registry)  # 13
        if unregistered is not None:
            raise _refused(unregistered)
        found = find_source(park_id, archive, dirs.parquet, save_files_dir(COMPANY))  # 14 to 16
        if isinstance(found, SourceRefused):
            raise _refused(found.message)
        target = _check_year(park_id, found, dirs.parquet, registry)  # 17a and 17b
        # Refusal 18 (decision 4): the ready mark is required only on a park's first run.
        first_run = not my.landed_autopilot_sessions(dirs.parquet, registry, park_id)
        if first_run and ready != ready_phrase(park_id):
            raise _refused(
                f"This is park {park_id}'s first autopilot run. Confirm it is ready with "
                f'READY="{ready_phrase(park_id)}".'
            )
    wait_for_low_load(options.load_average, options.clock, options.sleep)  # 19
    try:  # 20
        plugin = build()
    except pi.BuildError as exc:
        raise Refused(f"{exc}\nThe plugin did not build. {NOTHING_WRITTEN}") from exc
    return Cleared(
        settings=replace(settings, park=found.file),
        source=found,
        work_name=work_name,
        target_year=target,
        version=version,
        plugin=plugin,
        archive=archive,
        ready_confirmation=ready if first_run else None,
        ready_ignored=None if first_run else ready,
    )


class _BoundaryChanged(Exception):
    """The write boundary or the registration failed the re-check under the lock; nothing landed."""


def _planned_days(source: SourceFound) -> int:
    """Game days from the source's date to 1 March of the next game year (1 to 245)."""
    rest = sum(MONTH_DAYS[source.game_month + 1 :])  # the months after the source's month
    return MONTH_DAYS[source.game_month] - source.game_day + 1 + rest


def _failed_checks(problems: list[str], work: Path) -> None:  # a check failed: nothing landed
    say("The autopilot run failed its checks:")
    for problem in problems:
        say(f"  {problem}")
    say(f"Company data was not touched; the run folder is kept at {work}.")


def _land(cleared: Cleared, park_id: str, result: RunResult, project: Path) -> list[Path]:
    """The landing (spec section 6); ``guard`` re-checks boundary and registry under the lock."""
    work, user = result.work_dir, cleared.settings.user_dir

    def guard() -> None:
        unregistered = _registration_problem(park_id, registry_dir(COMPANY))
        if problem := write_boundary_problem(work, user, cleared.archive, project) or unregistered:
            raise _BoundaryChanged(problem)

    assert result.session_id is not None  # a run with no single session has problems
    return al.land(
        result.work_dir,
        park_id=park_id,
        session_id=result.session_id,
        ready_confirmation=cleared.ready_confirmation or "",
        data_root=landing_dirs(COMPANY).raw.parent,
        guard=guard,
        lock_wait_s=LANDING_LOCK_WAIT_S,
    )


def _after_landing(cleared: Cleared, park_id: str, result: RunResult) -> int:
    """Convert, report and back up as ``make play`` does; then the success report or exit 1."""
    dirs = landing_dirs(COMPANY)
    folder = RunFolder(result.work_dir)
    end_save = folder.save_dir / f"{park_id}-autopilot-{cleared.source.game_year + 1}.park"
    game_save_dir = cleared.settings.user_dir / "save"
    # replace_own_copy False (decision 9): never replace a file in the game's save folder.
    plan = BackupPlan(
        watch_folders(folder.user_data), game_save_dir, cleared.archive, dirs.parquet, False
    )
    records = save_files_dir(COMPANY)
    code = convert_and_report(
        dirs.raw, dirs.parquet, records, result.started, watch=result.watch, backup=plan
    )
    # A skipped backup is a backup problem too: without the copy the next run is refused.
    archived = is_own_copy(end_save, cleared.archive / file_label(None, park_id))
    dated = dated_copy(game_save_dir, end_save) if archived else None
    if archived and dated is None:  # the archive copy was made, so the recovery steps do not apply
        say(
            f"No dated copy of the end-of-year save was found in {game_save_dir}; the "
            f"backup copy failed. The run folder is kept at {result.work_dir}."
        )
        return EXIT_PROBLEM
    if code == 0 and dated is not None:
        report(
            ReportFacts(
                park_id=park_id,
                work_dir=result.work_dir,
                bench_dir=cleared.settings.bench_dir,
                ready_ignored=cleared.ready_ignored,
                dated=dated,
                source_year=cleared.source.game_year,
                target_year=cleared.target_year,
                session_id=result.session_id,
                event_count=result.event_count,
                source_file=cleared.source.file.name,
                source_date=(
                    cleared.source.game_year,
                    cleared.source.game_month,
                    cleared.source.game_day,
                ),
                summary=result.summary,
            )
        )
        return code
    if not archived:
        say(
            f"To make the backup: copy {end_save} into {game_save_dir}, load it with make play "
            "DATA_SET=company, save while paused, and quit. The next autopilot run of this park "
            "is refused until then."
        )
    return EXIT_PROBLEM


def _run_and_land(cleared: Cleared, park_id: str, options: Options, project: Path) -> int:
    """The order after the refusals: run, registry re-check, landing, convert and report."""
    work = cleared.settings.bench_dir / cleared.work_name
    g = cleared.source.game_year
    try:
        result = run_autopilot(
            cleared.settings,
            park_id=park_id,
            source=cleared.settings.park,
            work_name=cleared.work_name,
            g=g,
            loaded_save_id=cleared.source.save_id,
            loaded_save_session_id=cleared.source.session_id,
            built=cleared.plugin,
            options=options,
            planned_days=_planned_days(cleared.source),
        )
        if not result.reached_stop:
            reason = "; ".join(p.rstrip(".") for p in result.problems) or "the game never saved"
            say(
                f"The autopilot run did not reach 1 March of game year {g + 1}: {reason}. "
                f"Company data was not touched; the run folder is kept at {work}."
            )
            return EXIT_PROBLEM
        if result.problems:
            _failed_checks(result.problems, work)
            return EXIT_PROBLEM
        with chdir(project):  # a relative OPENRCT2_DATA_DIR means the project folder
            _land(cleared, park_id, result, project)
            # Signals stay ignored (``land`` set them) from the first link to the report's end.
            return _after_landing(cleared, park_id, result)
    except lock.Interrupted:
        say(f"Interrupted; company data was not touched; the run folder is kept at {work}.")
        return EXIT_INTERRUPTED
    except al.LandingLockHeld as held:
        say(
            f"The company landing lock is held ({held.holder_line}); nothing was landed. The "
            f"run folder is kept at {work}; rerun make autopilot-year when the other command "
            "ends."
        )
    except al.StagedLabelFailed as failed:
        _failed_checks(failed.problems, work)
    except _BoundaryChanged as changed:
        _failed_checks(str(changed).splitlines(), work)
    except al.LandingStepFailed as failed:
        data = landing_dirs(COMPANY).raw.parent
        names = ", ".join(f"data/company/{p.relative_to(data)}" for p in failed.landed)
        say(
            f"Landing failed at {failed.step}: {failed.cause}. Landed: {names or 'nothing'}; "
            f"no raw session landed. The run folder is kept at {work}."
        )
    return EXIT_PROBLEM


def main(
    argv: Sequence[str] | None = None,
    *,
    options: Options | None = None,
    build: Build | None = None,
    project_dir: Path = REPO_ROOT,
    game_check: GameCheck | None = None,
) -> int:
    """Return 0 (landed), 1 (a run, check, landing or backup problem), 2 or 130.

    The keywords are test seams; the command line never sets them. A relative
    ``OPENRCT2_DATA_DIR`` or ``OPENRCT2_BACKUP_DIR`` means the project folder.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-set", help="Must be company")
    parser.add_argument("--park", help="The company park's ID")
    parser.add_argument("--ready", help="The ready phrase; needed on a park's first run only")
    args = parser.parse_args(argv)
    if args.data_set != COMPANY:  # refusal 1
        say(f"{WRONG_DATA_SET} {NOTHING_WRITTEN}")
        return EXIT_REFUSED
    if not args.park:  # refusal 2; no data is read to list parks
        say(f"Give PARK=<park id>. {NOTHING_WRITTEN}")
        return EXIT_REFUSED
    handlers = {
        n: signal.getsignal(getattr(signal, n)) for n in lock.SIGNAL_NAMES if hasattr(signal, n)
    }
    lock.set_signal_handlers(lock.raise_interrupted)
    project = project_dir.resolve()
    chosen = options if options is not None else autopilot_options()
    try:
        cleared = _refuse(
            args.park,
            args.ready,
            options=chosen,
            build=build if build is not None else partial(pi.build_plugin, project),
            project=project,
            game_check=game_check if game_check is not None else platform_game_check(),
        )
        return _run_and_land(cleared, args.park, chosen, project)
    except Refused as refusal:
        say(str(refusal))
        return EXIT_REFUSED
    except lock.Interrupted:
        say(f"Interrupted. {NOTHING_WRITTEN}")
        return EXIT_INTERRUPTED
    finally:  # every handler this command changed is restored on every way out
        for name, handler in handlers.items():
            signal.signal(getattr(signal, name), handler)


if __name__ == "__main__":
    sys.exit(main())

"""Run the after-play steps for one company data set in order, stopping at the first failure.

The steps: register the waiting parks not yet registered (``make register-parks`` with
``--parks`` and ``--start-year``), the contract check (``make contracts``), the dbt build
(``make transform``), then the results summary (``make results``). ``--parks
"<id>:company,<id>:practice"`` must name every park with a session waiting (``play_status``).
``--start-year`` is checked before any step and passed to the register step. There is no state
file: rerunning the whole command resumes, because registered parks are skipped. Publishing is not
a step. Exit 0 every step passed, 1 a step failed, 2 refused before any step, 130 interrupted.
"""

from __future__ import annotations

import argparse
import shlex
import signal
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Never

import duckdb

from openrct2_analytics.config import DATA_SETS, ConfigError
from openrct2_analytics.ingest import lock, play_status, register_parks, results, unfiled
from openrct2_analytics.ingest.convert import landing_lock_path
from openrct2_analytics.ingest.landing_paths import landing
from openrct2_analytics.ingest.start_year import start_years

PROJECT_DIR = Path(__file__).resolve().parents[3]


class Refused(Exception):
    """The command was refused before any step ran."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class _AfterPlayParser(argparse.ArgumentParser):
    """Argument parser that reports invalid input as a refusal."""

    def error(self, message: str) -> Never:
        raise Refused("usage", message)


def _check_registered(
    parks: dict[str, bool], waiting: set[str], registered: dict[str, tuple[str, bool]]
) -> None:
    """Refuse an unknown listed park or one registered with the other choice.

    A park registered with the listed choice is skipped, so a rerun after a later step failed
    still starts.
    """
    unknown = sorted(park for park in parks if park not in waiting and park not in registered)
    if unknown:
        raise Refused("unknown-park", f"No waiting or registered park {', '.join(unknown)}")
    conflicts = sorted(
        park
        for park, practice in parks.items()
        if park in registered and registered[park][1] != practice
    )
    if conflicts:
        raise Refused(
            "choice-conflict",
            f"Park {', '.join(conflicts)} is already registered with the other choice",
        )


def check_can_start(data_set: str, project_dir: Path) -> play_status.PlayStatus:
    """Refuse an unsafe start (rehearsal, lock, building warehouse, seq-failed); return status."""
    if data_set == "rehearsal":
        raise Refused("rehearsal", "The capture command owns rehearsal deliveries")
    held = landing_lock_path(landing(data_set, project_dir).parquet)
    if held.exists():
        raise Refused("lock-taken", f'{held} exists; see ARCHITECTURE.md "Stale locks"')
    state, filed = play_status.warehouse_sessions(project_dir / play_status.WAREHOUSE, project_dir)
    if state == "building":
        raise Refused("warehouse-busy", "Another command is writing warehouse/dev/dev.duckdb")
    # Before read_status, which reads the registry feed: no registry read may come first.
    failed = unfiled.failed_waiting(landing(data_set, project_dir), filed)
    if failed:
        raise Refused("seq-failed", _seq_failed_detail(failed))
    status = play_status.read_status(data_set, project_dir)
    if status.warehouse == "building":
        raise Refused("warehouse-busy", "Another command is writing warehouse/dev/dev.duckdb")
    return status


def _seq_failed_detail(failed: dict[str, tuple[str, ...]]) -> str:
    named = "; ".join(
        f"session {session} of park {', '.join(parks)} failed its seq audit"
        for session, parks in sorted(failed.items())
    )
    return (
        f"{named}. Filing files every waiting session, so nothing is filed while one waits. "
        f"To see what removing it would do, run make delete-company-data SESSION={min(failed)} "
        "(a preview; it deletes nothing)"
    )


def _to_register(
    data_set: str, parks: dict[str, bool], start_year: int | None, project_dir: Path
) -> dict[str, bool]:
    """Refuse an unsafe start; return the listed waiting parks that are not registered yet."""
    status = check_can_start(data_set, project_dir)
    waiting = {park.park_id: park for session in status.sessions_waiting for park in session.parks}
    missing = sorted(waiting.keys() - parks.keys())
    if missing:
        raise Refused(
            "parks-missing", f"Choose company or practice (sandbox) for {', '.join(missing)}"
        )
    _check_registered(
        parks,
        set(waiting),
        register_parks.registered_parks(play_status.registry_feed_dir(data_set, project_dir)),
    )
    chosen = {
        park: practice
        for park, practice in parks.items()
        if park in waiting and not waiting[park].registered
    }
    if chosen:
        folders = landing(data_set, project_dir)
        start_years(
            chosen,
            start_year,
            parquet_dir=folders.parquet,
            raw_dir=folders.raw,
            feed=play_status.registry_feed_dir(data_set, project_dir),
        )
    return chosen


def _make(target: str, data_set: str) -> Callable[[], int]:
    # Make runs where the Makefile and the Python project live; ``project_dir`` only locates the
    # warehouse and relative landing folders, and is that same folder outside tests.
    def run() -> int:
        command = ["make", "--no-print-directory", target, f"DATA_SET={data_set}"]
        return subprocess.run(command, cwd=PROJECT_DIR, check=False).returncode

    return run


def _steps(
    data_set: str,
    chosen: dict[str, bool],
    start_year: int | None,
    project_dir: Path,
    *,
    registered: list[str] | None,
) -> list[tuple[str, str, Callable[[], int]]]:
    """Return each step's name, its own command for the reader, and how to run it."""
    steps: list[tuple[str, str, Callable[[], int]]] = []
    if chosen:
        listed = ",".join(f"{p}:{'practice' if flag else 'company'}" for p, flag in chosen.items())
        command = f"make register-parks DATA_SET={data_set} PARKS={shlex.quote(listed)}"
        arguments = ["--data-set", data_set, "--parks", listed]
        if start_year is not None:
            command += f" START_YEAR={start_year}"
            arguments.append(f"--start-year={start_year}")
        steps.append(
            (
                "register",
                command,
                lambda: register_parks.main(
                    arguments, project_dir=project_dir, registered=registered
                ),
            )
        )
    else:
        note = "after-play: register: no waiting park needs registering"
        if start_year is not None:
            note += f"; START_YEAR={start_year} not used"
        print(note)
    for target in ("contracts", "transform"):
        steps.append((target, f"make {target} DATA_SET={data_set}", _make(target, data_set)))
    steps.append(
        (
            "results",
            f"make results DATA_SET={data_set}",
            lambda: results.main(["--data-set", data_set], project_dir=project_dir),
        )
    )
    return steps


def _run(
    data_set: str,
    parks_text: str | None,
    start_year_text: str | None,
    project_dir: Path,
    *,
    registered: list[str] | None,
) -> int:
    # A malformed START_YEAR is refused first, even with nothing waiting.
    start_year = register_parks.parse_start_year(start_year_text)
    # An empty list (``PARKS=`` on the make command line) means no list was given.
    listed = (parks_text or "").strip()
    parks = register_parks.parse_parks(listed) if listed else {}
    chosen = _to_register(data_set, parks, start_year, project_dir)
    rerun = f"make after-play DATA_SET={data_set}"
    if listed:
        rerun += f" PARKS={shlex.quote(listed)}"
    if start_year is not None:
        rerun += f" START_YEAR={start_year}"
    for name, command, step in _steps(
        data_set, chosen, start_year, project_dir, registered=registered
    ):
        print(f"after-play: {name}: {command}", flush=True)
        code = step()
        if code != 0:
            print(
                f"after-play failed: step {name} exited {code} ({command}). "
                f"Fix the cause, then rerun the whole chain: {rerun}"
            )
            return 1
    print("after-play: every step passed")
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    project_dir: Path = PROJECT_DIR,
    registrations_landed: bool = False,
    registered: list[str] | None = None,
) -> int:
    """Run the after-play steps and map each outcome to its documented exit code.

    ``registered``, when given, receives the ID of each park this run wrote to a delivery.

    ``registrations_landed`` is true when the caller registered parks before this call, so a
    refusal here no longer leaves everything unchanged and its lines drop " Nothing was changed."
    """
    parser = _AfterPlayParser(description=__doc__)
    parser.add_argument("--data-set", choices=DATA_SETS, required=True)
    parser.add_argument("--parks", help='Every waiting park: "<id>:company,<id>:practice"')
    parser.add_argument("--start-year", help="Company start year of the one company park")
    handlers = {
        name: signal.getsignal(getattr(signal, name))
        for name in lock.SIGNAL_NAMES
        if hasattr(signal, name)
    }
    lock.set_signal_handlers(lock.raise_interrupted)
    unchanged = "" if registrations_landed else " Nothing was changed."
    try:
        args = parser.parse_args(argv)
        code = _run(
            args.data_set, args.parks, args.start_year, project_dir.resolve(), registered=registered
        )
    except Refused as error:
        print(f"after-play refused: {error.reason}: {error.detail}.{unchanged}")
        code = 2
    except register_parks.Refused as error:
        print(f"after-play refused: {error.reason}: {error.detail}.{unchanged}")
        code = 2
    except ConfigError as error:
        print(f"after-play refused: data-set: {error}.{unchanged}")
        code = 2
    except (OSError, ValueError, duckdb.Error) as error:
        print(f"after-play failed: io: {error}")
        code = 1
    except (lock.Interrupted, KeyboardInterrupt):
        print("after-play interrupted")
        code = 130
    finally:
        for name, handler in handlers.items():
            signal.signal(getattr(signal, name), handler)
    return code


if __name__ == "__main__":
    sys.exit(main())

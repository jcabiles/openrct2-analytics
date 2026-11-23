"""Preview or archive and delete company data, respecting the go-live cutoff."""

from __future__ import annotations

import argparse
import csv
import os
import platform
import shlex
import signal
import socket
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, chdir, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from openrct2_analytics import state
from openrct2_analytics.config import MAX_PORT, Config, ConfigError, data_root, landing_dirs
from openrct2_analytics.ingest import delete_apply, delete_archive, game_check, lock
from openrct2_analytics.ingest.capture import REPO_ROOT
from openrct2_analytics.ingest.convert import landing_lock_path
from openrct2_analytics.ingest.delete_plan import Plan, Scope, named_plan, print_plan
from openrct2_analytics.ingest.landing_paths import project_path
from openrct2_analytics.ingest.plugin_install import resolve_user_dir
from openrct2_analytics.ingest.publish_errors import PublishFailed, PublishRefused
from openrct2_analytics.ingest.publish_prepare import guard_path
from openrct2_analytics.ingest.registry_feed import registry_dir
from openrct2_analytics.ingest.site_company_land import (
    INPUT_PREFIX,
    STAGE_PREFIX,
    is_company_build,
)


def _port(text: str) -> int:
    value = int(text)
    if not 1 <= value <= MAX_PORT:
        raise argparse.ArgumentTypeError(f"must be 1-{MAX_PORT}, got {text!r}")
    return value


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    scopes = parser.add_mutually_exclusive_group()
    scopes.add_argument("--park")
    scopes.add_argument("--session")
    parser.add_argument("--confirm")
    parser.add_argument("--game-check-command")
    parser.add_argument("--port", type=_port, default=8765)
    return parser.parse_args(argv)


def _check_company_root(root: Path) -> None:
    # The alias checks in landing_dirs compare leaf folders only, so a company folder that is
    # itself a link (to the data root, or to rehearsal data) would pass them.
    company = root / "company"
    if company.is_symlink() or company.resolve() != root.resolve() / "company":
        raise PublishRefused(
            "unsafe-path", f"{company} is a link or resolves outside {root.resolve()}/company"
        )


def _settings(project: Path, scope: Scope) -> tuple[Path, Path, Config]:
    # The company folder check and the ID lookup precede the alias validation in landing_dirs.
    root = project_path(data_root(), project).absolute()
    _check_company_root(root)
    if scope.named:
        named_plan(scope, root / "company")
    config = Config.from_env()  # a ConfigError here is a data-set refusal, as in main()
    try:
        folder = state.state_dir()
        state.check_state_dir(folder, root, project, resolve_user_dir(config, platform.system()))
    except ConfigError as error:
        raise PublishRefused("unsafe-state-dir", str(error)) from error
    delete_archive.check_destination(folder, root, project)
    landing_dirs("company")
    registry_dir("company")
    warehouse = project / "warehouse"
    for path in (warehouse / "company.duckdb", warehouse / "previous/company.duckdb"):
        guard_path(path, root=warehouse, project_dir=project, allow=frozenset({"published"}))
    return root, folder, config


@contextmanager
def _capture_probes(args: argparse.Namespace, config: Config) -> Iterator[None]:
    system = platform.system()
    check = (
        game_check.command_check(shlex.split(args.game_check_command))
        if args.game_check_command
        else game_check.default_check(system, game_check.DEFAULT_PROCESS.get(system, "OpenRCT2"))
    )
    answer = check()
    if answer is not game_check.GameState.NOT_RUNNING:
        raise PublishRefused("capture-running", f"game check: {answer.value}")
    with ExitStack() as stack:
        for port in sorted({args.port, config.listener_port}):
            try:
                # The plugin sends to 127.0.0.1; the listener binds its configured host. Hosts
                # are compared by address: "localhost" and 127.0.0.1 are one bind, not two.
                addresses = {
                    socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][4]
                    for host in ("127.0.0.1", config.listener_host)
                }
                for address in sorted(addresses):
                    probe = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
                    probe.bind(address)
                    probe.listen()
            except (OSError, OverflowError) as error:
                raise PublishRefused("capture-running", f"port {port}: {error}") from error
        if args.confirm is None:
            stack.close()
        yield


@contextmanager
def _locks(project: Path, company: Path) -> Iterator[None]:
    warehouse = project / "warehouse"
    warehouse.mkdir(parents=True, exist_ok=True)
    company.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC).isoformat()
    with (
        lock.hold_lock(warehouse / "company.lock", f"delete {os.getpid()} {started}"),
        lock.hold_lock(
            landing_lock_path(company / "parquet"), f"pid {os.getpid()} started {started}"
        ),
    ):
        yield


def _local_site_folders(project: Path) -> list[Path]:
    """List `local/site-data` and the stage and input folders a killed site-company run leaves."""
    folders = [project / "local/site-data"] if os.path.lexists(project / "local/site-data") else []
    for prefix in (STAGE_PREFIX, INPUT_PREFIX):
        folders.extend(sorted((project / "local").glob(f"{prefix}*")))
    return folders


def _site_outputs(project: Path) -> tuple[list[Path], list[str]]:
    """List the company site outputs and explain a ``site/_site/`` that is kept."""
    paths: list[Path] = []
    notes = []

    site_data = project / "local/site-data"
    unsafe_local = False
    for relative in ("local", "local/site-data"):
        folder = project / relative
        if folder.is_symlink() or (folder.exists() and folder.resolve() != folder):
            notes.append(
                f"site data kept ({relative}/ is a link or resolves outside the project): "
                f"{site_data}"
            )
            unsafe_local = True
            break
    if not unsafe_local:
        paths.extend(_local_site_folders(project))

    built = project / "site/_site"
    unsafe_site = False
    for relative in ("site", "site/_site"):
        folder = project / relative
        if folder.is_symlink() or (folder.exists() and folder.resolve() != folder):
            if relative == "site/_site" and folder.is_symlink():
                notes.append(f"site build kept (a symbolic link): {built}")
            else:
                notes.append(
                    f"site build kept ({relative}/ is a link or resolves outside the project): "
                    f"{built}"
                )
            unsafe_site = True
            break
    if not unsafe_site and is_company_build(built):
        paths.append(built)
    elif not unsafe_site and built.exists():
        notes.append(f"site build kept (not a company build): {built}")
    return paths, notes


def _plan(scope: Scope, root: Path, project: Path, live: str | None) -> Plan:
    plan = delete_apply.build_plan(scope, root / "company", project / "warehouse", live)
    paths, notes = _site_outputs(project)
    plan.derived.extend(paths)
    plan.notes.extend(notes)
    return plan


def _execute(
    scope: Scope,
    paths: tuple[Path, Path, Path],
    live: str | None,
    on_step: delete_archive.StepObserver,
) -> None:
    project, root, folder = paths
    company = root / "company"
    with _locks(project, company):
        on_step("locked")
        # Recheck permanent-state evidence after acquiring locks too.
        inside = state.is_live(folder, root)
        live = inside if inside is not None else live
        _check_live(scope, live)
        if scope.named:
            for check, problems in (
                ("registry-check", delete_apply.registry_problems(company)),
                ("label-check", delete_apply.label_problems(company)),
            ):
                if problems:
                    raise PublishRefused(
                        check, f"{'; '.join(problems)}; fix the failing delivery first"
                    )
        plan = _plan(scope, root, project, live)
        print_plan(plan, company)
        if not plan.changes and not plan.derived:
            print("no company data")
            return
        archive = (
            delete_archive.archive(plan, folder, root, project, on_step=on_step)
            if plan.changes
            else None
        )
        if archive is not None:
            print(f"archive: {archive}")
        delete_apply.apply(plan, company, on_step)
        if archive is not None:
            delete_archive.complete(archive)
        rewritten = sum(change.kept is not None for change in plan.changes)
        print(
            f"{len(plan.changes)} files archived; {rewritten} rewritten; "
            f"{len(plan.changes) - rewritten + len(plan.derived)} paths removed"
        )


def _check_live(scope: Scope, live: str | None) -> None:
    if scope.named and live is not None:
        raise PublishRefused("live", f"raw captures are permanent since {live}")


def _run(args: argparse.Namespace, project: Path, on_step: delete_archive.StepObserver) -> int:
    scope = Scope(args.park, args.session)
    root, folder, config = _settings(project, scope)
    with _capture_probes(args, config):
        live = state.is_live(folder, root)
        _check_live(scope, live)
        if args.confirm is not None and args.confirm != scope.phrase:
            raise PublishRefused("confirmation", f"expected {scope.phrase!r}")
        if args.confirm is None:
            print_plan(_plan(scope, root, project, live), root / "company")
        else:
            _execute(scope, (project, root, folder), live, on_step)
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    project_dir: Path = REPO_ROOT,
    on_step: delete_archive.StepObserver = lambda _: None,
) -> int:
    """Run a preview or confirmed deletion; return publish-compatible exit codes."""
    args = _arguments(argv)
    handlers = {
        name: signal.getsignal(getattr(signal, name))
        for name in lock.SIGNAL_NAMES
        if hasattr(signal, name)
    }
    lock.set_signal_handlers(lock.raise_interrupted)
    try:
        project = project_dir.resolve()
        with chdir(project):
            code = _run(args, project, on_step)
    except PublishRefused as error:
        print(f"delete refused: {error.reason}: {error.detail}. Nothing was changed.")
        code = 2
    except lock.LockTaken as error:
        print(
            f'delete refused: lock-taken: {error}; see ARCHITECTURE.md "Stale locks". '
            "Nothing was changed."
        )
        code = 2
    except ConfigError as error:
        print(f"delete refused: data-set: {error}. Nothing was changed.")
        code = 2
    except PublishFailed as error:
        print(f"delete failed: {error.reason}: {error.detail}")
        code = 1
    except (OSError, csv.Error, UnicodeDecodeError) as error:
        print(f"delete failed: io: {error}")
        code = 1
    except (lock.Interrupted, KeyboardInterrupt):
        print("delete interrupted")
        code = 130
    finally:
        for name, handler in handlers.items():
            signal.signal(getattr(signal, name), handler)

    return code


if __name__ == "__main__":
    raise SystemExit(main())

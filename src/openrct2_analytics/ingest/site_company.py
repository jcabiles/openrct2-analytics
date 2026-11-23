"""Build the public site from the published company warehouse, in one command.

Steps, in order: refuse a rehearsal data set, a publish lock and a missing or linked published
file; take the published file's identity; refuse a linked or misplaced output folder, a linked
entry in ``site/`` and a missing ``npm``; refuse a sandbox park; export
``warehouse/company.duckdb`` read-only to a stage folder under ``local/``; run the sample-record
guard on the staged record; build the site there; run the page check; write the build stamp;
re-check the published file and the lock, then rename the staged folders onto
``local/site-data/`` and ``site/_site/`` (``site_company_land``). Temporary folders live under
``local/``. The committed ``site/_data/`` is never written.
Exit 0 done, 1 failed, 2 refused, 130 interrupted.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Never

import duckdb

from openrct2_analytics.config import DATA_SETS
from openrct2_analytics.ingest import lock, register_parks
from openrct2_analytics.ingest import site_company_land as land
from openrct2_analytics.showcase import export, page_check
from openrct2_analytics.showcase.page_check_site import PageCheckFailed

PROJECT_DIR = Path(__file__).resolve().parents[3]
SiteBuild = Callable[[Path, Path], int]
_PRACTICE_TABLE = "intermediate.int_park_registry__current"
_RECORD_FIELDS = export.SAMPLE_ENTRY.columns[1:]  # the columns after data_set


class _Refused(Exception):
    """The command was refused before anything was changed."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class StepFailed(Exception):
    """A step failed after work began; nothing was landed."""

    def __init__(self, step: str, detail: str) -> None:
        super().__init__(detail)
        self.step = step
        self.detail = detail


class _SiteCompanyParser(argparse.ArgumentParser):
    """Argument parser that reports invalid input as a refusal."""

    def error(self, message: str) -> Never:
        raise _Refused("usage", message)


def npm_build(page_input: Path, output: Path) -> int:
    """Run the real site build from the repository root, where ``package.json`` is."""
    return subprocess.run(
        [
            "npm",
            "run",
            "--silent",
            "site:build",
            "--",
            f"--input={page_input}",
            f"--output={output}",
        ],
        cwd=PROJECT_DIR,
        check=False,
    ).returncode


def _refuse_link(project: Path, relative: str, reason: str) -> None:
    """Refuse when ``relative`` under the project folder is a symbolic link."""
    if (project / relative).is_symlink():
        raise _Refused(reason, f"{relative} is a symbolic link")


def _check_published_path(project: Path) -> None:
    """Refuse a linked `warehouse/` folder or published file, before either is read."""
    for relative in ("warehouse", land.PUBLISHED.as_posix()):
        _refuse_link(project, relative, "published-file")


def _check_site_tree(project: Path) -> None:
    """Refuse a symbolic link anywhere in the part of `site/` that the build copies."""
    site = project / "site"
    for folder, names, files in os.walk(site):
        if Path(folder) == site:
            names[:] = [name for name in names if name not in ("_data", "_site")]
        for name in (*names, *files):
            _refuse_link(
                project, (Path(folder) / name).relative_to(project).as_posix(), "site-tree"
            )


def _check_output_folders(project: Path) -> None:
    """Refuse a linked, aliased or non-folder output, or `local/` and `site/` on two filesystems."""
    for relative in ("local", "local/site-data", "site", "site/_site"):
        folder = project / relative
        _refuse_link(project, relative, "output-folders")
        if folder.exists() and folder.resolve() != project / relative:
            raise _Refused("output-folders", f"{relative}/ resolves outside {relative}/")
        if folder.exists() and not folder.is_dir():
            raise _Refused("output-folders", f"{relative}/ is not a folder")
    local = project / "local"
    if (local if local.exists() else project).stat().st_dev != (project / "site").stat().st_dev:
        raise _Refused("output-folders", "local/ and site/ are on different filesystems")


def _check_practice_parks(published: Path) -> None:
    """Refuse a published file that lists a park registered as a throwaway sandbox park."""
    connection = duckdb.connect(str(published), read_only=True)
    try:
        rows = connection.execute(
            f"select park_id from {_PRACTICE_TABLE} where note = ? order by park_id",
            [register_parks.NOTE],
        ).fetchall()
    except (duckdb.CatalogException, duckdb.BinderException) as error:
        raise _Refused("registry", f"{_PRACTICE_TABLE} is missing from {land.PUBLISHED}") from error
    finally:
        connection.close()
    if rows:
        parks = [str(row[0]) for row in rows]
        commands = ", ".join(f"make delete-company-data PARK={park}" for park in parks)
        raise _Refused(
            "practice-park",
            f"the published warehouse lists sandbox park {', '.join(parks)}; "
            f"remove each with {commands}",
        )


def _record_row(path: Path, name: str) -> dict[str, object]:
    """The one row of a ``sample.json`` record; refuse a missing, malformed or incomplete file."""
    try:
        row = json.loads(path.read_text())["rows"][0]
        return {field: row[field] for field in ("data_set", *_RECORD_FIELDS)}
    except FileNotFoundError as error:
        raise _Refused("sample-record", f"the {name} is missing") from error
    except (OSError, ValueError, LookupError, TypeError) as error:
        raise _Refused(
            "sample-record", f"the {name} is not a valid sample record: {error}"
        ) from error


def _sample_guard(project: Path, exports: Path) -> None:
    """Refuse a staged sample record that is not the company's or repeats the committed one."""
    staged = _record_row(exports / "sample.json", "staged sample.json")
    committed = _record_row(
        project / "site" / "_data" / "sample.json", "committed site/_data/sample.json"
    )
    if staged["data_set"] != "company":
        raise _Refused(
            "sample-record",
            f"the staged sample.json has data_set {staged['data_set']}, not company",
        )
    if all(staged[field] == committed[field] for field in _RECORD_FIELDS):
        raise _Refused(
            "sample-record",
            "the staged sample.json holds the same parks, sessions and player_played as the "
            "committed site/_data/sample.json, so the page would state the committed sample, "
            "not the company data",
        )


def _build_and_land(
    project: Path, site_build: SiteBuild, stage: Path, start: land.PublishedStamp
) -> int:
    """Export, guard, build, check, stamp and land; return the number of exported files."""
    published = project / land.PUBLISHED
    exports, built = stage / land.EXPORTS_STAGE, stage / land.SITE_STAGE
    try:
        export.run(
            "write",
            published,
            export.load_allowlist(project / "site" / "exports.toml"),
            exports,
            data_set="company",
        )
    except export.ExportRefused as error:
        raise _Refused("export", str(error)) from error
    # Before the build: the page template reads the staged record and would crash on a bad one.
    _sample_guard(project, exports)
    with tempfile.TemporaryDirectory(prefix=land.INPUT_PREFIX, dir=project / "local") as scratch:
        page_input = Path(scratch) / "input"
        site = project / "site"
        shutil.copytree(
            site,
            page_input,
            ignore=lambda folder, names: (
                [name for name in names if name in ("_data", "_site")]
                if Path(folder) == site
                else []
            ),
        )
        shutil.copytree(exports, page_input / "_data")
        code = site_build(page_input, built)
    if code != 0:
        raise StepFailed("site-build", f"the site build exited {code}")
    if not (built / "index.html").is_file():
        raise StepFailed("site-build", "the site build wrote no index.html")
    try:
        page_check.check_page(built, exports)
    except PageCheckFailed as error:
        raise StepFailed("page-check", str(error)) from error
    land.write_stamp(built)
    count = sum(1 for path in exports.iterdir() if path.is_file())
    try:
        land.land(project, stage, start)
    except land.LandRefused as error:
        raise _Refused(error.reason, error.detail) from error
    return count


def _run(data_set: str, project: Path, site_build: SiteBuild) -> None:
    """Run the checks in the documented order, then build and land; print the last line."""
    if data_set != "company":
        raise _Refused("data-set", f"{data_set} figures never reach the site")
    if (project / land.LOCK).exists():
        raise _Refused("lock", f"{land.LOCK.as_posix()} exists; a publish, rollback or delete runs")
    _check_published_path(project)
    published = project / land.PUBLISHED
    if not published.is_file():
        raise _Refused(
            "published-file", "no published company file; run make publish DATA_SET=company"
        )
    # The published file's identity is taken here so that the re-check before landing covers
    # every later step, the practice-park check included.
    start = land.snapshot(project)
    _check_output_folders(project)
    _check_site_tree(project)
    if shutil.which("npm") is None:
        raise _Refused("tools", "npm is not on PATH; run make setup")
    _check_practice_parks(published)
    local = project / "local"
    created = not local.exists()
    local.mkdir(exist_ok=True)
    try:
        stage = local / f"{land.STAGE_PREFIX}{os.getpid()}"
        stage.mkdir()
        keep_stage = False
        try:
            count = _build_and_land(project, site_build, stage, start)
        except land.LandStuck:
            # The stage holds the only copy of the earlier outputs; main prints its path.
            keep_stage = True
            raise
        finally:
            if not keep_stage:
                shutil.rmtree(stage)
    finally:
        if created and not any(local.iterdir()):
            local.rmdir()
    print(
        f"site-company: exported {count} files from warehouse/company.duckdb to "
        "local/site-data/; built site/_site/"
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    project_dir: Path = PROJECT_DIR,
    site_build: SiteBuild = npm_build,
) -> int:
    """Run the command and map each outcome to its documented exit code."""
    parser = _SiteCompanyParser(description=__doc__)
    parser.add_argument("--data-set", choices=DATA_SETS, required=True)
    handlers = {
        name: signal.getsignal(getattr(signal, name))
        for name in lock.SIGNAL_NAMES
        if hasattr(signal, name)
    }
    lock.set_signal_handlers(lock.raise_interrupted)
    try:
        args = parser.parse_args(argv)
        _run(args.data_set, project_dir.resolve(), site_build)
        code = 0
    except _Refused as error:
        print(f"site-company refused: {error.reason}: {error.detail}. Nothing was changed.")
        code = 2
    except StepFailed as error:
        print(f"site-company failed: {error.step}: {error.detail}")
        code = 1
    except land.LandStuck as error:
        print(
            f"site-company failed: landing: {error.detail}; the stage folder {error.stage} "
            "was kept and holds the earlier outputs; nothing was deleted"
        )
        code = 1
    except (OSError, ValueError, duckdb.Error) as error:
        print(f"site-company failed: io: {error}")
        code = 1
    except (lock.Interrupted, KeyboardInterrupt):
        print("site-company interrupted")
        code = 130
    finally:
        for name, handler in handlers.items():
            signal.signal(getattr(signal, name), handler)
    return code


if __name__ == "__main__":
    sys.exit(main())

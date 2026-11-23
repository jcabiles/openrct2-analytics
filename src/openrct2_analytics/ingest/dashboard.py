"""Serve the company dashboard on localhost from the development warehouse.

The dashboard is the five-page app in ``src/openrct2_analytics/dashboard/app/`` (ADR 0054), filled
with figures from ``warehouse/dev/dev.duckdb``, the file ``make after-play`` rebuilds. Each load of
a page rebuilds the data when that file changed since the last attempt: the file is copied into
``local/dashboard/`` and only the copy is opened, so the server never takes DuckDB's lock on the
warehouse a build is writing; the data builder reads the copy's marts, and the app files and the
new ``data.js`` go into a build folder. A failed rebuild keeps the last good build and names the
failure in a banner on every page. Nothing outside ``local/dashboard/`` is written.
Exit 0 stopped, 1 failed, 2 refused, 130 interrupted.
"""

from __future__ import annotations

import argparse
import errno
import html
import json
import posixpath
import re
import shutil
import signal
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from socket import socket
from typing import Any, Never, cast
from urllib.parse import unquote

import duckdb

from openrct2_analytics.config import DATA_SETS, ConfigError, LandingDirs
from openrct2_analytics.dashboard import data
from openrct2_analytics.ingest import (
    capture_session,
    dashboard_sandbox,
    landing_paths,
    managed_years,
    park_label,
    play_status,
    unfiled,
)
from openrct2_analytics.ingest.convert import landing_lock_path
from openrct2_analytics.ingest.game_check import GameCheck, platform_game_check

PROJECT_DIR = Path(__file__).resolve().parents[3]
APP = Path(data.__file__).parent / "app"
DEV_WAREHOUSE = Path("warehouse/dev/dev.duckdb")
ROOT = Path("local/dashboard")
HOST = "127.0.0.1"
DEFAULT_PORT = 8780
PING_PATH = "/_dashboard/ping"
PING_BODY = b"openrct2-dashboard\n"
PAGES = ("executive.html", "finance.html", "attractions.html", "pricing.html", "operations.html")
_PAGE_PATHS = {"/": PAGES[0], "/index.html": PAGES[0], **{f"/{page}": page for page in PAGES}}
DATA_FILE = "data.js"
_BUILD_PREFIX = "build-"
_BUSY = (
    f"{DEV_WAREHOUSE.as_posix()} is being built; reload when make after-play finishes "
    "(if nothing is running, run make transform DATA_SET=company)"
)
_COPY = "warehouse.duckdb"
_BODY = re.compile(r"<body[^>]*>")
_STAMP = "%Y-%m-%d %H:%M"

Fingerprint = tuple[int, int]
UnfiledKey = tuple[object, ...]
RebuildError = (duckdb.Error, OSError)
UnfiledError = (duckdb.Error, OSError, ValueError, ConfigError)


class _Refused(Exception):
    """The server was not started."""


class _Parser(argparse.ArgumentParser):
    """Argument parser that reports invalid input as a refusal."""

    def error(self, message: str) -> Never:
        raise _Refused(message)


def _wal_path(warehouse: Path) -> Path:
    return warehouse.with_name(f"{warehouse.name}.wal")


class _NotReady(Exception):
    """The warehouse cannot be copied safely yet; the next page load tries again."""


@dataclass(frozen=True)
class Build:
    """One build: its folder, the warehouse state it came from, and its warnings."""

    folder: Path
    source: Fingerprint
    source_time: datetime
    built_at: datetime
    warnings: tuple[str, ...]
    sandbox: tuple[str, ...]
    filed: frozenset[str]

    @property
    def site(self) -> Path:
        """The folder of app files and ``data.js`` that the server serves."""
        return self.folder / "site"


def _warnings(copy: Path) -> tuple[str, ...]:
    """Name a data set other than company."""
    connection = duckdb.connect(str(copy), read_only=True)
    try:
        sets = [
            str(row[0])
            for row in connection.execute(
                "select distinct data_set from marts.dim_park order by data_set"
            ).fetchall()
        ]
    finally:
        connection.close()
    warnings = []
    if any(data_set != "company" for data_set in sets):
        warnings.append(
            f"The working copy holds {', '.join(sets)} data, not only company data; "
            "run make transform DATA_SET=company to rebuild it from company data."
        )
    return tuple(warnings)


def _write_data(site: Path, figures: dict[str, object], source_time: datetime) -> None:
    """Write the pages' data as one global, stamped with the warehouse's time."""
    stamped = {**figures, "as_of": source_time.strftime(_STAMP)}
    (site / DATA_FILE).write_text(f"window.DASHBOARD = {json.dumps(stamped)};\n")


class Dashboard:
    """The current build and the outcome of the last rebuild."""

    def __init__(
        self,
        project: Path,
        *,
        clock: Callable[[], float] = time.time,
        game: GameCheck | None = None,
    ) -> None:
        self.project = project
        self.clock = clock
        self.game = platform_game_check() if game is None else game
        self._unfiled_key: UnfiledKey | None = None
        self._recheck_at: float | None = None
        self.unfiled_line: str | None = None
        self.names_line: str | None = None
        self._labels: dict[str, str] = {}
        self.current: Build | None = None
        self.problem: str | None = None
        self._tried: Fingerprint | None = None
        # The rebuild-failure problem of the warehouse state in ``_tried``; None when it built.
        self._failure: str | None = None
        self.root = project / ROOT
        self.empty = self.root / "empty"

    def start(self) -> None:
        """Create the work folder and remove builds that an earlier server left."""
        for relative in ("local", ROOT.as_posix()):
            if (self.project / relative).is_symlink():
                raise _Refused(f"{relative} is a symbolic link")
        self.empty.mkdir(parents=True, exist_ok=True)
        for old in self.root.glob(f"{_BUILD_PREFIX}*"):
            shutil.rmtree(old)

    def static_root(self) -> Path:
        """The folder that requests other than the pages are served from."""
        return self.current.site if self.current is not None else self.empty

    def refresh(self) -> None:
        """Rebuild when the warehouse changed since the last try, then update the unfiled line."""
        missing = self._refresh_warehouse()
        self._refresh_unfiled(missing)

    def _refresh_warehouse(self) -> bool:
        """Rebuild when the warehouse changed; keep the old build on error. True when missing."""
        warehouse = self.project / DEV_WAREHOUSE
        source = managed_years.file_key(warehouse)
        if source is None:
            self.problem = (
                f"{DEV_WAREHOUSE.as_posix()} is missing; run make after-play DATA_SET=company"
            )
            return True
        if source == self._tried:
            # The same file: only a wal (a build is writing) or a past failure of this file can
            # leave the kept build stale; any other earlier problem, such as a missing file, ends.
            self.problem = _BUSY if _wal_path(warehouse).exists() else self._failure
            return False
        try:
            build = self._build(warehouse, source)
        except _NotReady as error:
            self.problem = str(error)
            return False
        except RebuildError as error:
            # Deliberate: the server keeps serving the last good build, and the banner and the log
            # carry the reason; the same warehouse state is not retried until it changes.
            self._tried = source
            hint = dashboard_sandbox.REBUILD_HINT if "park_number" in str(error) else ""
            self._failure = self.problem = f"the rebuild failed: {error}{hint}"
            print(f"dashboard: {self.problem}", file=sys.stderr)
            return False
        self._tried, self._failure = source, None
        previous, self.current, self.problem = self.current, build, None
        if previous is not None:
            shutil.rmtree(previous.folder)
        return False

    def _build(self, warehouse: Path, source: Fingerprint) -> Build:
        wal = _wal_path(warehouse)
        if wal.exists():
            raise _NotReady(_BUSY)
        folder = Path(tempfile.mkdtemp(prefix=_BUILD_PREFIX, dir=self.root))
        try:
            copy = folder / _COPY
            shutil.copyfile(warehouse, copy)
            if managed_years.file_key(warehouse) != source or wal.exists():
                raise _NotReady(_BUSY)
            warnings = _warnings(copy)
            figures = data.build(copy)
            parks = cast(list[dict[str, Any]], figures["parks"])
            sandbox = tuple(str(park["id"]) for park in parks if park["sandbox"])
            # The copy is never locked, so its state is always ready.
            filed = frozenset(play_status.warehouse_sessions(copy, self.project)[1] or ())
            copy.unlink()
            site = folder / "site"
            shutil.copytree(APP, site)
            source_time = datetime.fromtimestamp(source[0] / 1e9)
            _write_data(site, figures, source_time)
        except BaseException:
            shutil.rmtree(folder)
            raise
        return Build(folder, source, source_time, datetime.now(), warnings, sandbox, filed)

    def _refresh_unfiled(self, missing: bool) -> None:
        """Recompute the unfiled line when its files, game state or recheck time changed."""
        if not missing and self.current is None:
            self.unfiled_line, self._unfiled_key, self._recheck_at = None, None, None
            self.names_line, self._labels = None, {}
            return
        stale = self.current is not None and self.problem is not None and not missing
        filed = frozenset() if self.current is None or missing else self.current.filed
        source = "missing" if self.current is None or missing else self.current.folder
        now = self.clock()
        try:
            landing = landing_paths.landing("company", self.project)
            game = self.game()
            locked = landing_lock_path(landing.parquet).exists()
            key = (source, *unfiled.input_key(landing), game, locked, stale)
            due = self._recheck_at is not None and now >= self._recheck_at
            if key == self._unfiled_key and not due:
                return
            self._unfiled_key = key
            read_labels = self._refresh_names(landing)
            result = unfiled.find_unfiled(
                landing,
                set(filed),
                warehouse="ready" if source != "missing" else "missing",
                now=now,
                game=game,
                lock_present=locked,
                **({} if read_labels is None else {"park_labels": read_labels}),
            )
        except UnfiledError as error:
            # Deliberate: the banner and the log carry the reason. A failure of the check itself is
            # not tried again until the files change; a failure before the key exists (landing
            # folders, stat) is retried on each load but logged once while the message is the same.
            line = f"Play waiting to be filed could not be checked: {error}."
            if line != self.unfiled_line:
                print(f"dashboard: {line}", file=sys.stderr)
            self.unfiled_line = line
            self._recheck_at = None
            return
        self._recheck_at = result.recheck_at
        # An unreadable raw file withholds the app's offer, not this line: the banner reads as
        # it did before that reason existed (a live recording file still gives the recording line).
        unreadable = result.reason == "unreadable"
        recording = result.reason == "recording" or (unreadable and result.recheck_at is not None)
        offered = result.offer or (bool(result.parks) and unreadable and not recording)
        count = result.offerable_parks if offered and not stale else len(result.parks)
        noun = "1 park has" if count == 1 else f"{count} parks have"
        if result.parks and result.reason == "failed":
            self.unfiled_line = (
                f"{noun} play that can't be filed right now; a session failed its recording-gap "
                "check, so the app will not offer it"
            )
        elif result.parks and stale:
            self.unfiled_line = (
                f"{noun} play that may still be waiting to be filed; this page shows older data, "
                "so check in the OpenRCT2 Enterprise app"
            )
        elif result.parks and recording:
            self.unfiled_line = (
                f"{noun} play that can't be filed right now; the OpenRCT2 Enterprise app will "
                "offer it when it can"
            )
        elif offered:
            self.unfiled_line = (
                f"{noun} play waiting to be filed; open the OpenRCT2 Enterprise app to file it"
            )
        else:
            self.unfiled_line = None

    def _refresh_names(self, landing: LandingDirs) -> dict[str, str] | None:
        """Read the Sandbox parks' labels from the landing files; keep the figures on a failure.

        Returns the labels for the unfiled check to reuse (empty after a failed read, so it is not
        read again), or None when this build has no Sandbox park and nothing was read.
        """
        self._labels, previous, self.names_line = {}, self.names_line, None
        if self.current is None or not self.current.sandbox:
            return None
        try:
            self._labels = park_label.labels(park_label.park_facts(landing))
        except UnfiledError as error:
            # Deliberate: the figures stay, each Sandbox park shows by its ID, and the banner and
            # the log carry the reason; the read is not retried until the keyed files change.
            self.names_line = (
                f"Park names could not be read: {error}; Sandbox parks are shown by ID, "
                "first-played date unavailable."
            )
            if self.names_line != previous:
                print(f"dashboard: {self.names_line}", file=sys.stderr)
        return self._labels

    def banner(self) -> str:
        """The status lines shown above every page, escaped for HTML."""
        lines = []
        if self.current is not None:
            lines.append(
                f"Local dashboard from the working copy ({DEV_WAREHOUSE.as_posix()}), not the "
                f"published file. Figures as of {self.current.source_time.strftime(_STAMP)}; "
                "reload the page after make after-play to update them."
            )
        if self.problem is not None:
            kept = "The figures below are the last good build. " if self.current is not None else ""
            lines.append(f"{kept}Not updated: {self.problem}.")
        if self.current is not None:
            lines.extend(self.current.warnings)
            lines.extend(dashboard_sandbox.sandbox_sentences(self.current.sandbox, self._labels))
        if self.names_line is not None:
            lines.append(self.names_line)
        if self.unfiled_line is not None:
            lines.append(self.unfiled_line)
        items = "".join(f"<p style='margin:0.25em 0'>{html.escape(line)}</p>" for line in lines)
        return (
            "<div role='status' style='background:#fff4cc;color:#2b2100;padding:0.5em 1em;"
            f"font:14px/1.4 system-ui,sans-serif;border-bottom:1px solid #c9a400'>{items}</div>"
        )

    def page(self, name: str) -> tuple[int, bytes]:
        """The status code and body of one page of the app, with the banner after ``<body>``."""
        if self.current is None:
            body = f"<!doctype html><title>Park company dashboard</title><body>{self.banner()}"
            return 503, body.encode()
        text = (self.current.site / name).read_text()
        script = ""
        if self.current.sandbox:
            script = dashboard_sandbox.labels_script(self.current.sandbox, self._labels)
        shown = self.banner() + script
        return 200, _BODY.sub(lambda match: match.group(0) + shown, text, 1).encode()


class _Server(HTTPServer):
    """A single-threaded server, so a rebuild never runs while another request reads files."""

    def __init__(self, address: tuple[str, int], dashboard: Dashboard) -> None:
        self.dashboard = dashboard
        super().__init__(address, _Handler)


class _Handler(SimpleHTTPRequestHandler):
    """Serve the ping, the dashboard pages, and the current build's files."""

    server: _Server
    # A browser's idle spare connection would otherwise hold the single-threaded server.
    timeout = 5

    def __init__(self, request: socket, client_address: tuple[str, int], server: _Server) -> None:
        super().__init__(
            request, client_address, server, directory=str(server.dashboard.static_root())
        )

    def do_GET(self) -> None:
        """Answer the ping, rebuild and send a page, or serve a file of the current build."""
        # The static handler decodes and normalizes the path, so every spelling of a page's path
        # (`/%65xecutive.html`, `/./executive.html`) must be decided the same way here.
        path = posixpath.normpath(
            "/" + unquote(self.path.split("?", 1)[0].split("#", 1)[0]).lstrip("/")
        )
        if path == PING_PATH:
            self._send(200, "text/plain; charset=utf-8", PING_BODY)
        elif path in _PAGE_PATHS:
            dashboard = self.server.dashboard
            dashboard.refresh()
            code, body = dashboard.page(_PAGE_PATHS[path])
            self._send(code, "text/html; charset=utf-8", body)
        else:
            super().do_GET()

    def end_headers(self) -> None:
        """Mark every answer uncacheable, so a reload after a rebuild gets the new data.js."""
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _send(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(project: Path, port: int) -> _Server:
    """Bind the server, then prepare the dashboard; the caller runs ``serve_forever``.

    Binding comes first so that a refused second server never removes the running one's builds.
    """
    dashboard = Dashboard(project)
    try:
        server = _Server((HOST, port), dashboard)
    except OSError as error:
        if error.errno != errno.EADDRINUSE:
            raise
        raise _Refused(f"port {port} is in use; is the dashboard already running?") from error
    try:
        dashboard.start()
    except BaseException:
        server.server_close()
        raise
    return server


def main(argv: Sequence[str] | None = None, *, project_dir: Path = PROJECT_DIR) -> int:
    """Serve until interrupted; map each outcome to its documented exit code."""
    parser = _Parser(description=__doc__)
    parser.add_argument("--data-set", choices=DATA_SETS, required=True)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    # The launcher passes --detach so the server outlives its Terminal window whatever wrappers
    # sit between nohup and Python; a server started by hand still stops with its terminal.
    parser.add_argument("--detach", action="store_true")
    hangup = signal.getsignal(signal.SIGHUP)
    try:
        args = parser.parse_args(argv)
        if args.data_set != "company":
            raise _Refused(f"the dashboard shows company data only, not {args.data_set}")
        if args.port == capture_session.PLUGIN_PORT:
            raise _Refused(f"port {args.port} belongs to the game's recorder; use another port")
        server = serve(project_dir.resolve(), args.port)
    except _Refused as error:
        print(f"dashboard refused: {error}. Nothing was changed.")
        return 2
    except OSError as error:
        print(f"dashboard failed: {error}")
        return 1
    if args.detach:
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
    print(f"dashboard: serving http://{HOST}:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("dashboard interrupted")
        return 130
    finally:
        server.server_close()
        signal.signal(signal.SIGHUP, hangup)
    return 0


if __name__ == "__main__":
    sys.exit(main())

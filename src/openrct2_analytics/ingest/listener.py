"""Receive newline-delimited JSON events from the plugin and land them as dated JSON Lines files.

Run with `python -m openrct2_analytics.ingest.listener --data-set {rehearsal,company}`. Settings
come from `openrct2_analytics.config` (host and port; the raw folder is the data set's).

Each valid event gets a `received_at` (UTC, `YYYY-MM-DDTHH:MM:SS.mmmZ`) and is appended to
`<raw dir>/v<schema_version>/events-<UTC date of received_at>.jsonl`. Every other line is
appended, with the reason, its own `received_at` and the original text (undecodable bytes kept as
backslash escapes), to `<raw dir>/malformed-<UTC date>.jsonl`. Lines are strict UTF-8; duplicate
keys and the constants `NaN` and `Infinity` count as bad JSON. Blank lines carry nothing and are
skipped.
The listener only appends lines. A pre-go-live company delete may later archive,
rewrite or remove company raw files (ADR 0033); rehearsal files remain append-only.

A future replay must strip broker fields such as `received_at` from each stored line before
sending it again, because the listener refuses any line that already carries one.
"""

from __future__ import annotations

import argparse
import errno
import json
import math
import socket
import socketserver
import sys
import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from openrct2_analytics.config import (
    CAPTURE_DEFAULT_DATA_SET,
    DATA_SETS,
    Config,
    ConfigError,
    landing_dirs,
)

if TYPE_CHECKING:
    from _socket import _RetAddress
    from socketserver import _RequestType

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """Return the current time in UTC."""
    return datetime.now(UTC)


def format_received_at(moment: datetime) -> str:
    """Format a moment as UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`, the plugin's `emitted_at` format."""
    utc = moment.astimezone(UTC)
    return f"{utc:%Y-%m-%dT%H:%M:%S}.{utc.microsecond // 1000:03d}Z"


def rejection_reason(event: object) -> str | None:
    """Return why a parsed line cannot be landed as an event, or None if it can."""
    if not isinstance(event, dict):
        return "not a JSON object"
    version = event.get("schema_version")
    # bool is a subclass of int, and `true` is not a version.
    if type(version) is not int or version < 1:
        return "schema_version is not an integer of at least 1"
    if "received_at" in event:
        return "received_at already present"
    return None


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _ in pairs]
    for key in keys:
        if keys.count(key) > 1:
            raise ValueError(f"duplicate key {key!r}")
    return dict(pairs)


def _reject_constant(name: str) -> float:
    raise ValueError(f"non-standard constant {name}")


def _parse_finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"number out of range: {text}")
    return value


class Lander:
    """Appends lines to the raw folder; one lock serializes writes across connections.

    Args:
        raw_dir: Folder that receives `v<N>/` folders and the malformed files.
        clock: Returns the current time; tests pass a fixed or steppable one.
    """

    def __init__(self, raw_dir: Path, clock: Clock = utc_now) -> None:
        self.raw_dir = raw_dir
        self._clock = clock
        self._lock = threading.Lock()
        self._events_landed = 0

    @property
    def events_landed(self) -> int:
        """How many events this Lander has landed; malformed and blank lines are not counted."""
        with self._lock:
            return self._events_landed

    def land(self, line: bytes) -> bool | None:
        """Land one line and return True for an event, False for a malformed line, None if blank."""
        raw = line.decode("utf-8", errors="backslashreplace").strip()
        if not raw:
            return None
        received_at = format_received_at(self._clock())
        event, reason = self._classify(line, raw)
        if event is None:
            self._append(
                self._malformed_path(received_at), self._malformed(raw, reason, received_at)
            )
            return False
        event["received_at"] = received_at
        path = self.raw_dir / f"v{event['schema_version']}" / f"events-{received_at[:10]}.jsonl"
        self._append(path, json.dumps(event))
        with self._lock:
            self._events_landed += 1
        return True

    @staticmethod
    def _classify(line: bytes, raw: str) -> tuple[dict[str, object] | None, str]:
        """Return (event, "") for a landable line, else (None, the reason it is malformed)."""
        try:
            line.decode("utf-8")
        except UnicodeDecodeError:
            return None, "invalid UTF-8"
        try:
            parsed = json.loads(
                raw,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_constant,
                parse_float=_parse_finite_float,
            )
        except json.JSONDecodeError as exc:
            return None, exc.msg
        except ValueError as exc:  # raised by the three hooks above
            return None, str(exc)
        reason = rejection_reason(parsed)
        if reason is not None:
            return None, reason
        return parsed, ""

    def _malformed_path(self, received_at: str) -> Path:
        return self.raw_dir / f"malformed-{received_at[:10]}.jsonl"

    @staticmethod
    def _malformed(raw: str, reason: str, received_at: str) -> str:
        return json.dumps({"reason": reason, "line": raw, "received_at": received_at})

    def _append(self, path: Path, text: str) -> None:
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(text + "\n")
                handle.flush()


class EventHandler(socketserver.StreamRequestHandler):
    """Reads one connection's lines and hands each to the server's Lander."""

    server: EventServer

    def handle(self) -> None:
        """Land every line until the game disconnects."""
        print(f"game connected from {self.client_address}", file=sys.stderr, flush=True)
        events = malformed = 0
        try:
            for line in self.rfile:
                landed = self.server.lander.land(line)
                if landed is True:
                    events += 1
                elif landed is False:
                    malformed += 1
        finally:
            print(
                f"game disconnected: {events} events and {malformed} malformed lines written",
                file=sys.stderr,
                flush=True,
            )


class EventServer(socketserver.ThreadingTCPServer):
    """One thread per connection, all landing through one Lander.

    The server tracks its open connections and running handler threads, so a caller that
    has stopped it (``shutdown()``) can close what is still open and wait for every line
    to be written before ``server_close()``.
    """

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], lander: Lander) -> None:
        super().__init__(address, EventHandler)
        self.lander = lander
        self._tracking = threading.Condition()
        self._open: set[socket.socket] = set()
        self._handlers_running = 0

    def process_request(self, request: _RequestType, client_address: _RetAddress) -> None:
        """Track the connection and its handler thread, then start the thread."""
        with self._tracking:
            if isinstance(request, socket.socket):
                self._open.add(request)
            self._handlers_running += 1
        super().process_request(request, client_address)

    def process_request_thread(self, request: _RequestType, client_address: _RetAddress) -> None:
        """Handle one connection in its thread, then count the thread as finished."""
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._tracking:
                self._handlers_running -= 1
                self._tracking.notify_all()

    def shutdown_request(self, request: _RequestType) -> None:
        """Stop tracking a connection before it is closed, so it is never shut down twice."""
        with self._tracking:
            if isinstance(request, socket.socket):
                self._open.discard(request)
        super().shutdown_request(request)

    def close_connections(self) -> None:
        """Shut down every open connection; each handler then reads end of input and finishes."""
        # Accepted loss: with the game still connected, macOS discards bytes received but not
        # yet read, so the last lines are lost and a cut line lands as one malformed record.
        # After the game has closed its end (a normal quit) nothing is discarded.
        with self._tracking:
            for connection in self._open:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError as exc:
                    # macOS reports ENOTCONN when the client already closed its end; the
                    # handler then reaches end of input by itself.
                    if exc.errno != errno.ENOTCONN:
                        raise

    def wait_for_handlers(self, timeout: float) -> int:
        """Wait up to ``timeout`` seconds for every handler thread; return how many still run."""
        with self._tracking:
            self._tracking.wait_for(lambda: self._handlers_running == 0, timeout)
            return self._handlers_running

    @property
    def address(self) -> tuple[str, int]:
        """The bound host and port (the real port when 0 was requested)."""
        host, port = self.server_address[:2]
        return str(host), int(port)


def create_server(host: str, port: int, raw_dir: Path, clock: Clock = utc_now) -> EventServer:
    """Bind a listener to host and port (port 0 picks a free one); call serve_forever to run it."""
    return EventServer((host, port), Lander(raw_dir, clock))


def no_data_set_line(target: str) -> str:
    """The one line printed when a command that writes events is given no data set."""
    sets = " and ".join(DATA_SETS)
    return (
        f"Name a data set ({sets}), for example: make {target} DATA_SET=rehearsal. "
        "Nothing was changed."
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the listener on a data set's raw folder until interrupted.

    Returns:
        0 after a stop, 2 when refused (no data set, or landing folders that clash); nothing
        is bound or created in that case.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-set", choices=DATA_SETS, default=CAPTURE_DEFAULT_DATA_SET)
    args = parser.parse_args(argv)
    if args.data_set is None:
        print(no_data_set_line("listen"), file=sys.stderr)
        return 2
    try:
        config = Config.from_env()
        raw_dir = landing_dirs(args.data_set).raw
    except ConfigError as exc:
        print(f"{exc}. Nothing was changed.", file=sys.stderr)
        return 2
    with create_server(config.listener_host, config.listener_port, raw_dir) as server:
        host, port = server.address
        print(f"listening on {host}:{port}; writing to {raw_dir}", file=sys.stderr, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("stopped", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

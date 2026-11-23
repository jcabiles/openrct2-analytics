"""Behavioral tests for the listener, over a real socket on an ephemeral port."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest

from openrct2_analytics.ingest.listener import EventServer, create_server

START = datetime(2026, 9, 30, 23, 59, 59, 500_000, tzinfo=UTC)


class Clock:
    """A steppable clock: each call returns the current time, then `step` moves it."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def step(self, delta: timedelta) -> None:
        self.now += delta


def event(**fields: object) -> str:
    return json.dumps({"schema_version": 1, "event_type": "park_snapshot", **fields})


def jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def lines_landed(server: EventServer, raw_dir: Path, expected: int) -> None:
    """Wait until raw_dir holds `expected` lines in total (the server writes asynchronously)."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        total = sum(
            len(path.read_text(encoding="utf-8").splitlines()) for path in raw_dir.rglob("*.jsonl")
        )
        if total >= expected:
            return
        time.sleep(0.01)
    raise AssertionError(f"fewer than {expected} lines landed in {raw_dir}")


def send(server: EventServer, *lines: str) -> None:
    with socket.create_connection(server.address) as client:
        client.sendall(("".join(line + "\n" for line in lines)).encode("utf-8"))


@pytest.fixture(autouse=True)
def non_utc_process_zone(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run in UTC+14 so a file dated by local time lands on the wrong date, on any CI machine."""
    monkeypatch.setenv("TZ", "Pacific/Kiritimati")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def clock() -> Clock:
    return Clock(START)


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    return tmp_path / "raw"


@pytest.fixture
def server(raw_dir: Path, clock: Clock) -> Iterator[EventServer]:
    with create_server("127.0.0.1", 0, raw_dir, clock) as running:
        thread = threading.Thread(
            target=running.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        thread.start()
        yield running
        running.shutdown()
        thread.join(timeout=5)


def test_event_lands_under_version_folder_with_received_at(
    server: EventServer, raw_dir: Path, clock: Clock
) -> None:
    clock.now = datetime(2026, 9, 30, 12, 0, 0, 123_999, tzinfo=UTC)

    send(server, event(seq=1))
    lines_landed(server, raw_dir, 1)

    assert jsonl(raw_dir / "v1" / "events-2026-09-30.jsonl") == [
        {
            "schema_version": 1,
            "event_type": "park_snapshot",
            "seq": 1,
            "received_at": "2026-09-30T12:00:00.123Z",
        }
    ]


def test_version_two_lands_in_its_own_folder(server: EventServer, raw_dir: Path) -> None:
    send(server, event(schema_version=2))
    lines_landed(server, raw_dir, 1)

    assert (raw_dir / "v2" / "events-2026-09-30.jsonl").is_file()
    assert not (raw_dir / "v1").exists()


def test_date_is_utc_and_moves_at_midnight_on_one_connection(
    server: EventServer, raw_dir: Path, clock: Clock
) -> None:
    with socket.create_connection(server.address) as client:
        client.sendall((event(seq=1) + "\n").encode())
        lines_landed(server, raw_dir, 1)
        clock.step(timedelta(seconds=1))
        client.sendall((event(seq=2) + "\n").encode())
        lines_landed(server, raw_dir, 2)

    before = jsonl(raw_dir / "v1" / "events-2026-09-30.jsonl")
    after = jsonl(raw_dir / "v1" / "events-2026-10-01.jsonl")
    assert [e["seq"] for e in before] == [1]
    assert [e["seq"] for e in after] == [2]
    assert after[0]["received_at"] == "2026-10-01T00:00:00.500Z"


def test_non_utc_clock_is_converted_to_utc(
    server: EventServer, raw_dir: Path, clock: Clock
) -> None:
    clock.now = datetime(2026, 10, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=2)))

    send(server, event(seq=1))
    lines_landed(server, raw_dir, 1)

    assert jsonl(raw_dir / "v1" / "events-2026-09-30.jsonl")[0]["received_at"] == (
        "2026-09-30T23:00:00.000Z"
    )


def test_two_connections_append_to_one_file(server: EventServer, raw_dir: Path) -> None:
    with (
        socket.create_connection(server.address) as first,
        socket.create_connection(server.address) as second,
    ):
        first.sendall((event(seq=1) + "\n").encode())
        second.sendall((event(seq=2) + "\n").encode())
        first.sendall((event(seq=3) + "\n").encode())
        lines_landed(server, raw_dir, 3)

    landed = jsonl(raw_dir / "v1" / "events-2026-09-30.jsonl")
    assert sorted(cast(int, e["seq"]) for e in landed) == [1, 2, 3]


def test_existing_file_is_appended_not_rewritten(server: EventServer, raw_dir: Path) -> None:
    path = raw_dir / "v1" / "events-2026-09-30.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"kept": true}\n', encoding="utf-8")

    send(server, event(seq=1))
    lines_landed(server, raw_dir, 2)

    assert jsonl(path)[0] == {"kept": True}
    assert len(jsonl(path)) == 2


def test_blank_lines_are_skipped(server: EventServer, raw_dir: Path) -> None:
    send(server, "", "   ", event(seq=1))
    lines_landed(server, raw_dir, 1)

    assert len(jsonl(raw_dir / "v1" / "events-2026-09-30.jsonl")) == 1
    assert not list(raw_dir.glob("malformed-*"))


def test_a_line_cut_off_by_disconnect_is_kept_as_malformed(
    server: EventServer, raw_dir: Path
) -> None:
    fragment = '{"schema_version": 1, "se'
    with socket.create_connection(server.address) as client:
        client.sendall((event(seq=1) + "\n" + fragment).encode())
    lines_landed(server, raw_dir, 2)

    assert [e["seq"] for e in jsonl(raw_dir / "v1" / "events-2026-09-30.jsonl")] == [1]
    [record] = jsonl(raw_dir / "malformed-2026-09-30.jsonl")
    assert record["line"] == fragment


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        ("{not json", "Expecting property name"),
        ("[1, 2]", "not a JSON object"),
        ('"text"', "not a JSON object"),
        ('{"event_type": "park_snapshot"}', "schema_version is not an integer"),
        ('{"schema_version": true}', "schema_version is not an integer"),
        ('{"schema_version": 0}', "schema_version is not an integer"),
        ('{"schema_version": "1"}', "schema_version is not an integer"),
        ('{"schema_version": 1.0}', "schema_version is not an integer"),
        (
            '{"schema_version": 1, "received_at": "2020-01-01T00:00:00.000Z"}',
            "received_at already present",
        ),
        ('{"schema_version": 1, "seq": 5, "seq": 6}', "duplicate key 'seq'"),
        ('{"schema_version": 1, "x": NaN}', "non-standard constant NaN"),
        ('{"schema_version": 1, "x": Infinity}', "non-standard constant Infinity"),
        ('{"schema_version": 1, "x": 1e999}', "number out of range"),
    ],
)
def test_malformed_lines_go_to_the_side_file(
    server: EventServer, raw_dir: Path, line: str, reason: str
) -> None:
    send(server, line)
    lines_landed(server, raw_dir, 1)

    [record] = jsonl(raw_dir / "malformed-2026-09-30.jsonl")
    assert record["line"] == line
    assert str(record["reason"]).startswith(reason)
    assert record["received_at"] == "2026-09-30T23:59:59.500Z"
    assert not (raw_dir / "v1").exists()


def test_invalid_utf8_is_kept_as_malformed(server: EventServer, raw_dir: Path) -> None:
    with socket.create_connection(server.address) as client:
        client.sendall(b'{"schema_version": 1, "x": "\xff"}\n')
    lines_landed(server, raw_dir, 1)

    [record] = jsonl(raw_dir / "malformed-2026-09-30.jsonl")
    assert record["reason"] == "invalid UTF-8"
    assert record["line"] == '{"schema_version": 1, "x": "\\xff"}'


def test_a_valid_replacement_character_is_a_normal_event(
    server: EventServer, raw_dir: Path
) -> None:
    send(server, event(seq=1, name="caf\ufffd"))
    lines_landed(server, raw_dir, 1)

    [landed] = jsonl(raw_dir / "v1" / "events-2026-09-30.jsonl")
    assert landed["name"] == "caf\ufffd"
    assert not list(raw_dir.glob("malformed-*"))


def test_received_at_is_never_overwritten(server: EventServer, raw_dir: Path) -> None:
    sent = '{"schema_version": 1, "received_at": "2020-01-01T00:00:00.000Z"}'

    send(server, sent)
    lines_landed(server, raw_dir, 1)

    [record] = jsonl(raw_dir / "malformed-2026-09-30.jsonl")
    assert record["line"] == sent
    assert not (raw_dir / "v1").exists()


def test_malformed_date_moves_at_utc_midnight(
    server: EventServer, raw_dir: Path, clock: Clock
) -> None:
    send(server, "bad")
    lines_landed(server, raw_dir, 1)
    clock.step(timedelta(seconds=1))
    send(server, "bad")
    lines_landed(server, raw_dir, 2)

    assert (raw_dir / "malformed-2026-09-30.jsonl").is_file()
    assert (raw_dir / "malformed-2026-10-01.jsonl").is_file()


def test_server_binds_only_to_the_given_host(server: EventServer) -> None:
    assert server.address[0] == "127.0.0.1"


def test_events_landed_counts_events_only(server: EventServer, raw_dir: Path) -> None:
    send(server, event(seq=1), "bad", "", event(seq=2))
    lines_landed(server, raw_dir, 3)

    assert server.lander.events_landed == 2


def test_open_connections_are_closed_and_their_handlers_awaited(
    server: EventServer, raw_dir: Path
) -> None:
    with socket.create_connection(server.address) as client:
        client.sendall((event(seq=1) + "\n").encode())
        lines_landed(server, raw_dir, 1)
        assert server.wait_for_handlers(timeout=0.05) == 1  # still reading the open connection

        server.close_connections()

        assert server.wait_for_handlers(timeout=5) == 0
        assert client.recv(1) == b""

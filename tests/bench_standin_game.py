"""A stand-in for OpenRCT2, launched by the benchmark in place of the game binary.

It takes the game's argument shape (``host <park> --headless --port P --user-data-path U``)
and answers ``--version``. Its behavior comes from the JSON script named by
``BENCH_STANDIN_SCRIPT``: the listener port (the test seam, since the real plugin always
sends to 8765) and one entry per launch, in launch order (the last entry repeats). Each
launch appends its arguments to ``launches.jsonl`` beside the script.

An entry's keys, all optional:
    stats: game days to play, each a ``plugin_stats`` line (the first is the warm-up row)
        and a ``park_snapshot`` line (default 3); playing stops early on SIGTERM.
    rides: ``ride_snapshot`` lines to send each game day, after that day's ``park_snapshot``,
        each at a game tick inside the day's period (default 0).
    day_seconds: wall-clock seconds per game day (default 0).
    stats_fields: fields every ``plugin_stats`` line gets, for example the work counters.
    guest_counters: give each ``plugin_stats`` line the counters that change by day:
        ``boarding_polls_total`` rising by ``TICKS_PER_DAY // POLL_INTERVAL_TICKS`` a day, and
        ``guests_known`` and ``guests_known_in_park`` equal to the day's ``guests_in_park``.
    slow_row: index of a ``plugin_stats`` row sent with ``game_speed`` 2.
    exit_early: exit after sending, as a game that crashed would.
    ignore_term: ignore SIGTERM, so only a kill stops it.
    touch: a file to append a byte to, as if the run changed the fixture.
    save: read the save helper from the plugin folder, write the save into
        ``<user data>/save/<name>.park`` (the loaded park plus a marker naming this
        session), then send ``save_written``.
    slow_save: like ``save``, but send ``save_written`` first and then write the save in
        chunks over about 1 s, as the game does after its save hook; a SIGTERM during the
        write abandons the rest, as a stopped game would.
    final_lines: ``park_snapshot`` lines to send after SIGTERM (default 1).
    park_id: the ``park_id`` every line of this launch carries (default: ``event()``'s).
    guests: with a true value, each game day also sends one line each of ``guest_arrived``,
        ``guest_boarded``, ``guest_left`` and ``guest_snapshot``, after the day's rides.
    speed: the ``game_speed`` of every ``plugin_stats`` line (default 1); ``slow_row`` still
        sends 2.
    start_year: the game year the launch starts in; setting it gives every line a game date.
        ``session_start`` is on month 0, day 1 of that year, the game days spread evenly over
        the ``MONTHS_PER_YEAR`` months after it, so the last is on month 0 of ``start_year + 1``,
        and the save and final lines follow it there. ``emitted_at`` is one second per ``seq``
        after ``EMITTED_AT_BASE``. Without it the lines keep ``event()``'s fixed dates.
    start_date: ``[year, month, day]``, the game date the launch starts on (month 0 is March,
        month 7 October; the month lengths are ``MONTH_DAYS``). ``session_start`` carries it and
        game day ``n`` (0 first) is ``n + 1`` days after it, so a start on 31 October plays
        1 March of the next year first. Every line carries its day's date, and each game day
        that is day 1 of a month also sends a ``finance_month`` line for the month just ended.
        It replaces ``start_year``. With ``save`` or ``slow_save`` and a helper text that holds
        the line ``TARGET_YEAR = <year>;``, the launch saves on the day dated 1 March of that
        year, as the real helper does, and plays no later day; a helper text without that line
        (or a launch without ``start_date``) keeps the save after the last game day.
Each day's ``park_snapshot`` is built on the same tick as its ``plugin_stats`` line, as the
plugin's day callback builds both. Every launch's ``session_start`` reports the save it
loaded, as the plugin does: when the park carries a marker, ``loaded_save_id`` and
``loaded_save_session_id`` name the last session that saved it; otherwise both are left out
(a park the plugin never saved).
On SIGTERM it waits ``STOP_DELAY_SECONDS``, sends its final lines, records in
``launches.jsonl`` how many lines it sent in all, closes the connection and exits 0. A game
that exits early or ignores SIGTERM records its count once it has nothing more to send.
``--version`` records its arguments in ``versions.jsonl`` beside the script.
"""

from __future__ import annotations

import json
import os
import re
import signal
import socket
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import FrameType

from tests.test_convert import SNAPSHOT_PAYLOAD, event
from tests.test_convert_event_types import (
    FINANCE_PAYLOAD,
    RIDE_PAYLOAD,
    START_PAYLOAD,
    typed_event,
)
from tests.test_guest_event_types import PAYLOADS as GUEST_PAYLOADS

VERSION_LINE = "OpenRCT2, v0.5.5 (standin on HEAD)"
HELPER_FILE = "openrct2-analytics-bench-save.js"
TICKS_PER_DAY = 100
POLL_INTERVAL_TICKS = 20
STOP_DELAY_SECONDS = 0.3
MONTHS_PER_YEAR = 8  # the game's year runs from month 0 to 7
MONTH_DAYS = (31, 30, 31, 30, 31, 31, 30, 31)  # March to October
TARGET_YEAR_PATTERN = re.compile(r"TARGET_YEAR = (\d+);")
GUEST_TYPES = ("guest_arrived", "guest_boarded", "guest_left", "guest_snapshot")
EMITTED_AT_BASE = datetime(2026, 10, 1, tzinfo=UTC)
SAVE_CHUNKS = 6
SAVE_CHUNK_SECONDS = 0.15  # under the runner's 3 polls 200 ms apart, so it must wait
# Room for every final line in the kernel's send buffer, so the game can exit at once.
SEND_BUFFER_BYTES = 4 * 1024 * 1024


def plugin_line(line: str, overrides: dict[str, object] | None = None) -> bytes:
    """A line as the plugin sends it: without the listener's received_at."""
    doc = json.loads(line)
    del doc["received_at"]
    doc.update(overrides or {})
    return (json.dumps(doc) + "\n").encode("utf-8")


class Game:
    """One launch of the stand-in."""

    def __init__(self, argv: list[str], script_path: Path) -> None:
        script = json.loads(script_path.read_text(encoding="utf-8"))
        log = script_path.parent / "launches.jsonl"
        index = sum(1 for entry in read_log(log) if "argv" in entry)
        append(log, {"argv": argv})
        self.entry: dict[str, object] = script["launches"][min(index, len(script["launches"]) - 1)]
        self.port = int(script["listener_port"])
        self.park = Path(argv[1])
        self.user_data = Path(argv[argv.index("--user-data-path") + 1])
        self.session = f"standin-{index + 1}"
        self.seq = 0  # one line per seq, so this is also the count of lines sent
        self.stopping = False
        self.log = log
        self.date: tuple[int, int, int] | None = None  # the game date, with ``start_date``

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def number(self, key: str, default: int) -> int:
        value = self.entry.get(key, default)
        assert isinstance(value, int)
        return value

    def wire(self, line: str, month: int = 0, day: int = 0) -> bytes:
        """``line`` as sent: with this launch's park ID and, if planned, game date.

        ``month`` counts game months from the launch's start; ``day`` seeds the day of month.
        """
        overrides: dict[str, object] = {}
        if "park_id" in self.entry:
            overrides["park_id"] = self.entry["park_id"]
        if self.date is not None:
            year, game_month, game_day = self.date
            overrides.update(
                game_year=year,
                game_month=game_month,
                game_day=game_day,
                emitted_at=self.emitted_at(line),
            )
        elif "start_year" in self.entry:
            overrides.update(
                game_year=self.number("start_year", 0) + month // MONTHS_PER_YEAR,
                game_month=month % MONTHS_PER_YEAR,
                game_day=1 + day % 30,
                emitted_at=self.emitted_at(line),
            )
        return plugin_line(line, overrides)

    @staticmethod
    def emitted_at(line: str) -> str:
        moment = EMITTED_AT_BASE + timedelta(seconds=json.loads(line)["seq"])
        return f"{moment:%Y-%m-%dT%H:%M:%S}.000Z"

    def set_date(self, days_after_start: int) -> None:
        """Move ``self.date`` to the ``start_date`` plus ``days_after_start`` game days."""
        start = self.entry["start_date"]
        assert isinstance(start, list)
        year, month, day = start
        for _ in range(days_after_start):
            day += 1
            if day > MONTH_DAYS[month]:
                day, month = 1, month + 1
                if month == MONTHS_PER_YEAR:
                    month, year = 0, year + 1
        self.date = (year, month, day)

    def finance_line(self) -> bytes:
        """The ``finance_month`` line for the month before ``self.date``."""
        assert self.date is not None
        year, month, _ = self.date
        year, month = (year - 1, MONTHS_PER_YEAR - 1) if month == 0 else (year, month - 1)
        payload = {**FINANCE_PAYLOAD, "statement_year": year, "statement_month": month}
        return self.wire(typed_event(self.session, self.next_seq(), "finance_month", payload))

    def day_month(self, day: int) -> int:
        """The game month of game day ``day``; the days spread over a year, the last at its end."""
        days = self.number("stats", 3)
        return MONTHS_PER_YEAR if days == 1 else day * MONTHS_PER_YEAR // (days - 1)

    def record_sent(self) -> None:
        append(self.log, {"session": self.session, "sent": self.seq})

    def on_term(self, signum: int, frame: FrameType | None) -> None:
        if self.entry.get("ignore_term"):
            append(self.log, {"term_ignored": self.session})
            return
        self.stopping = True

    def connect(self) -> socket.socket:
        deadline = time.monotonic() + 10
        while True:
            try:
                client = socket.create_connection(("127.0.0.1", self.port))
            except ConnectionRefusedError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)
                continue
            client.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SEND_BUFFER_BYTES)
            return client

    def stats_line(self, day: int) -> bytes:
        start = day * TICKS_PER_DAY
        fields: dict[str, object] = {
            "period_start_ticks": start,
            "period_end_ticks": start + TICKS_PER_DAY,
            "period_ticks": TICKS_PER_DAY,
            "worst_tick_at_ticks": start + 25,
            "game_ticks_elapsed": start + TICKS_PER_DAY,
            "warmup": day == 0,
            "game_speed": 2 if self.entry.get("slow_row") == day else self.number("speed", 1),
        }
        extra = self.entry.get("stats_fields", {})
        assert isinstance(extra, dict)
        fields.update(extra)
        if self.entry.get("guest_counters"):
            in_park = SNAPSHOT_PAYLOAD["guests_in_park"]
            fields["boarding_polls_total"] = day * (TICKS_PER_DAY // POLL_INTERVAL_TICKS)
            fields["guests_known"] = fields["guests_known_in_park"] = in_park
        line = event(self.session, self.next_seq(), "plugin_stats", **fields)
        return self.wire(line, self.day_month(day), day)

    def ride_lines(self, day: int) -> bytes:
        """This day's ``rides`` snapshots, each halfway through the day's period."""
        halfway = day * TICKS_PER_DAY + TICKS_PER_DAY // 2
        return b"".join(
            self.wire(
                typed_event(
                    self.session,
                    self.next_seq(),
                    "ride_snapshot",
                    {**RIDE_PAYLOAD, "ride_id": ride, "game_ticks_elapsed": halfway},
                ),
                self.day_month(day),
                day,
            )
            for ride in range(1, self.number("rides", 0) + 1)
        )

    def guest_lines(self, day: int) -> bytes:
        """This day's ``guests`` lines: one of each guest type that the converter needs."""
        return b"".join(
            self.wire(
                typed_event(self.session, self.next_seq(), name, GUEST_PAYLOADS[name]),
                self.day_month(day),
                day,
            )
            for name in GUEST_TYPES
        )

    def loaded_save(self) -> dict[str, object]:
        """The save fields of this launch's ``session_start``, from the park's last marker."""
        markers = re.findall(rb"\+(standin-\d+)", self.park.read_bytes())
        if not markers:
            return {}
        session = markers[-1].decode()
        return {"loaded_save_id": f"save-{session}", "loaded_save_session_id": session}

    def save_written(self, client: socket.socket) -> None:
        payload: dict[str, object] = {"save_id": f"save-{self.session}"}
        line = typed_event(self.session, self.next_seq(), "save_written", payload)
        client.sendall(self.wire(line, MONTHS_PER_YEAR))

    def helper_text(self) -> str:
        return (self.user_data / "plugin" / HELPER_FILE).read_text(encoding="utf-8")

    def save(self, client: socket.socket, helper: str) -> None:
        name = re.search(r'SAVE_FILENAME = "([^"]+)"', helper)
        assert name is not None
        saved = self.user_data / "save" / f"{name.group(1)}.park"
        content = self.park.read_bytes() + f"+{self.session}".encode()
        if not self.entry.get("slow_save"):
            saved.write_bytes(content)
            self.save_written(client)
            return
        self.save_written(client)
        size = -(-len(content) // SAVE_CHUNKS)
        with saved.open("wb") as handle:
            for offset in range(0, len(content), size):
                if self.stopping:
                    return
                handle.write(content[offset : offset + size])
                handle.flush()
                time.sleep(SAVE_CHUNK_SECONDS)

    def play(self) -> None:
        signal.signal(signal.SIGTERM, self.on_term)
        touch = self.entry.get("touch")
        if isinstance(touch, str):
            with Path(touch).open("ab") as handle:
                handle.write(b"!")
        with self.connect() as client:
            payload = {**START_PAYLOAD, **self.loaded_save()}
            start = typed_event(self.session, self.next_seq(), "session_start", payload)
            if "start_date" in self.entry:
                self.set_date(0)
            client.sendall(self.wire(start, 0, 0))
            saves = bool(self.entry.get("save") or self.entry.get("slow_save"))
            helper = self.helper_text() if saves else ""
            target = TARGET_YEAR_PATTERN.search(helper) if "start_date" in self.entry else None
            saved = self.run_days(client, helper if saves else None, target)
            if saves and not saved and not target:
                self.save(client, helper)
            self.wind_down(client)

    def run_days(
        self, client: socket.socket, helper: str | None, target: re.Match[str] | None
    ) -> bool:
        """Send each day's lines; return True when the target-year save ended the run."""
        pause = self.entry.get("day_seconds", 0)
        assert isinstance(pause, int | float)
        for day in range(self.number("stats", 3)):
            if self.stopping:
                break
            time.sleep(pause)
            self.send_day(client, day)
            if target and helper and self.date == (int(target.group(1)), 0, 1):
                self.save(client, helper)  # the real helper pauses the game after this save
                return True
        return False

    def send_day(self, client: socket.socket, day: int) -> None:
        if "start_date" in self.entry:
            self.set_date(day + 1)
        client.sendall(self.stats_line(day))
        day_end = (day + 1) * TICKS_PER_DAY
        snapshot = event(self.session, self.next_seq(), game_ticks_elapsed=day_end)
        client.sendall(self.wire(snapshot, self.day_month(day), day))
        client.sendall(self.ride_lines(day))
        if self.entry.get("guests"):
            client.sendall(self.guest_lines(day))
        if self.date is not None and self.date[2] == 1:
            client.sendall(self.finance_line())

    def wind_down(self, client: socket.socket) -> None:
        if self.entry.get("exit_early") or self.entry.get("ignore_term"):
            self.record_sent()  # nothing more will be sent
        if self.entry.get("exit_early"):
            return
        while not self.stopping:
            time.sleep(0.02)
        time.sleep(STOP_DELAY_SECONDS)
        final = b"".join(
            self.wire(event(self.session, self.next_seq()), MONTHS_PER_YEAR)
            for _ in range(self.number("final_lines", 1))
        )
        client.sendall(final)
        self.record_sent()


def read_log(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def append(path: Path, record: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def main() -> None:
    argv = sys.argv[1:]
    script_path = Path(os.environ["BENCH_STANDIN_SCRIPT"])
    if argv[:1] == ["--version"]:
        append(script_path.parent / "versions.jsonl", {"argv": argv})
        print(VERSION_LINE)
        return
    Game(argv, script_path).play()


if __name__ == "__main__":
    main()

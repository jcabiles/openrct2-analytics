"""Progress lines for the headless autopilot run, and the run's summary afterwards.

``AutopilotProgress`` is the watch ``bench_play.play`` calls: ``on_landed`` for every landed
event (listener thread) and ``tick`` at every poll (main thread), both under one lock. It only
reads events, so a raw capture is never changed. ``on_landed`` only queues lines and ``tick``
prints them, so a print that raises never stops the listener thread from landing events.
``summarize`` totals the run from its raw events. Money stays in the game's tenths of a dollar;
``display_usd`` is the one conversion, for terminal text only (ADR 0052).
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

MONTH_NAMES = ("March", "April", "May", "June", "July", "August", "September", "October")
STALL_SECONDS = 60.0
# The 14 statement lines the plugin sends, in plugin/src/finance.ts order, each as <type>_tenths.
# Income is positive and spending negative, so their plain sum is the profit.
EXPENDITURE_TYPES = (
    "ride_construction",
    "ride_runningcosts",
    "land_purchase",
    "landscaping",
    "park_entrance_tickets",
    "park_ride_tickets",
    "shop_sales",
    "shop_stock",
    "food_drink_sales",
    "food_drink_stock",
    "wages",
    "marketing",
    "research",
    "interest",
)


def _int(value: object) -> int | None:
    """The value when it is an int (a bool is not), else None."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _date_text(year: int, month: int, day: int) -> str:
    return f"{MONTH_NAMES[month]} {day}, year {year}"


def _game_date(event: dict[str, object]) -> tuple[int, int, int] | None:
    year, month, day = (_int(event.get(key)) for key in ("game_year", "game_month", "game_day"))
    if year is None or month is None or day is None or not 0 <= month < len(MONTH_NAMES):
        return None
    return year, month, day


class AutopilotProgress:
    """Says the monthly line, the stall warning and the recovery line during a run."""

    def __init__(
        self,
        park_id: str,
        planned_days: int,
        limit_seconds: float,
        say: Callable[[str], None],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._park_id = park_id
        self._planned_days = planned_days
        self._limit_minutes = math.ceil(limit_seconds / 60)
        self._say = say
        self._clock = clock
        self._lock = threading.Lock()
        self._first_event: float | None = None
        self._last_event: float | None = None
        self._events = 0
        self._dates: set[tuple[int, int, int]] = set()
        self._last_date: tuple[int, int, int] | None = None
        self._announced_month: tuple[int, int] | None = None
        self._stalled = False
        self._queued: list[str] = []

    def on_landed(self, event: dict[str, object]) -> None:
        """Count one landed event; queue the recovery line, and the month line on a new month."""
        now = self._clock()
        with self._lock:
            if self._first_event is None:
                self._first_event = now
            self._last_event = now
            self._events += 1
            if self._stalled:
                self._stalled = False
                self._queued.append("autopilot: events are arriving again.")
            if event.get("event_type") != "park_snapshot":
                return
            date = _game_date(event)
            if date is None:
                return
            self._dates.add(date)
            self._last_date = date
            if self._announced_month != date[:2]:
                self._announced_month = date[:2]
                self._queue_month(date, now - self._first_event)

    def tick(self) -> None:
        """Say the queued lines, then the stall warning once after 60 s with no landed event."""
        with self._lock:
            lines, self._queued = self._queued, []
            if (
                self._last_event is not None
                and not self._stalled
                and self._clock() - self._last_event >= STALL_SECONDS
            ):
                self._stalled = True
                seen = "no game date has been seen yet"
                if self._last_date is not None:
                    seen = f"the last game date seen was {_date_text(*self._last_date)}"
                lines.append(
                    f"autopilot: no events for 60 s; {seen}. "
                    f"The run stops by itself at its time limit, {self._limit_minutes} min "
                    "after it started."
                )
        for line in lines:
            self._say(line)

    def _days_done(self) -> int:
        """Full game days done: each distinct date seen but the newest has ended."""
        return max(len(self._dates) - 1, 0)

    def _queue_month(self, date: tuple[int, int, int], elapsed: float) -> None:
        minutes, seconds = divmod(int(elapsed), 60)
        done = self._days_done()
        if done == 0:
            left = "estimating time left"
        else:
            days_left = max(self._planned_days - done, 0)
            left = f"about {math.ceil(elapsed / done * days_left / 60)} min left"
        self._queued.append(
            f"autopilot: park {self._park_id} · {_date_text(*date)} · {self._events} events · "
            f"{minutes} min {seconds} s elapsed · {left}"
        )


@dataclass(frozen=True)
class RunSummary:
    """What a run's raw events add up to; money in tenths of a dollar.

    Attributes:
        profit_tenths: Sum of the 14 statement lines over every ``finance_month`` event.
        statement_count: How many ``finance_month`` events the run held.
        first_statement: (year, month) of the first statement, or None.
        last_statement: (year, month) of the last statement, or None.
        guests_start: ``guests_in_park`` of the first ``park_snapshot``, or None.
        guests_end: ``guests_in_park`` of the last ``park_snapshot``, or None.
    """

    profit_tenths: int
    statement_count: int
    first_statement: tuple[int, int] | None
    last_statement: tuple[int, int] | None
    guests_start: int | None
    guests_end: int | None


def summarize(events: Iterable[dict[str, object]]) -> RunSummary:
    """Total the run's events; a missing or mistyped field is skipped, never an error."""
    profit = 0
    count = 0
    statements: list[tuple[int, int]] = []
    guests: list[int | None] = []
    for event in events:
        kind = event.get("event_type")
        if kind == "finance_month":
            count += 1
            for name in EXPENDITURE_TYPES:
                profit += _int(event.get(f"{name}_tenths")) or 0
            year, month = _int(event.get("statement_year")), _int(event.get("statement_month"))
            if year is not None and month is not None:
                statements.append((year, month))
        elif kind == "park_snapshot":
            guests.append(_int(event.get("guests_in_park")))
    return RunSummary(
        profit_tenths=profit,
        statement_count=count,
        first_statement=statements[0] if statements else None,
        last_statement=statements[-1] if statements else None,
        guests_start=guests[0] if guests else None,
        guests_end=guests[-1] if guests else None,
    )


def display_usd(tenths: int) -> str:
    """Game tenths of a dollar as display text: -1234 is ``-$123.40``."""
    dollars, rest = divmod(abs(tenths), 10)
    return f"{'-' if tenths < 0 else ''}${dollars:,}.{rest * 10:02d}"

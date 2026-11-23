"""Pinned copy and layout the showcase page check compares the built page against."""

from __future__ import annotations

MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MARK = "not checked: first month"
CAPTION = "Operating profit by company month, in US dollars"
HEADERS = ("Company month", "Operating profit")

CLOSE_RULE = (
    "a company year closes when every park expected in it has all eight monthly statements,"
    " march to october, and a park's partial first season does not hold a year open;"
    " at least one expected park must also be complete"
)
STATUS_WORDS = {
    "complete": "complete",
    "open": "not closed",
    "incomplete": "incomplete",
    "partial_first_season": "partial first season",
}
YEAR_CLOCK = "clock: company year"
PARK_COUNT = r"\b(one|two|three|four|five|six|seven|eight|nine|ten|single|\d+)\s+parks?\b"
MONEY_HEADER = "Operating profit (not yet reconciled)"
# Sample sentences of earlier builds that the page must no longer carry (lowercase).
STALE_SAMPLE_PHRASES = ("three headless sessions with no player",)
# Table id -> (caption, header row) of the two year tables.
YEAR_TABLES = {
    "company-year-table": (
        "Closed company years, operating profit in US dollars",
        [
            "Company year",
            "Parks reporting",
            "Partial first seasons",
            "Park-months checked",
            MONEY_HEADER,
        ],
    ),
    "park-year-table": (
        "Operating profit per park and company year, in US dollars",
        [
            "Company year",
            "Park ID",
            "Statements kept of expected",
            "Months checked",
            MONEY_HEADER,
            "Status",
        ],
    ),
}

FIGURE_PENDING = "figure pending"
# Invariant 3 clocks (game day, company date, wall-clock hour) plus the two company clocks.
CLOCKS = ("game day", "company date", "company month", "company year", "wall-clock hour")
# Built module path (relative to the site) -> {literal text: one-line reason}. A year, a number of
# 1,000 or more, or a string holding a formatted figure may appear in a module only if listed here.
MODULE_NUMBER_ALLOWLIST: dict[str, dict[str, str]] = {}

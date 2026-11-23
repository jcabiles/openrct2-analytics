"""The company start-year rules: which year the next company park may start in.

``next_start_year`` and ``start_years`` (moved out of the registry command unchanged) and the
planning and feed-check helpers added for the several-park chain read the registry and the
converted Parquet through ``managed_years`` and raise ``Refused``; nothing here writes. The registry
command re-exports ``Refused``, the one class every caller catches.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import duckdb

from openrct2_analytics.domain import start_year_plan
from openrct2_analytics.domain.start_year_plan import FIRST_START_YEAR as FIRST_START_YEAR
from openrct2_analytics.domain.start_year_plan import Planned, floor_year
from openrct2_analytics.ingest import capture_report, managed_years, registry_feed
from openrct2_analytics.ingest.contracts import LANDING_FOLDER
from openrct2_analytics.ingest.landing_paths import landing, project_path


class Refused(Exception):
    """An unchanged-tree refusal with a short reason code."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def first_sessions(starts: Path) -> list[tuple[str, int, datetime]]:
    """Return each park's first session start, ordered by ``emitted_at`` then park ID.

    The one home of "rank parks by their first recorded session". A row with no game year or no
    ``emitted_at`` cannot be ranked or shown, so it is skipped (a park with only such rows has no
    first session); unchecked converted data can hold one before ``make contracts`` runs.
    """
    with duckdb.connect(":memory:") as connection:
        rows = connection.execute(
            """SELECT park_id, game_year, emitted_at FROM read_parquet(?)
               WHERE game_year IS NOT NULL AND emitted_at IS NOT NULL
               QUALIFY row_number() OVER (
                   PARTITION BY park_id ORDER BY emitted_at, session_id
               ) = 1
               ORDER BY emitted_at, park_id""",
            [str(starts)],
        ).fetchall()
    return [(str(park), int(year), emitted) for park, year, emitted in rows]


def source_rows(audit: Path, starts: Path) -> list[tuple[str, int, datetime]]:
    """Return each audited park's first session start, ordered by the plugin clock."""
    with duckdb.connect(":memory:") as connection:
        audits = connection.execute(
            "SELECT park_id, park_count FROM read_parquet(?)", [str(audit)]
        ).fetchall()
    if any(count > 1 for _, count in audits):
        raise Refused("mixed-session", "A seq audit session contains more than one park")
    parks = {str(park) for park, _ in audits}
    rows = first_sessions(starts)
    found = {park for park, _, _ in rows}
    for park in sorted(parks - found):
        raise Refused("no-session-start", f"Park {park} has no session_start row")
    return [row for row in rows if row[0] in parks]


def registered_company_parks(feed: Path) -> dict[str, int]:
    """Return each registered non-practice company park's start year, by park ID."""
    return {
        park: row.company_start_year
        for park, row in managed_years.company_registrations(feed.parent).items()
        if not row.practice
    }


def _floor(feed: Path, parquet_dir: Path, registered: dict[str, int]) -> tuple[int, str]:
    """Return F and the park that sets it (the lowest park ID on a tie)."""
    return floor_year(registered, managed_years.company_managed_years(parquet_dir, feed.parent))


def _refuse_unconverted(raw_dir: Path, parquet_dir: Path) -> None:
    """Refuse (12) when a company raw file holds a session never converted."""
    stale = managed_years.unconverted_raw_file(raw_dir, parquet_dir)
    if stale is not None:
        raise Refused(
            "not-converted",
            f"{stale.name} holds a session that was never converted, so the latest managed "
            "year is unknown; run make convert DATA_SET=company first",
        )


def _floor_info(
    feed: Path, parquet_dir: Path, raw_dir: Path, registered: dict[str, int]
) -> tuple[int, str, list[str]]:
    """Return (F, the park that sets F, the registered company parks) for a non-empty registry.

    Raises:
        Refused: ``not-converted`` when a company raw file holds a session never converted.
    """
    _refuse_unconverted(raw_dir, parquet_dir)
    floor, setter = _floor(feed, parquet_dir, registered)
    return floor, setter, sorted(registered)


def next_start_year(feed: Path, parquet_dir: Path, raw_dir: Path) -> int | None:
    """Return the only start year the next company park accepts, or None before the first.

    Raises:
        Refused: ``not-converted`` when a company raw file holds a session never converted.
    """
    registered = registered_company_parks(feed)
    if not registered:
        return None
    return _floor_info(feed, parquet_dir, raw_dir, registered)[0] + 1


def start_years(
    chosen: dict[str, bool],
    start_year: int | None,
    *,
    parquet_dir: Path,
    raw_dir: Path,
    feed: Path,
) -> dict[str, int]:
    """Return the company start year of each chosen park (``chosen`` maps it to its practice flag).

    ``feed`` is the registry ``v1`` folder. Refusals follow the spec's order, 4 to 11.

    Raises:
        Refused: with the start-year reasons when the year cannot be written.
    """
    company = sorted(park for park, practice in chosen.items() if not practice)
    if start_year is not None and not company:
        raise Refused(
            "start-year-practice",
            "Sandbox parks take no START_YEAR, and every park being registered is a sandbox "
            f"park ({', '.join(sorted(chosen))})",
        )
    if len(company) > 1:
        raise Refused(
            "several-company-parks",
            f"Only one company park can be registered per run, and {len(company)} would be "
            f'({", ".join(company)}); register one at a time with PARKS="<id>:company"',
        )
    years = dict.fromkeys(chosen, FIRST_START_YEAR)
    if not company:
        return years
    park = company[0]
    registered = registered_company_parks(feed)
    if not registered:
        if start_year is None:
            return years
        if start_year != FIRST_START_YEAR:
            raise Refused(
                "start-year-first-park",
                f"Park {park} is the first company park, which starts in company year "
                f"{FIRST_START_YEAR}; drop START_YEAR",
            )
    else:
        floor_info = _floor_info(feed, parquet_dir, raw_dir, registered)
        start_year = _check_later_year(park, start_year, floor_info)
    _check_origin(park, parquet_dir)
    years[park] = start_year
    return years


def _check_later_year(
    park: str, start_year: int | None, floor_info: tuple[int, str, list[str]]
) -> int:
    """Return ``start_year`` when it is F + 1; refuse (8 to 10) otherwise.

    ``floor_info`` is (F, the park that sets F, the registered company parks).
    """
    floor, setter, registered = floor_info
    abandoned = (
        f"if {floor} looks too high, see ADR 0050 (play abandoned after the closing 1 March)"
    )
    if start_year is None:
        raise Refused(
            "start-year-required",
            f"Park {park} is not the first company park (registered: {', '.join(registered)}), "
            "so give its company start year with START_YEAR=<year>; by the business rules it is "
            f"{floor + 1}; {abandoned}",
        )
    if start_year <= floor:
        raise Refused(
            "start-year-overlap",
            f"Company year {start_year} overlaps park {setter}, whose latest company year is "
            f"{floor}; park {park} starts in {floor + 1}; {abandoned}",
        )
    if start_year > floor + 1:
        raise Refused(
            "start-year-gap",
            f"Company year {start_year} would leave company year {floor + 1} with no managed "
            f"park; the next park starts the March after {floor}, which park {setter} sets, so "
            f"START_YEAR must be {floor + 1}; {abandoned}",
        )
    return start_year


def _check_origin(park: str, parquet_dir: Path) -> None:
    """Refuse (11) a typed start year for a park whose first session is not in game year 1."""
    origins = source_rows(
        parquet_dir / capture_report.AUDIT_FILE,
        parquet_dir / LANDING_FOLDER / "session_start.parquet",
    )
    _require_origin_one(park, next(year for found, year, _ in origins if found == park))


def _require_origin_one(park: str, origin: int) -> None:
    if origin != 1:
        raise Refused(
            "start-year-origin",
            f"Park {park} has game-year origin {origin}; a company start year needs a park that "
            "began in game year 1, so capture the park from a new game before registering it",
        )


def check_registry_feed(feed: Path) -> None:
    """Refuse (``registry-check``) when the registry deliveries in ``feed`` fail the feed check.

    The one home of this check; ``register_parks.registered_parks`` and ``plan_start_years`` both
    call it. No delivery is fine: the first company park registers into an empty registry.
    """
    if sorted(feed.glob(registry_feed.FILE_GLOB)):
        problems = registry_feed.check_feed(feed.parent)
        if problems:
            raise Refused("registry-check", "; ".join(problems))


def plan_start_years(project_dir: Path, order: list[tuple[str, bool]]) -> list[Planned]:
    """Return the planned registration of each park in ``order``, before any is written.

    ``order`` holds (park ID, practice flag), the parks in registration order. Reads the company
    data set under ``project_dir``. Each earlier park counts as registered when the next one is
    planned, so a company park's year is the year after the parks before it. A Sandbox park takes
    no year and no origin check, and its days never count.

    Raises:
        Refused: ``registry-check`` when a registry delivery fails the feed check;
            ``not-converted`` when the converted files are missing or a company raw file holds a
            session never converted (also with an empty registry); ``start-year-origin`` for a
            company park after the first company park whose first session is not in game year 1.
    """
    folders = landing("company", project_dir)
    parquet_dir = folders.parquet
    raw_dir = folders.raw
    registry_dir = project_path(registry_feed.registry_dir("company"), project_dir)
    check_registry_feed(registry_dir / LANDING_FOLDER)
    audit = parquet_dir / capture_report.AUDIT_FILE
    starts = parquet_dir / LANDING_FOLDER / "session_start.parquet"
    if not audit.is_file() or not starts.is_file():
        raise Refused("not-converted", "Run make convert DATA_SET=company first")
    _refuse_unconverted(raw_dir, parquet_dir)
    origins = {park: year for park, year, _ in source_rows(audit, starts)}
    inputs = managed_years.read_managed_inputs(parquet_dir, registry_dir)
    company_before = bool(registered_company_parks(registry_dir / LANDING_FOLDER))
    for park, practice in order:
        if company_before and not practice:
            _require_origin_one(park, origins[park])
        company_before = company_before or not practice
    return start_year_plan.plan_years(
        [(park, origins[park], practice) for park, practice in order],
        inputs.registrations,
        days=inputs.days,
        last_save_seq=inputs.last_save_seq,
        session_start_year=inputs.session_start_year,
        autopilot_sessions=inputs.autopilot_sessions,
    )

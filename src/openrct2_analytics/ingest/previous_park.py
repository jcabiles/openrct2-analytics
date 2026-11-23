"""Word the note about the company park opened just before each park a filing registered.

``auto_file`` calls ``note_lines`` after a successful filing. The previous park of a new company
park is the one with the highest start year strictly below its own, chosen from the run's start
years and the registry, so the new park's own registry row is never needed. The previous park's
profit in its latest complete company year (``close_status = 'complete'``) is read, read-only,
from ``marts.obt_park_year`` of the development warehouse: the sum of all 14 statement lines,
kept in tenths until ``display_usd`` words it. A failed read gives one neutral line, never an
error, so the filing's exit code does not change.
"""

from __future__ import annotations

import csv
from collections.abc import Collection, Mapping
from decimal import Decimal
from pathlib import Path

import duckdb

from openrct2_analytics.config import ConfigError
from openrct2_analytics.ingest import play_status, start_year
from openrct2_analytics.ingest.autopilot_progress import display_usd
from openrct2_analytics.ingest.publish_audit import open_warehouse
from openrct2_analytics.ingest.query_interrupt import interrupt_as_signal

_SAME = (
    "auto-file: note: {new} opens after {prev}. The scenario challenge of {prev} is not recorded, "
    "so whether it was finished is not checked."
)
NOTE_WITH_PROFIT = (
    _SAME + " Its profit in company year {year}, its latest complete year, was {amount} in US "
    "dollars (all 14 statement lines of its 8 monthly statements)."
)
NOTE_NO_YEAR = _SAME + " {prev} has no complete company year (all 8 monthly statements)."
NEUTRAL_LINE = (
    "auto-file: the play is filed, but the note about the previous company park could not be "
    "shown ({error})."
)

_COMPLETE_YEARS = """
SELECT park_id, company_year, operating_profit + capital_spending + interest_costs
FROM marts.obt_park_year
WHERE park_id IN (SELECT unnest(?)) AND close_status = 'complete'
QUALIFY row_number() OVER (PARTITION BY park_id ORDER BY company_year DESC) = 1
"""


def previous_parks(
    registered: Mapping[str, int], years: Mapping[str, int | None]
) -> dict[str, str | None]:
    """Return each new park's previous park ID, or None.

    Args:
        registered: Earlier registered non-Sandbox company parks, park ID to start year.
        years: The run's new company parks, park ID to start year (None when it holds none).

    Returns:
        For each park of ``years``, the other park with the highest start year strictly below its
        own (the lowest park ID on a tie), among ``registered`` and the other new parks with a
        year; a new park's registry row is ignored in favour of the run's year.
    """
    known = {park: year for park, year in registered.items() if park not in years}
    known.update({park: year for park, year in years.items() if year is not None})
    result: dict[str, str | None] = {}
    for park, year in years.items():
        earlier = [] if year is None else [(-o, pid) for pid, o in known.items() if o < year]
        result[park] = min(earlier)[1] if earlier else None
    return result


def read_previous(
    project_dir: Path, park_ids: Collection[str]
) -> tuple[dict[str, tuple[int, int]], dict[str, str]]:
    """Read the latest complete year and the name of each listed park, with one connection.

    Returns:
        Park ID to (company year, profit in tenths of a dollar) for a park with a complete year,
        and park ID to ``park_name`` for a park whose ``marts.dim_park`` row has a name.

    Raises:
        FileNotFoundError: if the development warehouse does not exist.
        ValueError: if a year is not an ``int`` or a profit is not a ``Decimal`` (a null
            included), or a profit is not a whole number of tenths.
        duckdb.Error: if the warehouse cannot be read.
    """
    path = project_dir / play_status.WAREHOUSE
    if not path.is_file():
        raise FileNotFoundError(f"{play_status.WAREHOUSE.as_posix()} does not exist")
    connection = open_warehouse(path, project_dir=project_dir, read_only=True)
    try:
        with interrupt_as_signal():
            year_rows = connection.execute(_COMPLETE_YEARS, [list(park_ids)]).fetchall()
            name_rows = connection.execute(
                "SELECT park_id, park_name FROM marts.dim_park "
                "WHERE park_id IN (SELECT unnest(?)) AND park_name IS NOT NULL",
                [list(park_ids)],
            ).fetchall()
    finally:
        connection.close()
    complete: dict[str, tuple[int, int]] = {}
    for park, company_year, profit in year_rows:
        if not isinstance(company_year, int) or not isinstance(profit, Decimal):
            raise ValueError(f"park {park} has a year or profit of an unexpected type")
        tenths = profit * 10
        if tenths != tenths.to_integral_value():
            raise ValueError(f"park {park} has a profit of {profit}, not a whole number of tenths")
        complete[str(park)] = (company_year, int(tenths))
    return complete, {str(park): str(name) for park, name in name_rows}


def _registered(project_dir: Path) -> dict[str, int]:
    """Read the earlier registered company parks' start years."""
    try:
        return start_year.registered_company_parks(
            play_status.registry_feed_dir("company", project_dir)
        )
    except (KeyError, TypeError) as error:
        # latest_rows leaves the feed check to its caller, so a delivery without a column or with
        # a row cut short raises these; the neutral line must cover them like any read failure.
        raise ValueError(f"the park registry could not be read ({error!r})") from error


def note_lines(
    project_dir: Path, names: Mapping[str, str], years: Mapping[str, int | None]
) -> list[str]:
    """Return the lines to print about the park before each new company park of the run.

    Args:
        project_dir: Project folder that holds the registry feed and ``warehouse/dev/dev.duckdb``.
        names: Park ID to name, for the Company parks the run registered.
        years: The same parks' start years (None when the run holds none).

    Returns:
        One note per park with a previous park, in order of its start year then park ID; ``[]``
        when none has one (nothing is read when no park has a year, and the warehouse is not
        opened when no park has a previous park); exactly the neutral line when a read fails.
    """
    if all(year is None for year in years.values()):
        return []
    try:
        previous = previous_parks(_registered(project_dir), years)
        due = sorted(
            (year, park) for park, year in years.items() if year is not None and previous[park]
        )
        if not due:
            return []
        wanted = {str(previous[park]) for _, park in due}
        complete, prev_names = read_previous(project_dir, wanted)
        lines = []
        for _, park in due:
            prev = str(previous[park])
            fields = {
                "new": _one_line(names.get(park, park)),
                "prev": _one_line(prev_names.get(prev, prev)),
            }
            if prev in complete:
                year, tenths = complete[prev]
                lines.append(
                    NOTE_WITH_PROFIT.format(**fields, year=year, amount=display_usd(tenths))
                )
            else:
                lines.append(NOTE_NO_YEAR.format(**fields))
        return lines
    except (OSError, ValueError, csv.Error, duckdb.Error, ConfigError) as error:
        # The filing already succeeded, and these are the types auto_file turns into exit 1
        # (a missing or locked warehouse, a bad registry file, a folder alias, a mart of the wrong
        # shape); the note is advisory, so they become one neutral line and the exit code stays 0.
        return [NEUTRAL_LINE.format(error=_one_line_reason(error))]


def _one_line(text: str) -> str:
    """Return the text with each run of whitespace, line breaks included, as one space.

    The note is one line of output; a DuckDB error or a park name can span several lines.
    """
    return " ".join(text.split())


def _one_line_reason(error: Exception) -> str:
    return _one_line(str(error))

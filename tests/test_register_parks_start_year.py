"""The company start year of ``make register-parks``: the year rule and refusals 1, 2 and 4 to 11.

Every case starts from the spec's fixture, "Park 1 registered with start year 2000 and origin 1"
(``park_one``), and changes one thing. Expected texts are copied from the spec's section 4. The
two under-the-lock tests are in ``tests/test_register_parks_start_year_lock.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import TypedDict

import pytest

from openrct2_analytics.ingest import register_parks
from openrct2_analytics.ingest.start_year import next_start_year
from tests.autopilot_fixtures import (
    T0,
    event_row,
    plant_label,
    plant_park_snapshot,
    plant_registry,
    plant_save_written,
    plant_session_start,
)
from tests.test_register_parks import _copy, _rows, _tree

TODAY = date(2026, 11, 13)
WRITTEN = "park_registry_2026-11-13_01.csv"
ADR = "see ADR 0050 (play abandoned after the closing 1 March)"
# (park, session, session_start game date, hours after T0)
Session = tuple[str, str, tuple[int, int, int], int]
# (park, session, seq, game date); game month 0 is March.
Event = tuple[str, str, int, tuple[int, int, int]]
Registration = tuple[str, int, int, str, str, str]
Label = tuple[str, str, str, str, str, str]


class World(TypedDict):
    """The planted company data: converted Parquet, registry rows and session labels."""

    sessions: list[Session]
    days: list[Event]
    saves: list[Event]
    registry: list[Registration]
    labels: list[Label]


def park_one() -> World:
    """Park 1 registered (2000, origin 1), played through 1 March of game year 2 and saved there
    (Y = 2000); Park 2 captured from game year 1 and waiting to register."""
    return {
        "sessions": [("park-1", "s1", (1, 0, 1), 0), ("park-2", "s2", (1, 0, 1), 2)],
        "days": [
            ("park-1", "s1", 2, (1, 0, 2)),
            ("park-1", "s1", 3, (1, 7, 31)),
            ("park-1", "s1", 4, (2, 0, 1)),
        ],
        "saves": [("park-1", "s1", 5, (2, 0, 1))],
        "registry": [("park-1", 2000, 1, "company", "", "2026-11-12")],
        "labels": [],
    }


def later_year(world: World) -> World:
    """Add a second Park 1 session saved on 20 March of game year 2 (Y = 2001)."""
    world["sessions"].append(("park-1", "s1b", (2, 0, 1), 1))
    world["days"] += [("park-1", "s1b", 2, (2, 0, 2)), ("park-1", "s1b", 3, (2, 0, 20))]
    world["saves"].append(("park-1", "s1b", 4, (2, 0, 20)))
    return world


def _third_park() -> World:
    """Park 2 registered 2001 with managed days in 2001; Park 3 waits to register."""
    world = park_one()
    world["sessions"].append(("park-3", "s3", (1, 0, 1), 4))
    world["days"].append(("park-2", "s2", 2, (1, 3, 1)))
    world["saves"].append(("park-2", "s2", 3, (1, 3, 1)))
    world["registry"].append(("park-2", 2001, 1, "company", "", "2026-11-12"))
    return world


def _first_park(origin: int) -> World:
    """Park 2 alone, captured from game year ``origin``; no company park registered."""
    return {
        "sessions": [("park-2", "s2", (origin, 0, 1), 2)],
        "days": [],
        "saves": [],
        "registry": [],
        "labels": [],
    }


def plant(root: Path, world: World) -> None:
    """Write ``world`` as converted Parquet, its seq audit, registry and label deliveries."""
    parquet = root / "company" / "parquet"
    feed = root / "company" / "registry" / "v1"
    starts = [
        event_row(
            1,
            park_id=park,
            session_id=session,
            game_date=when,
            emitted_at=T0 + timedelta(hours=hours),
            park_name=park,
        )
        for park, session, when, hours in world["sessions"]
    ]
    plant_session_start(parquet, starts)
    audit = " UNION ALL ".join(
        f"SELECT '{park}' AS park_id, '{session}' AS session_id, 1 AS park_count, 0 AS missing, "
        "0 AS duplicates, 1 AS first_seq, 1 AS last_seq, 1 AS row_count"
        for park, session, _, _ in world["sessions"]
    )
    _copy(parquet / "audit" / "seq_audit.parquet", audit)
    for table, planter, events in (
        ("park_snapshot", plant_park_snapshot, world["days"]),
        ("save_written", plant_save_written, world["saves"]),
    ):
        (parquet / "v1" / f"{table}.parquet").unlink(missing_ok=True)
        if events:
            rows = [
                event_row(seq, park_id=park, session_id=session, game_date=when, save_id="save")
                for park, session, seq, when in events
            ]
            planter(parquet, rows)
    if world["registry"]:
        plant_registry(feed, world["registry"])
    if world["labels"]:
        plant_label(feed, world["labels"])


def overlap(year: str, setter: str, floor: int, park: str) -> str:
    """Refusal 9's text."""
    return (
        f"Company year {year} overlaps park {setter}, whose latest company year is {floor}; "
        f"park {park} starts in {floor + 1}; if {floor} looks too high, {ADR}"
    )


REQUIRED = (
    "Park park-2 is not the first company park (registered: park-1), so give its company start "
    "year with START_YEAR=<year>; by the business rules it is 2001; if 2000 looks too high, " + ADR
)
SEVERAL = (
    "Only one company park can be registered per run, and 2 would be (park-2, park-3); "
    'register one at a time with PARKS="<id>:company"'
)


@dataclass
class Company:
    """The company data folder under ``tmp_path`` and the register command run against it."""

    tmp_path: Path
    capsys: pytest.CaptureFixture[str]

    @property
    def root(self) -> Path:
        return self.tmp_path / "data"

    def plant(self, world: World) -> None:
        plant(self.root, world)

    def run(self, *args: str) -> int:
        self.capsys.readouterr()
        return register_parks.main(
            ["--data-set", "company", *args], project_dir=self.tmp_path, today=TODAY
        )

    def out(self) -> str:
        return self.capsys.readouterr().out

    def written(self) -> list[tuple[str, str, str, str]]:
        rows = _rows(self.root / "company" / "registry" / "v1" / WRITTEN)
        return [
            (row["park_id"], row["company_start_year"], row["game_year_origin"], row["note"])
            for row in rows
        ]

    def refused(self, args: list[str], reason: str, detail: str) -> None:
        before = _tree(self.tmp_path)
        assert self.run(*args) == 2
        assert _tree(self.tmp_path) == before
        assert self.out() == f"register refused: {reason}: {detail}. Nothing was changed.\n"

    def accepted(self, park: str, year: str) -> None:
        assert self.run("--start-year", year) == 0
        assert self.written() == [(park, year, "1", "")]
        assert self.out() == (
            f"Registered 1 park(s) in {WRITTEN}.\n"
            f"Park {park}: company start year {year} (START_YEAR).\n"
        )


@pytest.fixture
def company(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Company:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    return Company(tmp_path, capsys)


# Section 5 year cases.


def test_accepted_year(company: Company) -> None:
    company.plant(park_one())
    company.accepted("park-2", "2001")


def test_next_start_year_is_none_before_a_company_park_and_the_accepted_year_after(
    company: Company,
) -> None:
    folder = company.root / "company"
    company.plant(_first_park(1))
    assert next_start_year(folder / "registry" / "v1", folder / "parquet", folder / "raw") is None
    company.plant(park_one())
    assert next_start_year(folder / "registry" / "v1", folder / "parquet", folder / "raw") == 2001
    company.accepted("park-2", "2001")


@pytest.mark.parametrize("year", ["2000", "1999"])
def test_y_and_a_year_before_park_one_are_refused(company: Company, year: str) -> None:
    company.plant(park_one())
    company.refused(
        ["--start-year", year], "start-year-overlap", overlap(year, "park-1", 2000, "park-2")
    )


def test_gap_year_is_refused(company: Company) -> None:
    company.plant(park_one())
    company.refused(
        ["--start-year", "2002"],
        "start-year-gap",
        "Company year 2002 would leave company year 2001 with no managed park; the next park "
        "starts the March after 2000, which park park-1 sets, so START_YEAR must be 2001; "
        f"if 2000 looks too high, {ADR}",
    )


def test_days_after_the_last_save_do_not_count(company: Company) -> None:
    world = park_one()
    world["days"].append(("park-1", "s1", 6, (2, 0, 2)))
    company.plant(world)
    company.accepted("park-2", "2001")


def test_a_later_managed_year_raises_y(company: Company) -> None:
    company.plant(later_year(park_one()))
    company.refused(
        ["--start-year", "2001"], "start-year-overlap", overlap("2001", "park-1", 2001, "park-2")
    )
    company.accepted("park-2", "2002")


def test_no_managed_day_yet_uses_the_start_year(company: Company) -> None:
    world = park_one()
    world["saves"] = []
    company.plant(world)
    company.refused(
        ["--start-year", "2000"], "start-year-overlap", overlap("2000", "park-1", 2000, "park-2")
    )
    company.accepted("park-2", "2001")


def test_third_park(company: Company) -> None:
    company.plant(_third_park())
    company.refused(
        ["--start-year", "2001"], "start-year-overlap", overlap("2001", "park-2", 2001, "park-3")
    )
    company.accepted("park-3", "2002")


def test_origin_not_one_is_refused(company: Company) -> None:
    world = park_one()
    world["sessions"][1] = ("park-2", "s2", (5, 0, 1), 2)
    company.plant(world)
    company.refused(
        ["--start-year", "2001"],
        "start-year-origin",
        "Park park-2 has game-year origin 5; a company start year needs a park that began in "
        "game year 1, so capture the park from a new game before registering it",
    )


def test_load_near_the_year_end(company: Company) -> None:
    world = park_one()
    world["sessions"][0] = ("park-1", "s1", (1, 7, 31), 0)
    world["days"] = [("park-1", "s1", 2, (2, 0, 1))]
    world["saves"] = [("park-1", "s1", 3, (2, 0, 1))]
    company.plant(world)
    company.refused(
        ["--start-year", "2000"], "start-year-overlap", overlap("2000", "park-1", 2000, "park-2")
    )
    company.accepted("park-2", "2001")


def test_autopilot_days_do_not_count(company: Company) -> None:
    # Park 1's autopilot session runs from 2001 into 2002; counted, it would refuse 2002.
    world = _third_park()
    world["sessions"].append(("park-1", "s1a", (2, 0, 1), 6))
    world["days"] += [("park-1", "s1a", 2, (2, 1, 1)), ("park-1", "s1a", 3, (3, 1, 1))]
    world["saves"].append(("park-1", "s1a", 4, (3, 1, 1)))
    world["labels"] = [("s1a", "park-1", "autopilot", "", "company", "2026-11-12")]
    company.plant(world)
    company.accepted("park-3", "2002")


# Refusals 1, 2 and 4 to 8, each from its own planted state (9 to 11 are above).


@pytest.mark.parametrize("typed", ["20x1", "２００１"])
def test_start_year_not_in_digits_is_refused(company: Company, typed: str) -> None:
    company.plant(park_one())
    company.refused(
        ["--start-year", f" {typed} "],
        "start-year",
        f"START_YEAR must be a year written in digits, such as 2001; got '{typed}'",
    )


def test_start_year_with_practice_is_refused(company: Company) -> None:
    company.plant(park_one())
    company.refused(
        ["--practice", "--start-year", "2001"],
        "start-year-practice",
        'Sandbox parks take no START_YEAR; give PARKS="<id>:company" START_YEAR=<year> for '
        "the company park",
    )


def test_start_year_for_practice_parks_only_is_refused(company: Company) -> None:
    company.plant(park_one())
    company.refused(
        ["--parks", "park-2:practice", "--start-year", "2001"],
        "start-year-practice",
        "Sandbox parks take no START_YEAR, and every park being registered is a sandbox park "
        "(park-2)",
    )


def test_two_first_company_parks_are_refused_without_start_year(company: Company) -> None:
    world = park_one()
    world["sessions"].append(("park-3", "s3", (1, 0, 1), 4))
    world["registry"] = []
    company.plant(world)
    company.refused(["--parks", "park-2:company,park-3:company"], "several-company-parks", SEVERAL)


def test_start_year_for_the_first_park_must_be_2000(company: Company) -> None:
    company.plant(_first_park(1))
    company.refused(
        ["--start-year", "2001"],
        "start-year-first-park",
        "Park park-2 is the first company park, which starts in company year 2000; drop START_YEAR",
    )


def test_unconverted_raw_file_is_refused(company: Company) -> None:
    company.plant(park_one())
    raw = company.root / "company" / "raw" / "v1" / "events-2026-11-13.jsonl"
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps({"session_id": "s9", "park_id": "park-1"}) + "\n")
    company.refused(
        ["--start-year", "2001"],
        "not-converted",
        "events-2026-11-13.jsonl holds a session that was never converted, so the latest "
        "managed year is unknown; run make convert DATA_SET=company first",
    )


def test_start_year_is_required_for_a_later_park(company: Company) -> None:
    company.plant(park_one())
    company.refused([], "start-year-required", REQUIRED)


# Tie rules: two registered parks share F, listed highest ID first; the lowest ID is named.


def _tie() -> World:
    world = later_year(park_one())
    world["registry"].insert(0, ("park-9", 2001, 1, "company", "", "2026-11-12"))
    return world


def test_overlap_tie_names_the_lowest_id(company: Company) -> None:
    company.plant(_tie())
    company.refused(
        ["--start-year", "2001"], "start-year-overlap", overlap("2001", "park-1", 2001, "park-2")
    )


def test_gap_tie_names_the_lowest_id(company: Company) -> None:
    company.plant(_tie())
    company.refused(
        ["--start-year", "2003"],
        "start-year-gap",
        "Company year 2003 would leave company year 2002 with no managed park; the next park "
        "starts the March after 2001, which park park-1 sets, so START_YEAR must be 2002; "
        f"if 2001 looks too high, {ADR}",
    )


# Practice parks, park lists, the first park and a blank or unused START_YEAR.


def test_registered_practice_park_alone_does_not_require_start_year(company: Company) -> None:
    world = park_one()
    world["registry"] = [("park-1", 2000, 1, "company", register_parks.NOTE, "2026-11-12")]
    company.plant(world)
    assert company.run() == 0
    assert company.written() == [("park-2", "2000", "1", "")]


def test_park_list_gives_the_company_park_the_year_and_the_practice_park_2000(
    company: Company,
) -> None:
    world = park_one()
    world["sessions"].append(("park-3", "s3", (1, 0, 1), 4))
    company.plant(world)
    assert company.run("--parks", "park-3:practice,park-2:company", "--start-year", "2001") == 0
    assert company.written() == [
        ("park-2", "2001", "1", ""),
        ("park-3", "2000", "1", register_parks.NOTE),
    ]


def test_park_list_without_the_practice_mark_is_refused(company: Company) -> None:
    world = park_one()
    world["sessions"].append(("park-3", "s3", (1, 0, 1), 4))
    company.plant(world)
    company.refused(
        ["--parks", "park-3:company,park-2:company", "--start-year", "2001"],
        "several-company-parks",
        SEVERAL,
    )


def test_typed_2000_is_accepted_for_the_first_park(company: Company) -> None:
    company.plant(_first_park(1))
    company.accepted("park-2", "2000")


def test_typed_2000_for_a_first_park_with_origin_not_one_is_refused(company: Company) -> None:
    company.plant(_first_park(5))
    company.refused(
        ["--start-year", "2000"],
        "start-year-origin",
        "Park park-2 has game-year origin 5; a company start year needs a park that began in "
        "game year 1, so capture the park from a new game before registering it",
    )
    assert company.run() == 0
    assert company.written() == [("park-2", "2000", "5", "")]


@pytest.mark.parametrize("blank", ["", "  "])
def test_blank_start_year_is_not_given(company: Company, blank: str) -> None:
    company.plant(_first_park(1))
    assert company.run("--start-year", blank) == 0
    assert company.written() == [("park-2", "2000", "1", "")]
    assert company.out() == f"Registered 1 park(s) in {WRITTEN}.\n"


def test_start_year_with_nothing_to_register_is_not_used(company: Company) -> None:
    world = park_one()
    world["registry"].append(("park-2", 2001, 1, "company", "", "2026-11-12"))
    company.plant(world)
    before = _tree(company.tmp_path)
    assert company.run("--start-year", "2001") == 0
    assert _tree(company.tmp_path) == before
    assert company.out() == (
        "All captured parks are already registered.\n"
        "START_YEAR=2001 not used: no park waits to register.\n"
    )

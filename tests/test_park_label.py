"""Tests for ``park_label``: the one rule for naming a park, over planted landing files."""

from __future__ import annotations

import locale
import os
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.config import LandingDirs
from openrct2_analytics.ingest import park_label
from tests.test_after_play import _copy
from tests.test_managed_years_raw import write_raw_lines

UTC_MINUS_8 = timezone(timedelta(hours=-8))
Zone = Callable[[tzinfo], None]


@pytest.fixture
def landing(tmp_path: Path) -> LandingDirs:
    return LandingDirs(raw=tmp_path / "raw", parquet=tmp_path / "parquet")


@pytest.fixture(autouse=True)
def _utc_minus_8(fixed_local_zone: Zone) -> None:
    fixed_local_zone(UTC_MINUS_8)


def converted(landing: LandingDirs, rows: list[tuple[str, str, str | None, str]]) -> None:
    """Plant converted session_start rows: (park, session, name or None, emitted_at in UTC)."""
    query = " UNION ALL ".join(
        f"SELECT '{park}' AS park_id, '{session}' AS session_id, 1 AS game_year, "
        f"{'NULL::VARCHAR' if name is None else repr(name)} AS park_name, "
        f"TIMESTAMPTZ '{when.replace('T', ' ').replace('Z', '+00')}' AS emitted_at"
        for park, session, name, when in rows
    )
    _copy(landing.parquet / "v1" / "session_start.parquet", query)


def raw(
    landing: LandingDirs, session: str, park: str, name: str | None, *, when: str | None
) -> None:
    """Plant one raw session_start line in its own file, named after the session."""
    event: dict[str, object] = {
        "session_id": session,
        "park_id": park,
        "seq": 1,
        "event_type": "session_start",
    }
    if name is not None:
        event["park_name"] = name
    if when is not None:
        event["emitted_at"] = when
    write_raw_lines(landing.raw, f"events-{session}.jsonl", [event])


def label_map(landing: LandingDirs) -> dict[str, str]:
    return park_label.labels(park_label.park_facts(landing))


def test_label_names_the_first_played_day(landing: LandingDirs) -> None:
    converted(
        landing,
        [
            ("pa", "s1", "Bumbly Bazaar", "2026-11-15T20:00:00Z"),
            ("pb", "s2", "Electric Fields", "2026-11-05T20:00:00Z"),
        ],
    )

    assert label_map(landing) == {
        "pa": "Bumbly Bazaar (first played Nov 15)",
        "pb": "Electric Fields (first played Nov 5)",
    }


def test_every_month_has_its_english_name(landing: LandingDirs) -> None:
    converted(
        landing,
        [(f"p{n}", f"s{n}", "Park", f"2026-{n:02}-01T20:00:00Z") for n in range(1, 13)],
    )

    labels = label_map(landing)

    assert [labels[f"p{n}"] for n in range(1, 13)] == [
        "Park (first played Jan 1)",
        "Park (first played Feb 1)",
        "Park (first played Mar 1)",
        "Park (first played Apr 1)",
        "Park (first played May 1)",
        "Park (first played Jun 1)",
        "Park (first played Jul 1)",
        "Park (first played Aug 1)",
        "Park (first played Sep 1)",
        "Park (first played Oct 1)",
        "Park (first played Nov 1)",
        "Park (first played Dec 1)",
    ]


def test_month_ignores_the_locale(landing: LandingDirs, monkeypatch: pytest.MonkeyPatch) -> None:
    converted(landing, [("pa", "s1", "Park", "2026-12-15T20:00:00Z")])
    # Proof independent of installed locales: a locale-based strftime cannot print a marker.
    with monkeypatch.context() as months_patch:
        months_patch.setattr(park_label, "MONTHS", tuple(f"Month{n}" for n in range(1, 13)))
        assert label_map(landing) == {"pa": "Park (first played Month12 15)"}
    # Best effort: with a non-English locale installed the English name must still print.
    # The autouse fixed zone stays patched, so the day is Dec 15 on any machine.
    old = locale.setlocale(locale.LC_TIME)
    try:
        for name in ("de_DE.UTF-8", "fr_FR.UTF-8", "es_ES.UTF-8"):
            try:
                locale.setlocale(locale.LC_TIME, name)
                break
            except locale.Error:
                continue
        assert label_map(landing) == {"pa": "Park (first played Dec 15)"}
    finally:
        locale.setlocale(locale.LC_TIME, old)


def test_day_is_the_local_day_not_the_utc_day(landing: LandingDirs) -> None:
    converted(landing, [("pa", "s1", "Park", "2026-11-16T02:10:00Z")])

    assert label_map(landing) == {"pa": "Park (first played Nov 15)"}


def test_earliest_session_start_wins(landing: LandingDirs) -> None:
    converted(
        landing,
        [
            ("pa", "s1", "Park", "2026-11-20T20:00:00Z"),
            ("pa", "s2", "Park", "2026-11-18T20:00:00Z"),
        ],
    )
    raw(landing, "s3", "pa", "Park", when="2026-11-12T20:00:00Z")

    assert label_map(landing) == {"pa": "Park (first played Nov 12)"}


def test_raw_only_park_gets_its_first_played_day(landing: LandingDirs) -> None:
    raw(landing, "s1", "pa", "Raw Park", when="2026-11-12T20:00:00Z")

    assert label_map(landing) == {"pa": "Raw Park (first played Nov 12)"}


def test_nameless_raw_start_keeps_its_time(landing: LandingDirs) -> None:
    raw(landing, "s1", "pa", None, when="2026-11-12T20:00:00Z")

    assert label_map(landing) == {"pa": "pa (first played Nov 12)"}


def test_raw_start_without_offset_gives_no_time(landing: LandingDirs) -> None:
    raw(landing, "s1", "pa", "Raw Park", when="2026-11-12T20:00:00")

    assert label_map(landing) == {"pa": "Raw Park (pa)"}


def test_raw_start_unparsable_gives_no_time(landing: LandingDirs) -> None:
    raw(landing, "s1", "pa", "Raw Park", when="yesterday")

    assert label_map(landing) == {"pa": "Raw Park (pa)"}


def test_untimed_raw_start_sorts_after_timed_ones(landing: LandingDirs) -> None:
    raw(landing, "s1", "pa", "Timed Name", when="2026-11-12T20:00:00Z")
    raw(landing, "s2", "pa", "Untimed Name", when=None)

    facts = park_label.park_facts(landing)["pa"]

    assert facts.name == "Untimed Name"
    assert facts.first_played == datetime(2026, 11, 12, 20, tzinfo=UTC)


def test_untimed_raw_starts_tie_by_session_id_descending(landing: LandingDirs) -> None:
    raw(landing, "s1", "pa", "Lower Session", when=None)
    raw(landing, "s2", "pa", "Higher Session", when=None)

    assert park_label.park_facts(landing)["pa"].name == "Higher Session"


def test_latest_session_start_names_the_park(landing: LandingDirs) -> None:
    converted(
        landing,
        [
            ("pa", "s1", "Old Name", "2026-11-10T20:00:00Z"),
            ("pa", "s2", "New Name", "2026-11-11T20:00:00Z"),
        ],
    )
    raw(landing, "s3", "pa", "Raw Name", when="2026-11-12T20:00:00Z")

    assert park_label.park_facts(landing)["pa"].name == "New Name"
    assert park_label.park_names(landing.parquet) == {"pa": "New Name"}


def test_same_instant_starts_tie_by_session_id_descending(landing: LandingDirs) -> None:
    converted(
        landing,
        [
            ("pa", "s1", "Lower Session", "2026-11-10T20:00:00Z"),
            ("pa", "s2", "Higher Session", "2026-11-10T20:00:00Z"),
        ],
    )

    assert park_label.park_names(landing.parquet) == {"pa": "Higher Session"}
    assert label_map(landing) == {"pa": "Higher Session (first played Nov 10)"}


def test_blank_name_counts_as_missing(landing: LandingDirs) -> None:
    converted(
        landing,
        [
            ("pa", "s1", "   ", "2026-11-10T20:00:00Z"),
            ("pb", "s2", None, "2026-11-10T20:00:00Z"),
        ],
    )
    raw(landing, "s3", "pc", "", when="2026-11-10T20:00:00Z")

    assert label_map(landing) == {
        "pa": "pa (first played Nov 10)",
        "pb": "pb (first played Nov 10)",
        "pc": "pc (first played Nov 10)",
    }


def test_three_same_named_parks(landing: LandingDirs) -> None:
    converted(
        landing,
        [
            ("pa", "s1", "Bumbly Bazaar", "2026-11-15T23:42:00Z"),
            ("pc", "s3", "Bumbly Bazaar", "2026-11-16T18:00:00Z"),
            ("pd", "s4", "Electric Fields", "2026-11-14T17:00:00Z"),
        ],
    )
    raw(landing, "s2", "pb", "Bumbly Bazaar", when="2026-11-16T02:10:00Z")

    assert label_map(landing) == {
        "pa": "Bumbly Bazaar (Nov 15, 3:42 pm)",
        "pb": "Bumbly Bazaar (Nov 15, 6:10 pm)",
        "pc": "Bumbly Bazaar (first played Nov 16)",
        "pd": "Electric Fields (first played Nov 14)",
    }


def test_noon_and_midnight(landing: LandingDirs) -> None:
    converted(
        landing,
        [
            ("pa", "s1", "Twin", "2026-11-15T20:05:00Z"),
            ("pb", "s2", "Twin", "2026-11-15T08:05:00Z"),
        ],
    )

    assert label_map(landing) == {
        "pa": "Twin (Nov 15, 12:05 pm)",
        "pb": "Twin (Nov 15, 12:05 am)",
    }


def test_twin_outside_the_listed_parks_still_adds_the_time(landing: LandingDirs) -> None:
    converted(
        landing,
        [
            ("pa", "s1", "Twin", "2026-11-15T23:42:00Z"),
            ("pz", "s2", "Twin", "2026-11-16T01:00:00Z"),
        ],
    )

    labels = label_map(landing)

    assert park_label.label_of(labels, "pa") == "Twin (Nov 15, 3:42 pm)"


def test_the_same_month_and_day_in_different_years_are_twins(landing: LandingDirs) -> None:
    converted(
        landing,
        [
            ("pa", "s1", "Twin", "2025-11-15T23:42:00Z"),
            ("pb", "s2", "Twin", "2026-11-15T20:10:00Z"),
        ],
    )

    assert label_map(landing) == {
        "pa": "Twin (Nov 15, 3:42 pm)",
        "pb": "Twin (Nov 15, 12:10 pm)",
    }


def test_names_that_show_the_same_are_twins(landing: LandingDirs) -> None:
    converted(
        landing,
        [
            ("pc", "s3", "Beta", "2026-11-15T23:42:00Z"),
            ("pd", "s4", "Beta ", "2026-11-15T20:10:00Z"),
        ],
    )
    raw(landing, "s1", "pa", "Alpha\tPark", when="2026-11-15T23:42:00Z")
    raw(landing, "s2", "pb", "Alpha Park", when="2026-11-15T20:10:00Z")

    assert label_map(landing) == {
        "pa": "Alpha\tPark (Nov 15, 3:42 pm)",
        "pb": "Alpha Park (Nov 15, 12:10 pm)",
        "pc": "Beta (Nov 15, 3:42 pm)",
        "pd": "Beta  (Nov 15, 12:10 pm)",
    }


def test_names_that_show_the_same_share_the_minute_group(landing: LandingDirs) -> None:
    converted(
        landing,
        [
            ("pa", "s1", "Beta", "2026-11-15T23:42:10Z"),
            ("pb", "s2", "Beta ", "2026-11-15T23:42:50Z"),
        ],
    )

    assert label_map(landing) == {
        "pa": "Beta (Nov 15, 3:42 pm, pa)",
        "pb": "Beta  (Nov 15, 3:42 pm, pb)",
    }


def test_twins_in_the_same_minute_show_the_id(landing: LandingDirs) -> None:
    converted(
        landing,
        [
            ("pa", "s1", "Twin", "2026-11-15T23:42:10Z"),
            ("pb", "s2", "Twin", "2026-11-15T23:42:50Z"),
        ],
    )

    assert label_map(landing) == {
        "pa": "Twin (Nov 15, 3:42 pm, pa)",
        "pb": "Twin (Nov 15, 3:42 pm, pb)",
    }


def test_id_form_only_for_the_same_minute_group(landing: LandingDirs) -> None:
    converted(
        landing,
        [
            ("pa", "s1", "Twin", "2026-11-15T23:42:00Z"),
            ("pb", "s2", "Twin", "2026-11-15T23:42:30Z"),
            ("pc", "s3", "Twin", "2026-11-16T00:10:00Z"),
        ],
    )

    assert label_map(landing) == {
        "pa": "Twin (Nov 15, 3:42 pm, pa)",
        "pb": "Twin (Nov 15, 3:42 pm, pb)",
        "pc": "Twin (Nov 15, 4:10 pm)",
    }


def test_no_first_played_keeps_name_and_id(landing: LandingDirs) -> None:
    raw(landing, "s1", "pa", "Raw Park", when=None)

    assert label_map(landing) == {"pa": "Raw Park (pa)"}


def test_no_name_uses_the_id(landing: LandingDirs) -> None:
    converted(landing, [("pa", "s1", None, "2026-11-15T23:42:00Z")])

    assert label_map(landing) == {"pa": "pa (first played Nov 15)"}


def test_no_name_and_no_time_is_the_id(landing: LandingDirs) -> None:
    raw(landing, "s1", "pa", None, when=None)

    assert label_map(landing) == {"pa": "pa"}


def test_missing_parquet_gives_no_facts(landing: LandingDirs) -> None:
    assert park_label.park_facts(landing) == {}
    assert park_label.park_names(landing.parquet) == {}


def test_registry_only_park_is_its_id(landing: LandingDirs) -> None:
    converted(landing, [("pa", "s1", "Park", "2026-11-15T23:42:00Z")])
    feed = landing.parquet.parent / "registry" / "v1"
    feed.mkdir(parents=True)
    (feed / "park_registry_1.csv").write_text("park_id\nreg-only\n", encoding="utf-8")

    labels = label_map(landing)

    assert "reg-only" not in labels
    assert park_label.label_of(labels, "reg-only") == "reg-only"


def test_warehouse_only_park_is_its_id(landing: LandingDirs) -> None:
    converted(landing, [("pa", "s1", "Park", "2026-11-15T23:42:00Z")])
    warehouse = landing.parquet.parent / "dev.duckdb"
    with duckdb.connect(str(warehouse)) as connection:
        connection.execute("CREATE TABLE stg_session_start AS SELECT 'wh-only' AS park_id")

    labels = label_map(landing)

    assert "wh-only" not in labels
    assert park_label.label_of(labels, "wh-only") == "wh-only"


def test_failed_audit_only_park_is_its_id(landing: LandingDirs) -> None:
    converted(landing, [("pa", "s1", "Park", "2026-11-15T23:42:00Z")])
    _copy(
        landing.parquet / "audit" / "seq_audit.parquet",
        "SELECT 'audit-only' AS park_id, 's9' AS session_id, 2 AS park_count",
    )

    labels = label_map(landing)

    assert "audit-only" not in labels
    assert park_label.label_of(labels, "audit-only") == "audit-only"


def test_park_with_only_non_start_raw_events_is_its_id(landing: LandingDirs) -> None:
    write_raw_lines(
        landing.raw,
        "events-s1.jsonl",
        [{"session_id": "s1", "park_id": "pa", "seq": 2, "event_type": "park_snapshot"}],
    )

    facts = park_label.park_facts(landing)

    assert facts == {"pa": park_label.ParkFacts(name=None, first_played=None)}
    assert park_label.label_of(park_label.labels(facts), "pa") == "pa"


@pytest.fixture
def los_angeles() -> Iterator[None]:
    old = os.environ.get("TZ")
    os.environ["TZ"] = "America/Los_Angeles"
    time.tzset()
    try:
        yield
    finally:
        if old is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = old
        time.tzset()


def test_to_local_applies_the_offset_of_each_instant(
    los_angeles: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The autouse fixture patched to_local; undo it so the real function runs.
    monkeypatch.undo()
    october = park_label.to_local(datetime(2026, 10, 16, 6, 30, tzinfo=UTC))
    december = park_label.to_local(datetime(2026, 12, 16, 6, 30, tzinfo=UTC))

    assert (october.month, october.day, october.hour, october.minute) == (10, 15, 23, 30)
    assert (december.month, december.day, december.hour, december.minute) == (12, 15, 22, 30)

"""Tests for the rehearsal proof and landing: nine synthetic attempts, real convert and lock."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from openrct2_analytics.ingest.lock import (
    raise_interrupted,
    set_signal_handlers,
)
from openrct2_analytics.ingest.registry_feed import check_feed
from openrct2_analytics.ingest.rehearsal_land import Attempt, land, no_hook
from tests.test_convert import event, query, tree
from tests.test_convert_event_types import START_PAYLOAD, typed_event
from tests.test_guest_event_types import PAYLOADS

PARK_IDS = {1: "k1791580000001-rhpark", 2: "k1791590000000-abc123"}
THIRD_PARK = "k1791599999999-zzz999"
# (step, park) in the schedule's order: Park 2 joins at step 4.
PLAN = ((1, 1), (2, 1), (3, 1), (4, 2), (5, 1), (6, 2), (7, 1), (8, 2), (9, 1))
ORIGINS = {1: 1, 2: 4}
# Every session starts with session_start; its last event (a park_snapshot) crosses a year end, so
# the first park_snapshot of a park falls a year after its origin.
TYPES = (
    "session_start",
    "guest_arrived",
    "guest_boarded",
    "guest_left",
    "guest_snapshot",
    "park_snapshot",
)

Chain = dict[int, list[str]]
MALFORMED = 0  # a chain key outside the nine steps: lines for a malformed-*.jsonl file in step 2


def line(session: str, seq: int, event_type: str, park_id: str, *, year: int) -> str:
    if event_type == "park_snapshot":
        return event(session, seq, park_id=park_id, game_year=year)
    payload = START_PAYLOAD if event_type == "session_start" else PAYLOADS[event_type]
    return typed_event(session, seq, event_type, {**payload, "park_id": park_id, "game_year": year})


def session(name: str, park_id: str, year: int, types: tuple[str, ...] = TYPES) -> list[str]:
    last = len(types)
    return [
        line(name, seq, kind, park_id, year=year if seq < last else year + 1)
        for seq, kind in enumerate(types, start=1)
    ]


def clean_chain(types: tuple[str, ...] = TYPES) -> Chain:
    played = dict.fromkeys(ORIGINS, 0)
    chain: Chain = {}
    for step, park in PLAN:
        chain[step] = session(f"s{step}", PARK_IDS[park], ORIGINS[park] + played[park], types)
        played[park] += 1
    return chain


def write(root: Path, chain: Chain) -> list[Attempt]:
    attempts = []
    for step, park in PLAN:
        raw = root / f"attempt-{step}" / "raw"
        (raw / "v1").mkdir(parents=True)
        (raw / "v1" / "events-2026-10-18.jsonl").write_text("\n".join(chain[step]) + "\n")
        if step == 2 and MALFORMED in chain:  # the listener writes these beside v1/
            (raw / "malformed-2026-10-18.jsonl").write_text("\n".join(chain[MALFORMED]) + "\n")
        attempts.append(Attempt(step=step, park=park, raw=raw))
    return attempts


@pytest.fixture(autouse=True)
def installed_handlers(handlers: None) -> Iterator[None]:
    """Install the command's handlers; the conftest ``handlers`` fixture restores them."""
    set_signal_handlers(raise_interrupted)
    yield


def no_guard() -> None:
    """The write-boundary check is the capture command's; these tests run without it."""


def run(tmp_path: Path, chain: Chain, hook: Callable[[str], None] = no_hook) -> int:
    attempts = list(reversed(write(tmp_path / "work", chain)))  # list order must not matter
    work = tmp_path / "work"
    return land(
        attempts, combined=work / "combined", converted=work / "pq", guard=no_guard, hook=hook
    )


def landed(data_root: Path) -> list[str]:
    rehearsal = data_root / "rehearsal"
    return sorted(str(p.relative_to(rehearsal)) for p in rehearsal.rglob("*") if p.is_file())


def test_a_clean_two_park_chain_lands_nine_raw_files_and_one_checked_delivery(
    tmp_path: Path, data_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(tmp_path, clean_chain()) == 0

    files = landed(data_root)
    raw = [f for f in files if f.startswith("raw/v1/events-")]
    delivery = [f for f in files if f.startswith("registry/v1/park_registry_")]
    assert len(raw) == 9 and len(delivery) == 1 and len(files) == 10
    assert sorted(f.rsplit("-", 1)[1] for f in raw) == sorted(f"{n}.jsonl" for n in range(1, 10))
    assert check_feed(data_root / "rehearsal" / "registry") == []
    assert not (data_root / "rehearsal" / "parquet.lock").exists()
    rows = query(
        data_root / "rehearsal" / delivery[0],
        "SELECT park_id, company_start_year, game_year_origin FROM read_csv('{p}')",
    )
    # Origins are each park's first session_start year, never its first park_snapshot year.
    assert rows == [(PARK_IDS[1], 2000, 1), (PARK_IDS[2], 2003, 4)]
    assert "Park 2: k1791590000000-abc123, company start year 2003, game year origin 4." in (
        capsys.readouterr().out
    )


def drop_seq(chain: Chain) -> None:
    del chain[2][2]


def repeat_line(chain: Chain) -> None:
    chain[2].insert(2, chain[2][1])


def two_parks_in_session(chain: Chain) -> None:
    chain[2][2] = line("s2", 3, "guest_boarded", PARK_IDS[2], year=2)


def third_park(chain: Chain) -> None:
    chain[8] = session("s8", THIRD_PARK, 6)


def park1_with_park2_id(chain: Chain) -> None:
    chain[5] = session("s5", PARK_IDS[2], 4)


def no_guest_rows(chain: Chain) -> None:
    chain.update(clean_chain(tuple("park_snapshot" if t == "guest_boarded" else t for t in TYPES)))


def before_origin(chain: Chain) -> None:
    chain[5][2] = line("s5", 3, "guest_boarded", PARK_IDS[1], year=0)


def two_session_ids(chain: Chain) -> None:
    chain[2] += session("s2b", PARK_IDS[1], 2)


def two_session_starts(chain: Chain) -> None:
    chain[2].insert(5, line("s2", 6, "session_start", PARK_IDS[1], year=2))
    chain[2][6] = line("s2", 7, "park_snapshot", PARK_IDS[1], year=3)


def shared_session_id(chain: Chain) -> None:
    # Step 9 continues step 7's session_id and seq: each attempt is clean, the seq audit too.
    chain[9] = [
        line("s7", seq + len(TYPES), kind, PARK_IDS[1], year=6 if seq < len(TYPES) else 7)
        for seq, kind in enumerate(TYPES, start=1)
    ]


def repeated_year(chain: Chain) -> None:
    chain[5] = session("s5", PARK_IDS[1], 3)  # step 5 replays step 3's year


def skipped_year(chain: Chain) -> None:
    chain[5] = session("s5", PARK_IDS[1], 5)  # step 5 should play game year 4


def out_of_step_order(chain: Chain) -> None:
    chain[5], chain[7] = chain[7], chain[5]


def session_stays_in_its_start_year(chain: Chain) -> None:
    chain[5] = [
        line("s5", seq, kind, PARK_IDS[1], year=4) for seq, kind in enumerate(TYPES, start=1)
    ]  # step 5 starts in its planned year 4 but never crosses the year end


def first_step_event_before_the_first_session_start(chain: Chain) -> None:
    # Park 1's origin is its first session_start year (1), not the step's lowest year (0).
    chain[1][2] = line("s1", 3, "guest_boarded", PARK_IDS[1], year=0)


def park2_event_before_the_first_session_start(chain: Chain) -> None:
    chain[4][2] = line("s4", 3, "guest_boarded", PARK_IDS[2], year=3)


def malformed_line(chain: Chain) -> None:
    chain[MALFORMED] = ["{not json"]


def schema_error(chain: Chain) -> None:
    chain[3][5] = event("s3", 6, park_id=PARK_IDS[1], game_year="oops")


FAILURES = {
    "seq gap": (drop_seq, "seq audit: "),
    "seq repeat": (repeat_line, "seq audit: "),
    "session with two parks": (two_parks_in_session, "seq audit: "),
    "three parks": (third_park, "The chain holds 3 park_id values, not 2."),
    "park 1 session with park 2 id": (park1_with_park2_id, "do not share one park_id"),
    "no guest rows": (no_guest_rows, "No guest_boarded row"),
    "event before the origin": (before_origin, "before Park 1's origin 1"),
    "two session ids in an attempt": (two_session_ids, "Step 2 holds 2 session_id values"),
    "two session starts in an attempt": (two_session_starts, "Step 2 holds 2 session_start rows"),
    "fewer than nine session ids": (shared_session_id, "hold 8 distinct session_id values"),
    "repeated year": (repeated_year, "Step 5 (Park 1, session 4) plays game years 3 to 4"),
    "skipped year": (skipped_year, "Step 5 (Park 1, session 4) plays game years 5 to 6"),
    "session never crosses its year end": (
        session_stays_in_its_start_year,
        "Step 5 (Park 1, session 4) plays game years 4 to 4; the plan is 4 to 5.",
    ),
    "park 1 origin is its first session_start, not its lowest year": (
        first_step_event_before_the_first_session_start,
        "Step 1 has an event in game year 0, before Park 1's origin 1.",
    ),
    "park 2 origin is its first session_start, not its lowest year": (
        park2_event_before_the_first_session_start,
        "Step 4 has an event in game year 3, before Park 2's origin 4.",
    ),
    "malformed line": (malformed_line, "1 malformed line(s) in the attempts."),
    "schema error": (schema_error, "Schema error: "),
    "out of step order": (out_of_step_order, "Step 5 (Park 1, session 4) plays game years 5"),
}


@pytest.mark.parametrize("case", FAILURES)
def test_each_proof_failure_exits_1_and_leaves_the_data_folder_as_it_was(
    case: str, tmp_path: Path, data_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mutate, message = FAILURES[case]
    chain = clean_chain()
    mutate(chain)
    before = tree(data_root)

    assert run(tmp_path, chain) == 1

    out = capsys.readouterr().out
    assert message in out and "Nothing was landed." in out
    assert tree(data_root) == before


def test_a_delivery_failing_check_file_lands_nothing(
    tmp_path: Path, data_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Park 2's game years start at 0, so its origin 0 breaks the contract's minimum of 1.
    chain = clean_chain()
    for k, step in enumerate((4, 6, 8)):
        chain[step] = session(f"s{step}", PARK_IDS[2], k)
    seen: list[str] = []

    def hook(stage: str) -> None:
        if stage == "delivery-written":
            feed = data_root / "rehearsal" / "registry" / "v1"
            seen.extend(p.name for p in feed.glob("park_registry_*.csv"))

    assert run(tmp_path, chain, hook) == 1

    assert seen == []  # the delivery is written under its .incoming- name only
    assert "The registry delivery fails its check" in capsys.readouterr().out
    assert landed(data_root) == []
    assert sorted(p.name for p in (data_root / "rehearsal").iterdir()) == ["raw", "registry"]


def test_a_taken_lock_exits_1_with_nothing_landed(tmp_path: Path, data_root: Path) -> None:
    lock = data_root / "rehearsal" / "parquet.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("pid 1 started earlier\n")

    assert run(tmp_path, clean_chain()) == 1

    assert landed(data_root) == ["parquet.lock"]
    assert lock.read_text() == "pid 1 started earlier\n"


@pytest.mark.parametrize(
    "written_and_shown",
    [
        ("registry/v1/park_registry_2026-10-17_01.csv", "registry/v1/"),
        ("raw/v1/events-2026-10-17.jsonl", "raw/"),
    ],
)
def test_emptiness_is_rechecked_under_the_lock(
    written_and_shown: tuple[str, str],
    tmp_path: Path,
    data_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    written, shown = written_and_shown
    mid_chain = data_root / "rehearsal" / written

    def hook(stage: str) -> None:
        if stage == "locked":
            assert (data_root / "rehearsal" / "parquet.lock").is_file()
            mid_chain.parent.mkdir(parents=True, exist_ok=True)
            mid_chain.write_text("written mid-chain\n")

    assert run(tmp_path, clean_chain(), hook) == 1

    out = capsys.readouterr().out
    assert f"data/rehearsal/{shown} is not empty" in out and "half landed" in out
    assert landed(data_root) == [written]
    assert mid_chain.read_text() == "written mid-chain\n"

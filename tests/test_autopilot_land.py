"""Tests for the autopilot landing: label, records, then one raw file, under the landing lock.

Every test lays out a temporary company folder like ``data/company/`` and a work folder holding
``raw/v1/`` and ``save_files/v1/``; the real ``data/company/`` is never touched.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import signal
import stat
import threading
import time
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import pytest

from openrct2_analytics.ingest import autopilot_land, lock
from openrct2_analytics.ingest.autopilot_land import (
    LandingLockHeld,
    LandingStepFailed,
    StagedLabelFailed,
    land,
)

PARK = "park-a1"
SESSION = "sess-0001"
READY = "park-a1 is profitable and its scenario challenge is complete"
TODAY = date(2026, 11, 13)  # the local date the label delivery is named after
HEADER = "session_id,park_id,play_mode,ready_confirmation,data_set,delivered_on\n"

LABEL = "session_play_mode_2026-11-13_01.csv"
RECORD = "save_file_observation_2026-11-12-autopilot-sess-0001.jsonl"
RAW = "events-2026-11-12-autopilot-sess-0001.jsonl"


@pytest.fixture(autouse=True)
def caller_handlers(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Install the handlers the command installs, fix the local date, restore both afterwards."""
    numbers = [getattr(signal, n) for n in lock.SIGNAL_NAMES if hasattr(signal, n)]
    previous = {number: signal.getsignal(number) for number in numbers}
    lock.set_signal_handlers(lock.raise_interrupted)
    monkeypatch.setattr(autopilot_land, "_local_today", lambda: TODAY)
    yield
    for number, handler in previous.items():
        signal.signal(number, handler)


@pytest.fixture
def company(tmp_path: Path) -> Path:
    """A company folder whose three landing folders exist, as after earlier play."""
    root = tmp_path / "data" / "company"
    for folder in ("raw/v1", "save_files/v1", "registry/v1"):
        (root / folder).mkdir(parents=True)
    return root


def work_folder(
    root: Path,
    raw: dict[str, str] | None = None,
    records: dict[str, str] | None = None,
) -> Path:
    """Write a valid work folder: one raw file and one record file of one UTC day."""
    raw = raw if raw is not None else {"events-2026-11-12.jsonl": '{"seq": 1}\n{"seq": 2}\n'}
    records = records if records is not None else {"save_file_observation_2026-11-12.jsonl": "{}\n"}
    for folder, files in (("raw/v1", raw), ("save_files/v1", records)):
        (root / folder).mkdir(parents=True)
        for name, text in files.items():
            (root / folder / name).write_text(text, encoding="utf-8")
    return root


def listing(root: Path) -> dict[str, str]:
    """Every entry under ``root``, with a SHA-256 for files and ``dir`` for folders."""
    entries: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        key = path.relative_to(root).as_posix()
        if path.is_dir():
            entries[key] = "dir"
        else:
            entries[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return entries


def label_text(*rows: tuple[str, str, str]) -> str:
    return HEADER + "".join(
        f"{session},{PARK},autopilot,{ready},company,2026-11-13\n" for session, _, ready in rows
    )


def passes() -> None:
    """A guard with nothing to refuse, for tests not about the guard."""


def land_work(work: Path, company: Path, guard: Callable[[], None] = passes) -> list[Path]:
    """Land ``work`` as session SESSION of PARK with its ready phrase."""
    return land(
        work,
        park_id=PARK,
        session_id=SESSION,
        ready_confirmation=READY,
        data_root=company,
        guard=guard,
    )


def spy_links(monkeypatch: pytest.MonkeyPatch, after: Callable[[int], None]) -> list[str]:
    """Record each hard link's target name; call ``after`` with the link count after each link."""
    real = os.link
    made: list[str] = []

    def link(src: os.PathLike[str] | str, dst: os.PathLike[str] | str) -> None:
        real(src, dst)
        made.append(Path(dst).name)
        after(len(made))

    monkeypatch.setattr(os, "link", link)
    return made


def test_lands_label_then_records_then_one_raw_file_with_reader_names(
    tmp_path: Path, company: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = work_folder(tmp_path / "work")
    made = spy_links(monkeypatch, lambda count: None)

    landed = land(
        work,
        park_id=PARK,
        session_id=SESSION,
        ready_confirmation=READY,
        data_root=company,
        guard=passes,
    )

    assert made == [LABEL, RECORD, RAW]
    assert landed == [
        company / "registry/v1" / LABEL,
        company / "save_files/v1" / RECORD,
        company / "raw/v1" / RAW,
    ]
    assert (company / "registry/v1" / LABEL).read_text() == label_text((SESSION, PARK, READY))
    assert (company / "save_files/v1" / RECORD).read_text() == "{}\n"
    assert (company / "raw/v1" / RAW).read_text() == '{"seq": 1}\n{"seq": 2}\n'
    # The readers' globs: convert.py:392 and save_pairing.py:24.
    assert fnmatch.fnmatch(RAW, "events-*.jsonl")
    assert fnmatch.fnmatch(RECORD, "save_file_observation_*.jsonl")
    assert sorted(p.name for p in (company / "registry/v1").iterdir()) == [LABEL]
    assert not (company / "parquet.lock").exists()
    assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN  # still ignored for the report


def test_a_later_session_without_the_phrase_takes_the_next_delivery_number(
    tmp_path: Path, company: Path
) -> None:
    land(
        work_folder(tmp_path / "w1"),
        park_id=PARK,
        session_id=SESSION,
        ready_confirmation=READY,
        data_root=company,
        guard=passes,
    )

    landed = land(
        work_folder(tmp_path / "w2"),
        park_id=PARK,
        session_id="sess-0002",
        ready_confirmation="",
        data_root=company,
        guard=passes,
    )

    assert landed[0] == company / "registry/v1" / "session_play_mode_2026-11-13_02.csv"
    assert landed[0].read_text() == label_text(("sess-0002", PARK, ""))
    assert [p.name for p in landed[1:]] == [
        "save_file_observation_2026-11-12-autopilot-sess-0002.jsonl",
        "events-2026-11-12-autopilot-sess-0002.jsonl",
    ]


def test_a_run_across_utc_midnight_lands_two_records_and_one_joined_raw_file(
    tmp_path: Path, company: Path
) -> None:
    work = work_folder(
        tmp_path / "work",
        raw={
            "events-2026-11-13.jsonl": '{"seq": 3}\n',
            "events-2026-11-12.jsonl": '{"seq": 1}\n{"seq": 2}\n',
        },
        records={
            "save_file_observation_2026-11-13.jsonl": '{"b": 2}\n',
            "save_file_observation_2026-11-12.jsonl": '{"a": 1}\n',
        },
    )

    landed = land(
        work,
        park_id=PARK,
        session_id=SESSION,
        ready_confirmation=READY,
        data_root=company,
        guard=passes,
    )

    assert [p.name for p in landed] == [
        LABEL,
        "save_file_observation_2026-11-12-autopilot-sess-0001.jsonl",
        "save_file_observation_2026-11-13-autopilot-sess-0001.jsonl",
        "events-2026-11-12-autopilot-sess-0001.jsonl",
    ]
    assert landed[1].read_text() == '{"a": 1}\n'
    assert landed[2].read_text() == '{"b": 2}\n'
    assert landed[3].read_text() == '{"seq": 1}\n{"seq": 2}\n{"seq": 3}\n'
    assert [p.name for p in (company / "raw/v1").iterdir()] == [landed[3].name]


def test_a_staged_label_that_fails_the_checker_lands_nothing(tmp_path: Path, company: Path) -> None:
    work = work_folder(tmp_path / "work")
    before = listing(company)

    with pytest.raises(StagedLabelFailed) as caught:
        land(
            work,
            park_id=PARK,
            session_id=SESSION,
            ready_confirmation="",
            data_root=company,
            guard=passes,
        )

    assert any("first autopilot row" in problem for problem in caught.value.problems)
    assert listing(company) == before
    assert not (tmp_path / "data/company/parquet.lock").exists()


def test_a_failure_between_two_links_leaves_label_and_records_and_no_raw(
    tmp_path: Path, company: Path
) -> None:
    work = work_folder(tmp_path / "work")
    raw = company / "raw/v1"
    raw.chmod(stat.S_IRUSR | stat.S_IXUSR)  # the raw step cannot write its staged file
    try:
        with pytest.raises(LandingStepFailed) as caught:
            land(
                work,
                park_id=PARK,
                session_id=SESSION,
                ready_confirmation=READY,
                data_root=company,
                guard=passes,
            )
    finally:
        raw.chmod(stat.S_IRWXU)

    assert caught.value.step == "raw"
    assert caught.value.landed == [
        company / "registry/v1" / LABEL,
        company / "save_files/v1" / RECORD,
    ]
    assert isinstance(caught.value.cause, PermissionError)
    assert list(raw.iterdir()) == []
    assert sorted(p.name for p in (company / "registry/v1").iterdir()) == [LABEL]
    assert sorted(p.name for p in (company / "save_files/v1").iterdir()) == [RECORD]
    assert not (company / "parquet.lock").exists()


def test_a_taken_lock_lands_nothing_and_names_its_holder(tmp_path: Path, company: Path) -> None:
    work = work_folder(tmp_path / "work")
    (company / "parquet.lock").write_text("pid 4242 started 2026-11-13T09:00:00+0000\n")
    before = listing(company)

    with pytest.raises(LandingLockHeld) as caught:
        land(
            work,
            park_id=PARK,
            session_id=SESSION,
            ready_confirmation=READY,
            data_root=company,
            guard=passes,
            lock_wait_s=0.0,
        )

    assert caught.value.holder_line == "pid 4242 started 2026-11-13T09:00:00+0000"
    assert listing(company) == before


def test_a_lock_released_while_waiting_lets_the_landing_go_ahead(
    tmp_path: Path, company: Path
) -> None:
    work = work_folder(tmp_path / "work")
    held = company / "parquet.lock"
    held.write_text("pid 4242 started 2026-11-13T09:00:00+0000\n")
    release = threading.Timer(0.5, held.unlink)
    release.start()
    started = time.monotonic()
    try:
        landed = land(
            work,
            park_id=PARK,
            session_id=SESSION,
            ready_confirmation=READY,
            data_root=company,
            guard=passes,
            lock_wait_s=10.0,
        )
    finally:
        release.join()

    assert time.monotonic() - started >= 0.5
    assert [p.name for p in landed] == [LABEL, RECORD, RAW]


def test_an_interrupt_after_the_first_link_is_ignored_and_the_landing_finishes(
    tmp_path: Path, company: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = work_folder(tmp_path / "work")

    def interrupt(count: int) -> None:
        if count == 1:
            os.kill(os.getpid(), signal.SIGINT)

    spy_links(monkeypatch, interrupt)

    landed = land(
        work,
        park_id=PARK,
        session_id=SESSION,
        ready_confirmation=READY,
        data_root=company,
        guard=passes,
    )

    assert [p.name for p in landed] == [LABEL, RECORD, RAW]
    assert (company / "raw/v1" / RAW).read_text() == '{"seq": 1}\n{"seq": 2}\n'


def test_a_second_landing_of_the_same_session_is_refused_and_changes_nothing(
    tmp_path: Path, company: Path
) -> None:
    land(
        work_folder(tmp_path / "w1"),
        park_id=PARK,
        session_id=SESSION,
        ready_confirmation=READY,
        data_root=company,
        guard=passes,
    )
    before = listing(company)

    with pytest.raises(StagedLabelFailed) as caught:
        land(
            work_folder(tmp_path / "w2"),
            park_id=PARK,
            session_id=SESSION,
            ready_confirmation="",
            data_root=company,
            guard=passes,
        )

    assert any("unique" in problem for problem in caught.value.problems)
    assert listing(company) == before


def test_a_raw_name_already_taken_refuses_before_any_link_and_lands_nothing(
    tmp_path: Path, company: Path
) -> None:
    # The first landing's raw file stays after its label delivery was removed by hand.
    first = company / "raw/v1" / RAW
    first.write_text('{"seq": 1, "first": true}\n', encoding="utf-8")
    kept = first.read_bytes()
    before = listing(company)

    with pytest.raises(LandingStepFailed) as caught:
        land_work(work_folder(tmp_path / "work"), company)

    assert caught.value.step == "label"
    assert caught.value.landed == []
    assert isinstance(caught.value.cause, FileExistsError)
    assert str(caught.value.cause) == (
        f"{tmp_path}/data/company/raw/v1/{RAW} already exists; a landed file is never replaced"
    )
    assert first.read_bytes() == kept
    assert listing(company) == before
    assert sorted(p.name for p in (company / "raw/v1").iterdir()) == [RAW]


def test_a_label_name_taken_after_naming_is_refused_by_the_checker_before_any_link(
    tmp_path: Path, company: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    land_work(work_folder(tmp_path / "w1"), company)
    # As if a writer that ignores the lock placed this name between naming and linking.
    monkeypatch.setattr(autopilot_land, "_label_name", lambda feed, today: LABEL)
    before = listing(company)

    with pytest.raises(StagedLabelFailed) as caught:
        land(
            work_folder(tmp_path / "w2"),
            park_id=PARK,
            session_id="sess-0002",
            ready_confirmation="",
            data_root=company,
            guard=passes,
        )

    assert caught.value.problems == [
        f"staged file {LABEL} is already delivered in {tmp_path}/data/company/registry"
    ]
    assert listing(company) == before


@pytest.mark.parametrize(
    "leftover",
    [
        f"registry/v1/.incoming-{LABEL}",
        f"save_files/v1/.incoming-{RECORD}",
        f"raw/v1/.incoming-{RAW}",
    ],
)
def test_a_leftover_incoming_entry_refuses_before_any_link_naming_it(
    tmp_path: Path, company: Path, leftover: str
) -> None:
    (company / leftover).mkdir()
    before = listing(company)

    with pytest.raises(LandingStepFailed) as caught:
        land_work(work_folder(tmp_path / "work"), company)

    assert caught.value.step == "label"
    assert caught.value.landed == []
    assert isinstance(caught.value.cause, FileExistsError)
    assert str(caught.value.cause) == (
        f"{tmp_path}/data/company/{leftover} is left from an earlier landing"
    )
    assert listing(company) == before
    assert signal.getsignal(signal.SIGINT) is lock.raise_interrupted  # no link, still handled


@pytest.mark.parametrize(
    "raw",
    [
        {"events-2026-11-12.jsonl": '{"seq": 1}', "events-2026-11-13.jsonl": '{"seq": 2}\n'},
        {"events-2026-11-12.jsonl": '{"seq": 1}\n', "events-2026-11-13.jsonl": '{"seq": 2}'},
    ],
    ids=["first-part", "last-part"],
)
def test_a_raw_part_without_a_final_newline_fails_the_raw_step_and_lands_no_raw_file(
    tmp_path: Path, company: Path, raw: dict[str, str]
) -> None:
    work = work_folder(tmp_path / "work", raw=raw)
    cut = next(name for name, text in raw.items() if not text.endswith("\n"))

    with pytest.raises(LandingStepFailed) as caught:
        land_work(work, company)

    assert caught.value.step == "raw"
    assert caught.value.landed == [
        company / "registry/v1" / LABEL,
        company / "save_files/v1" / RECORD,
    ]
    assert str(caught.value.cause) == f"{tmp_path}/work/raw/v1/{cut} does not end in a newline"
    assert list((company / "raw/v1").iterdir()) == []


def test_a_landing_folder_made_a_link_while_the_lock_is_held_lands_nothing(
    tmp_path: Path, company: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = work_folder(tmp_path / "work")
    outside = tmp_path / "outside"
    outside.mkdir()
    real_hold = autopilot_land._hold

    def hold_then_swap(*args: object) -> None:
        real_hold(*args)  # type: ignore[arg-type]
        (company / "raw/v1").rmdir()
        (company / "raw/v1").symlink_to(outside, target_is_directory=True)

    def guard() -> None:
        assert (company / "parquet.lock").exists()  # called with the lock held
        for folder in ("registry/v1", "save_files/v1", "raw/v1"):
            if (company / folder).is_symlink():
                raise RuntimeError(f"{company / folder} is a link")

    monkeypatch.setattr(autopilot_land, "_hold", hold_then_swap)

    with pytest.raises(RuntimeError) as caught:
        land_work(work, company, guard)

    assert str(caught.value) == f"{tmp_path}/data/company/raw/v1 is a link"
    assert list(outside.iterdir()) == []
    assert list((company / "registry/v1").iterdir()) == []
    assert list((company / "save_files/v1").iterdir()) == []
    assert not (company / "parquet.lock").exists()
    assert signal.getsignal(signal.SIGINT) is lock.raise_interrupted

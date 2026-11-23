"""The rehearsal capture's refusals fire in R3 order: with two faults, the earlier item speaks.

Each pair sets up two adjacent items' faults at once; swapping those items' checks in
``rehearsal_capture.run`` turns the pair's test red. The single-fault tests are in
``test_rehearsal_refusals.py``.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from openrct2_analytics.ingest.game_check import GameState
from openrct2_analytics.ingest.rehearsal_chain import attempt_name
from tests.test_bench_run import REPO_ROOT
from tests.test_rehearsal_capture import AUTOSAVE_TIME, RehearsalHarness
from tests.test_rehearsal_refusals import FakeTime, held, refuse_unchanged

Fault = tuple[str, dict[str, object]]  # the text of the refusal it earns, and main's seams


def fault_3(rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch) -> Fault:
    monkeypatch.setenv("OPENRCT2_BENCH_DIR", str(REPO_ROOT / "data" / "sample"))
    return "data/sample/", {}


def fault_4(rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch) -> Fault:
    raw = rh.data_root / "rehearsal" / "raw"
    raw.mkdir(parents=True)
    (rh.data_root / "rehearsal" / "parquet").symlink_to(raw)
    return "resolve to, or nest inside", {}


def fault_5(rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch) -> Fault:
    (rh.data_root / "rehearsal").mkdir(parents=True, exist_ok=True)
    (rh.data_root / "rehearsal" / "parquet.lock").write_text("", encoding="utf-8")
    return "A parquet.lock is present", {}


def fault_6(rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch) -> Fault:
    (rh.bench.bench_dir / attempt_name(1, 1)).mkdir(parents=True)
    return "already holds", {}


def fault_7_fixture(rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch) -> Fault:
    rh.bench.fixture.write_bytes(b"another park")
    return "OPENRCT2_BENCH_PARK is not", {}


def fault_7_park2(rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch) -> Fault:
    rh.park2.write_bytes(b"another park two")
    rh.protected = rh.protected_state()  # the test changed the source on purpose
    return "OPENRCT2_REHEARSAL_PARK2 is not", {}


def fault_8(rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch) -> Fault:
    rh.bench.binary.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    return "did not answer --version", {}


def fault_9_process(rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch) -> Fault:
    return "OpenRCT2 is running", {"game_check": lambda: GameState.RUNNING}


def fault_9_autosave(rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch) -> Fault:
    return "autosave is", {"clock": lambda: AUTOSAVE_TIME + 60}


def fault_9_port(rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch) -> Fault:
    return "Cannot listen on", {}


def fault_10(rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch) -> Fault:
    fake = FakeTime()  # no real sleeping if the wait ever runs before the item above it
    return "load average stayed", {
        "load_average": lambda: 3.0,
        "clock": fake.clock,
        "sleep": fake.sleep,
    }


ADJACENT_FAULTS = [
    (fault_3, fault_5),
    (fault_4, fault_5),
    (fault_5, fault_6),
    (fault_6, fault_7_fixture),
    (fault_7_fixture, fault_7_park2),
    (fault_7_park2, fault_8),
    (fault_8, fault_9_process),
    (fault_9_process, fault_9_autosave),
    (fault_9_autosave, fault_9_port),
    (fault_9_port, fault_10),
]


@pytest.mark.parametrize(("first", "second"), ADJACENT_FAULTS, ids=lambda f: f.__name__)
def test_with_two_faults_the_earlier_item_refuses_first(
    rh: RehearsalHarness,
    *,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    first: Callable[[RehearsalHarness, pytest.MonkeyPatch], Fault],
    second: Callable[[RehearsalHarness, pytest.MonkeyPatch], Fault],
) -> None:
    match, seams = first(rh, monkeypatch)
    later_match, later_seams = second(rh, monkeypatch)
    assert later_match != match
    changes = {**later_seams, **seams}
    if first is fault_9_port or second is fault_9_port:
        with held(rh.bench.listener_port, "127.0.0.1"):
            refuse_unchanged(rh, capsys, match, **changes)  # type: ignore[arg-type]
    else:
        refuse_unchanged(rh, capsys, match, **changes)  # type: ignore[arg-type]

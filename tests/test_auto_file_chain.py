"""Auto-file with two or more company parks to register: plan and check all, then one at a time.

Every row written is a real delivery: the ``register_with`` seam wraps the real
``register_parks.register`` and fails only as a case tells it to. The fixture's parks are opened in
the reverse of their park ID order, and the park opened first played into its second company year,
so its planned registration moves the next park's year. Expected texts are copied from the spec's
R4 to R9; expected years are literals worked out from the planted days.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import pytest

from openrct2_analytics.ingest import (
    after_play,
    auto_file,
    lock,
    register_parks,
    registry_feed,
)
from tests.auto_file_support import (
    FIRST,
    NO_WAREHOUSE_LINE,
    SECOND,
    Asked,
    Filed,
    Registers,
    _before,
    _deliveries,
    _dim_park,
    _feed,
    _filed,
    _lock_path,
    _new,
    _run,
    _world,
)
from tests.auto_file_support import data as data  # noqa: F401  (pytest fixture)
from tests.test_after_play import _tree
from tests.test_auto_file_answers import RERUN, Registering, _registry
from tests.test_auto_file_several_parks import LoggedFiled
from tests.test_register_parks_start_year import plant

ANSWERS = Path("local") / "auto-file" / "answers.json"
ADR = "see ADR 0050 (play abandoned after the closing 1 March)"
STOPPED = "auto-file: after-play stopped, and these parks are already registered.\n"

N3_NO_WAREHOUSE = (
    "auto-file: the play is filed, but the note about the previous company park could not be "
    "shown (warehouse/dev/dev.duckdb does not exist).\n"
)


N3_NO_YEAR_TABLE = (
    "auto-file: the play is filed, but the note about the previous company park could not be "
    "shown (Catalog Error: Table with name obt_park_year does not exist! "
    'Did you mean "dim_park"? LINE 3: FROM marts.obt_park_year ^).\n'
)

NEW_LINES = _new(FIRST, 2000) + _new(SECOND, 2002)
FILED_FIRST = _filed((FIRST, 2000))
FILED_BOTH = _filed((FIRST, 2000), (SECOND, 2002))


@pytest.mark.parametrize("order", [(FIRST, SECOND), (SECOND, FIRST)])
def test_two_company_parks_are_registered_one_at_a_time(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], order: tuple[str, str]
) -> None:
    first, second = order
    plant(data, _world(first, second))
    _before(tmp_path, [])
    log: list[str] = []
    registers = Registers(log)
    filed = LoggedFiled(log)

    code, _, _ = _run(
        tmp_path, "company", asked=Asked(["1", "2"], log), filed=filed, register=registers
    )

    assert code == 0
    assert capsys.readouterr().out == (
        _new(first, 2000) + _new(second, 2002) + NO_WAREHOUSE_LINE + N3_NO_WAREHOUSE
    )
    # No registration before the last answer, one delivery per park, then one after-play call.
    assert log == ["ask", "ask", "register", "register", "file"]
    assert registers.calls == [({first: False}, None), ({second: False}, 2002)]
    assert _deliveries(data) == [[(first, "2000", "1", "")], [(second, "2002", "1", "")]]
    assert filed.calls == [
        ["--data-set", "company", "--parks", f"{first}:company,{second}:company"]
    ]
    assert filed.landed == [True]
    assert not (tmp_path / ANSWERS).exists()


def test_three_company_parks_get_three_years(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world = _world("park-c", "park-b")
    # park-b plays into its second company year too, so park-a starts the year after that.
    world["days"] += [("park-b", "s2", 2, (1, 0, 2)), ("park-b", "s2", 3, (2, 0, 20))]
    world["saves"].append(("park-b", "s2", 4, (2, 0, 20)))
    world["sessions"].append(("park-a", "s3", (1, 0, 1), 4))
    plant(data, world)
    _before(tmp_path, [])

    code, _, filed = _run(tmp_path, "company", asked=Asked(["1", "2", "3"]))

    assert code == 0
    assert capsys.readouterr().out == (
        _new("park-c", 2000)
        + _new("park-b", 2002)
        + _new("park-a", 2004)
        + NO_WAREHOUSE_LINE
        + N3_NO_WAREHOUSE
    )
    assert _deliveries(data) == [
        [("park-c", "2000", "1", "")],
        [("park-b", "2002", "1", "")],
        [("park-a", "2004", "1", "")],
    ]
    assert len(filed.calls) == 1


def test_an_earlier_play_company_park_and_a_new_company_park_are_filed_in_order(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # park-y is from an earlier play and was opened first; park-x is this play's only new park.
    plant(data, _world("park-y", "park-x"))
    _before(tmp_path, ["s1"])

    code, asked, filed = _run(tmp_path, "company", asked=Asked(["1"]))

    assert code == 0
    assert asked.prompts == [
        "Park park-y (first played Nov 12) from an earlier play is waiting. Where should it "
        "count?\n"
        "1. Company\n2. Sandbox\n3. Don't file now\n"
    ]
    assert capsys.readouterr().out == (
        _new("park-y", 2000) + _new("park-x", 2002) + NO_WAREHOUSE_LINE + N3_NO_WAREHOUSE
    )
    assert _deliveries(data) == [[("park-y", "2000", "1", "")], [("park-x", "2002", "1", "")]]
    assert filed.calls == [["--data-set", "company", "--parks", "park-y:company,park-x:company"]]


def test_a_refusal_for_the_second_park_stops_before_the_first_registration(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plant(data, _world(origin=9))
    _before(tmp_path, [])
    before = _tree(tmp_path)
    registers = Registers()

    code, _, filed = _run(tmp_path, "company", asked=Asked(["1", "2"]), register=registers)

    assert code == 2
    assert capsys.readouterr().out == (
        f"auto-file refused: start-year-origin: Park {SECOND} has game-year origin 9; a company "
        "start year needs a park that began in game year 1, so capture the park from a new game "
        "before registering it. Nothing was changed.\n"
    )
    assert registers.calls == []
    assert filed.calls == []
    assert _tree(tmp_path) == before


def test_an_unconverted_raw_session_refuses_before_the_first_registration(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plant(data, _world())
    _before(tmp_path, [])
    raw = data / "company" / "raw" / "v1"
    raw.mkdir(parents=True)
    (raw / "events-2026-11-15.jsonl").write_text('{"session_id": "s9"}\n', encoding="utf-8")
    before = _tree(tmp_path)
    registers = Registers()

    code, _, filed = _run(tmp_path, "company", asked=Asked(["1", "2"]), register=registers)

    assert code == 2
    assert capsys.readouterr().out == (
        "auto-file refused: not-converted: events-2026-11-15.jsonl holds a session that was "
        "never converted, so the latest managed year is unknown; run make convert "
        "DATA_SET=company first. Nothing was changed.\n"
    )
    assert registers.calls == []
    assert filed.calls == []
    assert _tree(tmp_path) == before


def test_a_changed_floor_is_refused_under_the_lock(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    plant(data, _world())
    _before(tmp_path, [])
    # A later session of the first park, played and saved into game year 3 (company year 2002).
    later = _world()
    later["sessions"].append((FIRST, "s1b", (2, 0, 20), 1))
    later["days"] += [(FIRST, "s1b", 2, (2, 0, 21)), (FIRST, "s1b", 3, (3, 0, 20))]
    later["saves"].append((FIRST, "s1b", 4, (3, 0, 20)))
    real_hold = lock.hold_lock
    calls: list[Path] = []

    @contextmanager
    def hold_after_landing(path: Path, note: str) -> Iterator[None]:
        calls.append(path)
        # The second registration's pre-lock year check has passed; the convert lands now.
        if len(calls) == 2:
            plant(data, later)
        with real_hold(path, note):
            yield

    monkeypatch.setattr(lock, "hold_lock", hold_after_landing)

    code, _, filed = _run(tmp_path, "company", asked=Asked(["1", "2"]), register=Registers())

    assert code == 1
    detail = (
        f"Company year 2002 overlaps park {FIRST}, whose latest company year is 2002; "
        f"park {SECOND} starts in 2003; if 2002 looks too high, {ADR}"
    )
    assert capsys.readouterr().out == (
        NEW_LINES + f"auto-file failed: start-year-overlap: {detail}.\n" + FILED_FIRST + RERUN
    )
    assert len(calls) == 2
    assert not _lock_path(data).exists()
    assert _deliveries(data) == [[(FIRST, "2000", "1", "")]]
    assert filed.calls == []


class AddsAPark(Asked):
    """``Asked`` that lands a third park's converted session after the last answer."""

    def __init__(self, answers: Sequence[str], data: Path) -> None:
        super().__init__(answers)
        self.data = data

    def __call__(self, prompt: str) -> str:
        reply = super().__call__(prompt)
        if not self.answers:
            world = _world()
            world["sessions"].append(("park-c", "s3", (1, 0, 1), 4))
            plant(self.data, world)
        return reply


def test_a_park_added_between_the_questions_and_the_first_registration_is_refused(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plant(data, _world())
    _before(tmp_path, [])
    registers = Registers()

    code, _, filed = _run(
        tmp_path, "company", asked=AddsAPark(["1", "2"], data), register=registers
    )

    assert code == 2
    assert capsys.readouterr().out == (
        "auto-file refused: waiting-list: the waiting parks changed while you were answering "
        "(added: park-c; removed: none). Nothing was changed.\n"
    )
    assert registers.calls == []
    assert filed.calls == []
    assert not _feed(data).exists()
    assert not (tmp_path / ANSWERS).exists()


class PrintsAndRefuses(Filed):
    """``Filed`` that prints an after-play refusal line, as after-play would, and returns 2."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        project_dir: Path,
        registrations_landed: bool = False,
        registered: list[str] | None = None,
    ) -> int:
        print("after-play refused: contracts: it broke")
        return super().__call__(
            argv,
            project_dir=project_dir,
            registrations_landed=registrations_landed,
            registered=registered,
        )


def _lock_line(data: Path) -> str:
    return f"{_lock_path(data)} is held ('test holder'); see ARCHITECTURE.md \"Stale locks\""


@pytest.mark.parametrize(
    "case",
    [
        "refusal",
        "lock-taken",
        "check-failed",
        "csv-error",
        "oserror",
        "interrupt",
        "exit-1",
        "exit-2",
    ],
)
def test_a_failure_after_the_first_registration_names_the_filed_parks(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    plant(data, _world())
    _before(tmp_path, [])
    raised: dict[str, tuple[BaseException, str, int]] = {
        "refusal": (
            register_parks.Refused("leftover", "a staged delivery"),
            "auto-file failed: leftover: a staged delivery.\n",
            1,
        ),
        "check-failed": (
            register_parks.CheckFailed("bad row"),
            "auto-file failed: check-failed: bad row.\n",
            1,
        ),
        "csv-error": (csv.Error("bad csv"), "auto-file failed: io: bad csv.\n", 1),
        "oserror": (OSError("disk full"), "auto-file failed: io: disk full.\n", 1),
        "interrupt": (KeyboardInterrupt(), "auto-file interrupted.\n", 130),
    }
    filed: Filed = Filed()
    if case in raised:
        error, first_line, expected = raised[case]
        registers = Registers(park=SECOND, raises=error)
        report, landed = first_line + FILED_FIRST, {FIRST}
    elif case == "lock-taken":
        registers = Registers(park=SECOND, locked=_lock_path(data))
        report, landed, expected = (
            f"auto-file failed: lock-taken: {_lock_line(data)}.\n" + FILED_FIRST,
            {FIRST},
            1,
        )
    else:
        registers = Registers()
        filed = Filed(1) if case == "exit-1" else PrintsAndRefuses(2)
        prefix = "" if case == "exit-1" else "after-play refused: contracts: it broke\n"
        report, landed, expected = prefix + STOPPED + FILED_BOTH, {FIRST, SECOND}, 1

    code, _, _ = _run(tmp_path, "company", asked=Asked(["1", "2"]), filed=filed, register=registers)

    out = capsys.readouterr().out
    assert code == expected
    assert out == NEW_LINES + report + RERUN
    assert "Nothing was changed" not in out
    assert set(_registry(tmp_path)) == landed


@pytest.mark.parametrize("case", ["lock-taken", "check-failed"])
def test_a_failure_at_the_first_registration_is_caught(
    data: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    plant(data, _world())
    _before(tmp_path, [])
    before = _tree(data)
    with pytest.MonkeyPatch.context() as patch:
        if case == "lock-taken":
            registers = Registers(park=FIRST, locked=_lock_path(data))
            plain = f"auto-file refused: lock-taken: {_lock_line(data)}. Nothing was changed.\n"
            expected = 2
        else:
            registers = Registers()
            # The staged delivery of the first park fails the registry contract.
            patch.setattr(registry_feed, "check_file", lambda path: ["bad row"])
            plain, expected = "auto-file failed: check-failed: bad row\n", 1
        code, _, filed = _run(tmp_path, "company", asked=Asked(["1", "2"]), register=registers)

    captured = capsys.readouterr()
    assert code == expected
    assert captured.out == NEW_LINES + plain
    assert "Traceback" not in captured.out + captured.err
    assert filed.calls == []
    assert _tree(data) == before
    # Nothing landed, so the answers stored before the first registration are removed again.
    assert not (tmp_path / ANSWERS).exists()


def test_an_after_play_refusal_after_a_landed_registration_has_no_nothing_was_changed(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plant(data, _world())
    _before(tmp_path, [])
    held = _lock_path(data)
    # A landing lock appears once the last park registered, so the real after-play refuses.
    registers = Registers(park=SECOND, after=lambda: held.write_text("pid 1\n", encoding="utf-8"))

    code = auto_file.main(
        ["--data-set", "company", "--count-as", "company"],
        project_dir=tmp_path,
        ask=Asked(["1", "2"]),
        file_with=after_play.main,
        is_terminal=lambda: True,
        register_with=registers,
    )

    out = capsys.readouterr().out
    assert code == 1
    assert out == (
        NEW_LINES
        + f'after-play refused: lock-taken: {held} exists; see ARCHITECTURE.md "Stale locks".\n'
        + STOPPED
        + FILED_BOTH
        + RERUN
    )
    assert "Nothing was changed" not in out


def test_rerun_after_a_partial_failure_files_the_rest(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plant(data, _world())
    _before(tmp_path, [])
    failing = Registers(park=SECOND, raises=register_parks.Refused("leftover", "a staged delivery"))
    first_code, _, _ = _run(tmp_path, "practice", asked=Asked(["1", "2"]), register=failing)
    assert first_code == 1
    written = sorted(_feed(data).glob("park_registry_*.csv"))
    assert len(written) == 1
    kept = written[0].read_bytes()
    capsys.readouterr()

    _dim_park(tmp_path, [(SECOND, 2, 2002), (FIRST, 1, 2000)])

    # Both parks were answered Company; the rerun is started as Sandbox, so only the stored
    # answers keep it from asking about either park.
    code, asked, filed = _run(tmp_path, "practice", filed=Registering(0))

    assert code == 0
    assert asked.prompts == []
    # The rerun registered only the second park, so only it gets a line (spec R18).
    assert capsys.readouterr().out == (
        _new(SECOND, 2002)
        + "park-a joins the company as Park 2, starting in company year 2002\n"
        + N3_NO_YEAR_TABLE
    )
    assert written[0].read_bytes() == kept
    assert _deliveries(data) == [[(FIRST, "2000", "1", "")], [(SECOND, "2002", "1", "")]]
    assert not (tmp_path / ANSWERS).exists()
    assert filed.calls == [
        [
            "--data-set",
            "company",
            "--parks",
            f"{FIRST}:company,{SECOND}:company",
            "--start-year",
            "2002",
        ]
    ]

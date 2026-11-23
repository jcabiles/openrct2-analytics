"""The line auto-file prints after filing: each new company park's number and start year.

The number and year are read from ``marts.dim_park`` of the development warehouse, so every case
plants a warehouse holding only that table. Park numbers are planted in an order that differs from
park ID order, so a line that sorted by park ID would fail. Expected lines are literals copied from
the spec's R1, R15 and R16. Each case starts from one valid play and changes one thing.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import ExitStack
from pathlib import Path

import pytest

from openrct2_analytics.ingest import after_play, play_status, register_parks
from tests.auto_file_support import (
    BEFORE,
    FIRST,
    SECOND,
    AfterPlayWithOutsideRegistration,
    Asked,
    Registers,
    _before,
    _dim_park,
    _feed,
    _register,
    _run,
    _sessions,
    _world,
)
from tests.auto_file_support import data as data  # noqa: F401  (pytest fixture)
from tests.test_after_play import _copy
from tests.test_auto_file_answers import (
    ALPHA_LINE,
    ANSWERS,
    BETA_SANDBOX_LINE,
    BOTH_FILED,
    RERUN,
    Registering,
    _plant,
)
from tests.test_auto_file_several_parks import TWO_PARKS
from tests.test_play_status import _writer_holds
from tests.test_register_parks_start_year import park_one, plant

ALPHA_JOINS = "Alpha joins the company as Park 1, starting in company year 2000\n"
PARK_2_NEW = (
    "auto-file: park park-2 (first played Nov 12)"
    " is new; registering it as company park, start year 2001.\n"
)
PARK_2_JOINS = "park-2 joins the company as Park 2, starting in company year 2001\n"
FIRST_NEW = (
    "auto-file: park park-b (first played Nov 12)"
    " is new; registering it as company park, start year 2000.\n"
)
SECOND_NEW = (
    "auto-file: park park-a (first played Nov 12)"
    " is new; registering it as company park, start year 2002.\n"
)
FIRST_JOINS = "park-b joins the company as Park 1, starting in company year 2000\n"
SECOND_JOINS = "park-a joins the company as Park 2, starting in company year 2002\n"
N3_NO_YEAR_TABLE = (
    "auto-file: the play is filed, but the note about the previous company park could not be "
    "shown (Catalog Error: Table with name obt_park_year does not exist! "
    'Did you mean "dim_park"? LINE 3: FROM marts.obt_park_year ^).\n'
)
UNREAD_PREFIX = "auto-file: the play is filed, but the park number could not be shown ("


class Watching(Registering):
    """``Registering`` that notes whether the record and answers files exist when it is called."""

    def __init__(self, stack: ExitStack | None = None, path: Path | None = None) -> None:
        super().__init__(0)
        self.stack = stack
        self.path = path
        self.present: list[bool] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        project_dir: Path,
        registrations_landed: bool = False,
        registered: list[str] | None = None,
    ) -> int:
        self.present = [(project_dir / BEFORE).exists(), (project_dir / ANSWERS).exists()]
        code = super().__call__(
            argv,
            project_dir=project_dir,
            registrations_landed=registrations_landed,
            registered=registered,
        )
        if self.stack is not None and self.path is not None:
            # A writer takes the warehouse's lock once after-play has returned 0.
            self.stack.enter_context(_writer_holds(self.path))
        return code


def _two_parks_filed(
    data: Path, tmp_path: Path, filed: Watching | None = None
) -> tuple[int, Watching]:
    """File Alpha as Company and Beta as Sandbox for real, with after-play returning 0."""
    _plant(data, TWO_PARKS)
    _before(tmp_path, [])
    filed = filed or Watching()
    code, _, _ = _run(tmp_path, "company", asked=Asked(["1", "3"]), filed=filed)
    return code, filed


def _files_cleared(tmp_path: Path) -> None:
    assert not (tmp_path / BEFORE).exists()
    assert not (tmp_path / ANSWERS).exists()


def _no_line(out: str) -> None:
    assert "joins the company" not in out


# R1, R4, R7, R8: the line.


def test_the_first_company_park_is_park_1_in_company_year_2000(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _plant(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])
    _dim_park(tmp_path, [("park-a", 1, 2000)])

    code, _, _ = _run(tmp_path, "company", filed=Registering(0))

    assert code == 0
    assert capsys.readouterr().out == ALPHA_LINE + ALPHA_JOINS


def test_a_later_company_park_filed_alone_is_park_2(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plant(data, park_one())
    _before(tmp_path, ["s1"])
    _dim_park(tmp_path, [("park-1", 1, 2000), ("park-2", 2, 2001)])

    code, _, _ = _run(tmp_path, "company", filed=Registering(0))

    assert code == 0
    assert capsys.readouterr().out == PARK_2_NEW + PARK_2_JOINS + N3_NO_YEAR_TABLE


def test_two_company_parks_filed_together_print_in_order_of_park_number(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plant(data, _world())
    _before(tmp_path, [])
    # park-a sorts first by ID and is planted first, but park-b is Park 1.
    _dim_park(tmp_path, [(SECOND, 2, 2002), (FIRST, 1, 2000)])

    code, _, _ = _run(tmp_path, "company", asked=Asked(["1", "2"]))

    assert code == 0
    assert capsys.readouterr().out == (
        FIRST_NEW + SECOND_NEW + FIRST_JOINS + SECOND_JOINS + N3_NO_YEAR_TABLE
    )


def test_the_year_is_the_one_in_dim_park_not_the_planned_one(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _plant(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])
    _dim_park(tmp_path, [("park-a", 1, 2005)])

    code, _, _ = _run(tmp_path, "company", filed=Registering(0))

    assert code == 0
    assert capsys.readouterr().out == (
        ALPHA_LINE + "Alpha joins the company as Park 1, starting in company year 2005\n"
    )


def test_a_park_with_no_session_name_is_named_by_its_park_id(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _plant(data, [("s1", "park-a", "Alpha")])
    nameless = "SELECT 's1' AS session_id, 'park-a' AS park_id, CAST(NULL AS VARCHAR) AS park_name"
    _copy(
        data / "company" / "parquet" / "v1" / "session_start.parquet",
        nameless + ", 1 AS game_year, TIMESTAMPTZ '2026-10-01 10:00:00+00' AS emitted_at",
    )
    _before(tmp_path, [])
    _dim_park(tmp_path, [("park-a", 1, 2000)])

    code, _, _ = _run(tmp_path, "company", filed=Registering(0))

    assert code == 0
    assert capsys.readouterr().out.endswith(
        "park-a joins the company as Park 1, starting in company year 2000\n"
    )


# R2, R6: which parks get a line.


def test_a_sandbox_park_filed_with_a_company_park_gets_no_line(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _plant(data, TWO_PARKS)
    _before(tmp_path, [])
    _dim_park(tmp_path, [("park-a", 1, 2000), ("park-b", None, 2000)])

    code, _, _ = _run(tmp_path, "company", asked=Asked(["1", "3"]), filed=Registering(0))

    assert code == 0
    assert capsys.readouterr().out == ALPHA_LINE + BETA_SANDBOX_LINE + ALPHA_JOINS


def test_an_earlier_registered_park_with_waiting_play_gets_no_line(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _sessions(data, [("s1", "park-a", "Alpha")])
    _register(data, "park-a", practice=False)
    _before(tmp_path, [])
    _dim_park(tmp_path, [("park-a", 1, 2000)])

    code, _, filed = _run(tmp_path, "company")

    assert code == 0
    assert len(filed.calls) == 1
    assert capsys.readouterr().out == ""


def test_an_earlier_park_and_a_new_park_print_one_line_and_the_rerun_prints_none(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plant(data, park_one())
    _before(tmp_path, ["s1"])
    _dim_park(tmp_path, [("park-1", 1, 2000), ("park-2", 2, 2001)])

    code, _, _ = _run(tmp_path, "company", filed=Registering(0))

    assert code == 0
    out = capsys.readouterr().out
    assert out.count("joins the company") == 1
    assert "park-1 joins" not in out
    _before(tmp_path, ["s1"])
    code, _, _ = _run(tmp_path, "company")
    assert code == 0
    assert capsys.readouterr().out == ""


def test_a_run_that_registers_only_a_sandbox_park_reads_no_warehouse(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _sessions(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])
    assert not (tmp_path / play_status.WAREHOUSE).exists()

    code, _, _ = _run(tmp_path, "practice")

    assert code == 0
    assert capsys.readouterr().out == (
        "auto-file: park Alpha (first played Oct 1) is new; registering it as a sandbox park.\n"
    )


# R5: nothing prints unless the run exits 0 after filing.


def test_no_line_when_after_play_fails(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _plant(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])
    _dim_park(tmp_path, [("park-a", 1, 2000)])

    code, _, _ = _run(tmp_path, "company", filed=Registering(1))

    assert code == 1
    _no_line(capsys.readouterr().out)
    assert (tmp_path / BEFORE).exists()


def test_no_line_when_a_registration_in_the_chain_raises(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plant(data, _world())
    _before(tmp_path, [])
    _dim_park(tmp_path, [(FIRST, 1, 2000), (SECOND, 2, 2002)])
    failing = Registers(park=SECOND, raises=register_parks.Refused("leftover", "a staged delivery"))

    code, _, filed = _run(tmp_path, "company", asked=Asked(["1", "2"]), register=failing)

    assert code == 1
    assert filed.calls == []
    _no_line(capsys.readouterr().out)


def test_no_line_when_the_run_is_refused_before_any_question(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _plant(data, TWO_PARKS)
    _before(tmp_path, [])
    _dim_park(tmp_path, [("park-a", 1, 2000), ("park-b", 2, 2001)])

    code, asked, filed = _run(tmp_path, "company", terminal=False)

    assert code == 2
    assert asked.prompts == [] and filed.calls == []
    _no_line(capsys.readouterr().out)


def test_no_line_when_dont_file_now_is_chosen(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _sessions(data, [("s1", "park-a", "Alpha"), ("s2", "park-b", "Beta")])
    _before(tmp_path, ["s1"])
    _dim_park(tmp_path, [("park-a", 1, 2000), ("park-b", 2, 2001)])

    code, _, filed = _run(tmp_path, "company", asked=Asked(["3"]))

    assert code == 2
    assert filed.calls == []
    _no_line(capsys.readouterr().out)


# R16: the read works, but a new company park has no number.


def test_a_company_park_missing_from_dim_park_gets_the_could_not_show_line(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _plant(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])
    _dim_park(tmp_path, [("park-z", 1, 2000)])

    code, _, _ = _run(tmp_path, "company", filed=Registering(0))

    assert code == 0
    assert capsys.readouterr().out == (
        ALPHA_LINE + "auto-file: the play is filed, but the park number could not be shown for "
        "Alpha.\n"
    )
    _files_cleared(tmp_path)


def test_a_company_park_with_a_null_number_gets_the_could_not_show_line(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _plant(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])
    _dim_park(tmp_path, [("park-a", None, 2000)])

    code, _, _ = _run(tmp_path, "company", filed=Registering(0))

    assert code == 0
    assert capsys.readouterr().out == (
        ALPHA_LINE + "auto-file: the play is filed, but the park number could not be shown for "
        "Alpha.\n"
    )


def test_the_numbered_parks_print_before_the_one_line_for_the_park_without(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plant(data, _world())
    _before(tmp_path, [])
    _dim_park(tmp_path, [(FIRST, 1, 2000)])

    code, _, _ = _run(tmp_path, "company", asked=Asked(["1", "2"]))

    assert code == 0
    assert capsys.readouterr().out == (
        FIRST_NEW
        + SECOND_NEW
        + FIRST_JOINS
        + "auto-file: the play is filed, but the park number could not be shown for park-a.\n"
        + N3_NO_YEAR_TABLE
    )


def test_two_parks_without_a_number_are_named_in_one_line(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plant(data, _world())
    _before(tmp_path, [])
    _dim_park(tmp_path, [("park-z", 1, 2000)])

    code, _, _ = _run(tmp_path, "company", asked=Asked(["1", "2"]))

    assert code == 0
    assert capsys.readouterr().out == (
        FIRST_NEW
        + SECOND_NEW
        + "auto-file: the play is filed, but the park number could not be shown for "
        "park-b, park-a.\n" + N3_NO_YEAR_TABLE
    )


# R17: an interrupt while the lines print, or during the read.


def test_an_interrupt_during_the_read_keeps_the_files_and_reports_the_filed_parks(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant(data, TWO_PARKS)
    _before(tmp_path, [])

    def interrupted(project_dir: Path, park_ids: Sequence[str]) -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr(play_status, "dim_park_numbers", interrupted)

    code, _, _ = _run(tmp_path, "company", asked=Asked(["1", "3"]), filed=Registering(0))

    out = capsys.readouterr().out
    assert code == 130
    assert out.startswith(ALPHA_LINE + BETA_SANDBOX_LINE + "auto-file interrupted.\n")
    assert out.endswith(BOTH_FILED + RERUN)
    assert "joins the company" not in out
    assert (tmp_path / BEFORE).exists()
    assert (tmp_path / ANSWERS).exists()


# R18: a failed run, then a rerun.


def test_a_rerun_that_registers_nothing_prints_no_line_for_the_failed_runs_park(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _plant(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])
    _dim_park(tmp_path, [("park-a", 1, 2000)])
    code, _, _ = _run(tmp_path, "company", filed=Registering(then=OSError("boom")))
    assert code == 1
    assert _feed(data).exists()
    capsys.readouterr()

    code, _, filed = _run(tmp_path, "company")

    assert code == 0
    assert len(filed.calls) == 1
    assert capsys.readouterr().out == ""


# R6: the joins line names only the parks this run registered.


def _real_after_play(
    data: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, outside: bool
) -> None:
    """File park-a through the real after-play."""
    _plant(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])
    _dim_park(tmp_path, [("park-a", 1, 2000)])
    # The make-backed steps need a real build; only the register step is under test.
    monkeypatch.setattr(after_play, "_make", lambda target, data_set: lambda: 0)

    code, _, _ = _run(tmp_path, "company", filed=AfterPlayWithOutsideRegistration(outside=outside))

    assert code == 0


def test_a_park_this_run_registered_gets_its_joins_line(
    data: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _real_after_play(data, tmp_path, monkeypatch, outside=False)

    assert ALPHA_JOINS in capsys.readouterr().out


def test_a_park_another_run_registered_meanwhile_gets_no_joins_line(
    data: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _real_after_play(data, tmp_path, monkeypatch, outside=True)

    out = capsys.readouterr().out
    assert "joins the company" not in out
    assert "after-play: register: no waiting park needs registering" in out

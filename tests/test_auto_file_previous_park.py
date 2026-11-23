"""The note auto-file prints after a successful filing about the previous company park.

Every case files for real through ``auto_file.main`` with a planted warehouse
(``marts.obt_park_year`` and ``marts.dim_park``). Expected lines are literals copied from the
spec's section 4 (N1, N2, N3).
Each negative case starts from the profitable-year case and changes one thing.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace

import pytest

from openrct2_analytics.config import ConfigError
from openrct2_analytics.ingest import play_status, previous_park
from tests.auto_file_support import (
    BEFORE,
    NO_WAREHOUSE_LINE,
    Asked,
    Registers,
    _before,
    _dim_park,
    _register,
    _run,
    plant_park_years,
)
from tests.auto_file_support import data as data  # noqa: F401  (pytest fixture)
from tests.test_auto_file_answers import ANSWERS, Registering, _plant
from tests.test_auto_file_park_number import PARK_2_JOINS, PARK_2_NEW, Watching
from tests.test_auto_file_several_parks import TWO_PARKS
from tests.test_register_parks_start_year import park_one, plant

ALPHA_NEW = (
    "auto-file: park Alpha (first played Oct 1) is new; registering it as company park, "
    "start year 2000.\n"
)
ALPHA_JOINS = "Alpha joins the company as Park 1, starting in company year 2000\n"
PARK_3_NEW = (
    "auto-file: park park-3 (first played Nov 12) is new; registering it as company park, "
    "start year 2003.\n"
)
PARK_3_JOINS = "park-3 joins the company as Park 3, starting in company year 2003\n"
N1_TAIL = (
    "The scenario challenge of Park One is not recorded, so whether it was finished is not checked."
)
N1_PROFIT = (
    "auto-file: note: park-2 opens after Park One. "
    + N1_TAIL
    + " Its profit in company year 2000, "
    "its latest complete year, was $1,234.50 in US dollars "
    "(all 14 statement lines of its 8 monthly statements).\n"
)
N1_LOSS = (
    "auto-file: note: park-2 opens after Park One. "
    + N1_TAIL
    + " Its profit in company year 2000, "
    "its latest complete year, was -$123.40 in US dollars "
    "(all 14 statement lines of its 8 monthly statements).\n"
)
N2_PARK_ONE = (
    "auto-file: note: park-2 opens after Park One. " + N1_TAIL + " Park One has no complete "
    "company year (all 8 monthly statements).\n"
)
N2_PARK_2 = (
    "auto-file: note: park-3 opens after Park Two. The scenario challenge of Park Two is not "
    "recorded, so whether it was finished is not checked. Park Two has no complete company year "
    "(all 8 monthly statements).\n"
)
N3_NO_WAREHOUSE = (
    "auto-file: the play is filed, but the note about the previous company park could not be "
    "shown (warehouse/dev/dev.duckdb does not exist).\n"
)
N3_NO_YEAR_TABLE = (
    "auto-file: the play is filed, but the note about the previous company park could not be "
    "shown (Catalog Error: Table with name obt_park_year does not exist! "
    'Did you mean "dim_park"? LINE 3: FROM marts.obt_park_year ^).\n'
)
N3_START = (
    "auto-file: the play is filed, but the note about the previous company park could not be "
)
Year = tuple[str, object, str, object, object, object]
YEAR_2000: list[Year] = [("park-1", 2000, "complete", 2000, -700, -65.5)]


def _later_park(data: Path, tmp_path: Path, years: list[Year]) -> None:
    """Park 1 is registered (2000); park 2 waits to register as the later company park (2001)."""
    plant(data, park_one())
    _before(tmp_path, ["s1"])
    _dim_park(tmp_path, [("park-1", 1, 2000), ("park-2", 2, 2001)])
    plant_park_years(tmp_path, years, {"park-1": "Park One"})


def _chain_world(data: Path, tmp_path: Path) -> None:
    """Park 1 is registered; parks 2 and 3 are new company parks of one play (2001 and 2003)."""
    world = park_one()
    world["sessions"].append(("park-3", "s3", (1, 0, 1), 4))
    world["days"] += [
        ("park-2", "s2", 2, (1, 0, 2)),
        ("park-2", "s2", 3, (1, 7, 31)),
        ("park-2", "s2", 4, (2, 0, 20)),
    ]
    world["saves"].append(("park-2", "s2", 5, (2, 0, 20)))
    plant(data, world)
    _before(tmp_path, ["s1"])
    _dim_park(tmp_path, [("park-1", 1, 2000), ("park-2", 2, 2001), ("park-3", 3, 2003)])
    plant_park_years(tmp_path, YEAR_2000, {"park-1": "Park One", "park-2": "Park Two"})


def _scan(out: str) -> None:
    assert "auto-file: note:" not in out
    assert "previous company park" not in out


# R16: the roadmap's five cases.


def test_a_profitable_previous_year_is_stated(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _later_park(data, tmp_path, YEAR_2000)

    code, _, _ = _run(tmp_path, "company", filed=Registering(0))

    assert code == 0
    assert capsys.readouterr().out == PARK_2_NEW + PARK_2_JOINS + N1_PROFIT


def test_an_unprofitable_previous_year_is_stated_with_a_minus_sign(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _later_park(data, tmp_path, [("park-1", 2000, "complete", 100, -200, -23.4)])

    code, _, _ = _run(tmp_path, "company", filed=Registering(0))

    assert code == 0
    assert capsys.readouterr().out == PARK_2_NEW + PARK_2_JOINS + N1_LOSS


def test_a_previous_park_with_no_complete_year_is_said_to_have_none(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _later_park(data, tmp_path, [("park-1", 2000, "open", 2000, -700, -65.5)])

    code, _, _ = _run(tmp_path, "company", filed=Registering(0))

    assert code == 0
    assert capsys.readouterr().out == PARK_2_NEW + PARK_2_JOINS + N2_PARK_ONE


def test_two_company_parks_through_the_chain_name_the_first_new_park_second(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _chain_world(data, tmp_path)

    code, _, _ = _run(tmp_path, "company", asked=Asked(["1", "2"]), register=Registers())

    assert code == 0
    assert capsys.readouterr().out == (
        PARK_2_NEW + PARK_3_NEW + PARK_2_JOINS + PARK_3_JOINS + N1_PROFIT + N2_PARK_2
    )


def test_the_first_company_park_gets_no_note(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _plant(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])
    _dim_park(tmp_path, [("park-a", 1, 2000)])

    code, _, _ = _run(tmp_path, "company", filed=Registering(0))

    assert code == 0
    assert capsys.readouterr().out == ALPHA_NEW + ALPHA_JOINS


# R1: no note unless after-play returned 0.


def test_no_note_when_after_play_fails(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _later_park(data, tmp_path, YEAR_2000)

    code, _, _ = _run(tmp_path, "company", filed=Registering(1))

    assert code == 1
    _scan(capsys.readouterr().out)


def _question_needed(data: Path, tmp_path: Path) -> None:
    """Park 0 is registered; park-a (an earlier play) and park-b (this play) need answers."""
    _plant(data, TWO_PARKS)
    _register(data, "park-0", practice=False)
    _before(tmp_path, ["s1"])
    _dim_park(tmp_path, [("park-0", 1, 2000), ("park-a", 2, 2001), ("park-b", 3, 2002)])
    plant_park_years(
        tmp_path, [("park-0", 2000, "complete", 2000, -700, -65.5)], {"park-0": "Park Zero"}
    )


def test_no_note_when_the_run_is_refused_before_any_question(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _question_needed(data, tmp_path)

    code, asked, filed = _run(tmp_path, "company", terminal=False)

    assert code == 2
    assert asked.prompts == [] and filed.calls == []
    _scan(capsys.readouterr().out)


def test_no_note_when_dont_file_now_is_chosen(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _question_needed(data, tmp_path)

    code, asked, filed = _run(tmp_path, "company", asked=Asked(["3"]))

    assert code == 2
    assert len(asked.prompts) == 1 and filed.calls == []
    _scan(capsys.readouterr().out)


# R2: more play for a registered park is not a new park.


def test_more_play_for_a_registered_later_park_gets_no_note(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world = park_one()
    world["registry"].append(("park-2", 2001, 1, "company", "", "2026-11-12"))
    plant(data, world)
    _before(tmp_path, ["s1"])
    _dim_park(tmp_path, [("park-1", 1, 2000), ("park-2", 2, 2001)])
    plant_park_years(tmp_path, YEAR_2000, {"park-1": "Park One"})

    code, _, filed = _run(tmp_path, "company", filed=Registering(0))

    assert code == 0
    assert len(filed.calls) == 1
    assert capsys.readouterr().out == ""


# R6: the one-park path with a seam that writes no registry row.


def test_the_one_park_path_names_the_previous_park_without_a_registry_row(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _later_park(data, tmp_path, YEAR_2000)

    code, _, filed = _run(tmp_path, "company")

    assert code == 0
    assert filed.calls == [
        [
            "--data-set",
            "company",
            "--parks",
            "park-1:company,park-2:company",
            "--start-year",
            "2001",
        ]
    ]
    assert capsys.readouterr().out == PARK_2_NEW + PARK_2_JOINS + N1_PROFIT


# R3: the first company park reads nothing.


def test_the_first_company_park_reads_no_warehouse(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _plant(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])
    path = _dim_park(tmp_path, [("park-a", 1, 2000)])

    with ExitStack() as stack:
        code, _, _ = _run(tmp_path, "company", filed=Watching(stack, path))

    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith(ALPHA_NEW)
    _scan(out)


def test_the_first_company_park_after_only_sandbox_parks_reads_no_warehouse(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _plant(data, [("s1", "park-a", "Alpha")])
    _register(data, "park-x", practice=True)
    _before(tmp_path, [])
    path = _dim_park(tmp_path, [("park-a", 1, 2000)])

    with ExitStack() as stack:
        code, _, _ = _run(tmp_path, "company", filed=Watching(stack, path))

    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith(ALPHA_NEW)
    _scan(out)


# R4: a Sandbox park gets no note.


def test_a_sandbox_and_a_company_park_filed_together_print_one_note(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world = park_one()
    world["sessions"].append(("park-3", "s3", (1, 0, 1), 4))
    plant(data, world)
    _before(tmp_path, ["s1"])
    _dim_park(tmp_path, [("park-1", 1, 2000), ("park-2", 2, 2001)])
    plant_park_years(tmp_path, YEAR_2000, {"park-1": "Park One"})

    code, _, _ = _run(tmp_path, "company", asked=Asked(["1", "3"]), filed=Registering(0))

    out = capsys.readouterr().out
    assert code == 0
    assert out.count("auto-file: note:") == 1
    assert out.endswith(PARK_2_JOINS + N1_PROFIT)


# R15: the notes are the last lines, in start-year order.


def test_the_notes_come_after_the_joins_lines_in_start_year_order(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _chain_world(data, tmp_path)

    code, _, _ = _run(tmp_path, "company", asked=Asked(["1", "2"]), register=Registers())

    assert code == 0
    last = capsys.readouterr().out.splitlines(keepends=True)[-4:]
    assert last == [PARK_2_JOINS, PARK_3_JOINS, N1_PROFIT, N2_PARK_2]


# R12: a read failure prints one neutral line and the filing still exits 0.


def test_no_warehouse_gives_one_neutral_line(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plant(data, park_one())
    _before(tmp_path, ["s1"])

    code, _, _ = _run(tmp_path, "company", filed=Registering(0))

    assert code == 0
    assert capsys.readouterr().out == PARK_2_NEW + NO_WAREHOUSE_LINE + N3_NO_WAREHOUSE
    assert not (tmp_path / BEFORE).exists()


def test_a_warehouse_without_the_year_table_gives_one_neutral_line(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _later_park(data, tmp_path, [])

    code, _, _ = _run(tmp_path, "company", filed=Registering(0))

    assert code == 0
    assert capsys.readouterr().out == PARK_2_NEW + PARK_2_JOINS + N3_NO_YEAR_TABLE
    assert not (tmp_path / BEFORE).exists()


def test_a_held_lock_gives_one_neutral_line_and_clears_the_files(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _plant(data, TWO_PARKS)
    _register(data, "park-0", practice=False)
    _before(tmp_path, [])
    path = _dim_park(tmp_path, [("park-0", 1, 2000), ("park-a", 2, 2001), ("park-b", 3, 2002)])
    plant_park_years(tmp_path, YEAR_2000, {})

    with ExitStack() as stack:
        code, _, _ = _run(tmp_path, "company", asked=Asked(["1", "3"]), filed=Watching(stack, path))

    out = capsys.readouterr().out
    assert code == 0
    assert out.count(N3_START) == 1
    assert "auto-file: note:" not in out
    assert not (tmp_path / BEFORE).exists()
    assert not (tmp_path / ANSWERS).exists()


# R13: an interrupt while the note is read ends the run at 130 with no failure report.


def test_an_interrupt_while_the_warehouse_is_read_ends_at_130(
    data: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _later_park(data, tmp_path, YEAR_2000)

    def interrupted(project_dir: Path, park_ids: object) -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr(previous_park, "read_previous", interrupted)

    code, _, _ = _run(tmp_path, "company", filed=Registering(0))

    captured = capsys.readouterr()
    assert code == 130
    assert "Traceback" not in captured.out + captured.err
    assert "Nothing was changed." not in captured.out
    assert "already registered by this run" not in captured.out
    assert "To file the rest" not in captured.out
    assert not (tmp_path / BEFORE).exists()


# R12: a ConfigError from the registry folder lookup is one neutral line.


def test_a_config_error_during_the_note_gives_one_neutral_line(
    data: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _later_park(data, tmp_path, YEAR_2000)

    def aliased(data_set: str, project_dir: Path) -> Path:
        raise ConfigError("Two landing folders are one folder")

    monkeypatch.setattr(
        previous_park,
        "play_status",
        SimpleNamespace(WAREHOUSE=play_status.WAREHOUSE, registry_feed_dir=aliased),
    )

    code, _, _ = _run(tmp_path, "company", filed=Registering(0))

    assert code == 0
    assert capsys.readouterr().out == (
        PARK_2_NEW + PARK_2_JOINS + N3_START + "shown (Two landing folders are one folder).\n"
    )

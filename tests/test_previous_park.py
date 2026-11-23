"""The note about the previous company park: its choice, its read and its wording."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from openrct2_analytics.config import ConfigError
from openrct2_analytics.ingest import (
    lock,
    play_status,
    previous_park,
    publish_audit,
    query_interrupt,
    registry_feed,
)
from tests.auto_file_support import _dim_park, plant_park_years
from tests.test_play_status import _writer_holds

N1 = (
    "auto-file: note: {new} opens after {prev}. The scenario challenge of {prev} is not recorded, "
    "so whether it was finished is not checked. Its profit in company year {year}, its latest "
    "complete year, was {amount} in US dollars (all 14 statement lines of its 8 monthly "
    "statements)."
)
N2 = (
    "auto-file: note: {new} opens after {prev}. The scenario challenge of {prev} is not recorded, "
    "so whether it was finished is not checked. {prev} has no complete company year (all 8 "
    "monthly statements)."
)
N3 = (
    "auto-file: the play is filed, but the note about the previous company park could not be "
    "shown ({error})."
)
YearRow = tuple[str, object, str, object, object, object]
N3_OPEN = N3.split("{error}")[0]
ALPHA_2000 = ("park-a", 2000, "complete", Decimal("160.00"), Decimal("-7.00"), Decimal("-0.50"))
ALPHA_N1 = N1.format(new="Beta", prev="Alpha", year=2000, amount="$152.50")
NEW = ({"park-b": "Beta"}, {"park-b": 2001})
UNEXPECTED = "park park-a has a year or profit of an unexpected type"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def _registry(project: Path, rows: list[tuple[str, int, bool]] | None = None) -> Path:
    """Plant one delivery: park-a (2000, company) by default; a row is (park, year, sandbox)."""
    rows = [("park-a", 2000, False)] if rows is None else rows
    feed = project / "data" / "company" / "registry" / "v1"
    feed.mkdir(parents=True)
    lines = [",".join(registry_feed.HEADER)]
    for park, year, sandbox in rows:
        note = registry_feed.PRACTICE_NOTE if sandbox else ""
        lines.append(f"{park},{year},3,company,{note},2026-10-18")
    (feed / "park_registry_2026-10-18_01.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return feed / "park_registry_2026-10-18_01.csv"


def _note(project: Path) -> list[str]:
    return previous_park.note_lines(project, *NEW)


def _planted(project: Path, *years: YearRow) -> None:
    """Plant the registry (park-a at 2000) and a warehouse with the given park-a year rows."""
    _registry(project)
    plant_park_years(project, [*years], {"park-a": "Alpha"})


# R5: the choice


def test_the_previous_park_follows_start_year_not_park_id() -> None:
    registered = {"park-c": 2000, "park-a": 2001}
    assert previous_park.previous_parks(registered, {"park-b": 2002}) == {"park-b": "park-a"}


def test_the_lowest_year_gets_no_previous_park() -> None:
    assert previous_park.previous_parks({"park-a": 2001}, {"park-z": 2000}) == {"park-z": None}


def test_a_tie_gives_the_lower_park_id() -> None:
    registered = {"park-b": 2001, "park-a": 2001}
    assert previous_park.previous_parks(registered, {"park-c": 2002}) == {"park-c": "park-a"}


def test_a_new_park_with_no_year_gets_none() -> None:
    assert previous_park.previous_parks({"park-a": 2000}, {"park-b": None}) == {"park-b": None}


def test_two_new_parks_of_one_run_chain_with_an_empty_registry() -> None:
    years = {"park-a": 2000, "park-b": 2001}
    assert previous_park.previous_parks({}, years) == {"park-a": None, "park-b": "park-a"}


def test_the_run_year_beats_the_registry_row_of_a_new_park() -> None:
    result = previous_park.previous_parks({"park-b": 2005, "park-a": 2000}, {"park-b": 2001})
    assert result == {"park-b": "park-a"}


def test_a_registry_year_does_not_come_before_the_run_year_for_a_later_new_park() -> None:
    registered = {"park-b": 2005, "park-a": 2000}
    result = previous_park.previous_parks(registered, {"park-b": 2001, "park-c": 2002})
    assert result == {"park-b": "park-a", "park-c": "park-b"}


def test_a_park_with_an_equal_start_year_is_not_the_previous_park() -> None:
    registered = {"park-a": 2000, "park-e": 2001}
    assert previous_park.previous_parks(registered, {"park-b": 2001}) == {"park-b": "park-a"}


def test_a_sandbox_park_is_never_the_previous_park(project: Path) -> None:
    _registry(project, [("park-a", 2000, False), ("park-s", 2001, True)])
    plant_park_years(project, [ALPHA_2000], {"park-a": "Alpha"})
    assert previous_park.note_lines(project, {"park-b": "Beta"}, {"park-b": 2002}) == [ALPHA_N1]


# R6: the new park's registry row is not needed


def test_a_new_park_absent_from_the_registry_gets_the_note(project: Path) -> None:
    _planted(project, ALPHA_2000)
    assert _note(project) == [ALPHA_N1]


def test_no_year_reads_nothing(project: Path) -> None:
    feed = _registry(project)
    feed.write_text("not,a,registry\n1\n", encoding="utf-8")
    path = plant_park_years(project, [ALPHA_2000], {"park-a": "Alpha"})
    with _writer_holds(path):
        assert previous_park.note_lines(project, {"park-b": "Beta"}, {"park-b": None}) == []


# R8: the year used


def _two_years(second_status: str, second_year: int = 2001) -> list[YearRow]:
    return [
        ALPHA_2000,
        ("park-a", second_year, second_status, Decimal("10.00"), Decimal("0.00"), Decimal("0.00")),
    ]


@pytest.mark.parametrize(
    ("status", "year", "amount"),
    [
        ("open", 2000, "$152.50"),
        ("complete", 2001, "$10.00"),
        ("incomplete", 2000, "$152.50"),
    ],
)
def test_the_latest_complete_year_is_used(
    project: Path, status: str, year: int, amount: str
) -> None:
    _planted(project, *_two_years(status))
    assert _note(project) == [N1.format(new="Beta", prev="Alpha", year=year, amount=amount)]


def test_a_partial_first_season_is_not_complete(project: Path) -> None:
    _planted(
        project,
        ("park-a", 2000, "partial_first_season", Decimal("1.00"), Decimal("0.00"), Decimal("0.00")),
    )
    assert _note(project) == [N2.format(new="Beta", prev="Alpha")]


# R9 and R11: the profit


@pytest.mark.parametrize(
    ("parts", "amount"),
    [
        (("160.00", "-7.00", "-0.50"), "$152.50"),
        (("1234.50", "0.00", "0.00"), "$1,234.50"),
        (("-100.00", "-20.00", "-3.40"), "-$123.40"),
    ],
)
def test_the_profit_is_the_sum_of_three_columns(
    project: Path, parts: tuple[str, str, str], amount: str
) -> None:
    operating, capital, interest = (Decimal(part) for part in parts)
    _planted(project, ("park-a", 2000, "complete", operating, capital, interest))
    assert _note(project) == [ALPHA_N1.replace("$152.50", amount)]


def test_a_null_interest_gives_the_neutral_line(project: Path) -> None:
    _planted(project, ("park-a", 2000, "complete", Decimal("1.00"), Decimal("1.00"), None))
    assert _note(project) == [N3.format(error=UNEXPECTED)]


def test_money_planted_as_double_gives_the_neutral_line(project: Path) -> None:
    _registry(project)
    plant_park_years(
        project,
        [("park-a", 2000, "complete", 160.0, -7.0, -0.5)],
        {"park-a": "Alpha"},
        money_type="DOUBLE",
    )
    assert _note(project) == [N3.format(error=UNEXPECTED)]


def test_a_year_planted_as_varchar_gives_the_neutral_line(project: Path) -> None:
    _registry(project)
    row = ("park-a", "2000", "complete", Decimal("1.00"), Decimal("0.00"), Decimal("0.00"))
    plant_park_years(project, [row], {"park-a": "Alpha"}, year_type="VARCHAR")
    assert _note(project) == [N3.format(error=UNEXPECTED)]


def test_a_profit_of_a_fraction_of_a_tenth_gives_the_neutral_line(project: Path) -> None:
    _planted(
        project, ("park-a", 2000, "complete", Decimal("0.05"), Decimal("0.00"), Decimal("0.00"))
    )
    error = "park park-a has a profit of 0.05, not a whole number of tenths"
    assert _note(project) == [N3.format(error=error)]


# R10: the text


def test_the_note_with_a_profit_reads_byte_for_byte(project: Path) -> None:
    _planted(project, ALPHA_2000)
    assert _note(project) == [
        "auto-file: note: Beta opens after Alpha. The scenario challenge of Alpha is not recorded, "
        "so whether it was finished is not checked. Its profit in company year 2000, its latest "
        "complete year, was $152.50 in US dollars (all 14 statement lines of its 8 monthly "
        "statements)."
    ]


def test_the_note_with_no_complete_year_reads_byte_for_byte(project: Path) -> None:
    _planted(project, ("park-a", 2000, "open", Decimal("1.00"), Decimal("0.00"), Decimal("0.00")))
    assert _note(project) == [
        "auto-file: note: Beta opens after Alpha. The scenario challenge of Alpha is not recorded, "
        "so whether it was finished is not checked. Alpha has no complete company year (all 8 "
        "monthly statements)."
    ]


def test_a_previous_park_with_no_name_shows_its_park_id(project: Path) -> None:
    _registry(project)
    plant_park_years(project, [ALPHA_2000], {})
    assert _note(project) == [ALPHA_N1.replace("Alpha", "park-a")]


def test_a_new_park_with_no_name_shows_its_park_id(project: Path) -> None:
    _planted(project, ALPHA_2000)
    assert previous_park.note_lines(project, {}, {"park-b": 2001}) == [
        ALPHA_N1.replace("Beta", "park-b")
    ]


def test_a_line_break_in_the_previous_park_name_keeps_the_profit_note_on_one_line(
    project: Path,
) -> None:
    _registry(project)
    plant_park_years(project, [ALPHA_2000], {"park-a": "Alpha\nGardens"})
    assert _note(project) == [
        N1.format(new="Beta", prev="Alpha Gardens", year=2000, amount="$152.50")
    ]


def test_a_line_break_in_the_previous_park_name_keeps_the_no_year_note_on_one_line(
    project: Path,
) -> None:
    _registry(project)
    open_year = ("park-a", 2000, "open", Decimal("1.00"), Decimal("0.00"), Decimal("0.00"))
    plant_park_years(project, [open_year], {"park-a": "Alpha\nGardens"})
    assert _note(project) == [N2.format(new="Beta", prev="Alpha Gardens")]


def test_a_line_break_in_the_new_park_name_keeps_the_note_on_one_line(project: Path) -> None:
    _planted(project, ALPHA_2000)
    lines = previous_park.note_lines(project, {"park-b": "Beta\nTwo"}, {"park-b": 2001})
    assert lines == [ALPHA_N1.replace("Beta", "Beta Two")]


def test_two_notes_follow_start_year_order(project: Path) -> None:
    _registry(project)
    plant_park_years(project, [ALPHA_2000], {"park-a": "Alpha", "park-b": "Beta"})
    names = {"park-c": "Gamma", "park-b": "Beta"}
    lines = previous_park.note_lines(project, names, {"park-c": 2002, "park-b": 2001})
    assert lines == [
        ALPHA_N1,
        N2.format(new="Gamma", prev="Beta"),
    ]


# R12: a read failure is one neutral line


def test_no_warehouse_file_gives_the_neutral_line(project: Path) -> None:
    _registry(project)
    error = "warehouse/dev/dev.duckdb does not exist"
    assert _note(project) == [N3.format(error=error)]


def test_a_held_lock_gives_the_neutral_line(project: Path) -> None:
    _registry(project)
    path = plant_park_years(project, [ALPHA_2000], {"park-a": "Alpha"})
    with _writer_holds(path):
        lines = _note(project)
    assert len(lines) == 1
    assert lines[0].startswith(N3_OPEN + "IO Error: Could not set lock on file")


def test_a_warehouse_without_the_year_table_gives_the_neutral_line(project: Path) -> None:
    _registry(project)
    plant_park_years(project, [], {"park-a": "Alpha"})
    lines = _note(project)
    assert len(lines) == 1
    assert lines[0].startswith(N3_OPEN + "Catalog Error: Table with name obt_park_year")


def test_a_multi_line_database_error_gives_one_neutral_line(project: Path) -> None:
    _registry(project)
    plant_park_years(project, [], {"park-a": "Alpha"})
    assert _note(project) == [
        N3.format(
            error="Catalog Error: Table with name obt_park_year does not exist! "
            'Did you mean "dim_park"? LINE 3: FROM marts.obt_park_year ^'
        )
    ]


def test_a_held_lock_note_keeps_the_database_text_on_one_line(project: Path) -> None:
    _registry(project)
    path = plant_park_years(project, [ALPHA_2000], {"park-a": "Alpha"})
    with _writer_holds(path):
        lines = _note(project)
    assert len(lines) == 1
    assert lines[0].startswith(N3_OPEN + "IO Error: Could not set lock on file")
    assert lines[0].endswith(").")
    assert "\n" not in lines[0]
    assert "\r" not in lines[0]


def test_a_config_error_from_the_registry_folder_gives_the_neutral_line(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _planted(project, ALPHA_2000)

    def aliased(data_set: str, project_dir: Path) -> Path:
        raise ConfigError("Two landing folders are one folder")

    monkeypatch.setattr(previous_park, "play_status", SimpleNamespace(registry_feed_dir=aliased))
    assert _note(project) == [N3.format(error="Two landing folders are one folder")]


def test_a_registry_without_the_year_column_gives_the_neutral_line(project: Path) -> None:
    feed = _registry(project)
    feed.write_text("park_id,data_set,note\npark-a,company,\n", encoding="utf-8")
    plant_park_years(project, [ALPHA_2000], {"park-a": "Alpha"})
    error = "the park registry could not be read (KeyError('company_start_year'))"
    assert _note(project) == [N3.format(error=error)]


def test_a_registry_row_cut_short_gives_the_neutral_line(project: Path) -> None:
    feed = _registry(project)
    feed.write_text(",".join(registry_feed.HEADER) + "\npark-a,2000\n", encoding="utf-8")
    plant_park_years(project, [ALPHA_2000], {"park-a": "Alpha"})
    error = (
        'the park registry could not be read (TypeError("int() argument must be a string, a '
        "bytes-like object or a real number, not 'NoneType'\"))"
    )
    assert _note(project) == [N3.format(error=error)]


# R3: no previous park, no read


def test_no_previous_park_opens_no_warehouse(project: Path) -> None:
    _registry(project, [])
    path = plant_park_years(project, [ALPHA_2000], {"park-a": "Alpha"})
    with _writer_holds(path):
        assert previous_park.note_lines(project, {"park-a": "Alpha"}, {"park-a": 2000}) == []


# R14: read-only and closed


def test_the_warehouse_is_closed_after_the_note(project: Path) -> None:
    _planted(project, ALPHA_2000)
    assert _note(project) == [ALPHA_N1]
    with duckdb.connect(str(project / play_status.WAREHOUSE)) as connection:
        connection.execute("INSERT INTO marts.dim_park (park_id) VALUES ('park-x')")
        count = connection.execute("SELECT count(*) FROM marts.dim_park").fetchone()
    assert count == (2,)


def test_the_warehouse_is_opened_read_only(project: Path) -> None:
    _planted(project, ALPHA_2000)
    path = project / play_status.WAREHOUSE
    with duckdb.connect(str(path), read_only=True):
        assert _note(project) == [ALPHA_N1]


def test_the_connection_is_closed_even_when_a_read_fails(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _registry(project)
    plant_park_years(project, [], {"park-a": "Alpha"})
    opened: list[duckdb.DuckDBPyConnection] = []
    real_open = publish_audit.open_warehouse

    def spy(*args: object, **kwargs: object) -> duckdb.DuckDBPyConnection:
        opened.append(real_open(*args, **kwargs))  # type: ignore[arg-type]
        return opened[-1]

    monkeypatch.setattr(previous_park, "open_warehouse", spy)
    assert len(_note(project)) == 1
    assert len(opened) == 1
    with pytest.raises(duckdb.ConnectionException):
        opened[0].execute("SELECT 1")


def test_a_dim_park_row_with_a_null_name_shows_its_park_id(project: Path) -> None:
    _registry(project)
    path = plant_park_years(project, [ALPHA_2000], {"park-a": "Alpha"})
    with duckdb.connect(str(path)) as connection:
        connection.execute("UPDATE marts.dim_park SET park_name = NULL WHERE park_id = 'park-a'")
    assert _note(project) == [ALPHA_N1.replace("Alpha", "park-a")]


# The planting helpers, in both orders


def _rows(project: Path) -> list[tuple[object, ...]]:
    with duckdb.connect(str(project / play_status.WAREHOUSE), read_only=True) as connection:
        return connection.execute(
            "SELECT park_id, park_number, company_start_year, park_name "
            "FROM marts.dim_park ORDER BY park_id"
        ).fetchall()


@pytest.mark.parametrize("names_first", [False, True])
def test_the_two_dim_park_helpers_agree_in_either_order(project: Path, names_first: bool) -> None:
    parent: list[tuple[str, int | None, int]] = [("park-a", 1, 2000), ("park-b", 2, 2001)]
    if names_first:
        plant_park_years(project, [ALPHA_2000], {"park-a": "Alpha", "park-c": "Gamma"})
        _dim_park(project, parent)
    else:
        _dim_park(project, parent)
        plant_park_years(project, [ALPHA_2000], {"park-a": "Alpha", "park-c": "Gamma"})
    assert _rows(project) == [
        ("park-a", 1, 2000, "Alpha"),
        ("park-b", 2, 2001, None),
        ("park-c", None, None, "Gamma"),
    ]
    assert play_status.dim_park_numbers(project, ["park-a", "park-b", "park-c"]) == {
        "park-a": (1, 2000),
        "park-b": (2, 2001),
    }


# R13: DuckDB's interrupt error becomes the interrupt; no other RuntimeError does


@pytest.mark.parametrize("cause", [lock.Interrupted("SIGINT"), KeyboardInterrupt()])
def test_query_interrupted_with_an_interrupt_cause_raises_the_interrupt(
    cause: BaseException,
) -> None:
    with pytest.raises(type(cause)) as raised, query_interrupt.interrupt_as_signal():
        raise RuntimeError("Query interrupted") from cause
    assert raised.value is cause


def test_query_interrupted_without_an_interrupt_cause_stays_a_runtime_error() -> None:
    with (
        pytest.raises(RuntimeError, match="Query interrupted"),
        query_interrupt.interrupt_as_signal(),
    ):
        raise RuntimeError("Query interrupted")


def test_another_runtime_error_with_an_interrupt_cause_stays_a_runtime_error() -> None:
    with pytest.raises(RuntimeError, match="boom"), query_interrupt.interrupt_as_signal():
        raise RuntimeError("boom") from lock.Interrupted("SIGINT")

"""Real Parquet, CSV and DuckDB coverage for the after-play command."""

from __future__ import annotations

import hashlib
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest import after_play, lock, register_parks, registry_feed
from openrct2_analytics.ingest.convert import landing_lock_path
from tests.test_play_status import _writer_holds
from tests.test_register_parks import _rows
from tests.test_register_parks_start_year import later_year, park_one, plant


def _copy(path: Path, query: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(f"COPY ({query}) TO '{path.as_posix()}' (FORMAT PARQUET)")


def _inputs(data: Path, *, year_a: int = 3) -> None:
    parquet = data / "company" / "parquet"
    _copy(
        parquet / "audit" / "seq_audit.parquet",
        "SELECT 'park-a' AS park_id, 's1' AS session_id, 1 AS park_count, 0 AS missing, "
        "0 AS duplicates, 1 AS first_seq, 1 AS last_seq, 1 AS row_count "
        "UNION ALL SELECT 'park-b', 's2', 1, 0, 0, 1, 1, 1",
    )
    _copy(
        parquet / "v1" / "session_start.parquet",
        "SELECT 's1' AS session_id, 'park-a' AS park_id, 'Alpha' AS park_name, "
        f"{year_a} AS game_year, TIMESTAMPTZ '2026-10-01 10:00:00+00' AS emitted_at "
        "UNION ALL SELECT 's2', 'park-b', 'Beta', 5, TIMESTAMPTZ '2026-10-02 10:00:00+00'",
    )


def _tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(str(path.relative_to(root)).encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


@pytest.fixture
def data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    _inputs(root)
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(root))
    return root


def _run(project: Path, *args: str) -> int:
    return after_play.main(args, project_dir=project)


@pytest.mark.parametrize(
    "scenario",
    [
        (["--data-set", "rehearsal", "--parks", "park-a:company"], "rehearsal"),
        (["--data-set", "company", "--parks", "park-a:company"], "parks-missing"),
        (["--data-set", "company"], "parks-missing"),
        (["--data-set", "company", "--parks", "park-a:maybe"], "parks"),
        (
            ["--data-set", "company", "--parks", "park-a:company,park-b:practice,park-x:company"],
            "unknown-park",
        ),
        (["--data-set", "other"], "usage"),
    ],
)
def test_refusals_run_no_step(
    data: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    scenario: tuple[list[str], str],
) -> None:
    args, reason = scenario
    before = _tree(tmp_path)
    assert _run(tmp_path, *args) == 2
    assert _tree(tmp_path) == before
    out = capsys.readouterr().out
    assert f"after-play refused: {reason}:" in out
    assert "after-play: register" not in out


def test_landing_lock_is_refused(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with lock.hold_lock(landing_lock_path(data / "company" / "parquet"), "test holder"):
        before = _tree(tmp_path)
        assert (
            _run(tmp_path, "--data-set", "company", "--parks", "park-a:company,park-b:practice")
            == 2
        )
        assert _tree(tmp_path) == before
    assert "after-play refused: lock-taken:" in capsys.readouterr().out


def test_warehouse_being_built_is_refused(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "warehouse" / "dev" / "dev.duckdb"
    path.parent.mkdir(parents=True)
    duckdb.connect(str(path)).close()
    with _writer_holds(path):
        assert (
            _run(tmp_path, "--data-set", "company", "--parks", "park-a:company,park-b:practice")
            == 2
        )
    assert "after-play refused: warehouse-busy:" in capsys.readouterr().out
    assert not (data / "company" / "registry").exists()


def test_first_failing_step_stops_the_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "data"
    _inputs(root, year_a=0)
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(root))
    parks = "park-a:company,park-b:practice"
    assert _run(tmp_path, "--data-set", "company", "--parks", parks) == 1
    out = capsys.readouterr().out
    assert "after-play failed: step register exited 1" in out
    assert f"rerun the whole chain: make after-play DATA_SET=company PARKS={parks}" in out
    assert "after-play: contracts" not in out
    assert not (root / "company" / "registry").exists()
    assert not (tmp_path / "warehouse").exists()


def test_contract_failure_stops_before_the_build_and_rerun_skips_registered_parks(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The steps after registering run through the real Makefile; the project folder (warehouse)
    # and the data folder are temporary, and the chain stops before any warehouse step.
    parks = "park-a:company,park-b:practice"
    assert _run(tmp_path, "--data-set", "company", "--parks", parks) == 1
    out = capsys.readouterr().out
    assert "Registered 2 park(s)" in out
    assert "after-play failed: step contracts exited" in out
    assert "after-play: transform" not in out
    assert len(list((data / "company" / "registry" / "v1").glob("park_registry_*.csv"))) == 1
    assert _run(tmp_path, "--data-set", "company", "--parks", parks) == 1
    out = capsys.readouterr().out
    assert "register: no waiting park needs registering" in out
    assert "after-play failed: step contracts exited" in out


@pytest.mark.parametrize("registered_practice", [True, False])
def test_park_registered_with_the_other_choice_is_refused(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], registered_practice: bool
) -> None:
    feed = data / "company" / "registry" / "v1"
    feed.mkdir(parents=True)
    note = register_parks.NOTE if registered_practice else ""
    (feed / "park_registry_2026-10-18_01.csv").write_text(
        f"{','.join(registry_feed.HEADER)}\npark-a,2000,3,company,{note},2026-10-18\n",
        encoding="utf-8",
    )
    asked = "company" if registered_practice else "practice"
    before = _tree(tmp_path)
    assert _run(tmp_path, "--data-set", "company", "--parks", f"park-a:{asked},park-b:company") == 2
    assert _tree(tmp_path) == before
    out = capsys.readouterr().out
    assert "after-play refused: choice-conflict: Park park-a" in out
    assert "after-play: register" not in out


def test_empty_park_list_is_no_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    # Nothing is converted, so no park waits; the chain starts and stops at the contract check.
    assert _run(tmp_path, "--data-set", "company", "--parks", "") == 1
    out = capsys.readouterr().out
    assert "refused" not in out
    assert "register: no waiting park needs registering" in out
    assert "after-play failed: step contracts exited" in out
    assert "rerun the whole chain: make after-play DATA_SET=company\n" in out


def test_empty_park_list_still_needs_every_waiting_park(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(tmp_path, "--data-set", "company", "--parks", " ") == 2
    assert "after-play refused: parks-missing: Choose company or practice (sandbox) for " in (
        capsys.readouterr().out
    )


ADR = "see ADR 0050 (play abandoned after the closing 1 March)"
BOTH = "park-a:company,park-b:company"
PLANTED = "park_registry_2026-10-18_01.csv"


def _register_park_a(data: Path) -> None:
    """Park-a is the registered company park (start year 2000); park-b waits to register."""
    feed = data / "company" / "registry" / "v1"
    feed.mkdir(parents=True)
    (feed / PLANTED).write_text(
        f"{','.join(registry_feed.HEADER)}\npark-a,2000,3,company,,2026-10-18\n",
        encoding="utf-8",
    )


def _park_b_from_year_one(data: Path) -> None:
    """Re-plant session_start so park-b began in game year 1 (the fixture gives it year 5)."""
    _copy(
        data / "company" / "parquet" / "v1" / "session_start.parquet",
        "SELECT 's1' AS session_id, 'park-a' AS park_id, 'Alpha' AS park_name, "
        "3 AS game_year, TIMESTAMPTZ '2026-10-01 10:00:00+00' AS emitted_at "
        "UNION ALL SELECT 's2', 'park-b', 'Beta', 1, TIMESTAMPTZ '2026-10-02 10:00:00+00'",
    )


def _refused_before_any_step(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str], line: str
) -> None:
    before = _tree(tmp_path)
    assert _run(tmp_path, "--data-set", "company", *args) == 2
    assert _tree(tmp_path) == before
    out = capsys.readouterr().out
    assert out == f"after-play refused: {line}. Nothing was changed.\n"


def test_start_year_reaches_the_register_step(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _register_park_a(data)
    _park_b_from_year_one(data)
    args = ["--data-set", "company", "--parks", BOTH, "--start-year", "2001"]
    assert _run(tmp_path, *args) == 1
    assert "Park park-b: company start year 2001 (START_YEAR)." in capsys.readouterr().out
    feed = data / "company" / "registry" / "v1"
    written = [path for path in feed.glob("park_registry_*.csv") if path.name != PLANTED]
    assert len(written) == 1
    rows = _rows(written[0])
    assert [(row["park_id"], row["company_start_year"]) for row in rows] == [("park-b", "2001")]


def test_printed_register_command_and_rerun_line_hold_start_year(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _register_park_a(data)
    _park_b_from_year_one(data)
    args = ["--data-set", "company", "--parks", BOTH, "--start-year", "2001"]
    assert _run(tmp_path, *args) == 1
    out = capsys.readouterr().out
    register = "make register-parks DATA_SET=company PARKS=park-b:company START_YEAR=2001\n"
    assert f"after-play: register: {register}" in out
    rerun = f"make after-play DATA_SET=company PARKS={BOTH} START_YEAR=2001\n"
    assert f"rerun the whole chain: {rerun}" in out


def test_rerun_line_has_no_start_year_when_none_was_given(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parks = "park-a:company,park-b:practice"
    assert _run(tmp_path, "--data-set", "company", "--parks", parks) == 1
    out = capsys.readouterr().out
    assert f"rerun the whole chain: make after-play DATA_SET=company PARKS={parks}\n" in out
    assert "START_YEAR" not in out


def test_rerun_with_the_park_registered_prints_the_not_used_line(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _register_park_a(data)
    _park_b_from_year_one(data)
    args = ["--data-set", "company", "--parks", BOTH, "--start-year", "2001"]
    assert _run(tmp_path, *args) == 1
    capsys.readouterr()
    assert _run(tmp_path, *args) == 1
    out = capsys.readouterr().out
    assert (
        "after-play: register: no waiting park needs registering; START_YEAR=2001 not used\n" in out
    )
    assert "after-play: contracts:" in out
    assert "START_YEAR=2001\n" in out.split("rerun the whole chain: ")[1]


def test_no_not_used_line_when_a_park_registers(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _register_park_a(data)
    _park_b_from_year_one(data)
    args = ["--data-set", "company", "--parks", BOTH, "--start-year", "2001"]
    assert _run(tmp_path, *args) == 1
    assert "not used" not in capsys.readouterr().out


def test_start_year_is_required_for_a_second_company_park(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _register_park_a(data)
    _park_b_from_year_one(data)
    line = (
        "start-year-required: Park park-b is not the first company park (registered: park-a), "
        "so give its company start year with START_YEAR=<year>; by the business rules it is "
        f"2001; if 2000 looks too high, {ADR}"
    )
    _refused_before_any_step(tmp_path, capsys, ["--parks", BOTH], line)


def test_two_company_parks_are_refused(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    line = (
        "several-company-parks: Only one company park can be registered per run, and 2 would be "
        '(park-a, park-b); register one at a time with PARKS="<id>:company"'
    )
    _refused_before_any_step(tmp_path, capsys, ["--parks", BOTH], line)


def test_start_year_that_is_not_digits_is_refused_with_nothing_waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    line = "start-year: START_YEAR must be a year written in digits, such as 2001; got 'abc'"
    _refused_before_any_step(tmp_path, capsys, ["--start-year", "abc"], line)


def test_start_year_with_game_year_origin_other_than_one_is_refused(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _register_park_a(data)
    line = (
        "start-year-origin: Park park-b has game-year origin 5; a company start year needs a "
        "park that began in game year 1, so capture the park from a new game before "
        "registering it"
    )
    _refused_before_any_step(tmp_path, capsys, ["--parks", BOTH, "--start-year", "2001"], line)


def test_start_year_at_or_before_the_last_managed_year_is_refused(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _register_park_a(data)
    _park_b_from_year_one(data)
    line = (
        "start-year-overlap: Company year 2000 overlaps park park-a, whose latest company year "
        f"is 2000; park park-b starts in 2001; if 2000 looks too high, {ADR}"
    )
    _refused_before_any_step(tmp_path, capsys, ["--parks", BOTH, "--start-year", "2000"], line)


def test_choice_conflict_is_refused_before_a_bad_start_year(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _register_park_a(data)
    _park_b_from_year_one(data)
    line = "choice-conflict: Park park-a is already registered with the other choice"
    parks = "park-a:practice,park-b:company"
    _refused_before_any_step(tmp_path, capsys, ["--parks", parks, "--start-year", "2000"], line)


def test_start_year_with_a_malformed_value_is_refused_before_a_missing_park(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    line = "start-year: START_YEAR must be a year written in digits, such as 2001; got 'abc'"
    _refused_before_any_step(
        tmp_path, capsys, ["--parks", "park-a:company", "--start-year", "abc"], line
    )


PARK_ONE_TWO = "park-1:company,park-2:company"


def _last_managed_year_2001(data: Path) -> None:
    """Park 1 (registered 2000) has a managed day in company year 2001; Park 2 waits."""
    plant(data, later_year(park_one()))


def test_start_year_equal_to_the_last_managed_year_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    _last_managed_year_2001(tmp_path / "data")
    line = (
        "start-year-overlap: Company year 2001 overlaps park park-1, whose latest company year "
        f"is 2001; park park-2 starts in 2002; if 2001 looks too high, {ADR}"
    )
    _refused_before_any_step(
        tmp_path, capsys, ["--parks", PARK_ONE_TWO, "--start-year", "2001"], line
    )


def test_start_year_after_the_last_managed_year_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    _last_managed_year_2001(tmp_path / "data")
    args = ["--data-set", "company", "--parks", PARK_ONE_TWO, "--start-year", "2002"]
    assert _run(tmp_path, *args) == 1
    out = capsys.readouterr().out
    assert "refused" not in out
    assert "Park park-2: company start year 2002 (START_YEAR)." in out


def test_unconverted_raw_file_is_refused_before_any_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    plant(tmp_path / "data", park_one())
    raw = tmp_path / "data" / "company" / "raw" / "v1" / "events-2026-11-13.jsonl"
    raw.parent.mkdir(parents=True)
    raw.write_text('{"session_id": "s9", "park_id": "park-1"}\n')
    line = (
        "not-converted: events-2026-11-13.jsonl holds a session that was never converted, so "
        "the latest managed year is unknown; run make convert DATA_SET=company first"
    )
    _refused_before_any_step(
        tmp_path, capsys, ["--parks", PARK_ONE_TWO, "--start-year", "2001"], line
    )


def test_start_year_for_a_practice_only_registration_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    plant(tmp_path / "data", park_one())
    line = (
        "start-year-practice: Sandbox parks take no START_YEAR, and every park being "
        "registered is a sandbox park (park-2)"
    )
    parks = "park-1:company,park-2:practice"
    _refused_before_any_step(tmp_path, capsys, ["--parks", parks, "--start-year", "2001"], line)

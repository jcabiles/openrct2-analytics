"""Two parks on one company calendar, with real dbt over a temporary two-park copy of the sample.

`tests/two_park_support.py` builds the copy; each case builds its own, runs the singular test
it checks (the export case runs the real export instead) and, for a planted disagreement, edits
one stored row of the built warehouse first (dbt unit tests attach only to models, not to
singular tests).
"""

from __future__ import annotations

import contextlib
import json
import re
import shutil
from pathlib import Path

import duckdb

from openrct2_analytics.ingest import play_status
from openrct2_analytics.showcase.export import main as export_main
from openrct2_analytics.showcase.page_check import main as page_check_main
from tests import test_dbt_environments as environments
from tests.page_check_support import render_page, write_every_status_served_files
from tests.two_park_support import (
    FIRST_PARK,
    REGISTRY_FILE,
    SECOND_PARK,
    TwoParks,
    build_two_parks,
    copy_with_second_park,
    query,
    run_test,
)

project = environments.project  # the fixture, re-exported so pytest finds it here

ALLOWLIST = Path(__file__).resolve().parents[1] / "site" / "exports.toml"
CALENDAR = "assert_park_years_share_one_company_calendar"
SECOND_PARKS_FIRST_STATEMENT = (
    f"park_id = '{SECOND_PARK}' and company_year = 2001 and statement_month = 0"
)


def stored_failures(two: TwoParks) -> list[tuple[object, ...]]:
    return query(
        two.warehouse,
        f"select failed_check, parks from dbt_test__audit.{CALENDAR} order by failed_check, parks",
    )


def edit_built(two: TwoParks, sql: str, expected_rows: int) -> None:
    """Run one `sql` statement on the built warehouse and check how many rows it changed."""
    with contextlib.closing(duckdb.connect(str(two.warehouse))) as db:
        changed = db.execute(sql).fetchone()
    assert changed == (expected_rows,)


def plant(two: TwoParks, assignment: str) -> None:
    """Change the second park's (2001, month 0) statement in the built `fct_park_month`."""
    with contextlib.closing(duckdb.connect(str(two.warehouse))) as db:
        changed = db.execute(
            f"update marts.fct_park_month set {assignment} where {SECOND_PARKS_FIRST_STATEMENT}"
        ).fetchone()
    assert changed == (1,)


def test_base_build_passes_the_calendar_check_with_one_year_row_per_park(
    project: Path, tmp_path: Path
) -> None:
    two = build_two_parks(project, tmp_path, f"+{CALENDAR}")

    assert run_test(two, CALENDAR) == (0, "PASS")
    assert query(
        two.warehouse,
        "select park_id, company_year from marts.obt_park_year order by park_id",
    ) == [(FIRST_PARK, 2000), (SECOND_PARK, 2001)]
    assert query(
        two.warehouse,
        "select park_id, company_year, close_status from intermediate.int_park_years__year_close "
        "order by park_id, company_year",
    ) == [
        (FIRST_PARK, 2000, "open"),
        (FIRST_PARK, 2001, "open"),
        (SECOND_PARK, 2001, "open"),
    ]


def test_two_park_build_exports_both_park_years_and_no_company_years(
    project: Path, tmp_path: Path
) -> None:
    two = build_two_parks(
        project,
        tmp_path,
        "+obt_park_year +obt_company_year +obt_ride_month +obt_ride_year +dim_park",
    )
    served = tmp_path / "served"

    assert (
        export_main(
            [
                "write",
                "--warehouse",
                str(two.warehouse),
                "--served-dir",
                str(served),
                "--allowlist",
                str(ALLOWLIST),
            ]
        )
        == 0
    )
    park_rows = json.loads((served / "park_year.json").read_text())["rows"]
    company_rows = json.loads((served / "company_year.json").read_text())["rows"]

    assert {row["park_id"] for row in park_rows} == {FIRST_PARK, SECOND_PARK}
    assert company_rows == []

    built = render_page(served, tmp_path)
    assert page_check_main(["--site", str(built), "--served-dir", str(served)]) == 0
    rendered = (built / "index.html").read_text()
    table = rendered.split('id="park-year-table"')[1].split("</table>")[0]
    assert FIRST_PARK in table
    assert SECOND_PARK in table


def test_dbt_built_dim_park_read_through_dim_park_numbers_gives_both_numbers_and_start_years(
    project: Path, tmp_path: Path
) -> None:
    two = build_two_parks(project, tmp_path, "+obt_park_year +dim_park")

    assert play_status.dim_park_numbers(two.project, [FIRST_PARK, SECOND_PARK]) == {
        FIRST_PARK: (1, 2000),
        SECOND_PARK: (2, 2001),
    }


def test_real_template_with_every_status_and_a_closed_year_passes_the_page_check(
    tmp_path: Path,
) -> None:
    served = tmp_path / "served"
    write_every_status_served_files(served)
    built = render_page(served, tmp_path)
    assert page_check_main(["--site", str(built), "--served-dir", str(served)]) == 0


def test_a_date_dated_two_ways_across_parks_fails_check_4(project: Path, tmp_path: Path) -> None:
    two = build_two_parks(project, tmp_path, f"+{CALENDAR}")
    plant(two, "statement_company_date = date '2000-03-01'")

    code, status = run_test(two, CALENDAR)

    assert (code != 0, status) == (True, "FAIL")
    assert stored_failures(two) == [(4, f"{FIRST_PARK}, {SECOND_PARK}")]


def test_a_company_month_dated_two_ways_across_parks_fails_check_5(
    project: Path, tmp_path: Path
) -> None:
    two = build_two_parks(project, tmp_path, f"+{CALENDAR}")
    plant(two, "company_year = 2000")

    code, status = run_test(two, CALENDAR)

    assert (code != 0, status) == (True, "FAIL")
    assert stored_failures(two) == [(5, f"{FIRST_PARK}, {SECOND_PARK}")]


def test_a_park_year_disagreeing_with_the_registry_recompute_fails_check_1(
    project: Path, tmp_path: Path
) -> None:
    two = build_two_parks(project, tmp_path, f"+{CALENDAR}")
    # No current registry row at all: the recompute is null, which `is distinct from` still flags.
    edit_built(
        two,
        f"delete from intermediate.int_park_registry__current where park_id = '{SECOND_PARK}'",
        1,
    )

    code, status = run_test(two, CALENDAR)

    assert (code != 0, status) == (True, "FAIL")
    assert stored_failures(two) == [(1, SECOND_PARK)]


def test_a_statement_date_after_1_october_fails_check_2(project: Path, tmp_path: Path) -> None:
    two = build_two_parks(project, tmp_path, f"+{CALENDAR}")
    edit_built(
        two,
        "update marts.obt_park_year set last_statement_company_date = date '2001-10-02' "
        f"where park_id = '{SECOND_PARK}'",
        1,
    )

    code, status = run_test(two, CALENDAR)

    assert (code != 0, status) == (True, "FAIL")
    assert stored_failures(two) == [(2, SECOND_PARK)]


def test_two_rows_for_one_company_year_fail_check_3(project: Path, tmp_path: Path) -> None:
    two = build_two_parks(project, tmp_path, f"+{CALENDAR}")
    # What duplicate current registry rows would produce in the park-year table: a second row.
    edit_built(
        two,
        f"insert into marts.obt_park_year select * from marts.obt_park_year "
        f"where park_id = '{SECOND_PARK}'",
        1,
    )

    code, status = run_test(two, CALENDAR)

    assert (code != 0, status) == (True, "FAIL")
    assert stored_failures(two) == [(3, SECOND_PARK), (3, SECOND_PARK)]


def test_two_parks_in_one_company_year_dating_a_month_differently_fail_checks_4_and_5(
    project: Path, tmp_path: Path
) -> None:
    two = build_two_parks(project, tmp_path, f"+{CALENDAR}", second_company_start_year=2000)
    assert run_test(two, CALENDAR) == (0, "PASS")
    edit_built(
        two,
        "update marts.fct_park_month "
        "set statement_company_date = statement_company_date + interval 1 month "
        f"where park_id = '{SECOND_PARK}'",
        3,
    )

    code, status = run_test(two, CALENDAR)

    assert (code != 0, status) == (True, "FAIL")
    assert {check for check, _ in stored_failures(two)} == {4, 5}


CLOSE = "assert_every_expected_park_closes_its_company_year"


def close_run(
    project: Path,
    target: str,
    data: Path,
    *args: str,
    run_id: str = "close-test",
) -> tuple[int, str, Path, str]:
    """Run one close-test dbt command and return its status, warehouse and output."""
    if target == "ci":
        output_dir = project / "ci-output"
        output_dir.mkdir(exist_ok=True)
        env = {"OPENRCT2_CI_DIR": str(output_dir)}
        warehouse = output_dir / "ci.duckdb"
    elif target == "dev":
        (project / "warehouse" / "dev").mkdir(parents=True, exist_ok=True)
        env = {}
        warehouse = project / "warehouse" / "dev" / "dev.duckdb"
    else:
        candidate = project / "warehouse" / "candidate" / f"run-{run_id}"
        candidate.mkdir(parents=True, exist_ok=True)
        env = {"OPENRCT2_PUBLISH_RUN_ID": run_id}
        warehouse = candidate / f"{target}.duckdb"
    variables = f"{{parquet_root: {data}, registry_root: {data / 'registry'}}}"
    done = environments.dbt(
        project,
        *args,
        "--target",
        target,
        "--no-partial-parse",
        "--vars",
        variables,
        env=env,
        parquet=False,
        registry=False,
    )
    found = re.search(rf"of \d+ (PASS|WARN|FAIL)\b[^\n]*?\b{CLOSE}\b", done.stdout)
    return done.returncode, found.group(1) if found else "", warehouse, done.stdout


def close_failures(warehouse: Path) -> list[tuple[object, ...]]:
    return query(
        warehouse,
        f"select failure_kind, park_id, company_year, statements_kept, "
        f"statements_expected, missing_statement_months, hint from dbt_test__audit.{CLOSE} "
        "order by failure_kind, park_id nulls first, company_year",
    )


def assert_three_statements(two: TwoParks) -> None:
    assert query(
        two.warehouse,
        "select park_id, count(*) from marts.fct_park_month group by park_id order by park_id",
    ) == [(FIRST_PARK, 3), (SECOND_PARK, 3)]


def test_close_flags_a_company_year_the_register_has_not_closed(
    project: Path, tmp_path: Path
) -> None:
    two = build_two_parks(project, tmp_path, f"+{CLOSE}")
    assert_three_statements(two)
    assert run_test(two, CLOSE) == (0, "PASS")
    assert query(two.warehouse, "select company_year from marts.obt_company_year") == []

    manifest = json.loads((project / "target" / "manifest.json").read_text())
    node = next(
        value for key, value in manifest["nodes"].items() if key.endswith(".obt_company_year")
    )
    schema = node["schema"]
    edit_built(two, f"insert into {schema}.obt_company_year (company_year) values (2000)", 1)
    code, status = run_test(two, CLOSE)
    assert (code != 0, status) == (True, "FAIL")
    assert close_failures(two.warehouse) == [
        (
            "company_year_not_closed",
            None,
            2000,
            None,
            None,
            None,
            "The company year is not marked closed by the park-year register.",
        )
    ]


def test_close_planted_hide_warns_on_ci_and_fails_on_rehearsal(
    project: Path, tmp_path: Path
) -> None:
    data = tmp_path / "planted-two-park-sample"
    copy_with_second_park(data)
    finance = data / "v1" / "finance_month.parquet"
    staged = finance.with_name("staged.parquet")
    with contextlib.closing(duckdb.connect()) as db:
        db.execute(f"create view src as select * from read_parquet('{finance}')")
        db.execute(
            "copy (select * replace ("
            f"case when park_id = '{FIRST_PARK}' and statement_year = 9 "
            "and statement_month = 2 then 10 else statement_year end as statement_year, "
            f"case when park_id = '{FIRST_PARK}' and statement_year = 9 "
            "and statement_month = 2 then 0 else statement_month end as statement_month, "
            f"case when park_id = '{FIRST_PARK}' and statement_year = 9 "
            "and statement_month = 2 then 10 else game_year end as game_year, "
            f"case when park_id = '{FIRST_PARK}' and statement_year = 9 "
            "and statement_month = 2 then 0 else game_month end as game_month) "
            "from src where not "
            f"(park_id = '{FIRST_PARK}' and statement_year = 9 and statement_month = 1)) "
            f"to '{staged}' (format parquet)"
        )
    staged.replace(finance)
    code, _, warehouse, output = close_run(project, "ci", data, "run", "--select", f"+{CLOSE}")
    assert code == 0, output
    # One statement removed and one moved but kept: two for the first park; the second is untouched.
    assert query(
        warehouse,
        "select park_id, count(*) from marts.fct_park_month group by park_id order by park_id",
    ) == [(FIRST_PARK, 2), (SECOND_PARK, 3)]
    assert query(
        warehouse,
        "select count(*) from marts.fct_park_month "
        f"where park_id = '{FIRST_PARK}' and statement_year = 10 and statement_month = 0",
    ) == [(1,)]
    code, status, warehouse, output = close_run(project, "ci", data, "test", "--select", CLOSE)
    assert (code, status) == (0, "WARN"), output
    assert close_failures(warehouse) == [
        (
            "park_year_incomplete",
            FIRST_PARK,
            2000,
            1,
            8,
            "1,2,3,4,5,6,7",
            (
                "Missing statement months 1,2,3,4,5,6,7; those before the last kept statement "
                "of the year, or all of them once a later year has a statement, are lost."
            ),
        )
    ]
    code, _, _, output = close_run(
        project, "rehearsal", data, "run", "--select", f"+{CLOSE}", run_id="close-rehearsal"
    )
    assert code == 0, output
    code, status, _, output = close_run(
        project,
        "rehearsal",
        data,
        "test",
        "--select",
        CLOSE,
        run_id="close-rehearsal",
    )
    assert (code != 0, status) == (True, "FAIL"), output


def test_close_hint_names_an_early_registry_start(project: Path, tmp_path: Path) -> None:
    data = tmp_path / "early-registry-sample"
    copy_with_second_park(data)
    # Game year 9 is now company year 2002, one year after the registry's start year 2001.
    registry = data / REGISTRY_FILE
    registry.write_text(registry.read_text().replace(",9,rehearsal,", ",8,rehearsal,"))
    code, _, warehouse, output = close_run(project, "ci", data, "run", "--select", f"+{CLOSE}")
    assert code == 0, output
    code, status, warehouse, output = close_run(project, "ci", data, "test", "--select", CLOSE)
    assert (code, status) == (0, "WARN"), output
    early = query(
        warehouse,
        "select company_year, missing_statement_months, hint "
        f"from dbt_test__audit.{CLOSE} where park_id = '{SECOND_PARK}' and company_year = 2001",
    )
    assert early == [
        (
            2001,
            "0,1,2,3,4,5,6,7",
            "The registry start year is earlier than the park's first captured day; the "
            "registry row was most likely entered wrong and needs a corrected delivery "
            "(ADR 0023).",
        )
    ]


def test_close_committed_sample_passes_on_ci(project: Path, tmp_path: Path) -> None:
    code, _, warehouse, output = close_run(
        project, "ci", environments.SAMPLE, "run", "--select", f"+{CLOSE}"
    )
    assert code == 0, output
    assert query(
        warehouse,
        "select park_id, count(*) from marts.fct_park_month group by park_id order by park_id",
    ) == [(FIRST_PARK, 3)]
    code, status, _, output = close_run(
        project, "ci", environments.SAMPLE, "test", "--select", CLOSE
    )
    assert (code, status) == (0, "PASS"), output


def test_close_severity_by_parse(project: Path, tmp_path: Path) -> None:
    planted = tmp_path / "severity-sample"
    shutil.copytree(environments.SAMPLE, planted)
    cases = [
        ("ci", environments.SAMPLE, "warn"),
        ("dev", Path("data/sample/rehearsal"), "warn"),
        ("dev", planted, "error"),
        ("rehearsal", planted, "error"),
    ]
    found = []
    for target, data, _expected in cases:
        code, _, _, output = close_run(project, target, data, "parse")
        assert code == 0, output
        manifest = json.loads((project / "target" / "manifest.json").read_text())
        nodes = [value for key, value in manifest["nodes"].items() if key.endswith(f".{CLOSE}")]
        assert len(nodes) == 1
        found.append(str(nodes[0]["config"]["severity"]).lower())
    assert found == [expected for _, _, expected in cases]

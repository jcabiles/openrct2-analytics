"""Acceptance tests for the site's JSON export: a real temporary DuckDB file, no mocks."""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.showcase.export import load_allowlist, main, render

ALLOWLIST = Path(__file__).resolve().parents[1] / "site" / "exports.toml"


@pytest.fixture
def warehouse(tmp_path: Path) -> Path:
    path = tmp_path / "wh.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute("create schema marts")
    connection.execute(
        "create table marts.fct_park_month as select * from (values "
        "('p1-2026-03', 'p1', date '2026-03-31', 4073.60::decimal(18,2)), "
        "('p1-2026-04', 'p1', date '2026-04-30', -120.05::decimal(18,2))"
        ") t(park_month_key, park_id, statement_company_date, operating_profit)"
    )
    connection.execute(
        "create table marts.obt_company_year as select * from (values "
        "(2026, 2, 1, 16, 4, 3953.55::decimal(18,2))"
        ") t(company_year, parks_reporting, parks_partial_first_season, statements_kept,"
        " months_checked, operating_profit)"
    )
    connection.execute(
        "create table marts.obt_park_year as select * from (values "
        "('p1|2026', 'p1', 2026, 2, 8, 'open', false, 1, 3953.55::decimal(18,2))"
        ") t(park_year_key, park_id, company_year, statements_kept, statements_expected,"
        " close_status, is_partial_first_season, months_checked, operating_profit)"
    )
    connection.execute(
        "create table marts.obt_park_month as select * from (values "
        "('p1-2026-03', 'p1', date '2026-03-31', 100.00::decimal(18,2), 40.00::decimal(18,2),"
        " 30.00::decimal(18,2), 20.00::decimal(18,2), 10.00::decimal(18,2),"
        " 40.0::decimal(18,1), 30.0::decimal(18,1), 20.0::decimal(18,1), 10.0::decimal(18,1))"
        ") t(park_month_key, park_id, company_date, operating_revenue, ride_revenue,"
        " food_drink_revenue, merchandise_revenue, entrance_revenue, ride_revenue_share_pct,"
        " food_drink_revenue_share_pct, merchandise_revenue_share_pct, entrance_revenue_share_pct)"
    )
    connection.execute(
        "create table marts.obt_ride_month as select * from (values "
        "('p1|1|1|2026-03', 'p1|1|1', 'p1', 'Wild Mouse', 2026, date '2026-03-31', 31,"
        " 98.5::decimal(18,1), 12, 400)"
        ") t(ride_month_key, ride_key, park_id, ride_name, company_year, company_date, ride_days,"
        " average_availability_from_downtime_pct, longest_queue_seen_minutes, riders)"
    )
    connection.execute(
        "create table marts.obt_ride_year as select * from (values "
        "('p1|1|1|2026', 'p1|1|1', 'p1', 'Wild Mouse', 2026, date '2026-03-01', date '2026-10-31',"
        " 245, 3000, 1, 70, 11)"
        ") t(ride_year_key, ride_key, park_id, ride_name, company_year, first_company_date,"
        " last_company_date, ride_days, riders, riders_rank_in_park_year, latest_guest_rating_pct,"
        " latest_ride_age_months)"
    )
    connection.execute(
        "create table marts.dim_park as select * from (values ('p1', 1, 'company')) "
        "t(park_id, park_number, data_set)"
    )
    connection.execute(
        "create table marts.fct_park_day as select * from (values "
        "('s1', date '2026-03-01'), ('s1', date '2026-03-02'), ('s2', date '2026-03-01'), "
        "('s3', date '2026-03-01')) t(session_id, company_date)"
    )
    connection.execute("create schema staging")
    connection.execute(
        "create table staging.stg_session_start as select * from (values "
        "('s1', true), ('s2', true), ('s3', true), ('s9', false)) t(session_id, headless)"
    )
    connection.close()
    return path


def run(mode: str, warehouse: Path, served: Path, *extra: str) -> int:
    args = [
        mode,
        "--warehouse",
        str(warehouse),
        "--served-dir",
        str(served),
        "--allowlist",
        str(ALLOWLIST),
    ]
    return main([*args, *extra])


def test_write_then_check_passes(warehouse: Path, tmp_path: Path) -> None:
    served = tmp_path / "served"
    assert run("write", warehouse, served) == 0
    assert run("check", warehouse, served) == 0


def test_changed_park_month_value_fails_and_names_the_row(
    warehouse: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    served = tmp_path / "served"
    run("write", warehouse, served)
    file = served / "park_month.json"
    file.write_text(file.read_text().replace("-120.05", "-120.06"))
    assert run("check", warehouse, served) == 1
    out = capsys.readouterr().out
    assert "park_id=p1, statement_company_date=2026-04-30" in out
    assert "operating_profit" in out


def test_changed_company_year_value_fails_and_names_the_row(
    warehouse: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    served = tmp_path / "served"
    run("write", warehouse, served)
    file = served / "company_year.json"
    file.write_text(file.read_text().replace("3953.55", "3953.56"))
    assert run("check", warehouse, served) == 1
    out = capsys.readouterr().out
    assert "company_year=2026" in out
    assert "operating_profit" in out


def test_changed_park_year_value_fails_and_names_the_row(
    warehouse: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    served = tmp_path / "served"
    run("write", warehouse, served)
    file = served / "park_year.json"
    file.write_text(file.read_text().replace("3953.55", "3953.56"))
    assert run("check", warehouse, served) == 1
    out = capsys.readouterr().out
    assert "company_year=2026, park_id=p1" in out
    assert "operating_profit" in out


DEPARTMENT_EXPORTS = {
    "ride_month": (
        "marts.obt_ride_month",
        [
            "ride_month_key",
            "ride_key",
            "park_id",
            "ride_name",
            "company_year",
            "company_date",
            "ride_days",
            "average_availability_from_downtime_pct",
            "longest_queue_seen_minutes",
            "riders",
        ],
    ),
    "ride_year": (
        "marts.obt_ride_year",
        [
            "ride_year_key",
            "ride_key",
            "park_id",
            "ride_name",
            "company_year",
            "first_company_date",
            "last_company_date",
            "ride_days",
            "riders",
            "riders_rank_in_park_year",
            "latest_guest_rating_pct",
            "latest_ride_age_months",
        ],
    ),
    "park_month_revenue": (
        "marts.obt_park_month",
        [
            "park_month_key",
            "park_id",
            "company_date",
            "operating_revenue",
            "ride_revenue",
            "food_drink_revenue",
            "merchandise_revenue",
            "entrance_revenue",
            "ride_revenue_share_pct",
            "food_drink_revenue_share_pct",
            "merchandise_revenue_share_pct",
            "entrance_revenue_share_pct",
        ],
    ),
}


@pytest.mark.parametrize("name", sorted(DEPARTMENT_EXPORTS))
def test_department_export_pins_its_relation_and_columns(name: str) -> None:
    relation, columns = DEPARTMENT_EXPORTS[name]
    entry = next(e for e in load_allowlist(ALLOWLIST) if e.name == name)
    assert entry.relation == relation
    assert entry.output == f"{name}.json"
    assert list(entry.columns) == columns
    assert not [c for c in entry.columns if "guest_visits" in c or c.endswith("_per_visit")]


def test_park_export_pins_its_relation_columns_and_order() -> None:
    entry = next(e for e in load_allowlist(ALLOWLIST) if e.name == "park")
    assert entry.relation == "marts.dim_park"
    assert entry.output == "park.json"
    assert list(entry.columns) == ["park_id", "park_number"]
    assert list(entry.order_by) == ["park_number", "park_id"]


def test_allowlist_serves_exactly_seven_files() -> None:
    assert sorted(e.output for e in load_allowlist(ALLOWLIST)) == [
        "company_year.json",
        "park.json",
        "park_month.json",
        "park_month_revenue.json",
        "park_year.json",
        "ride_month.json",
        "ride_year.json",
    ]


def test_relation_off_the_allowlist_exits_2_and_writes_nothing(
    warehouse: Path, tmp_path: Path
) -> None:
    served = tmp_path / "served"
    code = run("write", warehouse, served, "--relation", "intermediate.int_statements__labeled")
    assert code == 2
    assert not served.exists() or not list(served.iterdir())


def test_known_relation_writes_only_its_file(warehouse: Path, tmp_path: Path) -> None:
    served = tmp_path / "served"
    assert run("write", warehouse, served, "--relation", "marts.fct_park_month") == 0
    assert [file.name for file in served.iterdir()] == ["park_month.json"]


def test_allowlist_entry_outside_marts_exits_2(warehouse: Path, tmp_path: Path) -> None:
    allowlist = tmp_path / "exports.toml"
    allowlist.write_text(
        '[[export]]\nname = "x"\nrelation = "staging.stg_events"\noutput = "x.json"\n'
        'columns = ["a"]\norder_by = ["a"]\n'
    )
    connection = duckdb.connect(str(warehouse))
    connection.execute("create table staging.stg_events as select 1 as a")
    connection.close()
    served = tmp_path / "served"
    code = main(
        [
            "write",
            "--warehouse",
            str(warehouse),
            "--served-dir",
            str(served),
            "--allowlist",
            str(allowlist),
        ]
    )
    assert code == 2
    assert not served.exists()


def test_missing_warehouse_exits_2(tmp_path: Path) -> None:
    assert run("write", tmp_path / "absent.duckdb", tmp_path / "served") == 2


def test_money_keeps_two_decimals(warehouse: Path, tmp_path: Path) -> None:
    served = tmp_path / "served"
    run("write", warehouse, served)
    text = (served / "park_month.json").read_text()
    assert '"operating_profit": 4073.60' in text
    assert "4073.6\n" not in text
    assert json.loads(text)["rows"][0]["statement_company_date"] == "2026-03-31"


def _served_rows(file: Path) -> list[dict[str, object]]:
    return json.loads(file.read_text(), parse_float=Decimal)["rows"]  # type: ignore[no-any-return]


def test_reversed_rows_in_the_served_file_fail(warehouse: Path, tmp_path: Path) -> None:
    served = tmp_path / "served"
    run("write", warehouse, served)
    entry = next(e for e in load_allowlist(ALLOWLIST) if e.name == "park_month")
    file = served / "park_month.json"
    file.write_text(render(entry, list(reversed(_served_rows(file)))))
    assert run("check", warehouse, served) == 1


@pytest.mark.parametrize(
    ("key", "wrong"), [("name", "other"), ("relation", "marts.other"), ("columns", ["park_id"])]
)
def test_wrong_header_key_in_the_served_file_fails(
    warehouse: Path, tmp_path: Path, *, capsys: pytest.CaptureFixture[str], key: str, wrong: object
) -> None:
    served = tmp_path / "served"
    run("write", warehouse, served)
    file = served / "park_month.json"
    document = json.loads(file.read_text())
    document[key] = wrong
    file.write_text(json.dumps(document))
    assert run("check", warehouse, served) == 1
    assert f"header {key} differs" in capsys.readouterr().out


@pytest.mark.parametrize("change", ["drop_last", "duplicate_last"])
def test_row_count_mismatch_in_the_served_file_fails(
    warehouse: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], change: str
) -> None:
    served = tmp_path / "served"
    run("write", warehouse, served)
    entry = next(e for e in load_allowlist(ALLOWLIST) if e.name == "park_month")
    file = served / "park_month.json"
    rows = _served_rows(file)
    rows = rows[:-1] if change == "drop_last" else [*rows, rows[-1]]
    file.write_text(render(entry, rows))
    assert run("check", warehouse, served) == 1
    assert f"served has {len(rows)} rows, marts have 2" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{not json", "is not valid JSON"),
        ("[1, 2]", "is not a JSON object"),
        ('{"name": "park_month"}', "has no rows list"),
        ('{"name": "park_month", "rows": 3}', "has no rows list"),
    ],
)
def test_malformed_served_file_exits_1_with_a_message(
    warehouse: Path, tmp_path: Path, *, capsys: pytest.CaptureFixture[str], text: str, message: str
) -> None:
    served = tmp_path / "served"
    run("write", warehouse, served)
    (served / "park_month.json").write_text(text)
    assert run("check", warehouse, served) == 1
    assert message in capsys.readouterr().out


def test_rows_are_chronological_across_a_game_year_of_two_digits(
    warehouse: Path, tmp_path: Path
) -> None:
    connection = duckdb.connect(str(warehouse))
    connection.execute(
        "insert into marts.fct_park_month values "
        "('p1|10|0', 'p1', date '2027-01-31', 1.00), ('p1|9|0', 'p1', date '2026-09-30', 2.00)"
    )
    connection.close()
    served = tmp_path / "served"
    run("write", warehouse, served)
    keys = [row["park_month_key"] for row in _served_rows(served / "park_month.json")]
    assert keys == ["p1-2026-03", "p1-2026-04", "p1|9|0", "p1|10|0"]


def test_text_only_difference_names_the_row(
    warehouse: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    served = tmp_path / "served"
    run("write", warehouse, served)
    file = served / "park_month.json"
    file.write_text(file.read_text().replace("4073.60", "4073.6"))
    assert run("check", warehouse, served) == 1
    out = capsys.readouterr().out
    assert "park_id=p1, statement_company_date=2026-03-31" in out
    assert "different text" in out


def test_check_opens_a_read_only_warehouse(warehouse: Path, tmp_path: Path) -> None:
    served = tmp_path / "served"
    run("write", warehouse, served)
    os.chmod(warehouse, 0o444)
    assert run("check", warehouse, served) == 0


def test_check_with_a_missing_served_file_exits_1(warehouse: Path, tmp_path: Path) -> None:
    assert run("check", warehouse, tmp_path / "served") == 1


@pytest.mark.parametrize(
    "body",
    [
        '[[export]]\nname = "x"\nrelation = "marts.fct_park_month"\noutput = "x.json"\n'
        'columns = ["park_id"]\n',
        '[[export]]\nname = "x"\nrelation = "marts.fct_park_month"\noutput = "x.json"\n'
        'columns = ["park_id"]\norder_by = ["statement_company_date"]\n',
        "this is not toml",
    ],
)
def test_malformed_allowlist_exits_2(
    warehouse: Path, tmp_path: Path, body: str, capsys: pytest.CaptureFixture[str]
) -> None:
    allowlist = tmp_path / "exports.toml"
    allowlist.write_text(body)
    code = main(
        ["check", "--warehouse", str(warehouse), "--allowlist", str(allowlist)]
        + ["--served-dir", str(tmp_path / "served")]
    )
    assert code == 2
    assert "export refused" in capsys.readouterr().out


VALID_ALLOWLIST_ENTRY = (
    '[[export]]\nname = "x"\nrelation = "marts.fct_park_month"\noutput = "x.json"\n'
    'columns = ["park_id", "statement_company_date"]\norder_by = ["park_id"]\n'
)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (VALID_ALLOWLIST_ENTRY.replace('name = "x"', "name = 5"), "name must be a string"),
        (
            VALID_ALLOWLIST_ENTRY.replace('relation = "marts.fct_park_month"', "relation = 5"),
            "relation must be a string",
        ),
        (
            VALID_ALLOWLIST_ENTRY.replace('output = "x.json"', 'output = ["x.json"]'),
            "output must be a string",
        ),
        (
            VALID_ALLOWLIST_ENTRY.replace(
                'columns = ["park_id", "statement_company_date"]', 'columns = "park_id"'
            ),
            "columns must be a non-empty list of strings",
        ),
        (
            VALID_ALLOWLIST_ENTRY.replace(
                'columns = ["park_id", "statement_company_date"]', "columns = []"
            ),
            "columns must be a non-empty list of strings",
        ),
        (
            VALID_ALLOWLIST_ENTRY.replace(
                'columns = ["park_id", "statement_company_date"]', 'columns = ["park_id", 5]'
            ),
            "columns must be a non-empty list of strings",
        ),
        (
            VALID_ALLOWLIST_ENTRY.replace('order_by = ["park_id"]', 'order_by = "park_id"'),
            "order_by must be a non-empty list of strings",
        ),
        (
            VALID_ALLOWLIST_ENTRY.replace('order_by = ["park_id"]', "order_by = []"),
            "order_by must be a non-empty list of strings",
        ),
    ],
)
def test_allowlist_entry_type_errors_exit_2(
    warehouse: Path,
    tmp_path: Path,
    *,
    capsys: pytest.CaptureFixture[str],
    body: str,
    message: str,
) -> None:
    allowlist = tmp_path / "exports.toml"
    allowlist.write_text(body)
    code = main(
        ["check", "--warehouse", str(warehouse), "--allowlist", str(allowlist)]
        + ["--served-dir", str(tmp_path / "served")]
    )
    assert code == 2
    assert f"export refused: allowlist entry 1: {message}" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("", "needs a non-empty [[export]] list"),
        ('[[exports]]\nname = "x"\n', "unknown top-level keys ['exports']"),
        ("export = 1\n", "needs a non-empty [[export]] list"),
    ],
)
def test_allowlist_without_an_export_list_exits_2(
    warehouse: Path, tmp_path: Path, *, capsys: pytest.CaptureFixture[str], body: str, message: str
) -> None:
    allowlist = tmp_path / "exports.toml"
    allowlist.write_text(body)
    code = main(
        ["check", "--warehouse", str(warehouse), "--allowlist", str(allowlist)]
        + ["--served-dir", str(tmp_path / "served")]
    )
    assert code == 2
    assert message in capsys.readouterr().out


def test_listed_column_missing_from_the_mart_exits_2(warehouse: Path, tmp_path: Path) -> None:
    allowlist = tmp_path / "exports.toml"
    allowlist.write_text(
        '[[export]]\nname = "x"\nrelation = "marts.fct_park_month"\noutput = "x.json"\n'
        'columns = ["nope"]\norder_by = ["nope"]\n'
    )
    code = main(
        ["write", "--warehouse", str(warehouse), "--allowlist", str(allowlist)]
        + ["--served-dir", str(tmp_path / "served")]
    )
    assert code == 2

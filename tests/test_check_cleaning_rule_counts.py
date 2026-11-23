"""Behavioral tests for the cleaning-count gate using real manifests and DuckDB files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pytest

from check_cleaning_rule_counts import main

EXEMPT_NODES = [
    ("dim_date", "where timeline_status = 'kept'"),
    ("dim_park", 'where {{ timeline_status("starts.seq", "lineage") }} = \'kept\''),
]


def node(name: str, sql: str, *, schema: str = "main", alias: str | None = None) -> dict[str, Any]:
    """Make the subset of a dbt manifest node used by the script."""
    return {
        "unique_id": f"model.project.{name}",
        "resource_type": "model",
        "name": name,
        "schema": schema,
        "alias": alias or name,
        "raw_code": sql,
    }


def execute(
    tmp_path: Path,
    nodes: list[dict[str, Any]],
    counts: list[tuple[str, str]],
    *,
    schema: str = "main",
    alias: str = "fct_cleaning_rule_count",
    omit_table: bool = False,
) -> tuple[int, Path]:
    """Build a DuckDB counts relation and manifest, then run the command."""
    database = tmp_path / "ci.duckdb"
    con = duckdb.connect(str(database))
    if not omit_table:
        con.execute(f'create schema if not exists "{schema}"')
        con.execute(f'create table "{schema}"."{alias}" (rule_name varchar, model_name varchar)')
        if counts:
            con.executemany(f'insert into "{schema}"."{alias}" values (?, ?)', counts)
    con.close()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"nodes": {item["unique_id"]: item for item in nodes}}), encoding="utf-8"
    )
    return main([str(manifest), str(database)]), manifest


def execute_with_legacy_rule_column(
    tmp_path: Path, nodes: list[dict[str, Any]], counts: list[tuple[str, str]]
) -> int:
    """Run the command against a counts table with the former rule column name."""
    database = tmp_path / "ci.duckdb"
    con = duckdb.connect(str(database))
    con.execute('create table "fct_cleaning_rule_count" ("rule" varchar, model_name varchar)')
    if counts:
        con.executemany('insert into "fct_cleaning_rule_count" values (?, ?)', counts)
    con.close()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"nodes": {item["unique_id"]: item for item in nodes}}), encoding="utf-8"
    )
    return main([str(manifest), str(database)])


def complete_nodes(extra: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Include the two live exempt filters found in every project manifest."""
    return [node(name, sql) for name, sql in [*EXEMPT_NODES, *extra]] + [
        node("fct_cleaning_rule_count", "select 1")
    ]


def test_a_every_pattern_has_its_count_row(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = [
        ("repeat_delivery", "stg_x"),
        ("abandoned_branch", "model_x"),
        ("placeholder_null_minus_1", "ride_x"),
        ("placeholder_null_255", "ride_x"),
        ("placeholder_null_1275", "ride_x"),
        ("placeholder_null_65535", "ride_x"),
        ("last_reading_null", "counter_x"),
    ]
    nodes = complete_nodes(
        [
            ("stg_x", "where delivery_rank = 1"),
            ("model_x", "where timeline_status <> 'abandoned'"),
            (
                "ride_x",
                "nullif(shop_item, 255) nullif(a, -1) nullif(b, 1275) nullif(c, 65535)",
            ),
            ("counter_x", "{{ counter_change('x', 'seq') }}"),
        ]
    )
    code, _ = execute(tmp_path, nodes, rows)
    assert code == 0
    assert "every known cleaning filter" in capsys.readouterr().out


def test_b_delivery_rank_without_count_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = execute(tmp_path, complete_nodes([("stg_untracked", "where delivery_rank = 1")]), [])
    assert code == 1
    assert "stg_untracked: repeat_delivery: filter found" in capsys.readouterr().err


def test_c_macro_kept_and_both_abandoned_operators_are_found(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = [("abandoned_branch", name) for name in ("macro_model", "not_equal_model", "bang_model")]
    nodes = complete_nodes(
        [
            ("macro_model", '{{ timeline_status("x.seq", "lineage") }} = \'kept\''),
            ("not_equal_model", "where timeline_status <> 'abandoned'"),
            ("bang_model", "where timeline_status != 'abandoned'"),
        ]
    )
    code, _ = execute(tmp_path, nodes, rows)
    assert code == 0
    assert "every known cleaning filter" in capsys.readouterr().out


def test_d_only_placeholder_nullif_values_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    nodes = complete_nodes(
        [
            ("ordinary_nullif", "nullif(operating_days, 0) nullif(coalesce(x, 0), 0)"),
            ("placeholders", "nullif(shop_item, 255) nullif(excitement_hundredths, -1)"),
        ]
    )
    counts = [
        ("placeholder_null_255", "placeholders"),
        ("placeholder_null_minus_1", "placeholders"),
    ]
    code, _ = execute(tmp_path, nodes, counts)
    assert code == 0
    assert "every known cleaning filter" in capsys.readouterr().out


@pytest.mark.parametrize(
    "case",
    [
        ("counter_filter", "{{ counter_change('x', 'seq') }}", "last_reading_null"),
        ("null_minus_1", "nullif(x, -1)", "placeholder_null_minus_1"),
        ("null_255", "nullif(x, 255)", "placeholder_null_255"),
        ("null_1275", "nullif(x, 1275)", "placeholder_null_1275"),
        ("null_65535", "nullif(x, 65535)", "placeholder_null_65535"),
        ("macro_kept", "{{ timeline_status('x.seq', 'lineage') }} = 'kept'", "abandoned_branch"),
        ("column_not_equal", "where timeline_status <> 'abandoned'", "abandoned_branch"),
        ("column_bang_equal", "where timeline_status != 'abandoned'", "abandoned_branch"),
        (
            "macro_not_equal",
            "{{ timeline_status('x.seq', 'lineage') }} <> 'abandoned'",
            "abandoned_branch",
        ),
        (
            "macro_bang_equal",
            "{{ timeline_status('x.seq', 'lineage') }} != 'abandoned'",
            "abandoned_branch",
        ),
        (
            "macro_multiline",
            "{{ timeline_status(\n  'x.seq',\n  'lineage'\n) }} = 'kept'",
            "abandoned_branch",
        ),
        (
            "macro_whitespace_control",
            "{{- timeline_status('x.seq', 'lineage') -}} = 'kept'",
            "abandoned_branch",
        ),
        ("upper_timeline", "WHERE TIMELINE_STATUS = 'kept'", "abandoned_branch"),
        ("upper_delivery", "WHERE DELIVERY_RANK = 1", "repeat_delivery"),
        ("upper_nullif", "NULLIF(x, 255)", "placeholder_null_255"),
        ("upper_counter", "{{ COUNTER_CHANGE('x', 'seq') }}", "last_reading_null"),
        ("qualified_nullif", "nullif(ride.shop_item, 255)", "placeholder_null_255"),
        ("quoted_nullif", 'nullif("shop_item", 255)', "placeholder_null_255"),
        ("quoted_spaced_nullif", 'nullif("ride" . "shop_item", 255)', "placeholder_null_255"),
        ("spaced_dot_nullif", "nullif(ride . shop_item, 255)", "placeholder_null_255"),
    ],
)
def test_known_filter_without_count_fails(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    case: tuple[str, str, str],
) -> None:
    model_name, sql, rule = case
    code, _ = execute(tmp_path, complete_nodes([(model_name, sql)]), [])
    assert code == 1
    assert f"{model_name}: {rule}: filter found" in capsys.readouterr().err


def test_e_dimension_exemptions_pass_and_same_filter_elsewhere_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    nodes = complete_nodes([("ordinary_dimension", "where timeline_status = 'kept'")])
    code, _ = execute(tmp_path, nodes, [])
    assert code == 1
    error = capsys.readouterr().err
    assert "ordinary_dimension: abandoned_branch: filter found" in error
    assert "dim_date: abandoned_branch: filter found" not in error
    assert "dim_park: abandoned_branch: filter found" not in error


def test_f_missing_manifest_and_missing_counts_table_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, manifest = execute(tmp_path, complete_nodes([]), [], omit_table=True)
    assert code == 1
    assert "cannot read fct_cleaning_rule_count table" in capsys.readouterr().err
    code = main([str(manifest.with_name("absent.json")), str(tmp_path / "ci.duckdb")])
    assert code == 1
    assert "absent.json" in capsys.readouterr().err


def test_missing_database_file_fails_naming_the_path_and_creates_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"nodes": {}}), encoding="utf-8")
    database = tmp_path / "absent.duckdb"
    code = main([str(manifest), str(database)])
    assert code == 1
    assert str(database) in capsys.readouterr().err
    assert not database.exists()


def test_macro_pattern_does_not_span_two_macro_calls(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sql = "{{ timeline_status('a','b') }} as ts from x where {{ other(y) }} = 'kept'"
    code, _ = execute(tmp_path, complete_nodes([("two_macros", sql)]), [])
    assert code == 0
    assert "every known cleaning filter" in capsys.readouterr().out


def test_manifest_nodes_that_is_not_an_object_fails_plainly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"nodes": []}), encoding="utf-8")
    code = main([str(manifest), str(tmp_path / "ci.duckdb")])
    assert code == 1
    error = capsys.readouterr().err
    assert str(manifest) in error
    assert "not an object" in error
    assert "Traceback" not in error


def test_node_without_resource_type_names_node_and_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"nodes": {"model.p.broken": {"name": "broken"}}}))
    code = main([str(manifest), str(tmp_path / "ci.duckdb")])
    assert code == 1
    error = capsys.readouterr().err
    assert "model.p.broken" in error
    assert str(manifest) in error


def test_manifest_without_nodes_names_manifest_and_missing_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    code = main([str(manifest), str(tmp_path / "ci.duckdb")])
    assert code == 1
    error = capsys.readouterr().err
    assert str(manifest) in error
    assert "nodes" in error


def test_g_filters_inside_sql_and_jinja_comments_are_ignored(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    nodes = complete_nodes(
        [("comment_only", "-- delivery_rank = 1\n{# where timeline_status = 'kept' #}\nselect 1")]
    )
    code, _ = execute(tmp_path, nodes, [])
    assert code == 0
    assert "every known cleaning filter" in capsys.readouterr().out


def test_h_missing_exempt_filter_is_a_stale_exemption(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    nodes = [
        node("dim_date", "select 1"),
        node("dim_park", EXEMPT_NODES[1][1]),
        node("fct_cleaning_rule_count", "select 1"),
    ]
    code, _ = execute(tmp_path, nodes, [])
    assert code == 1
    assert "dim_date: stale abandoned_branch exemption" in capsys.readouterr().err


def test_i_counts_table_uses_manifest_schema_and_alias(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    nodes = complete_nodes([])
    nodes[-1]["schema"] = "counts_schema"
    nodes[-1]["alias"] = "counts_alias"
    code, _ = execute(tmp_path, nodes, [], schema="counts_schema", alias="counts_alias")
    assert code == 0
    assert "every known cleaning filter" in capsys.readouterr().out


def test_j_missing_pair_is_reported_when_each_half_has_another_row(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    model_name = "stg_untracked"
    nodes = complete_nodes([(model_name, "where delivery_rank = 1")])
    counts = [
        ("placeholder_null_255", model_name),
        ("repeat_delivery", "another_model"),
    ]
    code, _ = execute(tmp_path, nodes, counts)
    assert code == 1
    error = capsys.readouterr().err
    assert (
        f"{model_name}: repeat_delivery: filter found, no row in fct_cleaning_rule_count" in error
    )


def test_k_dim_park_missing_filter_is_a_stale_exemption(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    nodes = [
        node("dim_date", EXEMPT_NODES[0][1]),
        node("dim_park", "select 1"),
        node("fct_cleaning_rule_count", "select 1"),
    ]
    code, _ = execute(tmp_path, nodes, [])
    assert code == 1
    assert "dim_park: stale abandoned_branch exemption" in capsys.readouterr().err


def test_l_old_rule_column_does_not_fall_back_to_legacy_counts_schema(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    nodes = complete_nodes([("stg_tracked", "where delivery_rank = 1")])
    code = execute_with_legacy_rule_column(tmp_path, nodes, [("repeat_delivery", "stg_tracked")])
    assert code == 1
    assert "cannot read fct_cleaning_rule_count table" in capsys.readouterr().err

"""Behavioral tests for rule d (D16) of scripts/dbt_rules.py, on real temporary dbt project folders.

The helpers that build a project folder live in test_check_dbt_rules.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dbt_rules import check_forbidden
from tests.test_check_dbt_rules import STAGING, build, fails, write


def test_rule_d_a_tenths_column_read_outside_staging_fails(tmp_path: Path) -> None:
    sql = {"models/marts/fct_guest_day.sql": "select cash_tenths from {{ ref('stg_x') }}"}
    fails(
        check_forbidden(build(tmp_path, sql=sql)),
        "models/marts/fct_guest_day.sql",
        "d",
        "reads cash_tenths outside models/staging/",
    )


def test_rule_d_the_legal_forms_pass(tmp_path: Path) -> None:
    sql = {
        f"{STAGING}/stg_x.sql": "select {{ tenths_to_usd('cash_tenths') }} as cash_usd from a",
        f"{STAGING}/stg_z.sql": "with final as (select a from {{ source('l', 'x') }})\n"
        "select * from final",
        "models/marts/fct_y.sql": "-- cash_tenths is converted in staging\nselect "
        "{{ tenths_to_usd('a') }} as b, cash_usd /* wages_tenths */ from {{ ref('stg_x') }}",
    }
    assert check_forbidden(build(tmp_path, sql=sql)) == []


SRC = "{{ source('landing','save_written') }}"
STAR_FROM_SOURCE = [
    pytest.param("select * from {{ source('landing', 'session_start') }}", id="one line"),
    pytest.param(
        "with raw as (\n  SELECT\n    *\n  FROM {{ source('landing', 'a') }}\n) select 1",
        id="multi line, capitals",
    ),
    pytest.param(f"select distinct * from {SRC}", id="distinct"),
    pytest.param(f"select * exclude (x) from {SRC}", id="exclude"),
    pytest.param(f"select * replace (1 as x) from {SRC}", id="replace"),
    pytest.param(f"select *, 1 as x from {SRC}", id="star then an expression"),
    pytest.param(
        f"select *, row_number() over (partition by event_id order by received_at) as rn "
        f"from {SRC}",
        id="star then a window",
    ),
    pytest.param(f"select a.event_id, s.* from {SRC} as s", id="alias star not first"),
    pytest.param(
        "select * from {{ ref('stg_x') }} as a join "
        "{{ source('landing', 'save_written') }} as s on a.event_id = s.event_id",
        id="joined source",
    ),
    pytest.param(f"select columns(*) from {SRC}", id="columns star"),
    pytest.param(f"from {SRC}", id="FROM-first"),
    pytest.param(f"with a as (select 1 as x) from {SRC}", id="FROM-first after a CTE"),
    pytest.param(
        "{% set src = source('landing','save_written') %} select * from {{ src }}",
        id="set alias",
    ),
    pytest.param(
        f"with raw as (select *, 1 as x from {SRC}) select event_id from raw", id="star in a CTE"
    ),
    pytest.param(f"select 1 as x union all select * from {SRC}", id="after a union"),
]


@pytest.mark.parametrize("text", STAR_FROM_SOURCE)
def test_rule_d_select_star_from_a_source_fails(tmp_path: Path, text: str) -> None:
    sql = {f"{STAGING}/stg_x.sql": text}
    fails(
        check_forbidden(build(tmp_path, sql=sql)),
        f"{STAGING}/stg_x.sql",
        "d",
        "select * from a source()",
    )


def test_rule_d_comma_join_star_from_source_fails(tmp_path: Path) -> None:
    text = f"select * from {{{{ ref('stg_save_written') }}}} as a, {SRC} as s"
    fails(
        check_forbidden(build(tmp_path, sql={f"{STAGING}/stg_x.sql": text})),
        f"{STAGING}/stg_x.sql",
        "d",
        "select * from a source()",
    )


def test_rule_d_comma_join_qualified_star_from_source_fails(tmp_path: Path) -> None:
    text = f"select a.* from {{{{ ref('stg_save_written') }}}} as a, {SRC} as s"
    fails(
        check_forbidden(build(tmp_path, sql={f"{STAGING}/stg_x.sql": text})),
        f"{STAGING}/stg_x.sql",
        "d",
        "select * from a source()",
    )


def test_rule_d_comma_join_star_in_cte_from_source_fails(tmp_path: Path) -> None:
    text = (
        f"with raw as (select * from {{{{ ref('stg_save_written') }}}} as a, {SRC} as s) "
        "select event_id from raw"
    )
    fails(
        check_forbidden(build(tmp_path, sql={f"{STAGING}/stg_x.sql": text})),
        f"{STAGING}/stg_x.sql",
        "d",
        "select * from a source()",
    )


def test_rule_d_cross_join_star_from_source_fails(tmp_path: Path) -> None:
    text = f"select * from {{{{ ref('stg_save_written') }}}} as a cross join {SRC} as s"
    fails(
        check_forbidden(build(tmp_path, sql={f"{STAGING}/stg_x.sql": text})),
        f"{STAGING}/stg_x.sql",
        "d",
        "select * from a source()",
    )


def test_rule_d_natural_join_star_from_source_fails(tmp_path: Path) -> None:
    text = f"select * from {{{{ ref('stg_save_written') }}}} as a natural join {SRC} as s"
    fails(
        check_forbidden(build(tmp_path, sql={f"{STAGING}/stg_x.sql": text})),
        f"{STAGING}/stg_x.sql",
        "d",
        "select * from a source()",
    )


def test_rule_d_second_union_arm_star_from_source_fails(tmp_path: Path) -> None:
    text = f"select event_id from final union all select * from {SRC}"
    fails(
        check_forbidden(build(tmp_path, sql={f"{STAGING}/stg_x.sql": text})),
        f"{STAGING}/stg_x.sql",
        "d",
        "select * from a source()",
    )


def test_rule_d_parenthesized_source_from_star_fails(tmp_path: Path) -> None:
    text = "select * from ({{ source('landing','save_written') }}) as s"
    fails(
        check_forbidden(build(tmp_path, sql={f"{STAGING}/stg_x.sql": text})),
        f"{STAGING}/stg_x.sql",
        "d",
        "select * from a source()",
    )


def test_rule_d_named_columns_over_comma_join_source_pass(tmp_path: Path) -> None:
    text = (
        f"select a.event_id, s.received_at from {{{{ ref('stg_save_written') }}}} as a, {SRC} as s"
    )
    assert check_forbidden(build(tmp_path, sql={f"{STAGING}/stg_x.sql": text})) == []


def test_rule_d_outer_star_ignores_source_in_where_subquery(tmp_path: Path) -> None:
    text = (
        "select * from final where event_id in "
        "(select event_id from {{ source('landing','save_written') }})"
    )
    assert check_forbidden(build(tmp_path, sql={f"{STAGING}/stg_x.sql": text})) == []


@pytest.mark.parametrize(
    "text",
    [
        "with final as (select a from {{ source('l', 'x') }})\nselect * from final",
        f"with raw as (select event_id, count(*) as n from {SRC} group by 1) select * from raw",
        f"select event_id, a * b as c from {SRC}",
        "select a.event_id, s.received_at from {{ ref('stg_x') }} as a join "
        "{{ source('landing', 'save_written') }} as s on a.event_id = s.event_id",
        f"select e.event_id from {SRC} as e where exists (select * from final)",
        "select * from {{ ref('stg_x') }}",
        f"-- select * from {SRC}\nselect event_id from {SRC}",
        f"select 'from {SRC}' as x",
    ],
    ids=[
        "select * from final",
        "count star over a source",
        "multiplication",
        "named columns over joined source",
        "star in a subquery over another table",
        "star over a ref",
        "commented star",
        "string",
    ],
)
def test_rule_d_the_star_look_alikes_pass(tmp_path: Path, text: str) -> None:
    assert check_forbidden(build(tmp_path, sql={f"{STAGING}/stg_x.sql": text})) == []


def test_rule_d_a_comment_marker_inside_a_string_does_not_hide_a_tenths_read(
    tmp_path: Path,
) -> None:
    sql = {"models/marts/m.sql": "select 'a--b' as x, cash_tenths from {{ ref('stg_x') }}"}
    fails(
        check_forbidden(build(tmp_path, sql=sql)),
        "models/marts/m.sql",
        "d",
        "reads cash_tenths outside models/staging/",
    )


def test_rule_d_a_tenths_read_in_a_macro_fails(tmp_path: Path) -> None:
    sql = {"macros/leak.sql": "{% macro leak() %}cash_tenths{% endmacro %}"}
    fails(
        check_forbidden(build(tmp_path, sql=sql)),
        "macros/leak.sql",
        "d",
        "reads cash_tenths outside models/staging/",
    )


def test_rule_d_any_packages_yml_fails(tmp_path: Path) -> None:
    project = build(tmp_path)
    write(tmp_path / "packages.yml", "packages: []\n")
    fails(check_forbidden(project), "packages.yml", "d", "not allowed")

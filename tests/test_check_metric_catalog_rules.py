"""Planted faults for the rules the whole-branch review added to scripts/metric_catalog_rules.py.

Each case plants one fault in the small clean catalog of tests/test_check_metric_catalog.py and
expects a line naming the rule and the metric.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from check_metric_catalog import find_problems
from tests.test_check_metric_catalog import (
    EXPECTED,
    Doc,
    base_catalog,
    metric,
    park_day,
    problems_for,
    sales_meta,
    sales_params,
    sales_tree,
    set_key,
    visits_tree,
    write_root,
)

YOY = "north_yoy"


def measure_without_expr(doc: Doc) -> None:
    park_day(doc)["measures"].append({"name": "wages_tenths", "agg": "sum"})
    sales_params(doc)["measure"] = "wages_tenths"


def dimension_without_expr(doc: Doc) -> None:
    park_day(doc)["dimensions"].append({"name": "bogus_dim", "type": "categorical"})


def unlisted_guardrail(doc: Doc) -> None:
    sales_meta(doc)["role"] = "guardrail"


def equal_without_tolerance(doc: Doc) -> None:
    visits_tree(doc)["direction"] = "equal"
    del visits_tree(doc)["tolerance"]


CASES: list[tuple[str, str, Callable[[Doc], None]]] = [
    ("3b-empty-unit", "rule 3b: metric 'sales' has an empty", set_key(sales_meta, "unit", "")),
    ("3b-null-unit", "config.meta.unit", set_key(sales_meta, "unit", None)),
    ("3b-empty-grain", "config.meta.grain", set_key(sales_meta, "grain", " ")),
    ("3b-null-grain", "config.meta.grain", set_key(sales_meta, "grain", None)),
    ("3b-empty-source", "config.meta.roadmap_source", set_key(sales_meta, "roadmap_source", "")),
    ("3c-text-excludes", "rule 3c: metric 'sales'", set_key(sales_meta, "excludes", "x")),
    ("3c-text-sources", "rule 3c: metric 'sales'", set_key(sales_meta, "source_models", "s")),
    ("3g-typo", "rule 3g: metric 'sales' has role 'tre'", set_key(sales_meta, "role", "tre")),
    ("3g-case", "rule 3g: metric 'sales' has role 'Tree'", set_key(sales_meta, "role", "Tree")),
    ("6a-measure-name", "rule 6a: measure 'wages_tenths'", measure_without_expr),
    ("7a-measure-name", "rule 7a: metric 'sales' (usd) reads 'wages_tenths'", measure_without_expr),
    ("6a-dimension-name", "rule 6a: dimension 'bogus_dim'", dimension_without_expr),
    ("8b-unlisted", "rule 8b: guardrail metric 'sales' is not in", unlisted_guardrail),
    (
        "8d-outside-tree",
        "rule 8d: metric 'sales' has tree.parent 'sales_per_visit', which is not in the tree",
        set_key(sales_tree, "parent", "sales_per_visit"),
    ),
    ("8k", "rule 8k: hypothesis link of 'guest_visits'", equal_without_tolerance),
]


@pytest.mark.parametrize(("case", "needle", "mutate"), CASES, ids=[c[0] for c in CASES])
def test_each_planted_fault_is_named(
    tmp_path: Path, case: str, needle: str, mutate: Callable[[Doc], None]
) -> None:
    doc = base_catalog()
    mutate(doc)

    assert any(needle in line for line in problems_for(tmp_path, doc)), case


@pytest.mark.parametrize("role", ["tre", "supporting", "tree"])
def test_a_causal_link_is_rejected_whatever_the_role(tmp_path: Path, role: str) -> None:
    doc = base_catalog()
    sales_meta(doc)["role"] = role
    sales_tree(doc)["link"] = "causal"

    assert any("rule 8f: metric 'sales'" in line for line in problems_for(tmp_path, doc))


def with_year_over_year(expr: str, offset: str) -> Doc:
    """The clean catalog plus a year-over-year metric over `north`."""
    doc = base_catalog()
    prior = {"name": "north", "alias": "north_prior_year", "offset_window": offset}
    inputs = [{"name": "north"}, prior]
    params = {"expr": expr, "metrics": inputs}
    extra = {"unit": "fraction of the prior year"}
    doc["metrics"].append(metric(YOY, "derived", params, "supporting", extra=extra))
    return doc


def yoy_problems(root: Path, doc: Doc) -> list[str]:
    problems: list[str] = find_problems(write_root(root, json.dumps(doc)), EXPECTED | {YOY})
    return problems


def test_a_year_over_year_metric_over_its_prior_year_passes(tmp_path: Path) -> None:
    doc = with_year_over_year("(north - north_prior_year) / north_prior_year", "1 year")

    assert yoy_problems(tmp_path, doc) == []


@pytest.mark.parametrize(
    ("expr", "offset"),
    [
        ("(north - north_prior_year) / north_prior_year", "1 month"),
        ("(north - north_prior_year) / north", "1 year"),
        ("(north_prior_year - north) / north_prior_year", "1 year"),
    ],
    ids=["offset-1-month", "current-year-denominator", "terms-swapped"],
)
def test_a_year_over_year_metric_off_its_prior_year_is_rule_10a(
    tmp_path: Path, expr: str, offset: str
) -> None:
    problems = yoy_problems(tmp_path, with_year_over_year(expr, offset))

    assert any(f"rule 10a: metric {YOY!r}" in line for line in problems)

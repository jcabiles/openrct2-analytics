"""Behavioral tests for scripts/check_metric_catalog.py, on real temporary catalogs.

Each clause of the house rules has a planted fault. A JSON document is valid YAML, so the
catalogs are built as Python dicts and written with json.dumps.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import check_metric_catalog
from check_metric_catalog import find_problems, main

Doc = dict[str, Any]
REPO = Path(__file__).resolve().parent.parent
EXPECTED = frozenset({"north", "sales", "costs", "guest_visits", "sales_per_visit"})
STAGING_YAML = """version: 2
models:
  - name: stg_park_snapshot
    columns:
      - name: park_id
      - name: admissions_increase
      - name: classification
      - name: gross_usd
      - name: cost_usd
      - name: weather
"""
HYPOTHESIS_LINK = {
    "parent": "north",
    "link": "hypothesis",
    "claim": "visits move with profit",
    "direction": "positive",
    "lag": "same month",
    "evidence": "observational: one park",
    "rivals": ["weather"],
    "review": "each year-end close",
    "check": "a warn test",
    "tolerance": "10%",
}
EQUAL_LINK = {**HYPOTHESIS_LINK, "parent": "sales", "direction": "equal", "tolerance": ""}
THRESHOLD = {
    "value": 0.98,
    "unit": "fraction of the prior year",
    "direction": "at least",
    "basis": "a project decision, fixed before results",
}


def metric(name: str, kind: str, params: Doc, role: str, *, extra: Doc | None = None) -> Doc:
    base_meta: Doc = {
        "unit": "usd",
        "clock": "company date",
        "grain": "per park per company month",
        "owner": "the project owner",
        "status": "draft",
        "role": role,
        "source_models": ["stg_park_snapshot"],
        "excludes": ["abandoned-timeline rows"],
        "roadmap_source": "NEXT 4",
    }
    base_meta.update(extra or {})
    return {
        "name": name,
        "label": name,
        "description": f"What {name} means.",
        "type": kind,
        "type_params": params,
        "config": {"meta": base_meta},
    }


def identity_link() -> Doc:
    return {"parent": "north", "link": "identity", "reconciled_by": "equals the sum, exactly"}


def base_catalog() -> Doc:
    """A small catalog that breaks no rule."""
    park_day: Doc = {
        "name": "park_day",
        "model": "ref('stg_park_snapshot')",
        "entities": [
            {"name": "park_day", "type": "primary", "expr": "park_day_key"},
            {"name": "park", "type": "foreign", "expr": "park_id"},
        ],
        "dimensions": [{"name": "flag", "type": "categorical"}],
        "measures": [
            {"name": "visit_count", "agg": "sum", "expr": "admissions_increase"},
            {
                "name": "sales_usd",
                "agg": "sum",
                "expr": "case when classification = 'ride' then gross_usd end",
            },
            {"name": "costs_usd", "agg": "sum", "expr": "cost_usd"},
        ],
        "config": {
            "meta": {
                "planned_columns": [
                    {"name": "park_day_key", "planned_by": "later"},
                    {"name": "flag", "planned_by": "later"},
                ]
            }
        },
    }
    ride_day: Doc = {
        "name": "ride_day",
        "model": "ref('stg_ride')",
        "primary_entity": "ride_day",
        "measures": [{"name": "ride_count", "agg": "sum", "expr": "1"}],
        "config": {"meta": {"planned_model": True}},
    }
    filtered = {"name": "sales", "filter": "{{ Dimension('park_day__flag') }} = true"}
    metrics = [
        metric(
            "north",
            "derived",
            {"expr": "sales + costs", "metrics": [filtered, {"name": "costs"}]},
            "north_star",
            extra={"guardrails": ["guest_visits"]},
        ),
        metric(
            "sales", "simple", {"measure": "sales_usd"}, "tree", extra={"tree": identity_link()}
        ),
        metric(
            "costs", "simple", {"measure": "costs_usd"}, "tree", extra={"tree": identity_link()}
        ),
        metric(
            "guest_visits",
            "simple",
            {"measure": "visit_count"},
            "guardrail",
            extra={
                "tree": {
                    **copy.deepcopy(HYPOTHESIS_LINK),
                    "additional_links": [{**copy.deepcopy(HYPOTHESIS_LINK), "parent": "sales"}],
                },
                "unit": "visits",
                "guardrail_threshold": dict(THRESHOLD),
            },
        ),
        metric(
            "sales_per_visit",
            "ratio",
            {"numerator": "sales", "denominator": "guest_visits"},
            "supporting",
            extra={"unit": "usd per visit", "source_models": ["stg_park_snapshot", "stg_ride"]},
        ),
    ]
    return {"semantic_models": [park_day, ride_day], "metrics": metrics}


def get(doc: Doc, name: str) -> Doc:
    return next(item for item in doc["metrics"] if item["name"] == name)


def meta(doc: Doc, name: str) -> Doc:
    result: Doc = get(doc, name)["config"]["meta"]
    return result


def tree(doc: Doc, name: str) -> Doc:
    result: Doc = meta(doc, name)["tree"]
    return result


def write_root(root: Path, text: str) -> Path:
    (root / "metrics").mkdir(parents=True, exist_ok=True)
    (root / "metrics" / "catalog.yml").write_text(text, encoding="utf-8")
    (root / "models" / "staging").mkdir(parents=True, exist_ok=True)
    (root / "models" / "staging" / "stg_park_snapshot.yml").write_text(
        STAGING_YAML, encoding="utf-8"
    )
    return root


def problems_for(root: Path, doc: Doc) -> list[str]:
    problems: list[str] = find_problems(write_root(root, json.dumps(doc)), EXPECTED)
    return problems


def set_key(path: Callable[[Doc], Doc], key: str, value: object) -> Callable[[Doc], None]:
    def mutate(doc: Doc) -> None:
        path(doc)[key] = value

    return mutate


def drop_key(path: Callable[[Doc], Doc], key: str) -> Callable[[Doc], None]:
    def mutate(doc: Doc) -> None:
        del path(doc)[key]

    return mutate


def sales_meta(doc: Doc) -> Doc:
    return meta(doc, "sales")


def sales_tree(doc: Doc) -> Doc:
    return tree(doc, "sales")


def visits_tree(doc: Doc) -> Doc:
    return tree(doc, "guest_visits")


def visits_link(doc: Doc) -> Doc:
    result: Doc = visits_tree(doc)["additional_links"][0]
    return result


def visits_threshold(doc: Doc) -> Doc:
    result: Doc = meta(doc, "guest_visits")["guardrail_threshold"]
    return result


def threshold_on_supporting_metric(doc: Doc) -> None:
    meta(doc, "sales_per_visit")["guardrail_threshold"] = dict(THRESHOLD)


def park_day(doc: Doc) -> Doc:
    result: Doc = doc["semantic_models"][0]
    return result


def ride_day(doc: Doc) -> Doc:
    result: Doc = doc["semantic_models"][1]
    return result


def duplicate_semantic_model(doc: Doc) -> None:
    doc["semantic_models"].append(copy.deepcopy(ride_day(doc)))


def duplicate_measure(doc: Doc) -> None:
    ride_day(doc)["measures"][0]["name"] = "visit_count"


def duplicate_metric(doc: Doc) -> None:
    doc["metrics"].append(copy.deepcopy(get(doc, "costs")))


def add_unlisted_metric(doc: Doc) -> None:
    extra = copy.deepcopy(get(doc, "costs"))
    extra["name"] = "unlisted"
    doc["metrics"].append(extra)


def break_north_expr(doc: Doc) -> None:
    get(doc, "north")["type_params"]["expr"] = "sales + costs + ghost"


def break_money_column(doc: Doc) -> None:
    park_day(doc)["measures"][1]["expr"] = "case when classification = 'ride' then gross end"


def make_cycle(doc: Doc) -> None:
    tree(doc, "sales")["parent"] = "costs"
    tree(doc, "costs")["parent"] = "sales"


def make_guardrail_a_tree(doc: Doc) -> None:
    meta(doc, "guest_visits")["role"] = "tree"


def planned_column_exists(doc: Doc) -> None:
    park_day(doc)["config"]["meta"]["planned_columns"].append(
        {"name": "park_id", "planned_by": "x"}
    )


def filter_unknown_dimension(doc: Doc) -> None:
    get(doc, "north")["type_params"]["metrics"][0]["filter"] = "{{ Dimension('park_day__nope') }}"


def filter_unknown_entity(doc: Doc) -> None:
    get(doc, "north")["type_params"]["metrics"][0]["filter"] = "{{ Dimension('nowhere__flag') }}"


def planned_model_now_exists(doc: Doc) -> None:
    ride_day(doc)["model"] = "ref('stg_park_snapshot')"


def sales_params(doc: Doc) -> Doc:
    result: Doc = get(doc, "sales")["type_params"]
    return result


def ratio_params(doc: Doc) -> Doc:
    result: Doc = get(doc, "sales_per_visit")["type_params"]
    return result


def unknown_input_metric(doc: Doc) -> None:
    get(doc, "north")["type_params"]["metrics"][1] = {"name": "ghost_metric"}


def numerator_filters_on_unknown_dimension(doc: Doc) -> None:
    ratio_params(doc)["numerator"] = {
        "name": "sales",
        "filter": "{{ Dimension('park_day__nope') }}",
    }


def denominator_filters_on_unknown_dimension(doc: Doc) -> None:
    ratio_params(doc)["denominator"] = {
        "name": "guest_visits",
        "filter": "{{ Dimension('park_day__nope') }}",
    }


CASES: list[tuple[str, str, Callable[[Doc], None]]] = [
    ("2a", "rule 2a", duplicate_semantic_model),
    ("2b", "rule 2b", duplicate_measure),
    ("2c", "rule 2c", duplicate_metric),
    ("2d", "rule 2d", add_unlisted_metric),
    ("3a", "rule 3a", drop_key(lambda d: get(d, "sales"), "label")),
    ("3b", "rule 3b", drop_key(sales_meta, "unit")),
    ("3c", "rule 3c", set_key(sales_meta, "excludes", [])),
    ("3d", "rule 3d", set_key(sales_meta, "clock", "tuesday")),
    ("3e", "rule 3e", set_key(sales_meta, "owner", "someone else")),
    ("3f", "rule 3f", set_key(sales_meta, "status", "done")),
    ("4a", "rule 4a", set_key(lambda d: get(d, "sales")["type_params"], "measure", "nope")),
    ("4b", "rule 4b", break_north_expr),
    ("5a", "rule 5a", set_key(park_day, "model", "ref('missing')")),
    ("5b", "rule 5b", planned_model_now_exists),
    ("5c", "rule 5c", set_key(sales_meta, "source_models", ["nowhere"])),
    (
        "6a-expr",
        "rule 6a: measure 'sales_usd'",
        set_key(
            park_day, "measures", [{"name": "sales_usd", "agg": "sum", "expr": "bogus_column"}]
        ),
    ),
    (
        "6a-dimension",
        "rule 6a: metric 'north' filters on 'park_day__nope'",
        filter_unknown_dimension,
    ),
    ("6a-entity", "rule 6a: metric 'north' filters on 'nowhere__flag'", filter_unknown_entity),
    ("6b", "rule 6b", planned_column_exists),
    ("7a", "rule 7a", break_money_column),
    ("8a", "rule 8a", set_key(lambda d: meta(d, "north"), "role", "tree")),
    (
        "8b-missing",
        "rule 8b: north star 'north' lacks",
        drop_key(lambda d: meta(d, "north"), "guardrails"),
    ),
    ("8b-role", "rule 8b: guardrail 'guest_visits'", make_guardrail_a_tree),
    ("8c", "rule 8c", drop_key(lambda d: meta(d, "sales"), "tree")),
    ("8d-list", "rule 8d", set_key(sales_tree, "parent", ["north"])),
    ("8d-unknown", "rule 8d", set_key(sales_tree, "parent", "ghost")),
    ("8e", "rule 8e", make_cycle),
    ("8f", "rule 8f", set_key(sales_tree, "link", "causal")),
    ("8g", "rule 8g", drop_key(sales_tree, "reconciled_by")),
    ("8h-tolerance", "rule 8h", set_key(sales_tree, "tolerance", "1%")),
    ("8h-within", "rule 8h", set_key(sales_tree, "reconciled_by", "equals the sum within 1%")),
    ("8i", "rule 8i", drop_key(visits_tree, "check")),
    ("8j", "rule 8j", set_key(visits_tree, "evidence", "measured on one park")),
    ("9a", "rule 9a", set_key(lambda d: get(d, "sales")["type_params"], "fill_nulls_with", 0)),
    (
        "3a-type",
        "rule 3a: metric 'sales' lacks type or",
        drop_key(lambda d: get(d, "sales"), "type"),
    ),
    (
        "3a-type-params",
        "rule 3a: metric 'sales' lacks type_params",
        drop_key(lambda d: get(d, "sales"), "type_params"),
    ),
    ("3a-string-type-params", "rule 3a", set_key(lambda d: get(d, "sales"), "type_params", "x")),
    (
        "3c-source-models",
        "rule 3c: metric 'sales' has an empty source_models",
        set_key(sales_meta, "source_models", []),
    ),
    ("3d-list", "rule 3d", set_key(sales_meta, "clock", ["company date"])),
    ("3e-list", "rule 3e", set_key(sales_meta, "owner", ["the project owner"])),
    ("3f-dict", "rule 3f", set_key(sales_meta, "status", {"a": 1})),
    ("4a-numerator", "rule 4a", set_key(ratio_params, "numerator", "nope")),
    ("4a-denominator", "rule 4a", set_key(ratio_params, "denominator", "nope")),
    ("4a-input-metric", "rule 4a: metric 'north' references 'ghost_metric'", unknown_input_metric),
    ("5c-list", "rule 5c", set_key(sales_meta, "source_models", [["stg_park_snapshot"]])),
    (
        "6a-dimension-expr",
        "rule 6a: dimension 'flag'",
        set_key(lambda d: park_day(d)["dimensions"][0], "expr", "bogus_dim"),
    ),
    (
        "6a-entity-expr",
        "rule 6a: entity 'park'",
        set_key(lambda d: park_day(d)["entities"][1], "expr", "bogus_key"),
    ),
    (
        "6a-numerator-filter",
        "rule 6a: metric 'sales_per_visit' filters on",
        numerator_filters_on_unknown_dimension,
    ),
    (
        "6a-denominator-filter",
        "rule 6a: metric 'sales_per_visit' filters on",
        denominator_filters_on_unknown_dimension,
    ),
    ("8f-list", "rule 8f", set_key(sales_tree, "link", ["identity"])),
    ("9a-join", "rule 9a", set_key(sales_params, "join_to_timespine", True)),
    ("11a", "rule 11a", set_key(visits_link, "parent", "ghost")),
    ("11a-not-list", "rule 11a", set_key(visits_tree, "additional_links", "sales")),
    ("11b", "rule 11b", set_key(visits_link, "link", "identity")),
    ("11c", "rule 11c", set_key(visits_link, "parent", "north")),
    ("11d-claim", "rule 11d", drop_key(visits_link, "claim")),
    ("11e", "rule 11e", set_key(visits_link, "evidence", "measured on one park")),
    ("11f", "rule 11f", set_key(visits_tree, "additional_links", [EQUAL_LINK])),
    ("12a", "rule 12a: metric 'sales_per_visit'", threshold_on_supporting_metric),
    ("12b", "rule 12b", set_key(visits_threshold, "value", "98%")),
    ("12b-bool", "rule 12b", set_key(visits_threshold, "value", True)),
    ("12c", "rule 12c", drop_key(visits_threshold, "unit")),
    ("12d", "rule 12d", set_key(visits_threshold, "direction", "roughly")),
    ("12e", "rule 12e", set_key(visits_threshold, "basis", "an industry norm")),
    ("12f", "rule 12f", drop_key(lambda d: meta(d, "guest_visits"), "guardrail_threshold")),
]

RAW_CASES = [
    ("1b", "rule 1b", "semantic_models: [\n"),
    ("1c", "rule 1c", "semantic_models: []\nmetrics: []\nmetrics: []\n"),
    ("1d", "rule 1d", "semantic_models: []\nmetrics: []\nextra: 1\n"),
]


def test_clean_small_catalog_passes(tmp_path: Path) -> None:
    assert problems_for(tmp_path, base_catalog()) == []


@pytest.mark.parametrize(("case", "needle", "mutate"), CASES, ids=[c[0] for c in CASES])
def test_each_planted_fault_is_named(
    tmp_path: Path, case: str, needle: str, mutate: Callable[[Doc], None]
) -> None:
    doc = base_catalog()
    mutate(doc)

    assert any(needle in line for line in problems_for(tmp_path, doc)), case


@pytest.mark.parametrize(("case", "needle", "text"), RAW_CASES, ids=[c[0] for c in RAW_CASES])
def test_each_loading_fault_is_named(tmp_path: Path, case: str, needle: str, text: str) -> None:
    problems = find_problems(write_root(tmp_path, text), EXPECTED)

    assert any(needle in line for line in problems), case


def test_a_capitalized_observational_passes_rule_8j(tmp_path: Path) -> None:
    doc = base_catalog()
    visits_tree(doc)["evidence"] = "Observational: one park"

    assert problems_for(tmp_path, doc) == []


def test_an_at_most_threshold_with_a_whole_number_passes(tmp_path: Path) -> None:
    doc = base_catalog()
    visits_threshold(doc).update(value=10, direction="at most")

    assert problems_for(tmp_path, doc) == []


def test_a_list_role_is_rejected_naming_the_metric(tmp_path: Path) -> None:
    doc = base_catalog()
    sales_meta(doc)["role"] = ["tree"]
    del sales_meta(doc)["tree"]

    assert any("rule 3g: metric 'sales'" in line for line in problems_for(tmp_path, doc))


def test_missing_file_is_rule_1a(tmp_path: Path) -> None:
    assert find_problems(tmp_path, EXPECTED) == ["metrics/: rule 1a: no catalog file"]


def test_main_exits_one_and_prints_a_line_per_problem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_root(tmp_path, json.dumps(base_catalog()))

    assert main([str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "rule 2d" in err  # the small catalog is not the 39 committed names


def test_committed_catalog_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert find_problems(REPO) == []
    assert main([str(REPO)]) == 0
    assert "passes every house rule" in capsys.readouterr().out


def test_expected_names_are_the_thirty_nine_of_the_brief() -> None:
    assert len(check_metric_catalog.EXPECTED_METRICS) == 39

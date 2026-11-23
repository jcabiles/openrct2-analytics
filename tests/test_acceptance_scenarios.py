"""Behavioral tests for docs/acceptance/scenarios.yml, on the real file and the real catalog.

The scenario rules live here only; the catalog stays the one source of units, clocks and source
models. Each rule has a planted fault:
a temporary YAML file (a JSON document is valid YAML) built from the real one, loaded the same way.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from dbt.clients.checked_load import checked_load

from check_metric_catalog import load_catalog
from metric_catalog_yaml import Map, as_list, as_map, as_text, maps, meta_of

Doc = dict[str, Any]
REPO = Path(__file__).resolve().parent.parent
SCENARIOS = REPO / "docs" / "acceptance" / "scenarios.yml"
KEYS = {
    "id",
    "process",
    "question",
    "metrics",
    "unit",
    "clock",
    "parks",
    "grain",
    "correct_answer_form",
    "observational",
}
PROCESSES = {"finance", "admissions", "ride_operations", "stall_sales", "company"}
PARKS = {"one", "both", "company"}
STALL_METRICS = {
    "stall_profit",
    "stall_units_sold",
    "food_drink_revenue_by_item",
    "merchandise_revenue_by_item",
}
SOURCES = {
    "finance": {"stg_finance_month", "fct_park_month"},
    "admissions": {"stg_park_snapshot"},
    "ride_operations": {"stg_ride_snapshot", "stg_guest_boarded"},
    "stall_sales": {"stg_ride_snapshot"},
}
WEATHER = re.compile(r"weather|umbrella|temperature", re.IGNORECASE)
UMBRELLA_METRIC: Doc = {
    "name": "umbrella_sales",
    "label": "Umbrella sales",
    "config": {
        "meta": {"unit": "usd", "clock": "company date", "source_models": ["stg_ride_snapshot"]}
    },
}


def load_file(path: Path) -> Doc:
    """Load a scenarios file with dbt's own YAML loader."""
    data, failures = checked_load(path.read_text(encoding="utf-8"))
    assert failures == []
    return as_map(data)


def real_metrics() -> list[Map]:
    """Return the real catalog's metrics, failing if the catalog does not load."""
    catalog, problems = load_catalog(REPO)
    assert catalog is not None and problems == []
    return catalog.metrics


def sources_of(metric: Map) -> set[str]:
    """Return the source models a metric lists under `config.meta.source_models`."""
    return {as_text(name) for name in as_list(meta_of(metric).get("source_models"))}


def find_problems(doc: Doc, metrics: list[Map]) -> list[str]:
    """Return one line per broken rule, each naming the scenario or `coverage`."""
    problems: list[str] = []
    by_name = {as_text(m.get("name")): m for m in metrics}
    scenarios = list(maps(doc.get("scenarios")))
    if not as_text(doc.get("about")):
        problems.append("file: `about` is missing")
    if not 12 <= len(scenarios) <= 14:
        problems.append(f"coverage: {len(scenarios)} scenarios; need 12 to 14")
    ids = [as_text(s.get("id")) for s in scenarios]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"{dup}: duplicate id")
    for scenario in scenarios:
        problems += scenario_problems(scenario, by_name)
    return problems + coverage_problems(scenarios)


def scenario_problems(scenario: Map, by_name: dict[str, Map]) -> list[str]:
    """Return the problems of one scenario against the catalog."""
    sid = as_text(scenario.get("id")).strip() or "<no id>"
    found = [f"{sid}: missing key {key}" for key in sorted(KEYS - set(scenario))]
    found += [
        f"{sid}: {key} must be non-empty text"
        for key in ("id", "question", "grain", "correct_answer_form")
        if key in scenario and not as_text(scenario.get(key)).strip()
    ]
    if scenario.get("observational") is not True and "observational" in scenario:
        found.append(f"{sid}: observational must be true")
    if scenario.get("process") not in PROCESSES:
        found.append(
            f"{sid}: process {scenario.get('process')!r} is not one of {sorted(PROCESSES)}"
        )
    if scenario.get("parks") not in PARKS:
        found.append(f"{sid}: parks {scenario.get('parks')!r} is not one of {sorted(PARKS)}")
    cited = [as_text(n) for n in as_list(scenario.get("metrics"))]
    guards = [as_text(n) for n in as_list(scenario.get("guardrails"))]
    if not cited:
        found.append(f"{sid}: no metrics cited")
    for name in cited + guards:
        if name not in by_name:
            found.append(f"{sid}: metric {name} is not in the catalog")
    known = [by_name[n] for n in cited if n in by_name]
    found += cited_problems(sid, scenario, known)
    for name in guards:
        if name in by_name and WEATHER.search(f"{name} {as_text(by_name[name].get('label'))}"):
            found.append(f"{sid}: weather rule: guardrail {name} is a weather metric")
    return found + process_problems(sid, as_text(scenario.get("process")), cited, known)


def cited_problems(sid: str, scenario: Map, known: list[Map]) -> list[str]:
    """Check the units and clocks of the cited metrics, and the weather rule, for one scenario."""
    found: list[str] = []
    for metric in known:
        meta, name = meta_of(metric), as_text(metric.get("name"))
        for field in ("unit", "clock"):
            if meta.get(field) != scenario.get(field):
                found.append(
                    f"{sid}: {field} {scenario.get(field)!r} but {name} has {meta.get(field)!r}"
                )
        if WEATHER.search(f"{name} {as_text(metric.get('label'))}"):
            found.append(f"{sid}: weather rule: metric {name} is a weather metric")
    for field in ("question", "correct_answer_form"):
        if WEATHER.search(as_text(scenario.get(field))):
            found.append(f"{sid}: weather rule: {field} names weather, umbrella or temperature")
    return found


def process_problems(sid: str, process: str, cited: list[str], known: list[Map]) -> list[str]:
    """Check that a scenario's metrics read the source models of its process."""
    if process not in SOURCES:
        return []
    found: list[str] = []
    if not any(sources_of(m) & SOURCES[process] for m in known):
        found.append(f"{sid}: process {process}: no cited metric reads {sorted(SOURCES[process])}")
    stall = [n for n in cited if n in STALL_METRICS]
    if process == "stall_sales" and not stall:
        found.append(f"{sid}: process stall_sales: no cited metric is a stall metric")
    if process == "ride_operations" and len(stall) == len(cited):
        found.append(f"{sid}: process ride_operations: every cited metric is a stall metric")
    return found


def coverage_problems(scenarios: list[Map]) -> list[str]:
    """Check the coverage rules across the whole set."""
    found = [
        f"coverage: fewer than two {process} scenarios"
        for process in sorted(SOURCES)
        if sum(s.get("process") == process for s in scenarios) < 2
    ]
    cites = [(s, [as_text(n) for n in as_list(s.get("metrics"))]) for s in scenarios]
    north = [s for s, names in cites if "operating_profit" in names]
    if not north:
        found.append("coverage: no north-star scenario citing operating_profit")
    if not any(
        {"guest_visits", "average_park_rating"} <= set(as_list(s.get("guardrails"))) for s in north
    ):
        found.append(
            "coverage: no north-star scenario with guest_visits and average_park_rating guardrails"
        )
    if not any(s.get("parks") == "both" for s in scenarios):
        found.append("coverage: no scenario with parks: both")
    if not any(
        n.startswith("company_") and n.endswith("_yoy") for _, names in cites for n in names
    ):
        found.append("coverage: no scenario cites a company year-over-year (company_*_yoy) metric")
    return found


def write(tmp_path: Path, doc: Doc) -> Doc:
    """Write doc as a temporary scenarios file and load it back the way the real file is loaded."""
    path = tmp_path / "scenarios.yml"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return load_file(path)


def scenario(doc: Doc, sid: str) -> Doc:
    """Return the scenario with this id from a loaded document."""
    return next(s for s in doc["scenarios"] if s["id"] == sid)


def drop(doc: Doc, *ids: str) -> None:
    """Remove scenarios from a document in place."""
    doc["scenarios"] = [s for s in doc["scenarios"] if s["id"] not in ids]


def test_real_file_passes_every_rule() -> None:
    assert find_problems(load_file(SCENARIOS), real_metrics()) == []


def test_real_catalog_passes_the_weather_rule() -> None:
    names = [f"{m.get('name')} {m.get('label')}" for m in real_metrics()]
    assert [n for n in names if WEATHER.search(n)] == []


def test_real_scenarios_never_name_tenths_or_weather() -> None:
    text = json.dumps(load_file(SCENARIOS)["scenarios"])
    assert "tenth" not in text.lower()
    assert not WEATHER.search(text)


Edit = Callable[[Doc], None]
CASES: dict[str, tuple[str, Edit]] = {}


def fault(name: str, expect: str) -> Callable[[Edit], Edit]:
    """Register a planted fault: an edit of the loaded doc, and the message it must raise."""

    def register(edit: Edit) -> Edit:
        CASES[name] = (expect, edit)
        return edit

    return register


@fault("duplicate id", "AS-01: duplicate id")
def _duplicate(doc: Doc) -> None:
    scenario(doc, "AS-02")["id"] = "AS-01"


@fault("unknown metric", "AS-03: metric no_such_metric is not in the catalog")
def _unknown(doc: Doc) -> None:
    scenario(doc, "AS-03")["metrics"] = ["no_such_metric"]


@fault("wrong unit", "AS-01: unit 'count' but operating_profit has 'usd'")
def _unit(doc: Doc) -> None:
    scenario(doc, "AS-01")["unit"] = "count"


@fault("wrong clock", "AS-01: clock 'wall-clock hour' but operating_profit has 'company date'")
def _clock(doc: Doc) -> None:
    scenario(doc, "AS-01")["clock"] = "wall-clock hour"


@fault("missing observational", "AS-04: missing key observational")
def _observational(doc: Doc) -> None:
    del scenario(doc, "AS-04")["observational"]


@fault("coverage short by one process", "coverage: fewer than two stall_sales scenarios")
def _short_process(doc: Doc) -> None:
    drop(doc, "AS-11", "AS-12")


@fault("process mismatch", "AS-03: process finance: no cited metric reads")
def _mismatch(doc: Doc) -> None:
    scenario(doc, "AS-03").update(metrics=["guest_visits"], unit="count")


@fault("mixed unit across citations", "AS-03: unit 'usd' but guest_visits has 'count'")
def _mixed(doc: Doc) -> None:
    scenario(doc, "AS-03")["metrics"] = ["operating_profit", "guest_visits"]


@fault("no two-park scenario", "coverage: no scenario with parks: both")
def _no_both(doc: Doc) -> None:
    for sid in ("AS-02", "AS-04", "AS-06"):
        scenario(doc, sid)["parks"] = "one"


@fault("no year-over-year scenario", "coverage: no scenario cites a company year-over-year")
def _no_yoy(doc: Doc) -> None:
    drop(doc, "AS-06", "AS-13", "AS-14")


@fault(
    "only a same-park year-over-year scenario", "coverage: no scenario cites a company year-over"
)
def _same_park_yoy_only(doc: Doc) -> None:
    drop(doc, "AS-13", "AS-14")


@fault("no guardrail scenario", "coverage: no north-star scenario with guest_visits")
def _no_guardrail(doc: Doc) -> None:
    del scenario(doc, "AS-01")["guardrails"]


@fault("eleven scenarios", "coverage: 11 scenarios; need 12 to 14")
def _eleven(doc: Doc) -> None:
    drop(doc, "AS-03", "AS-05", "AS-09")


@fault("fifteen scenarios", "coverage: 15 scenarios; need 12 to 14")
def _fifteen(doc: Doc) -> None:
    doc["scenarios"].append(copy.deepcopy(scenario(doc, "AS-03")) | {"id": "AS-15"})


@fault(
    "stall_sales citing no stall metric", "AS-10: process stall_sales: no cited metric is a stall"
)
def _no_stall(doc: Doc) -> None:
    scenario(doc, "AS-10").update(metrics=["ride_profit"])


@fault("ride_operations citing only stall metrics", "AS-07: process ride_operations: every cited")
def _only_stall(doc: Doc) -> None:
    scenario(doc, "AS-07").update(metrics=["stall_profit"])


@fault("weather word in a question", "AS-05: weather rule: question")
def _weather_question(doc: Doc) -> None:
    scenario(doc, "AS-05")["question"] = "Did the weather lift our average park rating?"


@fault("observational false", "AS-04: observational must be true")
def _not_observational(doc: Doc) -> None:
    scenario(doc, "AS-04")["observational"] = False


@fault("temperature word in a question", "AS-05: weather rule: question")
def _temperature_question(doc: Doc) -> None:
    scenario(doc, "AS-05")["question"] = "Did the temperature lift our average park rating?"


@fault("about deleted", "file: `about` is missing")
def _no_about(doc: Doc) -> None:
    del doc["about"]


@fault("parks value outside the set", "AS-02: parks 'pair' is not one of")
def _bad_parks(doc: Doc) -> None:
    scenario(doc, "AS-02")["parks"] = "pair"


@fault("empty question", "AS-03: question must be non-empty text")
def _empty_question(doc: Doc) -> None:
    scenario(doc, "AS-03")["question"] = ""


@fault("blank id", "<no id>: id must be non-empty text")
def _blank_id(doc: Doc) -> None:
    scenario(doc, "AS-03")["id"] = "  "


@fault("unknown guardrail", "AS-01: metric no_such_guardrail is not in the catalog")
def _guardrail(doc: Doc) -> None:
    scenario(doc, "AS-01")["guardrails"] = ["guest_visits", "no_such_guardrail"]


@pytest.mark.parametrize("name", sorted(CASES))
def test_planted_fault_fails_naming_the_rule(name: str, tmp_path: Path) -> None:
    expect, edit = CASES[name]
    doc = load_file(SCENARIOS)
    edit(doc)
    problems = find_problems(write(tmp_path, doc), real_metrics())
    assert any(expect in p for p in problems), problems


def test_a_weather_metric_in_the_catalog_fails(tmp_path: Path) -> None:
    doc = load_file(SCENARIOS)
    scenario(doc, "AS-12")["metrics"] = ["food_drink_revenue_by_item", "umbrella_sales"]
    problems = find_problems(write(tmp_path, doc), [*real_metrics(), UMBRELLA_METRIC])
    assert "AS-12: weather rule: metric umbrella_sales is a weather metric" in problems


def test_a_weather_metric_as_a_guardrail_fails(tmp_path: Path) -> None:
    doc = load_file(SCENARIOS)
    scenario(doc, "AS-12")["guardrails"] = ["umbrella_sales"]
    problems = find_problems(write(tmp_path, doc), [*real_metrics(), UMBRELLA_METRIC])
    assert "AS-12: weather rule: guardrail umbrella_sales is a weather metric" in problems

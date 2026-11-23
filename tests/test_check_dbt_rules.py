"""Behavioral tests for scripts/check_dbt_rules.py, on real temporary dbt project folders.

Every rule (a) to (e) has a planted violation and a passing form. A JSON document is valid YAML, so
the model files are built as Python dicts and written with json.dumps. The real contracts are copied
into each folder, because the rules read them.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import check_dbt_rules
from check_dbt_rules import main
from dbt_rules import (
    ENVELOPE_MODEL,
    REPEAT_TEST,
    Project,
    check_contract,
    check_descriptions,
    check_repeat_test,
    check_required_tests,
    column_for,
    envelope_required,
)
from openrct2_analytics.ingest.contracts import (
    Field,
    load_envelope,
    load_fields,
    read_contract_version,
)

Doc = dict[str, Any]
REPO = Path(__file__).resolve().parent.parent
CONTRACTS = REPO / "contracts"
FIELDS: dict[str, list[Field]] = load_fields(CONTRACTS)
ENVELOPE_FIELDS: list[Field] = load_envelope(CONTRACTS)
CLEAN = "Rows of this model; no unit, no clock."
STAGING = "models/staging"
SESSION_YAML = f"{STAGING}/stg_session_start.yml"
ENVELOPE_YAML = f"{STAGING}/{ENVELOPE_MODEL}.yml"
ENVELOPE_SQL = f"{STAGING}/{ENVELOPE_MODEL}.sql"
MART_YAML = "models/marts/fct_guest_day.yml"


def version(contract: str) -> str:
    return read_contract_version((CONTRACTS / f"{contract}.odcs.yaml").read_text(encoding="utf-8"))


def repeat_test(source: str) -> Doc:
    return {REPEAT_TEST: {"arguments": {"source_relation": f"source('landing', '{source}')"}}}


def good_model(event_type: str) -> Doc:
    """A staging model that breaks no rule."""
    columns = [
        {
            "name": column_for(field.name),
            "description": CLEAN,
            "data_tests": (["not_null"] if field.required else [])
            + (["unique"] if field.name == "event_id" else []),
        }
        for field in FIELDS[event_type]
    ]
    return {
        "name": f"stg_{event_type}",
        "description": CLEAN,
        "meta": {"contract_version": version(event_type)},
        "data_tests": [repeat_test(event_type)],
        "columns": columns,
    }


def good_envelope() -> Doc:
    """A `stg_envelope` that breaks no rule."""
    columns = [
        {"name": f.name, "description": CLEAN, "data_tests": ["not_null"] if f.required else []}
        for f in ENVELOPE_FIELDS
    ]
    return {
        "name": ENVELOPE_MODEL,
        "description": CLEAN,
        "meta": {"contract_version": version("envelope")},
        "data_tests": [repeat_test("plugin_stats")],
        "columns": columns,
    }


def envelope_sql(types: list[str]) -> str:
    return "\nunion all\n".join(
        f"select event_id from {{{{ source('landing', '{t}') }}}}" for t in types
    )


def mart(description: str = CLEAN, column_description: str = CLEAN) -> Doc:
    return {
        "name": "fct_guest_day",
        "description": description,
        "columns": [{"name": "park_id", "description": column_description}],
    }


def column_of(model: Doc, name: str) -> Doc:
    return next(column for column in model["columns"] if column["name"] == name)


def build(
    root: Path,
    yaml: dict[str, list[Doc]] | None = None,
    sql: dict[str, str] | None = None,
    fields: dict[str, list[Field]] | None = None,
) -> Project:
    """Write a project folder under root and load it the way the script does."""
    shutil.copytree(CONTRACTS, root / "contracts")
    for name, specs in (yaml or {}).items():
        write(root / name, json.dumps({"version": 2, "models": specs}))
    for name, text in (sql or {}).items():
        write(root / name, text)
    models, problems = check_dbt_rules.load_models(root)
    assert problems == []
    return Project(root, models, fields or FIELDS)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fails(problems: list[str], path: str, rule: str, text: str) -> None:
    """Assert there is exactly one problem, naming the file and the rule and containing text."""
    assert len(problems) == 1, problems
    assert problems[0].startswith(f"{path}: rule {rule}: ")
    assert text in problems[0]


def test_the_repo_passes_every_rule(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(REPO)]) == 0
    assert "passes every house rule" in capsys.readouterr().out


def test_a_planted_violation_exits_one_and_names_the_file_and_rule(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    model = good_model("session_start")
    model["description"] = "No statements here."
    build(tmp_path, {SESSION_YAML: [model]})
    assert main([str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert f"{SESSION_YAML}: rule b: " in err
    assert "check_dbt_rules: 2 problem(s)." in err


def test_a_yaml_file_that_does_not_load_is_reported(tmp_path: Path) -> None:
    shutil.copytree(CONTRACTS, tmp_path / "contracts")
    write(tmp_path / MART_YAML, "models: [unclosed")
    _, problems = check_dbt_rules.load_models(tmp_path)
    assert len(problems) == 1
    assert problems[0].startswith(f"{MART_YAML}: does not load: ")


def test_every_contracted_type_and_the_envelope_pass(tmp_path: Path) -> None:
    models = [good_model(event_type) for event_type in FIELDS]
    project = build(
        tmp_path,
        {f"{STAGING}/stg_all.yml": [*models, good_envelope()], MART_YAML: [mart()]},
        {ENVELOPE_SQL: envelope_sql(sorted(FIELDS))},
    )
    assert [rule(project) for rule in check_dbt_rules.RULES] == [[]] * len(check_dbt_rules.RULES)


def test_a_staging_model_that_is_not_an_event_type_or_the_envelope_fails(tmp_path: Path) -> None:
    skeleton = {"name": "stg_not_an_event_type", "description": "No statements.", "columns": []}
    path = f"{STAGING}/stg_not_an_event_type.yml"
    project = build(tmp_path, {path: [skeleton]})
    fails(
        check_required_tests(project), path, "a", "neither stg_<contracted type> nor stg_envelope"
    )
    assert len(check_descriptions(project)) == 2
    for rule in (check_contract, check_repeat_test):
        assert rule(project) == []
    sources = {"version": 2, "sources": [{"name": "landing", "description": "No statements."}]}
    write(tmp_path / f"{STAGING}/_sources.yml", json.dumps(sources))
    models, problems = check_dbt_rules.load_models(tmp_path)
    assert (len(models), problems) == (1, [])


def test_a_staging_sql_with_an_unstaged_name_fails_once(tmp_path: Path) -> None:
    path = f"{STAGING}/stg_helper.sql"
    project = build(tmp_path, sql={path: "select 1 as x"})
    fails(check_required_tests(project), path, "a", "neither stg_<contracted type>")


@pytest.mark.parametrize(
    "path", ["models/marts/fct_guest_day.sql", f"{STAGING}/stg_session_start.sql"]
)
def test_a_model_sql_without_a_yaml_entry_fails(tmp_path: Path, path: str) -> None:
    project = build(tmp_path, sql={path: "select 1 as x"})
    fails(check_required_tests(project), path, "a", f"{Path(path).stem} has no YAML entry")


# Rule a: required tests.


def test_column_for_maps_tenths_to_usd_and_value_tenths_to_itself() -> None:
    assert column_for("cash_tenths") == "cash_usd"
    assert column_for("value_tenths") == "value_tenths"
    assert column_for("park_id") == "park_id"


def test_envelope_required_is_the_required_envelope_fields() -> None:
    assert envelope_required(FIELDS) == [f.name for f in ENVELOPE_FIELDS if f.required]


@pytest.mark.parametrize(
    ("event_type", "column"),
    [("finance_month", "cash_usd"), ("session_start", "_raw_line"), ("park_snapshot", "park_id")],
)
def test_rule_a_a_required_column_without_not_null_fails(
    tmp_path: Path, event_type: str, column: str
) -> None:
    model = good_model(event_type)
    column_of(model, column)["data_tests"] = []
    project = build(tmp_path, {SESSION_YAML: [model]})
    fails(check_required_tests(project), SESSION_YAML, "a", f"lacks not_null on {column}")


def test_rule_a_not_null_in_the_dict_form_and_the_tests_key_counts(tmp_path: Path) -> None:
    model = good_model("session_start")
    column_of(model, "park_id")["data_tests"] = [{"not_null": {"config": {"severity": "error"}}}]
    column_of(model, "seq")["tests"] = ["not_null"]
    column_of(model, "seq")["data_tests"] = []
    assert check_required_tests(build(tmp_path, {SESSION_YAML: [model]})) == []


SWITCHED_OFF = [
    pytest.param({"enabled": False}, id="disabled"),
    pytest.param({"severity": "warn"}, id="warn"),
    pytest.param({"where": "1 = 0"}, id="where"),
]


@pytest.mark.parametrize("where", ["config", "top level"])
@pytest.mark.parametrize("settings", SWITCHED_OFF)
@pytest.mark.parametrize("test", ["not_null", "unique"])
def test_rule_a_a_required_test_that_is_switched_off_does_not_count(
    tmp_path: Path, test: str, settings: Doc, where: str
) -> None:
    model = good_model("session_start")
    args = {"config": settings} if where == "config" else dict(settings)
    column = "park_id" if test == "not_null" else "event_id"
    tests = column_of(model, column)["data_tests"]
    tests[tests.index(test)] = {test: args}
    problems = check_required_tests(build(tmp_path, {SESSION_YAML: [model]}))
    fails(problems, SESSION_YAML, "a", f"lacks {test} on {column}")


def test_rule_a_a_required_column_missing_from_the_yaml_fails(tmp_path: Path) -> None:
    model = good_model("session_start")
    model["columns"] = [c for c in model["columns"] if c["name"] != "session_id"]
    project = build(tmp_path, {SESSION_YAML: [model]})
    fails(check_required_tests(project), SESSION_YAML, "a", "lacks not_null on session_id")


def test_rule_a_an_event_type_model_without_unique_event_id_fails(tmp_path: Path) -> None:
    model = good_model("session_start")
    column_of(model, "event_id")["data_tests"] = ["not_null"]
    project = build(tmp_path, {SESSION_YAML: [model]})
    fails(check_required_tests(project), SESSION_YAML, "a", "lacks unique on event_id")


def test_rule_a_value_tenths_maps_to_itself_when_required(tmp_path: Path) -> None:
    contracts = tmp_path / "patched"
    shutil.copytree(CONTRACTS, contracts)
    path = contracts / "ride_snapshot.odcs.yaml"
    marker = "name: value_tenths\n        logicalType: integer\n        physicalType: BIGINT\n"
    text = path.read_text(encoding="utf-8")
    assert marker + "        required: false" in text
    path.write_text(
        text.replace(marker + "        required: false", marker + "        required: true")
    )
    fields = load_fields(contracts)
    model = good_model("ride_snapshot")
    model["columns"].append({"name": "value_tenths", "description": CLEAN})
    yaml = {f"{STAGING}/stg_ride_snapshot.yml": [model]}
    project = build(tmp_path / "project", yaml, fields=fields)
    fails(
        check_required_tests(project),
        f"{STAGING}/stg_ride_snapshot.yml",
        "a",
        "lacks not_null on value_tenths",
    )


@pytest.mark.parametrize(
    ("column", "tests", "text"),
    [
        ("event_id", ["not_null", "unique"], "carries unique on event_id"),
        ("_raw_file", [], "lacks not_null on _raw_file"),
    ],
)
def test_rule_a_stg_envelope_needs_not_null_on_required_columns_and_no_unique(
    tmp_path: Path, column: str, tests: list[str], text: str
) -> None:
    envelope = good_envelope()
    column_of(envelope, column)["data_tests"] = tests
    project = build(tmp_path, {ENVELOPE_YAML: [envelope]})
    fails(check_required_tests(project), ENVELOPE_YAML, "a", text)


# Rule b: a unit statement and a clock statement in every description.

FAILING = [
    pytest.param("A plain description.", id="neither"),
    pytest.param("Count of rows; unit: rows.", id="unit only"),
    pytest.param("Count of rows; no unit.", id="no unit only"),
    pytest.param("A game day; clock: game day.", id="clock only"),
    pytest.param("A game day; no clock.", id="no clock only"),
    pytest.param("A count; unit: none; clock: game day.", id="unit none"),
    pytest.param("A count; unit: usd; clock: none.", id="clock none"),
    pytest.param("A count; unit: ; clock: game day.", id="unit without a word"),
    pytest.param("A count; unit: NONE; no clock.", id="unit none in capitals"),
    pytest.param("", id="empty"),
]
PASSING = [
    pytest.param("A count; no unit; no clock.", id="no unit, no clock"),
    pytest.param("A count; no unit; clock: game day.", id="no unit, clock"),
    pytest.param("Money; unit: usd; no clock.", id="unit, no clock"),
    pytest.param("Money; unit: usd; clock: company date.", id="unit, clock"),
    pytest.param("Money; UNIT: USD; CLOCK: Game Day.", id="capitals"),
    pytest.param(
        "Money, folded\n  over lines;\n  unit: tenths of\n  a dollar; clock: game day", id="folded"
    ),
]


def described(target: str, text: str) -> Doc:
    """A passing staging model whose model or one column description is text."""
    model = good_model("session_start")
    if target == "model":
        model["description"] = text
    else:
        column_of(model, "park_id")["description"] = text
    return model


@pytest.mark.parametrize("target", ["model", "column"])
@pytest.mark.parametrize("text", FAILING)
def test_rule_b_a_description_without_both_statements_fails(
    tmp_path: Path, target: str, text: str
) -> None:
    project = build(tmp_path, {SESSION_YAML: [described(target, text)]})
    problems = check_descriptions(project)
    assert problems
    assert all(p.startswith(f"{SESSION_YAML}: rule b: the description of ") for p in problems)
    label = "stg_session_start" if target == "model" else "stg_session_start.park_id"
    assert all(f"of {label} has no " in p for p in problems)


@pytest.mark.parametrize("target", ["model", "column"])
@pytest.mark.parametrize("text", PASSING)
def test_rule_b_a_description_with_both_statements_passes(
    tmp_path: Path, target: str, text: str
) -> None:
    project = build(tmp_path, {SESSION_YAML: [described(target, text)]})
    assert check_descriptions(project) == []


def test_rule_b_a_missing_description_fails_and_names_the_missing_statement(
    tmp_path: Path,
) -> None:
    model = good_model("session_start")
    del column_of(model, "park_id")["description"]
    problems = check_descriptions(build(tmp_path, {SESSION_YAML: [model]}))
    assert [p.split(" has no ")[1].split(" ")[0] for p in problems] == ["unit", "clock"]


@pytest.mark.parametrize(
    ("spec", "text"),
    [
        (mart(description="Money; unit: usd."), "description of fct_guest_day has no clock"),
        (mart(column_description="unit: usd."), "fct_guest_day.park_id has no clock"),
    ],
    ids=["model", "column"],
)
def test_rule_b_covers_every_model_outside_staging_whatever_its_name(
    tmp_path: Path, spec: Doc, text: str
) -> None:
    project = build(tmp_path, {MART_YAML: [spec]})
    fails(check_descriptions(project), MART_YAML, "b", text)


# Rule c: the contract version and the stg_envelope type list.


@pytest.mark.parametrize(("declared", "shown"), [("1.3.0", "'1.3.0'"), (None, "None")])
def test_rule_c_a_contract_version_that_differs_or_is_missing_fails(
    tmp_path: Path, declared: str | None, shown: str
) -> None:
    model = good_model("session_start")
    model["meta"] = {} if declared is None else {"contract_version": declared}
    project = build(tmp_path, {SESSION_YAML: [model]})
    text = f"{shown}; contracts/session_start.odcs.yaml is at {version('session_start')!r}"
    fails(check_contract(project), SESSION_YAML, "c", text)


def test_rule_c_config_meta_counts_when_meta_is_absent(tmp_path: Path) -> None:
    model = good_model("session_start")
    model["config"] = {"meta": model.pop("meta")}
    assert check_contract(build(tmp_path, {SESSION_YAML: [model]})) == []


def test_rule_c_stg_envelope_is_checked_against_the_envelope_contract(tmp_path: Path) -> None:
    envelope = good_envelope()
    envelope["meta"]["contract_version"] = "0.0.1"
    fails(
        check_contract(build(tmp_path, {ENVELOPE_YAML: [envelope]})),
        ENVELOPE_YAML,
        "c",
        "contracts/envelope.odcs.yaml",
    )


@pytest.mark.parametrize(
    ("types", "detail"),
    [
        (lambda t: [x for x in t if x != "plugin_stats"], "missing ['plugin_stats']"),
        (lambda t: [*t, "guest_exited"], "unexpected ['guest_exited']"),
        (
            lambda t: [*t, "finance_month"],
            f"listed {len(FIELDS) + 1} times for {len(FIELDS)} types",
        ),
    ],
    ids=["missing", "extra", "repeated"],
)
def test_rule_c_a_type_list_that_differs_fails(
    tmp_path: Path, types: Callable[[list[str]], list[str]], detail: str
) -> None:
    project = build(tmp_path, {}, {ENVELOPE_SQL: envelope_sql(types(sorted(FIELDS)))})
    fails(check_contract(project), ENVELOPE_SQL, "c", detail)


def test_rule_c_a_commented_out_source_does_not_count(tmp_path: Path) -> None:
    types = sorted(FIELDS)
    commented = envelope_sql(types[:-1]) + f"\n-- {envelope_sql(types[-1:])}\n"
    project = build(tmp_path, {}, {ENVELOPE_SQL: commented})
    fails(check_contract(project), ENVELOPE_SQL, "c", f"missing ['{types[-1]}']")


# Rule e: the R7 test applied.


def test_rule_e_an_event_type_model_without_the_test_fails(tmp_path: Path) -> None:
    model = good_model("session_start")
    model["data_tests"] = []
    fails(
        check_repeat_test(build(tmp_path, {SESSION_YAML: [model]})),
        SESSION_YAML,
        "e",
        f"does not apply {REPEAT_TEST}",
    )


@pytest.mark.parametrize("form", ["dict", "column"])
def test_rule_e_the_test_counts_in_each_form(tmp_path: Path, form: str) -> None:
    model = good_model("session_start")
    if form == "dict":
        model["data_tests"] = [
            {REPEAT_TEST: {"arguments": {"source_relation": "source('landing', 'session_start')"}}}
        ]
    else:
        model["data_tests"] = []
        column_of(model, "event_id")["data_tests"].append(repeat_test("session_start"))
    assert check_repeat_test(build(tmp_path, {SESSION_YAML: [model]})) == []


@pytest.mark.parametrize(
    ("tests", "text"),
    [
        ([repeat_test("session_start")], "to plugin_stats"),
        (["not_null"], f"does not apply {REPEAT_TEST}"),
    ],
    ids=["another source", "no test"],
)
def test_rule_e_stg_envelope_needs_the_test_for_plugin_stats(
    tmp_path: Path, tests: list[object], text: str
) -> None:
    envelope = good_envelope()
    envelope["data_tests"] = tests
    project = build(tmp_path, {ENVELOPE_YAML: [envelope]})
    fails(check_repeat_test(project), ENVELOPE_YAML, "e", text)

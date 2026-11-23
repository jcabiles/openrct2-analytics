"""Regression tests for dbt model files that have no matching YAML entry."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

import check_dbt_rules
from check_dbt_rules import main
from dbt_rules import (
    ENVELOPE_MODEL,
    Project,
    check_contract,
    check_forbidden,
    check_repeat_test,
    check_required_tests,
)
from openrct2_analytics.ingest.contracts import load_fields

REPO = Path(__file__).resolve().parent.parent
CONTRACTS = REPO / "contracts"
STAGING = "models/staging"
ENVELOPE_SQL = f"{STAGING}/{ENVELOPE_MODEL}.sql"
Doc = dict[str, Any]


def build(root: Path, yaml: dict[str, list[Doc]], sql: dict[str, str]) -> Project:
    """Create and load a real temporary project with the repository contracts."""
    shutil.copytree(CONTRACTS, root / "contracts")
    for name, specs in yaml.items():
        write(root / name, json.dumps({"version": 2, "models": specs}))
    for name, text in sql.items():
        write(root / name, text)
    models, problems = check_dbt_rules.load_models(root)
    assert problems == []
    return Project(root, models, load_fields(root / "contracts"))


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fails(problems: list[str], path: str, rule: str, text: str) -> None:
    """Assert one finding names the expected file, rule, and detail."""
    assert len(problems) == 1, problems
    assert problems[0].startswith(f"{path}: rule {rule}: ")
    assert text in problems[0]


def test_deleted_envelope_yaml_is_reported(tmp_path: Path) -> None:
    yaml_path = tmp_path / f"{STAGING}/{ENVELOPE_MODEL}.yml"
    project = build(
        tmp_path,
        {yaml_path.relative_to(tmp_path).as_posix(): [{"name": ENVELOPE_MODEL}]},
        {ENVELOPE_SQL: "select 1"},
    )
    yaml_path.unlink()
    models, problems = check_dbt_rules.load_models(tmp_path)
    assert problems == []
    project = Project(tmp_path, models, project.fields)

    fails(check_required_tests(project), ENVELOPE_SQL, "a", "has no YAML entry")


def test_yaml_less_contracted_type_sql_is_reported(tmp_path: Path) -> None:
    fields = load_fields(CONTRACTS)
    event_type = next(iter(fields))
    sql_path = f"{STAGING}/stg_{event_type}.sql"
    project = build(tmp_path, {}, {sql_path: "select 1"})

    fails(check_required_tests(project), sql_path, "a", "has no YAML entry")


def test_missing_envelope_sql_is_reported(tmp_path: Path) -> None:
    project = build(tmp_path, {}, {f"{STAGING}/stg_envelope_renamed.sql": "select 1"})

    fails(
        check_contract(project),
        ENVELOPE_SQL,
        "c",
        "stg_envelope.sql is missing",
    )


def test_repeat_test_requires_model_event_type_source(tmp_path: Path) -> None:
    fields = load_fields(CONTRACTS)
    event_type, other_type = list(fields)[:2]
    model_name = f"stg_{event_type}"
    path = f"{STAGING}/{model_name}.yml"
    project = build(
        tmp_path,
        {
            path: [
                {
                    "name": model_name,
                    "data_tests": [
                        {
                            "repeat_delivery_payload_differs": {
                                "arguments": {
                                    "source_relation": f"source('landing', '{other_type}')"
                                }
                            }
                        }
                    ],
                }
            ]
        },
        {},
    )

    fails(check_repeat_test(project), path, "e", f"without source {event_type}")


def test_envelope_repeat_test_requires_exact_plugin_stats_source(tmp_path: Path) -> None:
    path = f"{STAGING}/{ENVELOPE_MODEL}.yml"
    project = build(
        tmp_path,
        {
            path: [
                {
                    "name": ENVELOPE_MODEL,
                    "data_tests": [
                        {
                            "repeat_delivery_payload_differs": {
                                "arguments": {
                                    "source_relation": "source('landing', 'plugin_stats_old')"
                                }
                            }
                        }
                    ],
                }
            ]
        },
        {},
    )

    fails(check_repeat_test(project), path, "e", "to plugin_stats")


@pytest.mark.parametrize(
    ("model_kind", "test_form"),
    [
        ("event_type", "bare"),
        ("event_type", "config_only"),
        ("event_type", "arguments_without_source"),
        ("envelope", "bare"),
        ("envelope", "config_only"),
        ("envelope", "arguments_without_source"),
    ],
    ids=[
        "event_type-bare",
        "event_type-config_only",
        "event_type-arguments_without_source",
        "envelope-bare",
        "envelope-config_only",
        "envelope-arguments_without_source",
    ],
)
def test_repeat_test_requires_source_argument(
    tmp_path: Path, model_kind: str, test_form: str
) -> None:
    if model_kind == "event_type":
        event_type = next(iter(load_fields(CONTRACTS)))
        model_name = f"stg_{event_type}"
        detail = f"without source {event_type}"
    else:
        model_name = ENVELOPE_MODEL
        detail = "to plugin_stats"

    repeat_test: object
    if test_form == "bare":
        repeat_test = "repeat_delivery_payload_differs"
    elif test_form == "config_only":
        repeat_test = {"repeat_delivery_payload_differs": {"config": {"severity": "warn"}}}
    else:
        repeat_test = {"repeat_delivery_payload_differs": {"arguments": {}}}

    path = f"{STAGING}/{model_name}.yml"
    project = build(
        tmp_path,
        {path: [{"name": model_name, "data_tests": [repeat_test]}]},
        {},
    )

    fails(check_repeat_test(project), path, "e", detail)


@pytest.mark.parametrize(
    ("model_name", "source_type"),
    [("event_type", "event_type"), (ENVELOPE_MODEL, "plugin_stats")],
)
def test_repeat_test_accepts_correct_source(
    tmp_path: Path, model_name: str, source_type: str
) -> None:
    if model_name == "event_type":
        event_type = next(iter(load_fields(CONTRACTS)))
        model_name = f"stg_{event_type}"
        source_type = event_type
    path = f"{STAGING}/{model_name}.yml"
    project = build(
        tmp_path,
        {
            path: [
                {
                    "name": model_name,
                    "data_tests": [
                        {
                            "repeat_delivery_payload_differs": {
                                "arguments": {
                                    "source_relation": f"source('landing', '{source_type}')"
                                }
                            }
                        }
                    ],
                }
            ]
        },
        {},
    )

    assert check_repeat_test(project) == []


@pytest.mark.parametrize(
    "text",
    [
        "select distinct * from {{ source('landing', 'session_start') }}",
        "select s.* from {{ source('landing', 'session_start') }} s",
        "select * exclude (x) from {{ source('landing', 'session_start') }}",
        "select * replace (x as y) from {{ source('landing', 'session_start') }}",
    ],
    ids=["distinct", "qualified", "exclude", "replace"],
)
def test_forbidden_select_star_forms_from_source_fail(tmp_path: Path, text: str) -> None:
    path = f"{STAGING}/stg_x.sql"
    project = build(tmp_path, {}, {path: text})

    fails(check_forbidden(project), path, "d", "select * from a source()")


@pytest.mark.parametrize(
    "text",
    [
        "with final as (select a from {{ source('landing', 'session_start') }})\n"
        "select * from final",
        "select event_id, emitted_at from {{ source('landing', 'session_start') }}",
    ],
    ids=["star from cte", "named source columns"],
)
def test_forbidden_select_forms_without_source_star_pass(tmp_path: Path, text: str) -> None:
    project = build(tmp_path, {}, {f"{STAGING}/stg_x.sql": text})

    assert check_forbidden(project) == []


def test_dependencies_yml_fails_rule_d(tmp_path: Path) -> None:
    project = build(tmp_path, {}, {})
    write(tmp_path / "dependencies.yml", "packages: []\n")

    fails(check_forbidden(project), "dependencies.yml", "d", "not allowed")


def test_repo_passes_every_rule(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(REPO)]) == 0
    assert "passes every house rule" in capsys.readouterr().out

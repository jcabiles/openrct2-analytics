"""The dbt rules cover the park registry reference feed."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import check_dbt_rules
from dbt_rules import Project, check_contract, check_repeat_test, check_required_tests
from openrct2_analytics.ingest.contracts import load_reference_fields, read_contract_version

REPO = Path(__file__).resolve().parent.parent
FEED = REPO / "contracts" / "reference" / "park_registry.odcs.yaml"
REGISTRY = "models/staging/stg_park_registry.yml"
SQL = "models/staging/stg_park_registry.sql"
FIELDS = load_reference_fields(FEED.parent)["park_registry"]
LABEL_FEED = REPO / "contracts" / "reference" / "session_play_mode.odcs.yaml"
LABEL_REGISTRY = "models/staging/stg_session_play_mode.yml"
LABEL_FIELDS = load_reference_fields(FEED.parent)["session_play_mode"]


def make_project(root: Path) -> tuple[Project, dict[str, Any]]:
    contract = root / "contracts" / "reference" / FEED.name
    contract.parent.mkdir(parents=True)
    shutil.copyfile(FEED, contract)
    columns = [
        {
            "name": field.name,
            "description": "A feed field; no unit, no clock.",
            "data_tests": ["not_null"] if field.required else [],
        }
        for field in FIELDS
    ]
    spec: dict[str, Any] = {
        "name": "stg_park_registry",
        "description": "Registry feed rows; no unit, no clock.",
        "meta": {"contract_version": read_contract_version(FEED.read_text(encoding="utf-8"))},
        "columns": columns,
    }
    path = root / REGISTRY
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 2, "models": [spec]}), encoding="utf-8")
    sql = root / SQL
    sql.write_text("select park_id from registry", encoding="utf-8")
    models, problems = check_dbt_rules.load_models(root)
    assert problems == []
    return Project(root, models, {}), spec


def test_registry_model_with_feed_tests_and_version_passes(tmp_path: Path) -> None:
    project, _ = make_project(tmp_path)

    assert check_required_tests(project) == []
    assert check_contract(project) == []
    assert check_repeat_test(project) == []


def test_registry_version_mismatch_fails_rule_c(tmp_path: Path) -> None:
    project, spec = make_project(tmp_path)
    contract = tmp_path / "contracts" / "reference" / FEED.name
    contract.write_text(
        contract.read_text(encoding="utf-8").replace("version: 1.0.0", "version: 9.9.9"),
        encoding="utf-8",
    )

    problems = check_contract(project)

    assert len(problems) == 1
    assert problems[0].startswith(f"{REGISTRY}: rule c: ")
    assert "contracts/reference/park_registry.odcs.yaml" in problems[0]


def test_registry_missing_required_not_null_fails_rule_a(tmp_path: Path) -> None:
    project, spec = make_project(tmp_path)
    required = next(field for field in FIELDS if field.required)
    column = next(column for column in spec["columns"] if column["name"] == required.name)
    column["data_tests"] = []
    (tmp_path / REGISTRY).write_text(json.dumps({"version": 2, "models": [spec]}), encoding="utf-8")
    models, problems = check_dbt_rules.load_models(tmp_path)
    assert problems == []
    project = Project(project.root, models, project.fields)

    problems = check_required_tests(project)

    assert len(problems) == 1
    assert problems[0].startswith(f"{REGISTRY}: rule a: ")
    assert f"lacks not_null on {required.name}" in problems[0]


def make_label_project(root: Path) -> tuple[Project, dict[str, Any]]:
    """A project holding only `stg_session_play_mode`, with `session_play_mode`'s own contract."""
    contract = root / "contracts" / "reference" / LABEL_FEED.name
    contract.parent.mkdir(parents=True)
    shutil.copyfile(LABEL_FEED, contract)
    # The registry contract is absent: a model read against it would fail to load it.
    spec: dict[str, Any] = {
        "name": "stg_session_play_mode",
        "description": "Label feed rows; no unit, no clock.",
        "meta": {"contract_version": read_contract_version(LABEL_FEED.read_text(encoding="utf-8"))},
        "columns": [
            {
                "name": field.name,
                "description": "A feed field; no unit, no clock.",
                "data_tests": ["not_null"] if field.required else [],
            }
            for field in LABEL_FIELDS
        ],
    }
    path = root / LABEL_REGISTRY
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 2, "models": [spec]}), encoding="utf-8")
    (root / "models/staging/stg_session_play_mode.sql").write_text("select 1", encoding="utf-8")
    models, problems = check_dbt_rules.load_models(root)
    assert problems == []
    return Project(root, models, {}), spec


def test_label_model_with_its_own_contract_tests_and_version_passes(tmp_path: Path) -> None:
    project, _ = make_label_project(tmp_path)

    assert check_required_tests(project) == []
    assert check_contract(project) == []


def test_label_missing_column_of_its_own_contract_fails_rule_a(tmp_path: Path) -> None:
    project, spec = make_label_project(tmp_path)
    column = next(column for column in spec["columns"] if column["name"] == "play_mode")
    column["data_tests"] = []
    (tmp_path / LABEL_REGISTRY).write_text(
        json.dumps({"version": 2, "models": [spec]}), encoding="utf-8"
    )
    models, problems = check_dbt_rules.load_models(tmp_path)
    assert problems == []

    problems = check_required_tests(Project(tmp_path, models, {}))

    assert len(problems) == 1
    assert problems[0].startswith(f"{LABEL_REGISTRY}: rule a: ")
    assert "lacks not_null on play_mode" in problems[0]


def test_label_version_mismatch_fails_rule_c_against_its_own_contract(tmp_path: Path) -> None:
    project, _ = make_label_project(tmp_path)
    contract = tmp_path / "contracts" / "reference" / LABEL_FEED.name
    contract.write_text(
        contract.read_text(encoding="utf-8").replace("version: 1.0.0", "version: 9.9.9"),
        encoding="utf-8",
    )

    problems = check_contract(project)

    assert len(problems) == 1
    assert problems[0].startswith(f"{LABEL_REGISTRY}: rule c: ")
    assert "contracts/reference/session_play_mode.odcs.yaml" in problems[0]

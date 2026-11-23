"""Behavioral tests for scripts/check_exposures.py on hand-written dbt manifests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from check_exposures import main


def node(name: str, *, resource_type: str = "model") -> dict[str, str]:
    """Return a minimal dbt node."""
    return {
        "unique_id": f"{resource_type}.p.{name}",
        "resource_type": resource_type,
        "name": name,
    }


def exposure(*unique_ids: str) -> dict[str, dict[str, list[str]]]:
    """Return a minimal exposure with the supplied dependencies."""
    return {"depends_on": {"nodes": list(unique_ids)}}


def run(
    tmp_path: Path,
    nodes: list[dict[str, str]],
    exposures: dict[str, dict[str, dict[str, list[str]]]],
) -> int:
    """Write a minimal manifest and run the checker."""
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "nodes": {item["unique_id"]: item for item in nodes},
                "exposures": exposures,
            }
        ),
        encoding="utf-8",
    )
    return main([str(manifest)])


def test_every_obt_model_covered_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = run(
        tmp_path,
        [node("obt_company_month"), node("obt_park_month")],
        {
            "exposure:p:company": exposure("model.p.obt_company_month"),
            "exposure:p:park": exposure("model.p.obt_park_month"),
        },
    )
    assert code == 0
    assert capsys.readouterr().out == "check_exposures: every obt_ model has an exposure.\n"


def test_uncovered_obt_model_fails_and_names_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run(
        tmp_path,
        [node("obt_company_month"), node("obt_park_month")],
        {"exposure:p:company": exposure("model.p.obt_company_month")},
    )
    assert code == 1
    assert "obt_park_month: no exposure" in capsys.readouterr().err


def test_uncovered_fct_model_is_ignored(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = run(tmp_path, [node("fct_park_day")], {})
    assert code == 0
    assert "every obt_ model" in capsys.readouterr().out


def test_exposure_to_fct_does_not_cover_obt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run(
        tmp_path,
        [node("obt_company_month"), node("fct_park_day")],
        {"exposure:p:park": exposure("model.p.fct_park_day")},
    )
    assert code == 1
    assert "obt_company_month: no exposure" in capsys.readouterr().err


def test_uncovered_non_model_obt_node_is_ignored(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run(tmp_path, [node("obt_seed_lookup", resource_type="seed")], {})
    assert code == 0
    assert "every obt_ model" in capsys.readouterr().out


def test_malformed_manifest_fails_with_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{not json", encoding="utf-8")
    assert main([str(manifest)]) == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("check_exposures: ")
    assert "every obt_ model" not in captured.out


def test_missing_manifest_fails_with_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.json"
    assert main([str(missing)]) == 1
    assert str(missing) in capsys.readouterr().err

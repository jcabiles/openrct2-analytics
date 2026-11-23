"""Reading contract fields: a field the converter cannot use is an error, not a guess."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from openrct2_analytics.ingest.contracts import CONTRACTS_DIR, LANDING_FOLDER, load_fields

VERSION_LINE = re.compile(r"^version: (\S+)$", re.MULTILINE)


@pytest.fixture
def contracts_copy(tmp_path: Path) -> Path:
    target = tmp_path / "contracts"
    shutil.copytree(CONTRACTS_DIR, target)
    return target


def test_repeated_field_with_a_different_type_raises(contracts_copy: Path) -> None:
    path = contracts_copy / "park_snapshot.odcs.yaml"
    text = path.read_text(encoding="utf-8")
    start = text.index("name: session_id")
    at = text.index("physicalType: VARCHAR", start)
    path.write_text(text[:at] + "physicalType: BIGINT" + text[at + len("physicalType: VARCHAR") :])

    with pytest.raises(ValueError, match=r"park_snapshot\.session_id: type differs"):
        load_fields(contracts_copy)


def test_a_contract_field_with_no_name_raises(contracts_copy: Path) -> None:
    path = contracts_copy / "park_snapshot.odcs.yaml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("      - name: cash_tenths\n", "      - id: nameless\n", 1))

    with pytest.raises(ValueError, match="park_snapshot: a field has no name"):
        load_fields(contracts_copy)


def version_problems(contracts_dir: Path) -> list[str]:
    """Why the contracts' version lines break the one-version rule (ADR 0007), if they do."""
    versions = {
        path.name: VERSION_LINE.findall(path.read_text(encoding="utf-8"))
        for path in sorted(contracts_dir.glob("*.odcs.yaml"))
    }
    problems = [
        f"{name}: {len(found)} version lines" for name, found in versions.items() if len(found) != 1
    ]
    distinct = {found[0] for found in versions.values() if len(found) == 1}
    if len(distinct) != 1:
        problems.append(f"contracts disagree on the version: {sorted(distinct)}")
    problems += [
        f"major version {version} does not match the landing folder {LANDING_FOLDER}"
        for version in sorted(distinct)
        if f"v{version.split('.')[0]}" != LANDING_FOLDER
    ]
    return problems


def test_every_contract_shares_one_version_whose_major_is_the_landing_folder() -> None:
    assert len(list(CONTRACTS_DIR.glob("*.odcs.yaml"))) == 14
    assert version_problems(CONTRACTS_DIR) == []


def test_one_contract_at_a_different_version_fails(contracts_copy: Path) -> None:
    path = contracts_copy / "session_start.odcs.yaml"
    text = path.read_text(encoding="utf-8")
    path.write_text(VERSION_LINE.sub("version: 1.9.0", text, count=1), encoding="utf-8")

    assert version_problems(contracts_copy) == [
        "contracts disagree on the version: ['1.8.0', '1.9.0']"
    ]


def test_a_major_version_that_is_not_the_landing_folder_fails(contracts_copy: Path) -> None:
    for path in contracts_copy.glob("*.odcs.yaml"):
        text = path.read_text(encoding="utf-8")
        path.write_text(VERSION_LINE.sub("version: 2.0.0", text, count=1), encoding="utf-8")

    assert version_problems(contracts_copy) == [
        "major version 2.0.0 does not match the landing folder v1"
    ]

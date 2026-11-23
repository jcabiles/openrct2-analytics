"""Behavioral tests for scripts/check_contract_breaking.py, with the real `datacontract` tool.

Each test builds a temporary git repository holding the repo's real contracts, commits them, points
`refs/remotes/origin/develop` at that commit, and then edits the working tree: the real envelope
change, a planted field removal, and a planted type change.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from check_contract_breaking import SKIP_LINE, changed_contracts, main

REPO = Path(__file__).resolve().parent.parent
ENVELOPE = Path("contracts/envelope.odcs.yaml")
FEED = Path("contracts/reference/park_registry.odcs.yaml")
VERSION_LINE = re.compile(r"^version: (\d+)\.(\d+)\.(\d+)$", re.MULTILINE)
PROPERTY_LINE = re.compile(r"^      - name: (\S+)$", re.MULTILINE)
GIT = ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid"]


def run_git(root: Path, *args: str) -> str:
    """Run git in the temporary repository."""
    done = subprocess.run(
        [*GIT, "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository at version 1.3.0 with `origin/develop` on its only commit."""
    shutil.copytree(REPO / "contracts", tmp_path / "contracts")
    run_git(tmp_path, "init", "--quiet")
    run_git(tmp_path, "add", "contracts")
    run_git(tmp_path, "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "base")
    run_git(tmp_path, "update-ref", "refs/remotes/origin/develop", "HEAD")
    return tmp_path


def edit(root: Path, name: Path, old: str, new: str) -> None:
    """Replace one expected piece of text in a contract file."""
    path = root / name
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{name} lacks the text to replace"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def set_version(root: Path, version: str) -> None:
    """Move every contract to one shared version, as the version line requires."""
    for path in (root / "contracts").glob("*.odcs.yaml"):
        text = path.read_text(encoding="utf-8")
        assert VERSION_LINE.search(text), f"{path.name} lacks a version line"
        path.write_text(VERSION_LINE.sub(f"version: {version}", text, count=1), encoding="utf-8")


def set_contract_version(root: Path, name: Path, version: str) -> None:
    """Set one contract's version."""
    path = root / name
    text = path.read_text(encoding="utf-8")
    assert VERSION_LINE.search(text), f"{name} lacks a version line"
    path.write_text(VERSION_LINE.sub(f"version: {version}", text, count=1), encoding="utf-8")


def bumped_version(root: Path, *, major: bool = False) -> str:
    """Read the copied contract version and compute its next major or minor version."""
    text = (root / ENVELOPE).read_text(encoding="utf-8")
    found = VERSION_LINE.search(text)
    assert found, f"{ENVELOPE} lacks a version line"
    major_version, minor_version, _ = (int(part) for part in found.groups())
    if major:
        return f"{major_version + 1}.0.0"
    return f"{major_version}.{minor_version + 1}.0"


def first_property(text: str) -> tuple[str, str]:
    """Return the game-year property, or the first schema property, and its YAML block."""
    matches = list(PROPERTY_LINE.finditer(text))
    assert matches, f"{ENVELOPE} has no properties"
    selected = next((match for match in matches if match.group(1) == "game_year"), matches[0])
    position = matches.index(selected)
    end = (
        matches[position + 1].start()
        if position + 1 < len(matches)
        else text.index("    quality:", selected.start())
    )
    return selected.group(1), text[selected.start() : end]


def check(root: Path, monkeypatch: pytest.MonkeyPatch, ci: str | None = "1") -> int:
    """Run the check on root with `CI` set (or unset when ci is None)."""
    if ci is None:
        monkeypatch.delenv("CI", raising=False)
    else:
        monkeypatch.setenv("CI", ci)
    return main([str(root)])


def test_removed_field_under_a_minor_bump_fails(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, property_block = first_property((repo / ENVELOPE).read_text(encoding="utf-8"))
    edit(repo, ENVELOPE, property_block, "")
    set_version(repo, bumped_version(repo))
    assert check(repo, monkeypatch) == 1
    err = capsys.readouterr().err
    assert "without a major version bump" in err
    assert "contracts/envelope.odcs.yaml" in err
    assert "Removed property game_year" in err


def test_changed_type_under_a_minor_bump_fails(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, property_block = first_property((repo / ENVELOPE).read_text(encoding="utf-8"))
    changed_type = property_block.replace("logicalType: integer", "logicalType: string", 1)
    changed_type = changed_type.replace("physicalType: INTEGER", "physicalType: VARCHAR", 1)
    assert changed_type != property_block, "the first property has no editable integer type"
    edit(repo, ENVELOPE, property_block, changed_type)
    set_version(repo, bumped_version(repo))
    assert check(repo, monkeypatch) == 1
    assert "Changed type" in capsys.readouterr().err


def test_removed_field_under_a_major_bump_passes(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, property_block = first_property((repo / ENVELOPE).read_text(encoding="utf-8"))
    edit(repo, ENVELOPE, property_block, "")
    set_version(repo, bumped_version(repo, major=True))
    assert check(repo, monkeypatch) == 0


def test_unrelated_contract_major_bump_does_not_allow_envelope_breaking_change(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, property_block = first_property((repo / ENVELOPE).read_text(encoding="utf-8"))
    edit(repo, ENVELOPE, property_block, "")
    set_contract_version(repo, ENVELOPE, "1.4.0")
    set_contract_version(repo, Path("contracts/save_written.odcs.yaml"), "2.0.0")

    assert check(repo, monkeypatch) == 1
    err = capsys.readouterr().err
    assert "without a major version bump" in err
    assert "contracts/envelope.odcs.yaml" in err


def test_envelope_major_bump_allows_envelope_breaking_change(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, property_block = first_property((repo / ENVELOPE).read_text(encoding="utf-8"))
    edit(repo, ENVELOPE, property_block, "")
    set_contract_version(repo, ENVELOPE, "2.0.0")

    assert check(repo, monkeypatch) == 0


def test_deleted_contract_under_a_minor_bump_fails(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    deleted = Path("contracts/save_written.odcs.yaml")
    (repo / deleted).unlink()
    set_version(repo, bumped_version(repo))
    assert check(repo, monkeypatch) == 1
    err = capsys.readouterr().err
    assert "without a major version bump" in err
    assert str(deleted) in err


def test_deleted_contract_under_a_major_bump_passes(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deleted = "contracts/save_written.odcs.yaml"
    (repo / deleted).unlink()
    set_version(repo, bumped_version(repo, major=True))
    base = run_git(repo, "merge-base", "HEAD", "origin/develop")
    assert (deleted, "D") in changed_contracts(repo, base)
    assert check(repo, monkeypatch) == 0


def test_deleted_reference_contract_is_not_allowed_by_event_major_bump(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / FEED).unlink()
    set_contract_version(repo, ENVELOPE, "2.0.0")

    assert check(repo, monkeypatch) == 1
    err = capsys.readouterr().err
    assert "without a major version bump" in err
    assert str(FEED) in err


def test_renamed_contract_with_removed_property_under_a_minor_bump_fails(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    type_contracts = []
    for path in sorted((repo / "contracts").glob("*.odcs.yaml")):
        if path.relative_to(repo) == ENVELOPE:
            continue
        text = path.read_text(encoding="utf-8")
        if len(list(PROPERTY_LINE.finditer(text))) >= 2:
            type_contracts.append(path)
    assert type_contracts, "no type contract has at least two properties"

    original = type_contracts[0]
    old_name = original.relative_to(repo)
    new_name = old_name.with_name(f"{old_name.name.removesuffix('.odcs.yaml')}_renamed.odcs.yaml")
    text = (repo / old_name).read_text(encoding="utf-8")
    _, property_block = first_property(text)
    edit(repo, old_name, property_block, "")
    (repo / old_name).rename(repo / new_name)
    set_version(repo, bumped_version(repo))
    assert check(repo, monkeypatch) == 1
    err = capsys.readouterr().err
    assert "without a major version bump" in err
    assert str(old_name) in err


def test_envelope_change_passes_under_a_minor_bump(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = repo / ENVELOPE
    text = path.read_text(encoding="utf-8")
    property_match = PROPERTY_LINE.search(text)
    assert property_match, f"{ENVELOPE} has no properties"
    added_names = ("_test_added_text", "_test_added_count")
    assert all(f"- name: {name}" not in text for name in added_names)
    added_properties = (
        "      - name: _test_added_text\n"
        "        logicalType: string\n"
        "        physicalType: VARCHAR\n"
        "        required: true\n"
        "        description: Added text property for the compatibility check.\n"
        "      - name: _test_added_count\n"
        "        logicalType: integer\n"
        "        physicalType: BIGINT\n"
        "        required: true\n"
        "        description: Added count property for the compatibility check.\n"
    )
    text = text[: property_match.start()] + added_properties + text[property_match.start() :]

    unique_line = re.search(r"^        unique: true\n", text, re.MULTILINE)
    if unique_line is not None:
        text = text[: unique_line.start()] + text[unique_line.end() :]
        assert re.search(r"^        unique: true$", text, re.MULTILINE) is None
    else:
        assert "unique: true" not in text
    path.write_text(text, encoding="utf-8")
    set_version(repo, bumped_version(repo))
    assert check(repo, monkeypatch) == 0


def test_new_contract_file_passes_as_an_addition(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = (repo / "contracts/save_written.odcs.yaml").read_text(encoding="utf-8")
    added = source.replace("name: save_written", "name: save_loaded")
    (repo / "contracts/save_loaded.odcs.yaml").write_text(added, encoding="utf-8")
    run_git(repo, "add", "contracts")
    assert check(repo, monkeypatch) == 0


def test_ci_unset_skips_with_a_notice(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, property_block = first_property((repo / ENVELOPE).read_text(encoding="utf-8"))
    edit(repo, ENVELOPE, property_block, "")
    assert check(repo, monkeypatch, ci=None) == 0
    assert capsys.readouterr().out == SKIP_LINE + "\n"


def test_ci_set_without_origin_develop_fails(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_git(repo, "update-ref", "-d", "refs/remotes/origin/develop")
    assert check(repo, monkeypatch) == 1
    assert "origin/develop is not fetched" in capsys.readouterr().err


def test_develop_tip_addition_is_not_a_branch_breaking_change(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shared = run_git(repo, "rev-parse", "HEAD")
    contract = Path("contracts/save_written.odcs.yaml")
    text = (repo / contract).read_text(encoding="utf-8")
    property_match = PROPERTY_LINE.search(text)
    assert property_match, f"{contract} has no properties"
    required_property = (
        "      - name: _develop_required_text\n"
        "        logicalType: string\n"
        "        physicalType: VARCHAR\n"
        "        required: true\n"
        "        description: Required property added on develop.\n"
    )
    assert "_develop_required_text" not in text
    text = text[: property_match.start()] + required_property + text[property_match.start() :]
    (repo / contract).write_text(text, encoding="utf-8")
    set_version(repo, bumped_version(repo))
    run_git(repo, "add", "contracts")
    run_git(
        repo, "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "develop contract addition"
    )
    run_git(repo, "update-ref", "refs/remotes/origin/develop", "HEAD")
    run_git(repo, "reset", "--hard", shared)

    assert run_git(repo, "rev-parse", "HEAD") == shared
    assert run_git(repo, "merge-base", "HEAD", "origin/develop") == shared
    assert run_git(repo, "rev-parse", "origin/develop") != shared
    assert check(repo, monkeypatch) == 0


def test_registry_removed_feed_field_under_a_minor_bump_fails(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    text = (repo / FEED).read_text(encoding="utf-8")
    start = text.index("      - name: note\n")
    removed = text[start : text.index("      - name: delivered_on\n")]
    edit(repo, FEED, removed, "")
    set_contract_version(repo, FEED, "1.1.0")
    assert check(repo, monkeypatch) == 1
    err = capsys.readouterr().err
    assert "without a major version bump" in err
    assert str(FEED) in err
    assert "Removed property note" in err

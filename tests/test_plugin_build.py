"""Tests for building the plugin: the real build, a failed build, a build with no output, no npm."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from openrct2_analytics.ingest import plugin_install as pi

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_real_build_writes_the_plugin() -> None:
    built = REPO_ROOT / pi.BUILT_PLUGIN
    built.unlink(missing_ok=True)  # git-ignored build output

    assert pi.build_plugin(REPO_ROOT) == built

    assert b"registerPlugin" in built.read_bytes()


def test_failed_build_deletes_the_output_and_reports_the_compiler(tmp_path: Path) -> None:
    root = tmp_path / "copy"
    shutil.copytree(REPO_ROOT / "plugin", root / "plugin", ignore=shutil.ignore_patterns("dist"))
    shutil.copy(REPO_ROOT / "package.json", root / "package.json")
    (root / "node_modules").symlink_to(REPO_ROOT / "node_modules")
    (root / "plugin" / "src" / "broken.ts").write_text('const wrong: number = "text";\n')
    stale = root / pi.BUILT_PLUGIN
    stale.parent.mkdir(parents=True)
    stale.write_text("stale output of an earlier build")

    with pytest.raises(pi.BuildError, match="broken.ts"):
        pi.build_plugin(root)

    assert not stale.exists()


def test_a_build_that_exits_zero_without_output_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"scripts": {"plugin:build": "node -e \\"\\""}}')
    stale = tmp_path / pi.BUILT_PLUGIN
    stale.parent.mkdir(parents=True)
    stale.write_text("stale output of an earlier build")

    with pytest.raises(pi.BuildError, match="wrote no"):
        pi.build_plugin(tmp_path)

    assert not stale.exists()


def test_missing_npm_is_a_build_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    with pytest.raises(pi.BuildError, match="npm"):
        pi.build_plugin(tmp_path)

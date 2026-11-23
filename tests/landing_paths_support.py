"""Shared fixture and refusal text for the caller tests of the landing-folder join."""

from __future__ import annotations

from pathlib import Path

import pytest

EMPTY_ROOT = "Environment variable OPENRCT2_DATA_DIR must not be empty"


@pytest.fixture
def relative_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return the project folder; the data root is relative and the working folder is elsewhere."""
    project = tmp_path / "project"
    project.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "data-x")
    monkeypatch.chdir(elsewhere)
    return project

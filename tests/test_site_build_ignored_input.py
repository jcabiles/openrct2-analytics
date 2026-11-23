"""The real site build reads an input folder under the repository's git-ignored `local/`."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from openrct2_analytics.ingest import site_company
from openrct2_analytics.ingest import site_company_land as land

REPO = site_company.PROJECT_DIR


@pytest.fixture
def ignored_folder() -> Iterator[Path]:
    """A folder under the repository's `local/`, named so `make delete-company-data` clears it."""
    local = REPO / "local"
    created = not local.exists()
    local.mkdir(exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix=land.INPUT_PREFIX, dir=local))
    try:
        ignored = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", str(folder)])
        assert ignored.returncode == 0, "the test folder must be git-ignored to reproduce the bug"
        yield folder
    finally:
        shutil.rmtree(folder)
        if created and not any(local.iterdir()):
            local.rmdir()


def test_the_site_build_writes_the_page_from_a_git_ignored_input(ignored_folder: Path) -> None:
    page_input = ignored_folder / "input"
    shutil.copytree(REPO / "site", page_input, ignore=shutil.ignore_patterns("_site"))

    code = site_company.npm_build(page_input, ignored_folder / "site")

    assert code == 0
    assert (ignored_folder / "site" / "index.html").is_file()

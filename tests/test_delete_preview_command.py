"""The ``make delete-company-data`` preview names the park from the company landing folder."""

from collections.abc import Callable
from datetime import timedelta, timezone, tzinfo
from pathlib import Path

import pytest

from openrct2_analytics.config import LandingDirs
from openrct2_analytics.ingest.delete_data import main
from tests.test_delete_data import setup
from tests.test_delete_plan import event, write
from tests.test_park_label import converted


def test_the_command_preview_reads_the_labels_from_the_company_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixed_local_zone: Callable[[tzinfo], None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    project, data, _, args = setup(tmp_path, monkeypatch)
    fixed_local_zone(timezone(timedelta(hours=-8)))
    company = data / "company"
    write(company / "raw/v1/events-a.jsonl", event("p", "s"))
    converted(
        LandingDirs(raw=company / "raw", parquet=company / "parquet"),
        [("p", "s", "Alpha Park", "2026-10-17T00:00:00Z")],
    )

    assert main([*args, "--park", "p"], project_dir=project) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "scope: park='p', session=None"
    assert lines[1] == "park p: Alpha Park (first played Oct 16)"

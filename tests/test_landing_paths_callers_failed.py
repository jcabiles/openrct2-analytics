"""Caller tests of the landing-folder join for two sites the other caller files do not reach.

Both relative-root tests set ``OPENRCT2_DATA_DIR=data-x``, plant files under
``<project>/data-x/company/`` and run from a different, empty working folder: the seq-failed
lookup of ``after_play.check_can_start`` and the park-label lookup of ``auto_file._file``.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from openrct2_analytics.ingest import after_play, auto_file, capture_session
from tests.landing_paths_support import relative_root as relative_root  # noqa: F401  (fixture)
from tests.test_after_play import _copy
from tests.test_register_parks_start_year import park_one, plant


@pytest.fixture
def utc(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Show first-played days in UTC, so the label's day is the same on every machine."""
    before = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    if before is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = before
    time.tzset()


def test_after_play_check_can_start_finds_a_failed_session_under_the_project(
    relative_root: Path,
) -> None:
    plant(relative_root / "data-x", park_one())
    # One valid audit changed in one thing: park-1's session s1 now has a gap (missing = 1).
    _copy(
        relative_root / "data-x" / "company" / "parquet" / "audit" / "seq_audit.parquet",
        "SELECT 'park-1' AS park_id, 's1' AS session_id, 1 AS park_count, 1 AS missing, "
        "0 AS duplicates, 1 AS first_seq, 1 AS last_seq, 1 AS row_count",
    )
    with pytest.raises(after_play.Refused) as caught:
        after_play.check_can_start("company", relative_root)
    assert caught.value.reason == "seq-failed"
    assert caught.value.detail == (
        "session s1 of park park-1 failed its seq audit. Filing files every waiting session, "
        "so nothing is filed while one waits. To see what removing it would do, run "
        "make delete-company-data SESSION=s1 (a preview; it deletes nothing)"
    )


def test_auto_file_labels_a_waiting_park_from_the_folders_under_the_project(
    relative_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    utc: None,
) -> None:
    monkeypatch.setattr(capture_session, "discard_typed_input", lambda: None)
    plant(relative_root / "data-x", park_one())
    prompts: list[str] = []

    def dont_file_now(prompt: str) -> str:
        prompts.append(prompt)
        return "3"

    argv = ["--data-set", "company", "--count-as", "company"]
    code = auto_file.main(
        argv, project_dir=relative_root, ask=dont_file_now, is_terminal=lambda: True
    )
    assert code == 2
    assert prompts == [
        "Park park-2 (first played Nov 12) from an earlier play is waiting. "
        "Where should it count?\n1. Company\n2. Sandbox\n3. Don't file now\n"
    ]
    assert capsys.readouterr().out == (
        "auto-file: local/auto-file/converted-before.json is missing, so no park counts as this "
        "play's; every unregistered park is asked about.\n"
        "auto-file refused: not-now: Don't file now was chosen for park park-2 "
        "(first played Nov 12). Nothing was changed.\n"
        "To file it, run: make auto-file DATA_SET=company COUNT_AS=company\n"
    )

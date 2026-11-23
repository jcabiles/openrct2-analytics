"""The two bases of the rehearsal capture (spec R3): input settings and the data folder.

Relative input settings mean the folder the command started in; a relative data folder means the
project folder. Every test starts the command from a folder outside the project and passes a
``build`` that raises, so none can build or launch anything.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

from openrct2_analytics.ingest.game_check import GameState
from openrct2_analytics.ingest.rehearsal_capture import main
from tests.test_rehearsal_capture import AUTOSAVE_TIME, DATA_SET, RehearsalHarness
from tests.test_rehearsal_refusals import (
    NOTHING,
    build_not_reached,
    refuse_unchanged,
    snapshot,
    temp_project,
)


def start_outside(rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Two levels down, so no relative name that works from here also works from the project folder.
    outside = rh.bench.root / "deep" / "outside"
    outside.mkdir(parents=True)
    monkeypatch.chdir(outside)
    return outside


def relative(path: Path, start: Path) -> str:
    return os.path.relpath(path, start)


def test_relative_park_settings_name_files_from_the_starting_folder(
    rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = start_outside(rh, monkeypatch)
    project = temp_project(rh.bench.root / "project")
    monkeypatch.setenv("OPENRCT2_BENCH_PARK", relative(rh.bench.fixture, outside))
    monkeypatch.setenv("OPENRCT2_REHEARSAL_PARK2", relative(rh.park2, outside))
    rh.bench.fixture.write_bytes(b"another park")  # item 7 refuses; item 2 did not

    refuse_unchanged(
        rh, capsys, "OPENRCT2_BENCH_PARK is not the benchmark park", project_dir=project
    )


def test_a_relative_player_folder_is_the_one_rule_a_guards(
    rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = start_outside(rh, monkeypatch)
    project = temp_project(rh.bench.root / "project")
    monkeypatch.setenv("OPENRCT2_USER_DIR", relative(rh.bench.user_dir, outside))
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(rh.bench.user_dir / "data"))
    refuse_unchanged(
        rh,
        capsys,
        "equals, contains or lies inside the player's OpenRCT2 folder",
        project_dir=project,
    )


def test_a_fresh_autosave_in_a_relative_player_folder_refuses_with_the_process_check_skipped(
    rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = start_outside(rh, monkeypatch)
    project = temp_project(rh.bench.root / "project")
    monkeypatch.setenv("OPENRCT2_USER_DIR", relative(rh.bench.user_dir, outside))
    before = snapshot(rh)

    def game_check_not_reached() -> GameState:
        raise AssertionError("--skip-process-check must not list processes")

    options = rh.options(clock=lambda: AUTOSAVE_TIME + 60.0)

    code = main(
        [*DATA_SET, "--skip-process-check"],
        options=dataclasses.replace(options, game_check=game_check_not_reached),
        build=build_not_reached,
        project_dir=project,
    )

    assert code == 2
    out = capsys.readouterr().out
    assert "The newest real OpenRCT2 autosave is 1.0 minutes old" in out
    assert out.endswith(f"{NOTHING}\n")
    assert snapshot(rh) == before

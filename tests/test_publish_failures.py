"""Publish failure paths: unsafe rollback folder, corrupt candidate, signalled child."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from openrct2_analytics.ingest.publish import main
from tests.test_publish import error_line, land_sample, project_for, standin

REPO_ROOT = Path(__file__).resolve().parents[1]
HOLD_AT_BUILT = """
import sys, time
from pathlib import Path
from openrct2_analytics.ingest import publish
from tests.publish_standin import build_standin

def hold(*args, **kwargs):
    Path(sys.argv[1]).write_text("ready")
    time.sleep(120)

publish.audit_candidate = hold
sys.exit(publish.main(
    ["--data-set", "rehearsal"],
    run_id="child-run",
    build=build_standin("rehearsal", version="candidate"),
    project_dir=Path(sys.argv[2]),
))
"""

pytestmark = pytest.mark.usefixtures("landing_root")


def test_publish_refuses_a_rollback_folder_that_is_a_symbolic_link(
    tmp_path: Path, landing_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    land_sample(landing_root, "rehearsal")
    project = project_for(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / "warehouse").mkdir()
    (project / "warehouse" / "previous").symlink_to(outside, target_is_directory=True)

    result = main(["--data-set", "rehearsal"], build=standin("rehearsal"), project_dir=project)

    assert result == 2
    assert error_line(capsys.readouterr().out).startswith("publish refused: unsafe-path: ")
    assert list(outside.iterdir()) == []
    assert sorted(path.name for path in (project / "warehouse").iterdir()) == ["previous"]


def test_publish_reports_a_corrupt_candidate_as_one_line(
    tmp_path: Path, landing_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    land_sample(landing_root, "rehearsal")
    project = project_for(tmp_path)

    def garbage(_candidate_dir: Path, candidate_file: Path, _snapshot_dir: Path) -> None:
        candidate_file.write_bytes(b"not a duckdb file" * 100)

    result = main(["--data-set", "rehearsal"], build=garbage, project_dir=project)

    assert result == 1
    assert error_line(capsys.readouterr().out).startswith("publish failed: candidate-unreadable: ")
    assert not (project / "warehouse" / "rehearsal.lock").exists()
    assert list((project / "warehouse" / "candidate").iterdir()) == []


@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGHUP], ids=lambda number: number.name)
def test_a_signal_to_a_child_publisher_held_at_built_exits_130_and_cleans_up(
    tmp_path: Path, landing_root: Path, number: signal.Signals
) -> None:
    land_sample(landing_root, "rehearsal")
    project, ready = project_for(tmp_path), tmp_path / "ready"
    child = subprocess.Popen(
        [sys.executable, "-c", HOLD_AT_BUILT, str(ready), str(project)],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 30
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "the child never reached the audit"
        assert (project / "warehouse" / "rehearsal.lock").is_file()
        assert (project / "warehouse" / "candidate" / "run-child-run").is_dir()

        child.send_signal(number)
        output, _ = child.communicate(timeout=30)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate()

    assert child.returncode == 130, output
    assert f"publish interrupted: {number.name}" in output
    assert not (project / "warehouse" / "rehearsal.lock").exists()
    assert list((project / "warehouse" / "candidate").iterdir()) == []
    assert not (project / "warehouse" / "rehearsal.duckdb").exists()

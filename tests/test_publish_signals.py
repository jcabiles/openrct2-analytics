"""Command-line publish cleanup when the process receives a signal."""

from __future__ import annotations

import os
import shutil
import signal
from pathlib import Path

import pytest

from openrct2_analytics.ingest import publish
from tests.publish_standin import build_standin, read_stamp, write_stamped

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_V1 = REPO_ROOT / "data" / "sample" / "rehearsal" / "v1"
SAMPLE_FEED_V1 = REPO_ROOT / "data" / "sample" / "rehearsal" / "registry" / "v1"
RUN_ID = "signal-test"


@pytest.mark.parametrize("signal_name", ["SIGTERM", "SIGHUP"])
def test_interrupt_at_built_exits_130_and_cleans_up_after_releasing_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, signal_name: str
) -> None:
    """Each command-line signal preserves the published version and removes its candidate."""
    data_root = tmp_path / "data"
    landing = data_root / "rehearsal" / "parquet"
    landing.parent.mkdir(parents=True)
    shutil.copytree(SAMPLE_V1, landing / "v1")
    shutil.copytree(SAMPLE_FEED_V1, landing.parent / "registry" / "v1")
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(data_root))

    project = tmp_path / "project"
    published = project / "warehouse" / "rehearsal.duckdb"
    lock_file = project / "warehouse" / "rehearsal.lock"
    candidates = project / "warehouse" / "candidate"
    write_stamped(published, "published-before-signal")
    writes: list[tuple[str, bool]] = []

    class RecordingStderr:
        def write(self, text: str) -> int:
            writes.append((text, lock_file.exists()))
            return len(text)

        def flush(self) -> None:
            pass

    original_publish = publish.publish

    def signal_at_built(
        name: str,
        *,
        run_id: str | None = None,
        build: publish.BuildStep | None = None,
        on_step: publish.StepObserver = lambda _: None,
        project_dir: Path = REPO_ROOT,
    ) -> publish.PublishSummary:
        def observe(step: str) -> None:
            on_step(step)
            if step == "built":
                os.kill(os.getpid(), getattr(signal, signal_name))

        return original_publish(
            name,
            run_id=run_id,
            build=build,
            on_step=observe,
            project_dir=project_dir,
        )

    monkeypatch.setattr(publish, "publish", signal_at_built)
    recorded_output = RecordingStderr()
    monkeypatch.setattr("sys.stdout", recorded_output)
    monkeypatch.setattr("sys.stderr", recorded_output)
    original_handlers = {
        name: signal.getsignal(getattr(signal, name)) for name in ("SIGINT", "SIGHUP", "SIGTERM")
    }
    try:
        assert (
            publish.main(
                ["--data-set", "rehearsal"],
                run_id=RUN_ID,
                build=build_standin("rehearsal", version="candidate"),
                project_dir=project,
            )
            == 130
        )
        message = f"publish interrupted: {signal_name}; the lock was removed."
        message_writes = [(text, lock_existed) for text, lock_existed in writes if message in text]
        assert message_writes, "publish interruption message was not written"
        assert f"{message}\n" in "".join(text for text, _ in writes)
        assert all(not lock_existed for _, lock_existed in message_writes), (
            "interrupt message was written while the publish lock remained"
        )
        assert not lock_file.exists()
        assert not list(candidates.glob("run-*"))
        assert read_stamp(published) == "published-before-signal"
    finally:
        for name, handler in original_handlers.items():
            signal.signal(getattr(signal, name), handler)

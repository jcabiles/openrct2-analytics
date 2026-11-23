"""Landing snapshots use the converter's lock and copy only versioned Parquet."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from openrct2_analytics.ingest.convert import landing_lock_path
from openrct2_analytics.ingest.publish_errors import PublishFailed
from openrct2_analytics.ingest.publish_snapshot import take_snapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCK_HOLDER = """
import sys
import time
from pathlib import Path
from openrct2_analytics.ingest.lock import hold_lock

lock = Path(sys.argv[1])
stop = Path(sys.argv[2])
with hold_lock(lock, "conversion test"):
    while not stop.exists():
        time.sleep(0.01)
"""


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep machine-specific OpenRCT2 settings out of each test."""
    for name in [key for key in os.environ if key.startswith("OPENRCT2_")]:
        monkeypatch.delenv(name)


def file_bytes(folder: Path) -> dict[Path, bytes]:
    """Return every regular file below ``folder`` with its relative path and bytes."""
    return {
        path.relative_to(folder): path.read_bytes() for path in folder.rglob("*") if path.is_file()
    }


def wait_for_file(path: Path, process: subprocess.Popen[bytes]) -> None:
    """Wait for a child to acquire its lock, failing if it exits or times out."""
    deadline = time.monotonic() + 10
    while not path.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert path.exists(), "conversion child did not acquire the landing lock"


def test_conversion_holding_the_landing_lock_makes_snapshot_fail_converting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A child conversion's real landing lock prevents publish from taking a copy."""
    project = tmp_path / "project"
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    landing = tmp_path / "data" / "rehearsal" / "parquet"
    source = landing / "v1"
    source.mkdir(parents=True)
    (source / "park_snapshot.parquet").write_bytes(b"parquet bytes")
    candidate = project / "warehouse" / "candidate" / "run-test"
    candidate.mkdir(parents=True)
    lock_path = landing.with_name("parquet.lock")
    stop = tmp_path / "stop-child"
    process = subprocess.Popen(
        [sys.executable, "-c", LOCK_HOLDER, str(lock_path), str(stop)],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_file(lock_path, process)

        with pytest.raises(PublishFailed) as failed:
            take_snapshot(project, "rehearsal", candidate, lambda _step: None)

        assert failed.value.reason == "converting"
        assert str(lock_path) in failed.value.detail
    finally:
        stop.write_text("stop", encoding="utf-8")
        process.wait(timeout=10)


def test_symlinked_landing_uses_unresolved_conversion_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lock beside the configured symlink prevents a snapshot from taking a copy."""
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "data")
    landing = project / "data" / "rehearsal" / "parquet"
    actual_landing = project / "actual-parquet"
    source = actual_landing / "v1"
    source.mkdir(parents=True)
    (source / "park_snapshot.parquet").write_bytes(b"parquet bytes")
    landing.parent.mkdir(parents=True)
    landing.symlink_to(actual_landing, target_is_directory=True)
    candidate = project / "warehouse" / "candidate" / "run-test"
    candidate.mkdir(parents=True)
    lock_path = landing_lock_path(landing)
    stop = tmp_path / "stop-child"
    process = subprocess.Popen(
        [sys.executable, "-c", LOCK_HOLDER, str(lock_path), str(stop)],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_file(lock_path, process)

        with pytest.raises(PublishFailed) as failed:
            take_snapshot(project, "rehearsal", candidate, lambda _step: None)

        assert failed.value.reason == "converting"
        assert str(lock_path) in failed.value.detail
    finally:
        stop.write_text("stop", encoding="utf-8")
        process.wait(timeout=10)


def test_snapshot_holding_landing_lock_makes_convert_refuse_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The converter command exits 2 with the shared lock path while snapshot is paused."""
    project = tmp_path / "project"
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    landing = tmp_path / "data" / "rehearsal" / "parquet"
    source = landing / "v1"
    source.mkdir(parents=True)
    (source / "park_snapshot.parquet").write_bytes(b"parquet bytes")
    (landing / "audit").mkdir()
    (landing / "audit" / "seq_audit.parquet").write_bytes(b"audit bytes")
    candidate = project / "warehouse" / "candidate" / "run-test"
    candidate.mkdir(parents=True)
    locked = threading.Event()
    release = threading.Event()

    def observe(step: str) -> None:
        if step == "landing-locked":
            locked.set()
            if not release.wait(10):
                raise TimeoutError("test did not release the snapshot lock")

    with ThreadPoolExecutor(max_workers=1) as executor:
        snapshot = executor.submit(take_snapshot, project, "rehearsal", candidate, observe)
        try:
            assert locked.wait(10), "snapshot did not acquire the landing lock"
            before = file_bytes(tmp_path)
            lock_path = landing.with_name("parquet.lock")
            done = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "openrct2_analytics.ingest.convert",
                    "--raw-dir",
                    str(tmp_path / "raw"),
                    "--out-dir",
                    str(landing),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            assert done.returncode == 2, done.stdout + done.stderr
            assert str(lock_path) in done.stdout
            assert file_bytes(tmp_path) == before
        finally:
            release.set()

    assert snapshot.result(timeout=10) == candidate / "landing"


def test_snapshot_contains_only_v1_at_snapshot_taken_and_does_not_change_landing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The callback sees a completed v1-only copy after the lock has been released."""
    project = tmp_path / "project"
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    landing = tmp_path / "data" / "rehearsal" / "parquet"
    source_v1 = landing / "v1"
    source_v1.mkdir(parents=True)
    (source_v1 / "park_snapshot.parquet").write_bytes(b"park")
    (source_v1 / "plugin_stats.parquet").write_bytes(b"stats")
    (landing / "audit").mkdir()
    (landing / "audit" / "seq_audit.parquet").write_bytes(b"audit")
    feed_v1 = tmp_path / "data" / "rehearsal" / "registry" / "v1"
    feed_v1.mkdir(parents=True)
    (feed_v1 / "park_registry_2026-10-10_01.csv").write_bytes(b"feed")
    before = file_bytes(landing)
    candidate = project / "warehouse" / "candidate" / "run-test"
    candidate.mkdir(parents=True)
    steps: list[str] = []
    lock_path = landing.with_name("parquet.lock")

    def observe(step: str) -> None:
        steps.append(step)
        if step == "snapshot-taken":
            assert not lock_path.exists()
            assert {path.name for path in (candidate / "landing").iterdir()} == {"v1", "registry"}

    snapshot_dir = take_snapshot(project, "rehearsal", candidate, observe)

    assert snapshot_dir == candidate / "landing"
    assert steps == ["landing-locked", "snapshot-taken"]
    assert file_bytes(snapshot_dir / "v1") == {
        Path("park_snapshot.parquet"): b"park",
        Path("plugin_stats.parquet"): b"stats",
    }
    assert file_bytes(landing) == before
    assert file_bytes(snapshot_dir / "registry") == {
        Path("v1/park_registry_2026-10-10_01.csv"): b"feed"
    }


@pytest.mark.parametrize("create_v1", [False, True], ids=["missing-landing", "empty-v1"])
def test_no_parquet_files_fails_without_creating_a_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, create_v1: bool
) -> None:
    """A missing landing or empty v1 folder fails with the publish no-input reason."""
    project = tmp_path / "project"
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    landing = tmp_path / "data" / "rehearsal" / "parquet"
    if create_v1:
        (landing / "v1").mkdir(parents=True)
    candidate = project / "warehouse" / "candidate" / "run-test"
    candidate.mkdir(parents=True)

    with pytest.raises(PublishFailed) as failed:
        take_snapshot(project, "rehearsal", candidate, lambda _step: None)

    assert failed.value.reason == "no-input"
    assert not (candidate / "landing").exists()
    assert not landing.with_name("parquet.lock").exists()


def test_snapshot_folder_oserror_is_reported_as_snapshot_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real filesystem error creating the snapshot is translated with its path."""
    project = tmp_path / "project"
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    landing = tmp_path / "data" / "rehearsal" / "parquet"
    source_v1 = landing / "v1"
    source_v1.mkdir(parents=True)
    (source_v1 / "park_snapshot.parquet").write_bytes(b"parquet bytes")
    candidate = project / "warehouse" / "candidate" / "run-test"
    candidate.mkdir(parents=True)
    snapshot_dir = candidate / "landing"
    snapshot_dir.write_text("blocks directory creation", encoding="utf-8")

    with pytest.raises(PublishFailed) as failed:
        take_snapshot(project, "rehearsal", candidate, lambda _step: None)

    assert failed.value.reason == "snapshot"
    assert str(snapshot_dir / "v1") in failed.value.detail


def test_unreadable_v1_folder_is_reported_as_snapshot_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real unreadable landing folder fails snapshot listing with its path."""
    project = tmp_path / "project"
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    landing = tmp_path / "data" / "rehearsal" / "parquet"
    source_v1 = landing / "v1"
    source_v1.mkdir(parents=True)
    (source_v1 / "park_snapshot.parquet").write_bytes(b"parquet bytes")
    candidate = project / "warehouse" / "candidate" / "run-test"
    candidate.mkdir(parents=True)
    original_mode = source_v1.stat().st_mode & 0o777
    try:
        source_v1.chmod(0o000)
        assert not os.access(source_v1, os.R_OK)

        with pytest.raises(PublishFailed) as failed:
            take_snapshot(project, "rehearsal", candidate, lambda _step: None)

        assert failed.value.reason == "snapshot"
        assert str(source_v1) in failed.value.detail
    finally:
        source_v1.chmod(original_mode)


def test_lock_folder_oserror_is_reported_as_snapshot_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real filesystem error creating the lock is translated with its path."""
    project = tmp_path / "project"
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    landing = tmp_path / "data" / "rehearsal" / "parquet"
    source_v1 = landing / "v1"
    source_v1.mkdir(parents=True)
    (source_v1 / "park_snapshot.parquet").write_bytes(b"parquet bytes")
    candidate = project / "warehouse" / "candidate" / "run-test"
    candidate.mkdir(parents=True)
    lock_path = landing_lock_path(landing)
    lock_folder = lock_path.parent
    original_mode = lock_folder.stat().st_mode & 0o777
    lock_folder.chmod(0o500)
    try:
        assert not os.access(lock_folder, os.W_OK)

        with pytest.raises(PublishFailed) as failed:
            take_snapshot(project, "rehearsal", candidate, lambda _step: None)

        assert failed.value.reason == "snapshot"
        assert str(lock_path) in failed.value.detail
    finally:
        lock_folder.chmod(original_mode)


@pytest.mark.parametrize("absolute", [False, True], ids=["relative", "absolute"])
def test_landing_path_resolves_from_project_or_keeps_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, absolute: bool
) -> None:
    """Relative config roots use the project, while absolute roots remain absolute."""
    project = tmp_path / "project"
    root = tmp_path / "external-data" if absolute else Path("data")
    configured_root = str(root if absolute else root.as_posix())
    monkeypatch.setenv("OPENRCT2_DATA_DIR", configured_root)
    landing = (root if absolute else project / root) / "rehearsal" / "parquet"
    source = landing / "v1"
    source.mkdir(parents=True)
    (source / "park_snapshot.parquet").write_bytes(b"parquet")
    candidate = project / "warehouse" / "candidate" / "run-test"
    candidate.mkdir(parents=True)

    snapshot_dir = take_snapshot(project, "rehearsal", candidate, lambda _step: None)

    assert (snapshot_dir / "v1" / "park_snapshot.parquet").read_bytes() == b"parquet"


def land_parquet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Land one Parquet file for ``rehearsal`` and return the data set's folder."""
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    data_set = tmp_path / "data" / "rehearsal"
    (data_set / "parquet" / "v1").mkdir(parents=True)
    (data_set / "parquet" / "v1" / "park_snapshot.parquet").write_bytes(b"park")
    return data_set


def test_registry_feed_copy_takes_only_delivery_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only ``park_registry_*.csv`` deliveries are copied, byte for byte."""
    feed_v1 = land_parquet(tmp_path, monkeypatch) / "registry" / "v1"
    feed_v1.mkdir(parents=True)
    (feed_v1 / "park_registry_2026-10-10_01.csv").write_bytes(b"one")
    (feed_v1 / "park_registry_2026-10-11_01.csv").write_bytes(b"two")
    (feed_v1 / "notes.txt").write_bytes(b"ignored")
    candidate = tmp_path / "project" / "warehouse" / "candidate" / "run-test"
    candidate.mkdir(parents=True)

    snapshot_dir = take_snapshot(tmp_path / "project", "rehearsal", candidate, lambda _step: None)

    assert file_bytes(snapshot_dir / "registry" / "v1") == {
        Path("park_registry_2026-10-10_01.csv"): b"one",
        Path("park_registry_2026-10-11_01.csv"): b"two",
    }


def test_registry_feed_folder_exists_in_the_snapshot_without_a_feed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A data set with no feed still gets an empty ``registry/v1`` for the contract check."""
    land_parquet(tmp_path, monkeypatch)
    candidate = tmp_path / "project" / "warehouse" / "candidate" / "run-test"
    candidate.mkdir(parents=True)

    snapshot_dir = take_snapshot(tmp_path / "project", "rehearsal", candidate, lambda _step: None)

    assert (snapshot_dir / "registry" / "v1").is_dir()
    assert list((snapshot_dir / "registry" / "v1").iterdir()) == []

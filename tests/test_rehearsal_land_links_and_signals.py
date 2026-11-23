"""Tests for the rehearsal proof and landing: nine synthetic attempts, real convert and lock."""

from __future__ import annotations

import os
import shutil
import signal
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from openrct2_analytics.ingest import rehearsal_capture, rehearsal_land
from openrct2_analytics.ingest.capture import Refused
from openrct2_analytics.ingest.lock import (
    Interrupted,
)
from openrct2_analytics.ingest.registry_feed import check_feed
from openrct2_analytics.ingest.rehearsal_land import land
from tests.test_bench_run import REPO_ROOT
from tests.test_convert import tree
from tests.test_rehearsal_capture import RehearsalHarness
from tests.test_rehearsal_land import (
    clean_chain,
    installed_handlers,  # noqa: F401  (a pytest fixture, used by name)
    landed,
    no_guard,
    run,
    write,
)


def link_data_root(root: Path, target: Path) -> None:
    shutil.rmtree(root)
    root.symlink_to(target)


def link_rehearsal(root: Path, target: Path) -> None:
    (root / "rehearsal").symlink_to(target)


@pytest.mark.parametrize("link", [link_data_root, link_rehearsal])
def test_a_link_made_before_landing_is_refused_before_anything_is_created_through_it(
    link: Callable[[Path, Path], None],
    tmp_path: Path,
    data_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    protected = tmp_path / "plugin-src"
    protected.mkdir()
    (protected / "kept.ts").write_text("untouched\n")
    link(data_root, protected)

    def guard() -> None:
        if (data_root / "rehearsal").resolve().is_relative_to(protected.resolve()):
            raise Refused("The landing folder lies inside plugin/src/.")

    attempts = write(tmp_path / "work", clean_chain())
    work = tmp_path / "work"
    code = land(attempts, combined=work / "combined", converted=work / "pq", guard=guard)

    assert code == 1
    assert "lies inside plugin/src/" in capsys.readouterr().out
    assert [p.name for p in protected.iterdir()] == ["kept.ts"]


def kill_at(wanted: str, signum: int = signal.SIGINT) -> Callable[[str], None]:
    calls: list[str] = []

    def hook(stage: str) -> None:
        calls.append(stage)
        if stage == wanted and calls.count(wanted) == 1:
            os.kill(os.getpid(), signum)

    return hook


def test_an_interrupt_during_the_copy_leaves_no_incoming_folder(
    tmp_path: Path, data_root: Path
) -> None:
    assert run(tmp_path, clean_chain(), kill_at("copying")) == 130

    assert landed(data_root) == []
    assert not list((data_root / "rehearsal").rglob(".incoming-*"))


def test_a_signal_before_the_renames_lands_nothing_and_exits_130(
    tmp_path: Path, data_root: Path
) -> None:
    assert run(tmp_path, clean_chain(), kill_at("checked")) == 130

    assert landed(data_root) == []
    assert not list((data_root / "rehearsal").rglob(".incoming-*"))


@pytest.mark.parametrize("name", ["SIGINT", "SIGHUP", "SIGTERM"])
def test_a_signal_between_the_renames_is_deferred_and_both_renames_finish(
    name: str, tmp_path: Path, data_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(tmp_path, clean_chain(), kill_at("between-renames", signal.Signals[name])) == 130

    files = landed(data_root)
    assert len([f for f in files if f.startswith("raw/v1/events-")]) == 9
    assert len([f for f in files if f.startswith("registry/v1/park_registry_")]) == 1
    assert not list((data_root / "rehearsal").rglob(".incoming-*"))
    assert check_feed(data_root / "rehearsal" / "registry") == []
    assert "both finished, so the capture is landed" in capsys.readouterr().out
    # The deferred signal is re-raised through the restored handler, which disarms itself as in
    # every other command (so uv's second forwarded signal is ignored); before, the handler stayed
    # armed and a second signal could leave parquet.lock behind.
    assert signal.getsignal(signal.Signals[name]) is signal.SIG_IGN
    assert not (data_root / "rehearsal" / "parquet.lock").exists()


def test_the_raw_folder_is_renamed_before_the_delivery(tmp_path: Path, data_root: Path) -> None:
    rehearsal = data_root / "rehearsal"
    seen: dict[str, object] = {}

    def hook(stage: str) -> None:
        if stage == "between-renames":
            seen["raw"] = (rehearsal / "raw" / "v1").is_dir()
            seen["delivery"] = [
                p.name
                for p in (rehearsal / "registry" / "v1").iterdir()
                if not p.name.startswith(".")
            ]

    assert run(tmp_path, clean_chain(), hook) == 0

    assert seen == {"raw": True, "delivery": []}


def test_a_signal_after_checking_and_before_the_renames_leaves_no_incoming_entry(
    tmp_path: Path, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def signal_arrives(handler: Callable[[int, object], None]) -> None:
        raise Interrupted("SIGINT")

    monkeypatch.setattr(rehearsal_land, "set_signal_handlers", signal_arrives)

    assert run(tmp_path, clean_chain()) == 130

    assert landed(data_root) == []
    assert not list((data_root / "rehearsal").rglob(".incoming-*"))


def test_swapped_park_labels_are_refused(tmp_path: Path, data_root: Path) -> None:
    attempts = write(tmp_path / "work", clean_chain())
    swapped = [replace(a, park=3 - a.park) for a in attempts]
    work = tmp_path / "work"

    with pytest.raises(ValueError, match="scheduled park"):
        land(swapped, combined=work / "combined", converted=work / "pq", guard=no_guard)

    assert not (data_root / "rehearsal").exists()


def fail_incoming_rename(monkeypatch: pytest.MonkeyPatch, which: int) -> Callable[[], None]:
    """Make the ``which``-th rename of an ``.incoming-`` entry raise (1 raw folder, 2 delivery).

    Returns:
        A function that stops the failure, so a later run in the same test renames normally.
    """
    real_rename = Path.rename
    state = {"which": which, "calls": 0}

    def rename(self: Path, target: Path) -> Path:
        if self.name.startswith(".incoming-") and state["which"]:
            state["calls"] += 1
            if state["calls"] == state["which"]:
                raise OSError("rename failed")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", rename)
    return lambda: state.update(which=0)


def test_a_failed_first_rename_removes_the_incoming_entries_and_lands_nothing(
    tmp_path: Path, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fail_incoming_rename(monkeypatch, 1)

    with pytest.raises(OSError, match="rename failed"):
        run(tmp_path, clean_chain())

    assert landed(data_root) == []
    assert not list((data_root / "rehearsal").rglob(".incoming-*"))
    assert not (data_root / "rehearsal" / "parquet.lock").exists()


def test_a_failed_second_rename_leaves_a_half_landing_the_next_run_refuses(
    tmp_path: Path,
    data_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stop_failing = fail_incoming_rename(monkeypatch, 2)

    with pytest.raises(OSError, match="rename failed"):
        run(tmp_path, clean_chain())

    half = landed(data_root)
    assert len([f for f in half if f.startswith("raw/v1/events-")]) == 9
    assert [f for f in half if ".incoming-" in f] != []  # the delivery was never renamed
    assert not [f for f in half if f.startswith("registry/v1/park_registry_")]
    stop_failing()
    capsys.readouterr()

    assert run(tmp_path / "again", clean_chain()) == 1

    out = capsys.readouterr().out
    assert "is not empty" in out and "half landed" in out
    assert landed(data_root) == half


def real_data_tree() -> dict[str, int]:
    """Paths and sizes under the real repo's ``data/``; a missing folder is an empty tree."""
    return {
        str(p.relative_to(REPO_ROOT)): p.lstat().st_size
        for p in (REPO_ROOT / "data").rglob("*")
        if not p.is_dir()
    }


def test_a_relative_data_root_means_the_project_folder_even_from_another_working_folder(
    rh: RehearsalHarness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = rh.bench.root / "project"
    feeds = project / "data" / "company" / "registry" / "v1"
    feeds.mkdir(parents=True)
    (feeds / "park_registry_kept.csv").write_text("kept\n")
    rehearsal = project / "data" / "rehearsal"
    rehearsal.mkdir()
    (rehearsal / "registry").symlink_to(project / "data" / "company" / "registry")
    elsewhere = rh.bench.root / "elsewhere"
    elsewhere.mkdir()
    real_data_before = real_data_tree()  # read before any patching
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "data")
    monkeypatch.chdir(elsewhere)
    before = (tree(project), tree(elsewhere))

    code = rehearsal_capture.main(
        ["--data-set", "rehearsal"],
        options=rh.options(),
        build=lambda: pytest.fail("the run got past its refusals to the plugin build"),
        project_dir=project,
    )

    assert code == 2
    assert "data/company/" in capsys.readouterr().out
    assert (tree(project), tree(elsewhere)) == before
    assert real_data_tree() == real_data_before
    assert sorted(p.name for p in feeds.iterdir()) == ["park_registry_kept.csv"]

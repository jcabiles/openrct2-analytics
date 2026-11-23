"""The shared lock helper, on real files in a temporary folder."""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from openrct2_analytics.ingest import lock
from openrct2_analytics.ingest.lock import LockTaken, hold_lock

LINE = "pid 4242 started 2026-10-07T10:00:00+0000"


class FailingOs:
    """The ``os`` module with one function replaced; every other name is the real one."""

    def __init__(self, name: str, replacement: object) -> None:
        self.name = name
        self.replacement = replacement

    def __getattr__(self, name: str) -> object:
        return self.replacement if name == self.name else getattr(os, name)


def test_the_lock_exists_with_its_line_inside_the_block_and_is_gone_after(tmp_path: Path) -> None:
    path = tmp_path / "parquet.lock"

    with hold_lock(path, LINE):
        assert path.read_text(encoding="utf-8") == LINE + "\n"

    assert not path.exists()


def test_a_taken_lock_raises_with_its_path_and_line_and_is_left_alone(tmp_path: Path) -> None:
    path = tmp_path / "parquet.lock"
    path.write_text(LINE + "\n", encoding="utf-8")

    with pytest.raises(LockTaken) as taken, hold_lock(path, "pid 1 started later"):
        pytest.fail("the body must not run")

    assert taken.value.path == path
    assert taken.value.line == LINE
    assert path.read_text(encoding="utf-8") == LINE + "\n"


def test_a_lock_removed_before_its_line_is_read_raises_with_an_empty_holder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "parquet.lock"
    path.write_text(LINE + "\n", encoding="utf-8")
    read_text = Path.read_text
    raced = False

    def vanish_once(self: Path, encoding: str | None = None, errors: str | None = None) -> str:
        nonlocal raced
        if self == path and not raced:
            raced = True
            raise FileNotFoundError(path)
        return read_text(self, encoding, errors)

    monkeypatch.setattr(Path, "read_text", vanish_once)

    with pytest.raises(LockTaken) as taken, hold_lock(path, "pid 1 started later"):
        pytest.fail("the body must not run")

    assert raced
    assert taken.value.path == path
    assert taken.value.line == ""


def test_removing_the_lock_inside_the_block_exits_cleanly(tmp_path: Path) -> None:
    path = tmp_path / "parquet.lock"

    with hold_lock(path, LINE):
        path.unlink()

    assert not path.exists()


def test_a_body_that_raises_still_removes_the_lock(tmp_path: Path) -> None:
    path = tmp_path / "parquet.lock"

    with pytest.raises(RuntimeError, match="boom"), hold_lock(path, LINE):
        raise RuntimeError("boom")

    assert not path.exists()


def test_a_failed_line_write_still_removes_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "parquet.lock"

    def disk_full(descriptor: int, data: bytes) -> int:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(lock, "os", FailingOs("write", disk_full))

    with pytest.raises(OSError, match="No space left"), hold_lock(path, LINE):
        pytest.fail("the body must not run")

    assert not path.exists()


def test_a_cleanup_error_becomes_a_note_on_the_first_error_and_the_lock_is_still_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "parquet.lock"

    def close_then_fail(descriptor: int) -> None:
        os.close(descriptor)
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(lock, "os", FailingOs("close", close_then_fail))

    with pytest.raises(RuntimeError, match="boom") as raised, hold_lock(path, LINE):
        raise RuntimeError("boom")

    assert any("Input/output error" in note for note in raised.value.__notes__)
    assert not path.exists()


def test_a_cleanup_error_alone_surfaces_and_the_lock_is_still_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "parquet.lock"

    def close_then_fail(descriptor: int) -> None:
        os.close(descriptor)
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(lock, "os", FailingOs("close", close_then_fail))

    with pytest.raises(OSError, match="Input/output error"), hold_lock(path, LINE):
        pass

    assert not path.exists()

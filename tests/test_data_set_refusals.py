"""Landing folders per data set, and every command that refuses without or with a clashing one."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from openrct2_analytics.config import ConfigError, landing_dirs
from openrct2_analytics.ingest import contracts, convert, listener
from tests.test_capture import Folders, command_argv, free_port
from tests.test_convert import land, session_lines, tree

NAMES_BOTH = "rehearsal and company"
HOLD_THEN_SLEEP = """
import sys, time
from pathlib import Path
from openrct2_analytics.ingest import convert

def hold(*args, **kwargs):
    Path(sys.argv[1]).write_text("ready")
    time.sleep(120)

convert._convert_locked = hold
sys.exit(convert.main(["--raw-dir", sys.argv[2], "--out-dir", sys.argv[3]]))
"""


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [n for n in os.environ if n.startswith("OPENRCT2_")]:
        monkeypatch.delenv(name)


def linked_root(tmp_path: Path) -> Path:
    """A data root whose ``company`` folder is a symbolic link to ``rehearsal``."""
    root = tmp_path / "data"
    (root / "rehearsal").mkdir(parents=True)
    (root / "company").symlink_to(root / "rehearsal")
    return root


# ---- landing_dirs ----


@pytest.mark.parametrize("data_set", ["rehearsal", "company"])
def test_landing_dirs_default_to_the_data_folder(data_set: str) -> None:
    folders = landing_dirs(data_set)

    assert folders.raw == Path("data") / data_set / "raw"
    assert folders.parquet == Path("data") / data_set / "parquet"


def test_the_data_root_comes_from_the_environment_and_each_set_gets_its_own_folders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path))

    rehearsal, company = landing_dirs("rehearsal"), landing_dirs("company")

    assert rehearsal.raw == tmp_path / "rehearsal" / "raw"
    assert company.parquet == tmp_path / "company" / "parquet"
    assert len({rehearsal.raw, rehearsal.parquet, company.raw, company.parquet}) == 4


@pytest.mark.parametrize("value", ["", " "])
def test_an_empty_data_root_is_a_config_error(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", value)

    with pytest.raises(ConfigError, match="OPENRCT2_DATA_DIR"):
        landing_dirs("rehearsal")


@pytest.mark.parametrize("data_set", ["", "staging", "Rehearsal"])
def test_an_empty_or_unknown_data_set_is_a_config_error(data_set: str) -> None:
    with pytest.raises(ConfigError, match="rehearsal, company"):
        landing_dirs(data_set)


def test_two_data_sets_that_share_a_folder_are_refused_naming_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = linked_root(tmp_path)
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(root))

    with pytest.raises(ConfigError, match="company.*rehearsal|rehearsal.*company") as raised:
        landing_dirs("rehearsal")

    assert str(root / "company" / "raw") in str(raised.value)
    assert str(root / "rehearsal" / "raw") in str(raised.value)


def test_the_listener_and_convert_refuse_linked_data_sets_and_write_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = linked_root(tmp_path)
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(root))
    monkeypatch.setenv("OPENRCT2_LISTENER_PORT", "0")

    def must_not_bind(*args: object, **kwargs: object) -> None:
        raise AssertionError("the listener bound a port for linked data sets")

    monkeypatch.setattr(listener, "create_server", must_not_bind)
    before = tree(tmp_path)

    assert listener.main(["--data-set", "rehearsal"]) == 2
    assert convert.main(["--data-set", "rehearsal"]) == 2

    assert tree(tmp_path) == before
    captured = capsys.readouterr()
    assert captured.err.count("one folder") == 1
    assert captured.out == (
        f"Two landing folders are one folder: {root / 'rehearsal' / 'raw'} and "
        f"{root / 'company' / 'raw'} (both resolve to {root / 'rehearsal' / 'raw'}). "
        "Nothing was written.\n"
    )


def nested_root(tmp_path: Path) -> Path:
    """A data root whose ``company/raw`` is a link into ``rehearsal/parquet/audit``."""
    root = tmp_path / "data"
    (root / "rehearsal" / "raw").mkdir(parents=True)
    (root / "rehearsal" / "parquet" / "audit").mkdir(parents=True)
    (root / "company").mkdir()
    (root / "company" / "raw").symlink_to(root / "rehearsal" / "parquet" / "audit")
    return root


@pytest.mark.parametrize("kind", ["raw", "parquet"])
def test_a_child_folder_aliased_to_the_other_data_sets_child_is_refused(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "data"
    (root / "rehearsal" / kind / "v1").mkdir(parents=True)
    (root / "company" / kind).mkdir(parents=True)
    (root / "company" / kind / "v1").symlink_to(root / "rehearsal" / kind / "v1")
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(root))

    for data_set in ("rehearsal", "company"):
        with pytest.raises(ConfigError, match="nest") as raised:
            landing_dirs(data_set)
        assert str(root / "rehearsal" / kind) in str(raised.value)
        assert str(root / "company" / kind / "v1") in str(raised.value)


def test_a_folder_nested_inside_another_data_sets_folder_is_refused_naming_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = nested_root(tmp_path)
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(root))

    for data_set in ("rehearsal", "company"):
        with pytest.raises(ConfigError, match="nest") as raised:
            landing_dirs(data_set)
        assert str(root / "rehearsal" / "parquet") in str(raised.value)
        assert str(root / "company" / "raw") in str(raised.value)


def test_convert_refuses_a_nested_data_set_and_keeps_the_other_sets_captures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = nested_root(tmp_path)
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(root))
    land(root / "company" / "raw", *session_lines("c-sess", 3))
    land(root / "rehearsal" / "raw", *session_lines("r-sess", 3))
    captures = sorted((root / "company" / "raw" / "v1").glob("*.jsonl"))
    assert captures
    before = tree(tmp_path)

    assert convert.main(["--data-set", "rehearsal"]) == 2

    assert all(path.is_file() for path in captures)
    assert tree(tmp_path) == before


# ---- the bare listener and capture ----


def test_the_bare_listener_exits_2_naming_both_data_sets_and_creates_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENRCT2_LISTENER_PORT", str(free_port()))

    assert listener.main([]) == 2

    line = capsys.readouterr().err.strip()
    assert NAMES_BOTH in line
    assert "make listen DATA_SET=rehearsal" in line
    assert not (tmp_path / "data").exists()


def test_the_bare_capture_exits_2_before_any_port_build_install_or_folder(
    tmp_path: Path,
) -> None:
    folders = Folders(tmp_path)
    (folders.user / "plugin").mkdir(parents=True)
    folders.plugin_file.parent.mkdir()
    folders.plugin_file.write_bytes(b"stand-in build\n")
    port = free_port()
    argv = command_argv(folders, port)
    at = argv.index("--data-set")
    bare = argv[:at] + argv[at + 2 :]
    before = tree(tmp_path)

    done = subprocess.run(
        bare, env=folders.env(), capture_output=True, text=True, timeout=60, check=False
    )

    assert done.returncode == 2, done.stdout + done.stderr
    assert NAMES_BOTH in done.stderr
    assert "make capture-data DATA_SET=rehearsal" in done.stderr
    assert tree(tmp_path) == before
    assert not folders.data.exists() and not folders.capture.exists()
    assert not list((folders.user / "plugin").iterdir())
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))  # still free


# ---- convert and contracts ----


@pytest.mark.parametrize(
    "argv", [[], ["--raw-dir", "raw"], ["--out-dir", "out"], ["--data-set", "staging"]]
)
def test_convert_refuses_without_a_data_set_or_both_folders(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        convert.main(argv)

    assert stopped.value.code == 2


@pytest.mark.parametrize(
    "argv", [[], ["--data-set", "rehearsal", "--data-root", "x"], ["--data-set", "x"]]
)
def test_contracts_requires_exactly_one_of_data_set_and_data_root(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        contracts.main(argv)

    assert stopped.value.code == 2


def test_convert_refuses_a_taken_lock_naming_the_file_and_its_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw, out = tmp_path / "raw", tmp_path / "parquet"
    land(raw, *session_lines("sa", 2))
    held = tmp_path / "parquet.lock"
    held.write_text("pid 4242 started 2026-10-07T10:00:00+0000\n", encoding="utf-8")
    before = tree(tmp_path)

    assert convert.main(["--raw-dir", str(raw), "--out-dir", str(out)]) == 2

    printed = capsys.readouterr().out
    assert str(held) in printed
    assert "pid 4242 started 2026-10-07T10:00:00+0000" in printed
    assert "Environments and publishing" in printed
    assert tree(tmp_path) == before


def test_convert_removes_its_lock_when_it_finishes(tmp_path: Path) -> None:
    raw, out = tmp_path / "raw", tmp_path / "parquet"
    land(raw, *session_lines("sa", 2))

    assert convert.main(["--raw-dir", str(raw), "--out-dir", str(out)]) == 0

    assert not (tmp_path / "parquet.lock").exists()


@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGHUP], ids=lambda number: number.name)
def test_a_signal_during_a_conversion_exits_130_and_leaves_no_lock(
    tmp_path: Path, number: signal.Signals
) -> None:
    raw, out, ready = tmp_path / "raw", tmp_path / "parquet", tmp_path / "ready"
    land(raw, *session_lines("sa", 2))
    child = subprocess.Popen(
        [sys.executable, "-c", HOLD_THEN_SLEEP, str(ready), str(raw), str(out)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 30
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "the child never reached the held conversion"
        assert (tmp_path / "parquet.lock").is_file()

        child.send_signal(number)
        output, _ = child.communicate(timeout=30)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate()

    assert child.returncode == 130, output
    assert not (tmp_path / "parquet.lock").exists()
    assert not out.exists()

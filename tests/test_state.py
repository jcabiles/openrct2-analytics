"""External state defaults and independent fail-closed go-live evidence."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openrct2_analytics import state
from openrct2_analytics.config import ConfigError


def test_defaults(tmp_path: Path) -> None:
    assert (
        state.default_state_dir("Darwin", tmp_path, None, None)
        == tmp_path / "Library/Application Support/openrct2-analytics"
    )
    assert (
        state.default_state_dir("Linux", tmp_path, None, None)
        == tmp_path / ".local/share/openrct2-analytics"
    )
    assert (
        state.default_state_dir("Linux", tmp_path, tmp_path / "xdg", None)
        == tmp_path / "xdg/openrct2-analytics"
    )
    assert (
        state.default_state_dir("Windows", tmp_path, None, tmp_path / "local")
        == tmp_path / "local/openrct2-analytics"
    )


@pytest.mark.parametrize("value", ["", "  "])
def test_empty_setting(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("OPENRCT2_STATE_DIR", value)
    with pytest.raises(ConfigError, match="OPENRCT2_STATE_DIR must not be empty"):
        state.state_dir()


def test_marker_writer_refuses_either_existing_marker(tmp_path: Path) -> None:
    folder, data = tmp_path / "state", tmp_path / "data"
    now = datetime.now(UTC)
    state.write_go_live_marker(folder, data, now)
    assert state.is_live(folder, data) == now.isoformat()
    for marker in state.marker_paths(folder, data):
        assert marker.exists()
        assert json.loads(marker.read_text()) == {
            "data_set": "company",
            "went_live_at": now.isoformat(),
        }
    with pytest.raises(FileExistsError):
        state.write_go_live_marker(folder, data, now)
    state.marker_paths(folder, data)[0].unlink()
    with pytest.raises(FileExistsError):
        state.write_go_live_marker(folder, data, now)
    assert not state.marker_paths(folder, data)[0].exists()


def test_dangling_marker_is_live_and_prevents_writer(tmp_path: Path) -> None:
    folder, data = tmp_path / "state", tmp_path / "data"
    marker = state.marker_paths(folder, data)[0]
    marker.parent.mkdir(parents=True)
    marker.symlink_to(tmp_path / "missing-marker-target")
    assert state.is_live(folder, data) == "unknown (unreadable state or marker)"
    with pytest.raises(FileExistsError):
        state.write_go_live_marker(folder, data, datetime.now(UTC))
    assert marker.is_symlink()
    assert not state.marker_paths(folder, data)[1].exists()


def test_no_marker_anywhere_is_not_live(tmp_path: Path) -> None:
    assert state.is_live(tmp_path / "state", tmp_path / "data") is None


@pytest.mark.parametrize("copy", [0, 1])
@pytest.mark.parametrize("broken", ["json", "unreadable"])
def test_one_broken_marker_alone_is_live(tmp_path: Path, copy: int, broken: str) -> None:
    folder, data = tmp_path / "state", tmp_path / "data"
    state.write_go_live_marker(folder, data, datetime.now(UTC))
    markers = state.marker_paths(folder, data)
    markers[1 - copy].unlink()
    target = markers[copy]
    if broken == "json":
        target.write_text("broken")
    else:
        target.chmod(0)
    try:
        assert state.is_live(folder, data)
    finally:
        target.chmod(0o600)


def test_unlistable_state_folder_without_markers_is_live(tmp_path: Path) -> None:
    folder, data = tmp_path / "state", tmp_path / "data"
    folder.mkdir()
    folder.chmod(0o300)
    try:
        assert state.is_live(folder, data)
    finally:
        folder.chmod(0o700)


@pytest.mark.parametrize("date", ["", "   "])
@pytest.mark.parametrize("copy", [0, 1])
def test_blank_marker_date_is_live_but_not_blank(tmp_path: Path, date: str, copy: int) -> None:
    folder, data = tmp_path / "state", tmp_path / "data"
    state.write_go_live_marker(folder, data, datetime.now(UTC))
    markers = state.marker_paths(folder, data)
    markers[1 - copy].unlink()
    markers[copy].write_text(json.dumps({"data_set": "company", "went_live_at": date}))
    result = state.is_live(folder, data)
    assert result
    assert result != date


def test_safety_resolves_nonexistent_descendants_and_symlinks(tmp_path: Path) -> None:
    project, data, user = tmp_path / "project", tmp_path / "data", tmp_path / "user"
    data.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(data, target_is_directory=True)
    with pytest.raises(ConfigError):
        state.check_state_dir(alias / "not-created/state", data, project, user)
    state.check_state_dir(tmp_path / "state", data, project, user)


def test_state_folder_in_other_letter_case_follows_the_disk(tmp_path: Path) -> None:
    project, data, user = tmp_path / "project", tmp_path / "data", tmp_path / "user"
    data.mkdir()
    # The disk's letter-case rule decides whether DATA and data are one folder.
    if (tmp_path / "DATA").exists():
        with pytest.raises(ConfigError):
            state.check_state_dir(tmp_path / "DATA/company/state", data, project, user)
    else:
        state.check_state_dir(tmp_path / "DATA/company/state", data, project, user)

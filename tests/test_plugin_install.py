"""Behavioral tests for the plugin-install module, on temp folders with real files and links."""

from __future__ import annotations

import os
import resource
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openrct2_analytics.config import Config
from openrct2_analytics.ingest import plugin_install as pi

FAKE_HOME = Path("/fake/home")
NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)
OLD, NEW = 1_000_000_000, 2_000_000_000  # file times in seconds


def make_config(**overrides: Path | None) -> Config:
    fields: dict[str, Path | str | int | None] = {
        "listener_host": "127.0.0.1",
        "listener_port": 8765,
        "openrct2_user_dir": None,
        "capture_dir": Path("capture"),
        "backup_dir": Path("backups"),
        "xdg_config_home": None,
        "userprofile": None,
        "home": FAKE_HOME,
    }
    fields.update(overrides)
    return Config(**fields)  # type: ignore[arg-type]


@pytest.fixture
def user_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "game"
    (folder / "plugin").mkdir(parents=True)
    return folder


@pytest.fixture
def capture_dir(tmp_path: Path) -> Path:
    return tmp_path / "capture"


@pytest.fixture
def built(tmp_path: Path) -> Path:
    path = tmp_path / "built.js"
    path.write_bytes(b"registerPlugin({name: 'x'});\n")
    return path


def test_default_user_dir_per_platform() -> None:
    assert pi.default_user_dir("Darwin", FAKE_HOME, None, None) == (
        FAKE_HOME / "Library" / "Application Support" / "OpenRCT2"
    )
    assert pi.default_user_dir("Linux", FAKE_HOME, None, None) == FAKE_HOME / ".config" / "OpenRCT2"
    assert pi.default_user_dir("Linux", FAKE_HOME, Path("/fake/xdg"), None) == Path(
        "/fake/xdg/OpenRCT2"
    )
    assert pi.default_user_dir("Windows", FAKE_HOME, None, Path("/fake/profile")) == Path(
        "/fake/profile/Documents/OpenRCT2"
    )
    assert pi.default_user_dir("Windows", FAKE_HOME, None, None) == (
        FAKE_HOME / "Documents" / "OpenRCT2"
    )


def test_unknown_platform_raises() -> None:
    with pytest.raises(ValueError, match="Plan9"):
        pi.default_user_dir("Plan9", FAKE_HOME, None, None)


def test_override_wins_over_the_platform_default() -> None:
    config = make_config(openrct2_user_dir=Path("/fake/override"), xdg_config_home=Path("/x"))
    assert pi.resolve_user_dir(config, "Linux") == Path("/fake/override")
    assert pi.resolve_user_dir(make_config(), "Darwin") == (
        FAKE_HOME / "Library" / "Application Support" / "OpenRCT2"
    )


def test_paths_under_the_user_and_capture_folders() -> None:
    assert pi.install_path(Path("u")) == Path("u/plugin/openrct2-analytics.js")
    assert pi.temp_path(Path("u")) == Path("u/plugin/.openrct2-analytics.js.capture-tmp")
    assert pi.record_path(Path("c")) == Path("c/installed-plugin.json")


# ---- record ----


def test_record_round_trips_and_deletes(capture_dir: Path) -> None:
    record = pi.InstallRecord(Path("/p/plugin.js"), "ab" * 32, NOW.isoformat())

    assert pi.read_record(capture_dir) is None
    pi.write_record(capture_dir, record)
    assert pi.read_record(capture_dir) == record
    pi.delete_record(capture_dir)
    assert pi.read_record(capture_dir) is None
    pi.delete_record(capture_dir)  # already gone is fine


def test_an_existing_record_is_never_overwritten(capture_dir: Path) -> None:
    first = pi.InstallRecord(Path("/p/one.js"), "ab" * 32, NOW.isoformat())
    pi.write_record(capture_dir, first)

    with pytest.raises(pi.RecordError, match="already exists"):
        pi.write_record(capture_dir, pi.InstallRecord(Path("/p/two.js"), "cd" * 32, "later"))

    assert pi.read_record(capture_dir) == first
    assert [p.name for p in capture_dir.iterdir()] == [pi.RECORD_FILE_NAME]


def test_a_link_planted_at_the_scratch_name_is_replaced_not_followed(
    capture_dir: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("untouched")
    capture_dir.mkdir()
    (capture_dir / pi.RECORD_TEMP_NAME).symlink_to(outside)
    record = pi.InstallRecord(Path("/p/plugin.js"), "ab" * 32, NOW.isoformat())

    pi.write_record(capture_dir, record)

    assert outside.read_text() == "untouched"
    assert pi.read_record(capture_dir) == record
    assert [p.name for p in capture_dir.iterdir()] == [pi.RECORD_FILE_NAME]


def test_unreadable_record_raises(capture_dir: Path) -> None:
    capture_dir.mkdir()
    pi.record_path(capture_dir).write_text("{not json")

    with pytest.raises(pi.RecordError, match="installed-plugin.json"):
        pi.read_record(capture_dir)


# ---- classification ----


def record_for(user_dir: Path, content: bytes) -> pi.InstallRecord:
    probe = user_dir / "probe"
    probe.write_bytes(content)
    record = pi.InstallRecord(pi.install_path(user_dir), pi.sha256_file(probe), NOW.isoformat())
    probe.unlink()
    return record


def test_absent_install_path(user_dir: Path) -> None:
    assert pi.classify_install_path(user_dir, None) is pi.InstallState.ABSENT


def test_own_file_is_a_leftover(user_dir: Path) -> None:
    record = record_for(user_dir, b"ours")
    pi.install_path(user_dir).write_bytes(b"ours")

    assert pi.classify_install_path(user_dir, record) is pi.InstallState.LEFTOVER


def test_file_with_a_different_hash_is_foreign(user_dir: Path) -> None:
    record = record_for(user_dir, b"ours")
    pi.install_path(user_dir).write_bytes(b"theirs")

    assert pi.classify_install_path(user_dir, record) is pi.InstallState.FOREIGN


def test_file_without_a_record_is_foreign(user_dir: Path) -> None:
    pi.install_path(user_dir).write_bytes(b"ours")

    assert pi.classify_install_path(user_dir, None) is pi.InstallState.FOREIGN


def test_record_naming_another_path_is_refused_even_when_the_file_is_absent(
    user_dir: Path,
) -> None:
    record = pi.InstallRecord(Path("/elsewhere/openrct2-analytics.js"), "0" * 64, NOW.isoformat())

    assert pi.classify_install_path(user_dir, record) is pi.InstallState.RECORD_ELSEWHERE


def test_symlink_is_unsafe_and_never_followed(user_dir: Path, tmp_path: Path) -> None:
    target = tmp_path / "target.js"
    target.write_bytes(b"ours")
    record = record_for(user_dir, b"ours")
    pi.install_path(user_dir).symlink_to(target)

    assert pi.classify_install_path(user_dir, record) is pi.InstallState.UNSAFE


def test_directory_is_unsafe(user_dir: Path) -> None:
    pi.install_path(user_dir).mkdir()

    assert pi.classify_install_path(user_dir, None) is pi.InstallState.UNSAFE


def test_fifo_is_unsafe_and_is_not_opened(user_dir: Path) -> None:
    os.mkfifo(pi.install_path(user_dir))

    assert pi.classify_install_path(user_dir, None) is pi.InstallState.UNSAFE


def test_extra_hard_link_is_unsafe(user_dir: Path, tmp_path: Path) -> None:
    record = record_for(user_dir, b"ours")
    pi.install_path(user_dir).write_bytes(b"ours")
    os.link(pi.install_path(user_dir), tmp_path / "other-name")

    assert pi.classify_install_path(user_dir, record) is pi.InstallState.UNSAFE


def test_own_temporary_link_does_not_make_the_file_unsafe(user_dir: Path) -> None:
    record = record_for(user_dir, b"ours")
    pi.install_path(user_dir).write_bytes(b"ours")
    os.link(pi.install_path(user_dir), pi.temp_path(user_dir))

    assert pi.classify_install_path(user_dir, record) is pi.InstallState.LEFTOVER


def test_a_different_file_at_the_temporary_name_does_not_excuse_two_links(
    user_dir: Path,
) -> None:
    pi.install_path(user_dir).write_bytes(b"ours")
    pi.temp_path(user_dir).write_bytes(b"ours")  # same bytes, but a separate file
    os.link(pi.install_path(user_dir), user_dir / "plugin" / "third")
    record = record_for(user_dir, b"ours")

    assert pi.classify_install_path(user_dir, record) is pi.InstallState.UNSAFE


def test_a_third_link_beside_the_temporary_name_is_unsafe(user_dir: Path) -> None:
    record = record_for(user_dir, b"ours")
    pi.install_path(user_dir).write_bytes(b"ours")
    os.link(pi.install_path(user_dir), pi.temp_path(user_dir))
    os.link(pi.install_path(user_dir), user_dir / "plugin" / "third")

    assert pi.classify_install_path(user_dir, record) is pi.InstallState.UNSAFE


def test_temporary_file_states(user_dir: Path) -> None:
    record = record_for(user_dir, b"ours")
    assert pi.classify_temp(user_dir, record) is pi.TempState.ABSENT

    pi.temp_path(user_dir).write_bytes(b"ours")
    assert pi.classify_temp(user_dir, record) is pi.TempState.OWN
    assert pi.classify_temp(user_dir, None) is pi.TempState.OTHER

    pi.temp_path(user_dir).write_bytes(b"theirs")
    assert pi.classify_temp(user_dir, record) is pi.TempState.OTHER


def test_temporary_symlink_is_other(user_dir: Path, tmp_path: Path) -> None:
    target = tmp_path / "t"
    target.write_bytes(b"ours")
    record = record_for(user_dir, b"ours")
    pi.temp_path(user_dir).symlink_to(target)

    assert pi.classify_temp(user_dir, record) is pi.TempState.OTHER


# ---- scan ----


def test_scan_finds_other_files_that_register_the_plugin_name(user_dir: Path) -> None:
    plugin_dir = user_dir / "plugin"
    (plugin_dir / "deep" / "er").mkdir(parents=True)
    twin = plugin_dir / "deep" / "er" / "renamed.js"
    twin.write_text('registerPlugin({name: "openrct2-analytics"})')
    (plugin_dir / "only-register.js").write_text("registerPlugin({name: 'other'})")
    (plugin_dir / "only-name.js").write_text('"openrct2-analytics"')
    (plugin_dir / "notes.txt").write_text('registerPlugin "openrct2-analytics"')
    (plugin_dir / "binary.js").write_bytes(b'\xff\xfe registerPlugin "openrct2-analytics"')
    pi.install_path(user_dir).write_text('registerPlugin({name: "openrct2-analytics"})')

    found = pi.find_other_plugin_files(user_dir)

    assert found == [plugin_dir / "binary.js", twin]


# ---- install ----


def test_install_publishes_the_file_with_a_record_and_no_temporary_name(
    user_dir: Path, capture_dir: Path, built: Path
) -> None:
    record = pi.install(user_dir, capture_dir, built, now=NOW)

    target = pi.install_path(user_dir)
    assert target.read_bytes() == built.read_bytes()
    assert target.stat().st_nlink == 1
    assert not pi.temp_path(user_dir).exists()
    assert pi.read_record(capture_dir) == record
    assert record.path == target
    assert record.sha256 == pi.sha256_file(built)
    assert record.installed_at == "2026-09-30T12:00:00+00:00"
    assert pi.classify_install_path(user_dir, record) is pi.InstallState.LEFTOVER


def test_a_file_that_appears_after_the_checks_survives_the_install(
    user_dir: Path, capture_dir: Path, built: Path
) -> None:
    assert pi.classify_install_path(user_dir, None) is pi.InstallState.ABSENT
    pi.install_path(user_dir).write_bytes(b"someone else's plugin")

    with pytest.raises(pi.InstallRaceError, match="appeared"):
        pi.install(user_dir, capture_dir, built, now=NOW)

    assert pi.install_path(user_dir).read_bytes() == b"someone else's plugin"
    assert not pi.temp_path(user_dir).exists()
    assert pi.read_record(capture_dir) is None


def test_a_foreign_file_at_the_temporary_name_is_not_overwritten(
    user_dir: Path, capture_dir: Path, built: Path
) -> None:
    pi.temp_path(user_dir).write_bytes(b"not ours")

    with pytest.raises(pi.InstallRaceError):
        pi.install(user_dir, capture_dir, built, now=NOW)

    assert pi.temp_path(user_dir).read_bytes() == b"not ours"
    assert not pi.install_path(user_dir).exists()
    assert pi.read_record(capture_dir) is None


def test_install_refuses_while_a_record_exists_and_leaves_the_plugin_folder_alone(
    user_dir: Path, capture_dir: Path, built: Path
) -> None:
    earlier = pi.InstallRecord(pi.install_path(user_dir), "ab" * 32, NOW.isoformat())
    pi.write_record(capture_dir, earlier)

    with pytest.raises(pi.RecordError, match="already exists"):
        pi.install(user_dir, capture_dir, built, now=NOW)

    assert list((user_dir / "plugin").iterdir()) == []
    assert pi.read_record(capture_dir) == earlier


def test_the_record_is_written_before_any_plugin_file_exists(
    user_dir: Path, tmp_path: Path, built: Path
) -> None:
    blocked = tmp_path / "not-a-folder"
    blocked.write_text("a regular file where the capture folder should be")

    with pytest.raises(OSError):  # noqa: PT011  # the exact errno is the platform's
        pi.install(user_dir, blocked, built, now=NOW)

    assert not pi.install_path(user_dir).exists()
    assert not pi.temp_path(user_dir).exists()


def test_a_failed_temporary_write_removes_the_temporary_file_and_the_record(
    user_dir: Path, capture_dir: Path, tmp_path: Path
) -> None:
    big = tmp_path / "big.js"
    big.write_bytes(b"x" * 200_000)
    resource.setrlimit(resource.RLIMIT_FSIZE, (50_000, resource.RLIM_INFINITY))
    try:
        with pytest.raises(OSError, match="too large"):
            pi.install(user_dir, capture_dir, big, now=NOW)
    finally:
        resource.setrlimit(resource.RLIMIT_FSIZE, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))

    assert not pi.temp_path(user_dir).exists()
    assert not pi.install_path(user_dir).exists()
    assert pi.read_record(capture_dir) is None
    pi.install(user_dir, capture_dir, big, now=NOW)  # the next install is not wedged


# ---- removal ----


def test_removal_without_a_record_touches_nothing(user_dir: Path, capture_dir: Path) -> None:
    pi.install_path(user_dir).write_bytes(b"theirs")

    assert pi.remove_installed(user_dir, capture_dir) is pi.RemovalOutcome.NO_RECORD
    assert pi.install_path(user_dir).read_bytes() == b"theirs"


def test_removal_deletes_our_file_then_the_record(
    user_dir: Path, capture_dir: Path, built: Path
) -> None:
    pi.install(user_dir, capture_dir, built, now=NOW)

    assert pi.remove_installed(user_dir, capture_dir) is pi.RemovalOutcome.REMOVED
    assert not pi.install_path(user_dir).exists()
    assert pi.read_record(capture_dir) is None


def test_removal_after_a_kill_between_publish_and_cleanup_removes_both_names(
    user_dir: Path, capture_dir: Path, built: Path
) -> None:
    record = pi.install(user_dir, capture_dir, built, now=NOW)
    pi.install_path(user_dir).unlink()
    pi.temp_path(user_dir).write_bytes(built.read_bytes())
    os.link(pi.temp_path(user_dir), pi.install_path(user_dir))  # the state a kill leaves
    assert pi.classify_install_path(user_dir, record) is pi.InstallState.LEFTOVER

    assert pi.remove_installed(user_dir, capture_dir) is pi.RemovalOutcome.REMOVED
    assert not pi.install_path(user_dir).exists()
    assert not pi.temp_path(user_dir).exists()
    assert pi.read_record(capture_dir) is None


def test_removal_clears_a_record_when_neither_file_exists(
    user_dir: Path, capture_dir: Path, built: Path
) -> None:
    pi.install(user_dir, capture_dir, built, now=NOW)
    pi.install_path(user_dir).unlink()

    assert pi.remove_installed(user_dir, capture_dir) is pi.RemovalOutcome.RECORD_CLEARED
    assert pi.read_record(capture_dir) is None


def test_removal_leaves_a_changed_file_and_keeps_the_record(
    user_dir: Path, capture_dir: Path, built: Path
) -> None:
    record = pi.install(user_dir, capture_dir, built, now=NOW)
    pi.install_path(user_dir).unlink()
    pi.install_path(user_dir).write_bytes(b"replaced by the player")

    assert pi.remove_installed(user_dir, capture_dir) is pi.RemovalOutcome.NOT_OURS
    assert pi.install_path(user_dir).read_bytes() == b"replaced by the player"
    assert pi.read_record(capture_dir) == record


def test_removal_leaves_a_record_for_another_path_alone(
    user_dir: Path, capture_dir: Path, built: Path
) -> None:
    record = pi.install(user_dir, capture_dir, built, now=NOW)
    other = user_dir.parent / "other-game"
    (other / "plugin").mkdir(parents=True)

    assert pi.remove_installed(other, capture_dir) is pi.RemovalOutcome.NOT_OURS
    assert pi.install_path(user_dir).exists()
    assert pi.read_record(capture_dir) == record


def test_failed_removal_keeps_the_record_and_reports_it(
    user_dir: Path, capture_dir: Path, built: Path
) -> None:
    record = pi.install(user_dir, capture_dir, built, now=NOW)
    plugin_dir = user_dir / "plugin"
    plugin_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)  # a folder that forbids unlinking
    try:
        with pytest.raises(pi.RemovalError, match="record was kept"):
            pi.remove_installed(user_dir, capture_dir)
    finally:
        plugin_dir.chmod(stat.S_IRWXU)

    assert pi.install_path(user_dir).exists()
    assert pi.read_record(capture_dir) == record


@pytest.mark.parametrize("shape", ["symlink", "extra_hard_link"])
def test_removal_refuses_a_symlink_or_an_extra_hard_link_and_keeps_the_record(
    user_dir: Path, capture_dir: Path, built: Path, shape: str
) -> None:
    record = pi.install(user_dir, capture_dir, built, now=NOW)
    target = pi.install_path(user_dir)
    other = user_dir.parent / "other-name"
    if shape == "symlink":
        target.unlink()
        other.write_bytes(built.read_bytes())  # the recorded bytes, behind a symlink
        target.symlink_to(other)
    else:
        os.link(target, other)

    assert pi.remove_installed(user_dir, capture_dir) is pi.RemovalOutcome.NOT_OURS

    assert target.is_symlink() == (shape == "symlink")
    assert target.exists()
    assert other.read_bytes() == built.read_bytes()
    assert pi.read_record(capture_dir) == record

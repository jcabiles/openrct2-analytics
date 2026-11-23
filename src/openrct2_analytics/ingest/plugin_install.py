"""Find the player's OpenRCT2 folder, build the plugin, and prove which plugin file is ours.

This is the one module that decides whether a file in the player's plugin folder was
installed by the capture command. The proof is an install record
(``<capture dir>/installed-plugin.json``: install path, SHA-256 of the installed bytes,
install time): a file is the command's own only when it is a plain, singly linked file at
the recorded install path whose SHA-256 equals the record. Nothing else is ever
overwritten or deleted.

Install order: write the record, copy the built plugin to a temporary name the game never
loads (no ``.js`` suffix), publish it with a hard link (which fails instead of overwriting),
remove the temporary name. A process killed anywhere in that sequence leaves only files
that ``remove_installed`` can prove are ours.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from openrct2_analytics.config import Config

PLUGIN_FILE_NAME = "openrct2-analytics.js"
TEMP_FILE_NAME = ".openrct2-analytics.js.capture-tmp"
RECORD_FILE_NAME = "installed-plugin.json"
RECORD_TEMP_NAME = ".installed-plugin.json.tmp"
BUILT_PLUGIN = Path("plugin") / "dist" / PLUGIN_FILE_NAME
BUILD_COMMAND = ("npm", "run", "--silent", "plugin:build")
# A plugin file that registers itself under our name would load beside ours.
PLUGIN_MARKERS = (b"registerPlugin", b'"openrct2-analytics"')
# The install path plus the command's own temporary name.
LINKS_WITH_TEMP_NAME = 2


class BuildError(Exception):
    """Raised when the plugin build fails; the message carries the compiler output."""


class RecordError(Exception):
    """Raised when the install record cannot be read, or one already exists at install time."""


class InstallRaceError(Exception):
    """Raised when a file appeared at the install or temporary path; that file was left alone."""


class RemovalError(Exception):
    """Raised when a file proven ours could not be removed; the install record was kept."""


class InstallState(Enum):
    """What the install path holds, judged against the install record."""

    ABSENT = "absent"
    LEFTOVER = "leftover"  # the command's own file: recorded path, same SHA-256, safe shape
    FOREIGN = "foreign"  # a plain file the command did not install
    UNSAFE = "unsafe"  # symlink, not a regular file, or linked more than once
    RECORD_ELSEWHERE = "record_elsewhere"  # the record names a different install path


class TempState(Enum):
    """What the temporary name holds, judged against the install record."""

    ABSENT = "absent"
    OWN = "own"  # a regular file whose SHA-256 equals the record
    OTHER = "other"


class RemovalOutcome(Enum):
    """What ``remove_installed`` did."""

    NO_RECORD = "no_record"  # nothing to do
    REMOVED = "removed"  # removed our file or temporary file, then the record
    RECORD_CLEARED = "record_cleared"  # neither of our files existed; only the record went
    NOT_OURS = "not_ours"  # the file at the install path is not proven ours; nothing touched


@dataclass(frozen=True)
class InstallRecord:
    """The proof that the command installed a file.

    Attributes:
        path: The install path the command published.
        sha256: SHA-256 hex digest of the installed bytes.
        installed_at: ISO-8601 UTC time of the install.
    """

    path: Path
    sha256: str
    installed_at: str


def default_user_dir(
    system: str, home: Path, xdg_config_home: Path | None, userprofile: Path | None
) -> Path:
    """Return OpenRCT2's standard user folder for a platform.

    Args:
        system: ``platform.system()``: "Darwin", "Linux" or "Windows".
        home: The player's home folder.
        xdg_config_home: ``XDG_CONFIG_HOME`` if set (Linux).
        userprofile: ``USERPROFILE`` if set (Windows); falls back to ``home``.

    Returns:
        The default folder, which may not exist.

    Raises:
        ValueError: if ``system`` is not one of the three platforms.
    """
    if system == "Darwin":
        return home / "Library" / "Application Support" / "OpenRCT2"
    if system == "Linux":
        return (xdg_config_home or home / ".config") / "OpenRCT2"
    if system == "Windows":
        return (userprofile or home) / "Documents" / "OpenRCT2"
    raise ValueError(f"Unsupported platform: {system!r}")


def resolve_user_dir(config: Config, system: str) -> Path:
    """Return ``OPENRCT2_USER_DIR`` when set, else ``default_user_dir`` for the platform."""
    if config.openrct2_user_dir is not None:
        return config.openrct2_user_dir
    return default_user_dir(system, config.home, config.xdg_config_home, config.userprofile)


def install_path(user_dir: Path) -> Path:
    """Return where the plugin is installed under a user folder."""
    return user_dir / "plugin" / PLUGIN_FILE_NAME


def temp_path(user_dir: Path) -> Path:
    """Return the command's temporary name, which the game never loads."""
    return user_dir / "plugin" / TEMP_FILE_NAME


def record_path(capture_dir: Path) -> Path:
    """Return where the install record lives."""
    return capture_dir / RECORD_FILE_NAME


def build_plugin(repo_root: Path) -> Path:
    """Run ``npm run --silent plugin:build`` in ``repo_root`` and return the built file.

    The compiler writes its output even on a type error, so a failed build deletes the
    output: a failed build can never be installed by a later run.

    Raises:
        BuildError: if npm is missing, the build exits non-zero (carrying its output), or
            it exits zero without writing the output.
    """
    built = repo_root / BUILT_PLUGIN
    built.unlink(missing_ok=True)  # only this build's output may be installed
    try:
        result = subprocess.run(  # noqa: S603  # fixed argument list, no shell
            BUILD_COMMAND, cwd=repo_root, capture_output=True, text=True, check=False
        )
    except FileNotFoundError as exc:
        raise BuildError("npm was not found on PATH") from exc
    if result.returncode != 0:
        built.unlink(missing_ok=True)
        raise BuildError((result.stdout + result.stderr).strip() or "build failed with no output")
    if not built.is_file():
        raise BuildError(f"The build exited cleanly but wrote no {built}.")
    return built


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_record(capture_dir: Path) -> InstallRecord | None:
    """Return the install record, or None when there is none.

    Raises:
        RecordError: if the record file exists but is not a valid record.
    """
    path = record_path(capture_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return InstallRecord(Path(raw["path"]), str(raw["sha256"]), str(raw["installed_at"]))
    except FileNotFoundError:
        return None
    except (ValueError, KeyError, TypeError) as exc:
        raise RecordError(f"The install record {path} is not valid: {exc}") from exc


def write_record(capture_dir: Path, record: InstallRecord) -> None:
    """Write the install record atomically, creating the capture folder if needed.

    The record is written to a sibling file and hard-linked to its name, so a kill never
    leaves a torn record and an existing record is never overwritten.

    Raises:
        RecordError: if an install record already exists.
    """
    capture_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "path": str(record.path),
        "sha256": record.sha256,
        "installed_at": record.installed_at,
    }
    final = record_path(capture_dir)
    sibling = capture_dir / RECORD_TEMP_NAME
    # Unlink first, then create exclusively: a sibling left by a killed run must not wedge
    # the next one, and a link planted at the scratch name is removed, never written through.
    sibling.unlink(missing_ok=True)
    with sibling.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2) + "\n")
    try:
        os.link(sibling, final)  # raises instead of overwriting
    except FileExistsError as exc:
        raise RecordError(f"An install record already exists at {final}; it was kept.") from exc
    finally:
        sibling.unlink(missing_ok=True)


def delete_record(capture_dir: Path) -> None:
    """Delete the install record; already gone is fine."""
    record_path(capture_dir).unlink(missing_ok=True)


def _lstat_or_none(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _is_plain_file(info: os.stat_result) -> bool:
    return stat.S_ISREG(info.st_mode)  # false for a symlink, since the stat is an lstat


def classify_install_path(user_dir: Path, record: InstallRecord | None) -> InstallState:
    """Judge the install path against the record; reads the file only when its shape is safe."""
    target = install_path(user_dir)
    if record is not None and record.path != target:
        return InstallState.RECORD_ELSEWHERE
    info = _lstat_or_none(target)
    if info is None:
        return InstallState.ABSENT
    if not _is_plain_file(info) or (info.st_nlink > 1 and not _only_temp_link(user_dir, info)):
        return InstallState.UNSAFE
    if record is not None and sha256_file(target) == record.sha256:
        return InstallState.LEFTOVER
    return InstallState.FOREIGN


def _only_temp_link(user_dir: Path, info: os.stat_result) -> bool:
    """True when the one other hard link is the command's own temporary name (same file)."""
    temp = _lstat_or_none(temp_path(user_dir))
    return (
        info.st_nlink == LINKS_WITH_TEMP_NAME
        and temp is not None
        and (temp.st_dev, temp.st_ino) == (info.st_dev, info.st_ino)
    )


def classify_temp(user_dir: Path, record: InstallRecord | None) -> TempState:
    """Judge the temporary name against the record."""
    temp = temp_path(user_dir)
    info = _lstat_or_none(temp)
    if info is None:
        return TempState.ABSENT
    if record is not None and _is_plain_file(info) and sha256_file(temp) == record.sha256:
        return TempState.OWN
    return TempState.OTHER


def find_other_plugin_files(user_dir: Path) -> list[Path]:
    """Return other ``.js`` files under the plugin folder that register ``openrct2-analytics``.

    The install path itself is excluded. Files are matched on bytes, so unreadable text
    encodings cannot hide a match.
    """
    own = install_path(user_dir)
    found = []
    for candidate in sorted((user_dir / "plugin").rglob("*.js")):
        if candidate == own or not candidate.is_file():
            continue
        data = candidate.read_bytes()
        if all(marker in data for marker in PLUGIN_MARKERS):
            found.append(candidate)
    return found


def install(
    user_dir: Path, capture_dir: Path, built_file: Path, now: datetime | None = None
) -> InstallRecord:
    """Install the built plugin: record, temporary copy, hard-link publish, remove temp name.

    The caller has already checked that the install path is absent. If a file appears
    there (or at the temporary name) afterwards, it is left alone, the record is deleted
    so it matches what is on disk, and ``InstallRaceError`` is raised.

    Raises:
        RecordError: if an install record already exists; nothing is touched.
        InstallRaceError: if a file appeared at the install or temporary path.
        OSError: if writing the temporary copy failed; the temporary file and the record
            are removed first.
    """
    data = built_file.read_bytes()
    stamp = (now or datetime.now(UTC)).isoformat()
    target, temp = install_path(user_dir), temp_path(user_dir)
    record = InstallRecord(target, hashlib.sha256(data).hexdigest(), stamp)
    write_record(capture_dir, record)
    try:
        handle = temp.open("xb")  # "x": never overwrite a file we did not create
    except FileExistsError as exc:
        delete_record(capture_dir)
        raise InstallRaceError(f"A file already exists at {temp}; it was left alone.") from exc
    try:
        with handle:
            handle.write(data)
    except OSError:
        temp.unlink(missing_ok=True)  # "xb" succeeded, so this file is provably our own
        delete_record(capture_dir)
        raise
    try:
        os.link(temp, target)  # raises instead of overwriting
    except FileExistsError as exc:
        temp.unlink()
        delete_record(capture_dir)
        raise InstallRaceError(f"A file appeared at {target}; it was left alone.") from exc
    temp.unlink()
    return record


def remove_installed(user_dir: Path, capture_dir: Path) -> RemovalOutcome:
    """Remove the command's own plugin file and temporary name, then the record.

    Used both for a normal exit and for leftovers from a killed session. A file is removed
    only when proven ours (``classify_install_path`` and ``classify_temp``). The record is
    deleted only after our files are gone; anything not proven ours is untouched and the
    record is kept.

    Raises:
        RemovalError: if removing one of our files failed; the record is kept.
    """
    record = read_record(capture_dir)
    if record is None:
        return RemovalOutcome.NO_RECORD
    state = classify_install_path(user_dir, record)
    if state not in (InstallState.ABSENT, InstallState.LEFTOVER):
        return RemovalOutcome.NOT_OURS
    doomed = [install_path(user_dir)] if state is InstallState.LEFTOVER else []
    if classify_temp(user_dir, record) is TempState.OWN:
        doomed.append(temp_path(user_dir))
    for path in doomed:
        try:
            path.unlink()
        except OSError as exc:
            raise RemovalError(
                f"Could not remove {path}: {exc}; the install record was kept."
            ) from exc
    delete_record(capture_dir)
    return RemovalOutcome.REMOVED if doomed else RemovalOutcome.RECORD_CLEARED

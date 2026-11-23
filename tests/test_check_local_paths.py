"""Behavioral tests for scripts/check_local_paths.py, on real temporary git repos.

Cases, from the spec (R1 to R7 and R9) and its ticket. The per-form cases (R1: every form, each
left-boundary and following-character guard, drive letters, file links) are in
`tests/test_check_local_paths_forms.py`.
- R2: a shared-folder path is reported; so is a line with a shared-folder path plus a
  home-folder path; there is no exemption.
- R3: an untracked file with a path exits 0; after `git add` it exits 1.
- R4: a text file with one undecodable byte plus a path is reported; a NUL-byte file holding a
  path is skipped.
- R5: a tracked file deleted from the work tree does not fail the run; an unreadable file
  exits non-zero naming the file; a file in a merge conflict is reported once.
- Review fixes: a read error after the file check, and a symlink target, are reported.
- R6: `main` returns 1 on a hit and 0 on a clean repo; the ROOT argument is honoured; a folder
  outside any git work tree is walked; a ROOT that does not exist exits 2.
- R7: the script finds itself clean.
- R9: every planted path is joined from parts here, so this file holds no path of any form.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import check_local_paths

SLASH = "/"
MESSAGE = "absolute local path (reword it, or build it at run time in a test)"
SCRIPT = Path(check_local_paths.__file__)

USERS = SLASH + "Users" + SLASH + "alice"
SHARED = SLASH + "Users" + SLASH + "Shared" + SLASH + "setup"


def report(*hits: str) -> str:
    """Return the exact stderr for the given `path:line` hits."""
    lines = [f"{hit}: {MESSAGE}" for hit in hits]
    return "\n".join([*lines, f"check_local_paths: {len(hits)} problem(s)."]) + "\n"


def make_repo(root: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


def write(root: Path, name: str, content: str | bytes) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)


def track(root: Path, name: str) -> None:
    subprocess.run(["git", "add", name], cwd=root, check=True)


def planted(root: Path, content: str | bytes, name: str = "notes.md") -> None:
    write(root, name, content)
    track(root, name)


def run(root: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = check_local_paths.main([str(root)])
    return code, capsys.readouterr().err


def test_clean_repo_returns_zero_and_prints_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    planted(make_repo(tmp_path), "no paths here\nrelative/dir/file.txt\n~/notes and $HOME/x\n")

    assert run(tmp_path, capsys) == (0, "")


def test_shared_folder_path_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    planted(make_repo(tmp_path), f"copy to {SHARED}\n")

    assert run(tmp_path, capsys) == (1, report("notes.md:1"))


def test_line_with_shared_and_home_folder_paths_is_reported_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    planted(make_repo(tmp_path), f"ok\ncopy {SHARED} to {USERS}\n")

    assert run(tmp_path, capsys) == (1, report("notes.md:2"))


def test_each_hit_line_and_file_is_reported_in_path_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    planted(root, f"{USERS}\nclean\n{SHARED}\n", "b.md")
    planted(root, f"{USERS}\n", "a.md")

    code, err = run(root, capsys)

    assert code == 1
    assert err == report("a.md:1", "b.md:1", "b.md:3")


def test_untracked_file_is_not_checked_and_tracking_it_fails_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    write(root, "scratch.md", f"see {USERS}\n")

    assert run(root, capsys) == (0, "")

    track(root, "scratch.md")

    assert run(root, capsys) == (1, report("scratch.md:1"))


def test_undecodable_byte_does_not_hide_a_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    planted(make_repo(tmp_path), b"bad \xff byte\nsee " + USERS.encode() + b"\n")

    assert run(tmp_path, capsys) == (1, report("notes.md:2"))


def test_file_with_a_nul_byte_is_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    planted(make_repo(tmp_path), b"see " + USERS.encode() + b"\n", "data.bin")
    write(tmp_path, "data.bin", b"see " + USERS.encode() + b"\x00\n")

    assert run(tmp_path, capsys) == (0, "")


def test_tracked_file_deleted_from_the_work_tree_does_not_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    planted(root, f"see {USERS}\n", "gone.md")
    (root / "gone.md").unlink()

    assert run(root, capsys) == (0, "")


def test_unreadable_file_exits_nonzero_naming_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A tracked name past the 255-byte limit makes the file system refuse the lookup for every
    # user, root included, so no permission trick is needed. The entry is added to the index
    # alone, because such a file cannot be created.
    root = make_repo(tmp_path)
    planted(root, "fine\n", "clean.md")
    name = "x" * 300 + ".md"
    blob = (
        subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            cwd=root,
            input=b"text\n",
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .strip()
    )
    subprocess.run(
        ["git", "update-index", "--add", "--cacheinfo", f"100644,{blob},{name}"],
        cwd=root,
        check=True,
    )

    code, err = run(root, capsys)

    assert code == 1
    assert err == f"check_local_paths: cannot read {root / name}: File name too long\n"


def test_a_read_error_after_the_file_check_exits_nonzero_naming_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path)
    planted(root, "fine\n", "clean.md")
    planted(root, "text\n", "locked.md")
    real_read_bytes = Path.read_bytes

    def read_bytes(self: Path) -> bytes:
        if self.name == "locked.md":
            raise PermissionError(13, "Permission denied", str(self))
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)

    code, err = run(root, capsys)

    assert code == 1
    assert err == f"check_local_paths: cannot read {root / 'locked.md'}: Permission denied\n"


def link(root: Path, name: str, target: str) -> None:
    os.symlink(target, root / name)
    track(root, name)


def test_a_symlink_target_with_a_private_path_is_reported_naming_the_link(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    planted(root, "fine\n", "clean.md")
    link(root, "shortcut", USERS + SLASH + "notes.md")

    assert run(root, capsys) == (1, report("shortcut:1"))


def test_a_symlink_target_inside_the_repo_is_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    planted(root, "fine\n", "clean.md")
    link(root, "shortcut", "clean.md")

    assert run(root, capsys) == (0, "")


def git(root: Path, *args: str) -> None:
    identity = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", *identity, *args], cwd=root, check=True, capture_output=True)


def test_a_file_in_a_merge_conflict_is_reported_once_per_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    planted(root, "base\n")
    git(root, "commit", "-m", "base")
    git(root, "switch", "-c", "side")
    write(root, "notes.md", f"see {USERS}\n")
    git(root, "commit", "-am", "side")
    git(root, "switch", "-")
    write(root, "notes.md", f"see {SHARED}\n")
    git(root, "commit", "-am", "main")
    merge = subprocess.run(["git", "merge", "side"], cwd=root, capture_output=True, check=False)
    assert merge.returncode == 1  # a real conflict: git lists notes.md in three stages

    # Lines: the marker, the current side, the divider, the other side, the marker.
    assert run(root, capsys) == (1, report("notes.md:2", "notes.md:4"))


def test_a_root_that_does_not_exist_exits_two_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "absent"

    assert run(missing, capsys) == (2, f"check_local_paths: not a folder: {missing}\n")


def test_root_argument_is_honoured(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dirty, clean = tmp_path / "dirty", tmp_path / "clean"
    dirty.mkdir()
    clean.mkdir()
    planted(make_repo(dirty), f"{USERS}\n")
    planted(make_repo(clean), "fine\n")

    assert run(dirty, capsys) == (1, report("notes.md:1"))
    assert run(clean, capsys) == (0, "")


def test_folder_outside_any_git_work_tree_is_walked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "sub/notes.md", f"see {USERS}\n")
    write(tmp_path, "node_modules/pkg/x.md", f"see {USERS}\n")

    assert run(tmp_path, capsys) == (1, report("sub/notes.md:1"))


def test_the_script_finds_itself_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    planted(make_repo(tmp_path), SCRIPT.read_text(encoding="utf-8"), "check_local_paths.py")

    assert run(tmp_path, capsys) == (0, "")

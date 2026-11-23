"""Behavioral tests for scripts/check_file_sizes.py, on real temporary folders and git repos."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import check_file_sizes

WHERE = "in `BASELINE` in `scripts/check_file_sizes.py`"


def write_lines(path: Path, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x = 1\n" * count, encoding="utf-8")


def git_init(root: Path, gitignore: str = "") -> Path:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / ".gitignore").write_text(gitignore, encoding="utf-8")
    return root


def test_file_at_the_limit_passes_and_one_over_fails(tmp_path: Path) -> None:
    write_lines(tmp_path / "src" / "ok.py", 500)
    write_lines(tmp_path / "web" / "big.tsx", 501)

    problems = check_file_sizes.find_problems(tmp_path, baseline={})

    assert problems == [
        "web/big.tsx: 501 lines, over the 500-line limit. Split it by responsibility."
    ]


@pytest.mark.parametrize("suffix", [".py", ".ts", ".tsx", ".css", ".sql", ".mjs"])
def test_every_checked_language_is_limited(tmp_path: Path, suffix: str) -> None:
    write_lines(tmp_path / f"big{suffix}", 501)

    assert len(check_file_sizes.find_problems(tmp_path, baseline={})) == 1


def test_git_checkout_skips_gitignored_files(tmp_path: Path) -> None:
    root = git_init(tmp_path, "venv/\ndbt_packages/\n")
    write_lines(root / "venv" / "lib" / "site.py", 900)
    write_lines(root / "dbt_packages" / "pkg" / "model.sql", 900)

    assert check_file_sizes.find_problems(root, baseline={}) == []


def test_git_checkout_counts_real_folders_with_generic_names(tmp_path: Path) -> None:
    root = git_init(tmp_path)
    write_lines(root / "src" / "app" / "local" / "big.py", 501)
    write_lines(root / "src" / "app" / "target" / "big.sql", 501)

    assert check_file_sizes.find_problems(root, baseline={}) == [
        "src/app/local/big.py: 501 lines, over the 500-line limit. Split it by responsibility.",
        "src/app/target/big.sql: 501 lines, over the 500-line limit. Split it by responsibility.",
    ]


def test_monorepo_subfolder_uses_the_outer_repos_gitignore(tmp_path: Path) -> None:
    git_init(tmp_path, "venv/\n")
    project = tmp_path / "apps" / "service"
    write_lines(project / "venv" / "lib" / "site.py", 900)
    write_lines(project / "src" / "big.py", 501)

    assert check_file_sizes.find_problems(project, baseline={}) == [
        "src/big.py: 501 lines, over the 500-line limit. Split it by responsibility."
    ]


@pytest.mark.parametrize(
    ("git_file", "git_message"),
    [
        ("garbage\n", "invalid gitfile format"),
        # git 2.55 on Linux prints "(null)" where older gits print the path.
        (
            "gitdir: /nonexistent/repo\n",
            "not a git repository|gitfile does not point to a valid repository",
        ),
    ],
)
def test_corrupted_git_raises_with_gits_message(
    tmp_path: Path, git_file: str, git_message: str
) -> None:
    (tmp_path / ".git").write_text(git_file, encoding="utf-8")

    with pytest.raises(RuntimeError, match=git_message):
        check_file_sizes.find_problems(tmp_path, baseline={})


def test_missing_git_binary_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(FileNotFoundError):
        check_file_sizes.find_problems(tmp_path, baseline={})


def test_snapshot_walk_skips_generated_and_installed_files(tmp_path: Path) -> None:
    for rel in (
        "frontend/src/api/types.gen.ts",
        "frontend/node_modules/pkg/index.ts",
        "backend/.venv/lib/site.py",
        "uv.lock",
        "frontend/package-lock.json",
    ):
        write_lines(tmp_path / rel, 900)

    assert check_file_sizes.find_problems(tmp_path, baseline={}) == []


def test_baselined_file_may_stay_at_its_count(tmp_path: Path) -> None:
    write_lines(tmp_path / "old.py", 800)

    assert check_file_sizes.find_problems(tmp_path, baseline={"old.py": 800}) == []


def test_baselined_file_that_grows_fails(tmp_path: Path) -> None:
    write_lines(tmp_path / "old.py", 801)

    assert check_file_sizes.find_problems(tmp_path, baseline={"old.py": 800}) == [
        f"old.py: 801 lines, grew past its entry of 800 {WHERE}. Shrink it back."
    ]


def test_baselined_file_that_shrinks_must_lower_its_entry(tmp_path: Path) -> None:
    write_lines(tmp_path / "old.py", 700)

    assert check_file_sizes.find_problems(tmp_path, baseline={"old.py": 800}) == [
        f"old.py: 700 lines, shrank below its entry of 800 {WHERE}. Lower the entry to 700."
    ]


def test_baselined_file_within_the_limit_must_leave_the_baseline(tmp_path: Path) -> None:
    write_lines(tmp_path / "old.py", 400)

    assert check_file_sizes.find_problems(tmp_path, baseline={"old.py": 800}) == [
        f"old.py: 400 lines, now within the limit. Delete its entry {WHERE}."
    ]


def test_baseline_entry_for_a_missing_file_fails(tmp_path: Path) -> None:
    assert check_file_sizes.find_problems(tmp_path, baseline={"gone.py": 800}) == [
        f"gone.py: not found. Delete its entry {WHERE}."
    ]


def test_final_line_without_newline_is_counted(tmp_path: Path) -> None:
    path = tmp_path / "a.py"
    path.write_text("a\nb\nc", encoding="utf-8")

    assert check_file_sizes.count_lines(path) == 3


def test_main_exits_nonzero_and_reports(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_lines(tmp_path / "big.py", 501)

    assert check_file_sizes.main([str(tmp_path)]) == 1
    assert "big.py: 501 lines" in capsys.readouterr().err


def test_main_exits_zero_on_a_clean_tree(tmp_path: Path) -> None:
    write_lines(tmp_path / "small.py", 10)

    assert check_file_sizes.main([str(tmp_path)]) == 0

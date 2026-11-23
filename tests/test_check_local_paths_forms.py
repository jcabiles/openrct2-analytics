"""Per-form tests for scripts/check_local_paths.py (spec R1), on real temporary git repos.

Every form runs through every guard: it is reported with a valid following character; it is not
reported after a left-boundary character, without its slash, or after a character that cannot
start a folder name. Each negative case changes one thing in a line that is reported otherwise.
Windows drive letters and file links have their own cases. Every planted path is joined from
parts here (R9), so this file holds no path of any form.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_check_local_paths import make_repo, planted, report, run

SLASH = "/"
BACKSLASH = "\\"
COLON = ":"


def head(*parts: str) -> str:
    """Return a path prefix with its trailing slash, for example `/home/`."""
    return SLASH + SLASH.join(parts) + SLASH


# Forms that need only the trailing slash.
SLASH_ONLY = {
    "private-tmp": head("private", "tmp"),
    "private-var": head("private", "var"),
    "var-folders": head("var", "folders"),
    "var-tmp": head("var", "tmp"),
}
# Forms that need a letter, digit, `_` or `.` after the slash.
FOLLOWED = {
    "tmp": head("tmp"),
    "home": head("home"),
    "root": head("root"),
    "volumes": head("Volumes"),
    "users": head("Users"),
    "system-users": head("System", "Volumes", "Data", "Users"),
}
ALL = {**SLASH_ONLY, **FOLLOWED}
ALL_FORMS = [pytest.param(prefix, id=name) for name, prefix in ALL.items()]
FOLLOWED_FORMS = [pytest.param(prefix, id=name) for name, prefix in FOLLOWED.items()]
LEFT_BOUNDARY = list("aZ5_.~$}-")


@pytest.mark.parametrize("prefix", ALL_FORMS)
def test_each_form_is_reported_with_file_and_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], prefix: str
) -> None:
    planted(make_repo(tmp_path), f"first\nsecond\nsee {prefix}scratch here\n")

    assert run(tmp_path, capsys) == (1, report("notes.md:3"))


@pytest.mark.parametrize("prefix", ALL_FORMS)
@pytest.mark.parametrize("before", ["", " ", "(", "`", '"', "="])
def test_a_non_boundary_character_before_the_prefix_is_a_hit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], prefix: str, before: str
) -> None:
    planted(make_repo(tmp_path), f"{before}{prefix}scratch\n")

    assert run(tmp_path, capsys) == (1, report("notes.md:1"))


@pytest.mark.parametrize("prefix", ALL_FORMS)
@pytest.mark.parametrize("before", LEFT_BOUNDARY)
def test_a_left_boundary_character_before_the_prefix_is_not_a_hit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], prefix: str, before: str
) -> None:
    planted(make_repo(tmp_path), f"see {before}{prefix}scratch\n")

    assert run(tmp_path, capsys) == (0, "")


@pytest.mark.parametrize("prefix", ALL_FORMS)
def test_a_web_url_with_the_same_segments_is_not_a_hit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], prefix: str
) -> None:
    planted(make_repo(tmp_path), "see https:" + SLASH * 2 + "host" + prefix + "scratch\n")

    assert run(tmp_path, capsys) == (0, "")


@pytest.mark.parametrize("prefix", ALL_FORMS)
def test_a_prefix_without_its_trailing_slash_is_not_a_hit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], prefix: str
) -> None:
    planted(make_repo(tmp_path), f"see {prefix.rstrip(SLASH)} here\n")

    assert run(tmp_path, capsys) == (0, "")


@pytest.mark.parametrize("prefix", FOLLOWED_FORMS)
@pytest.mark.parametrize("follow", list("aZ5_."))
def test_a_letter_digit_underscore_or_dot_after_the_slash_is_a_hit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], prefix: str, follow: str
) -> None:
    planted(make_repo(tmp_path), f"see {prefix}{follow}x\n")

    assert run(tmp_path, capsys) == (1, report("notes.md:1"))


@pytest.mark.parametrize("prefix", FOLLOWED_FORMS)
@pytest.mark.parametrize("follow", [" ", "-", "~", "$", "{", "/", ""])
def test_another_character_or_none_after_the_slash_is_not_a_hit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], prefix: str, follow: str
) -> None:
    planted(make_repo(tmp_path), f"see {prefix}{follow}\n")

    assert run(tmp_path, capsys) == (0, "")


@pytest.mark.parametrize("prefix", [pytest.param(p, id=n) for n, p in SLASH_ONLY.items()])
def test_a_slash_only_form_is_a_hit_with_nothing_after_the_slash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], prefix: str
) -> None:
    planted(make_repo(tmp_path), f"see {prefix}\n")

    assert run(tmp_path, capsys) == (1, report("notes.md:1"))


@pytest.mark.parametrize(
    "text",
    [
        head("private", "usr") + "x",
        head("var", "log") + "x",
        "docs" + head("tmp") + "x",
    ],
)
def test_a_neighbouring_folder_is_not_a_hit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    planted(make_repo(tmp_path), f"see {text}\n")

    assert run(tmp_path, capsys) == (0, "")


@pytest.mark.parametrize("letter", ["A", "C", "Z", "a", "c", "z"])
def test_a_windows_drive_with_an_upper_or_lower_case_letter_is_a_hit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], letter: str
) -> None:
    planted(make_repo(tmp_path), f"see {letter}{COLON}{BACKSLASH}Users\n")

    assert run(tmp_path, capsys) == (1, report("notes.md:1"))


def test_a_windows_drive_at_line_start_is_a_hit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    planted(make_repo(tmp_path), "D" + COLON + BACKSLASH + "work\n")

    assert run(tmp_path, capsys) == (1, report("notes.md:1"))


@pytest.mark.parametrize(
    "text",
    [
        "ab" + COLON + BACKSLASH + "Users",
        "1" + COLON + BACKSLASH + "Users",
        "_" + COLON + BACKSLASH + "Users",
        BACKSLASH + "C" + COLON + BACKSLASH + "Users",
        "C" + COLON + BACKSLASH + "1",
        "C" + COLON + SLASH + "Users",
    ],
)
def test_a_windows_drive_needs_a_lone_letter_and_a_letter_after_the_backslash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    planted(make_repo(tmp_path), f"see {text}\n")

    assert run(tmp_path, capsys) == (0, "")


@pytest.mark.parametrize(
    "link",
    [
        "file" + COLON + SLASH * 3 + "x",
        "FILE" + COLON + SLASH * 3 + "x",
        "File" + COLON + SLASH * 3 + "x",
        "file" + COLON + SLASH * 2 + "localhost" + SLASH + "x",
        "FILE" + COLON + SLASH * 2 + "LocalHost" + SLASH + "x",
    ],
)
def test_a_local_file_link_is_a_hit_in_any_letter_case(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], link: str
) -> None:
    planted(make_repo(tmp_path), f"see {link}\n")

    assert run(tmp_path, capsys) == (1, report("notes.md:1"))


@pytest.mark.parametrize("before", LEFT_BOUNDARY)
def test_a_left_boundary_character_before_a_file_link_is_not_a_hit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], before: str
) -> None:
    planted(make_repo(tmp_path), f"see {before}file{COLON}{SLASH * 3}x\n")

    assert run(tmp_path, capsys) == (0, "")


def test_a_profile_link_with_three_slashes_is_not_a_hit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    planted(make_repo(tmp_path), "see pro" + "file" + COLON + SLASH * 3 + "topic\n")

    assert run(tmp_path, capsys) == (0, "")


@pytest.mark.parametrize(
    "link",
    [
        "file" + COLON + SLASH * 2 + "x",
        "file" + COLON + SLASH * 2 + "remote" + SLASH + "x",
        "file" + COLON + SLASH + "x",
    ],
)
def test_a_file_link_without_an_empty_or_localhost_host_is_not_a_hit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], link: str
) -> None:
    planted(make_repo(tmp_path), f"see {link}\n")

    assert run(tmp_path, capsys) == (0, "")

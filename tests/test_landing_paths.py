"""Tests for ingest/landing_paths.py and for the scanner that guards against copies of its rule."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from openrct2_analytics.config import ConfigError
from openrct2_analytics.ingest import landing_paths
from openrct2_analytics.ingest.landing_paths import landing, project_path

INGEST_DIR = Path(landing_paths.__file__).parent
PACKAGE_DIR = INGEST_DIR.parent

# The guard's patterns (multi-line mode). A match is a second copy of the rule that
# ``landing_paths`` already holds.
PATTERNS = {
    "P1": r"^\s*def _?absolute\(",
    "P3": r"\.is_absolute\(\)\s+else\b",
    "P4": r"if not (\w+)\.is_absolute\(\):\n\s+\w+ = [^\n]*/",
    "P5": r"if (\w+)\.is_absolute\(\):\n\s+return \1\n\s+return [^\n]*/",
    "P6": (
        r"\b(?:project|project_dir|PROJECT_DIR)\s*/\s*[^\n]*"
        r"(?:landing_dirs\(|landing\(|data_root\(|registry_dir\(|save_files_dir\(|\bfolders?\b)"
    ),
    "P7a": r"play_status\.landing\b",
    "P7b": r"^\s*def landing\(",
    "P7c": (
        r"^from openrct2_analytics\.ingest\.play_status import "
        r"(?:\([^)]*\blanding\b[^)]*\)|[^\n(]*\blanding\b)"
    ),
}
# P8: a local name assigned from a configuration helper, then joined to the project folder later
# in the same function (the two-step copy).
HELPER_CALL = r"(?:landing_dirs\(|landing\(|data_root\(|registry_dir\(|save_files_dir\()"
ASSIGNED = rf"^[ \t]*(\w+)[ \t]*=[ \t]*[^\n]*{HELPER_CALL}[^\n]*$"
FUNCTION_END = r"\n[ \t]*(?:async )?def "
# The one allowed match: ``archive_dir`` in autopilot_year.py, out of scope for the move.
ALLOWED_FILE = "autopilot_year.py"
ALLOWED_LINE = "    return backup if backup.is_absolute() else project / backup"


def scan(folder: Path, patterns: dict[str, str] = PATTERNS) -> list[str]:
    """Return ``file:line: pattern`` for each copy of the rule in ``folder``."""
    found: list[str] = []
    allowance_used = False
    for path in sorted(folder.rglob("*.py")):
        if path.name == "landing_paths.py":
            continue
        text = path.read_text(encoding="utf-8")
        for name, pattern in patterns.items():
            for match in re.finditer(pattern, text, re.MULTILINE):
                # ``\s*`` may start the match on blank lines; the match is the first non-space.
                start = match.start() + len(match.group(0)) - len(match.group(0).lstrip())
                line_no = text.count("\n", 0, start) + 1
                line = text.splitlines()[line_no - 1]
                allowed = name == "P3" and path.name == ALLOWED_FILE and line == ALLOWED_LINE
                if allowed and not allowance_used:
                    allowance_used = True
                    continue
                found.append(f"{path.name}:{line_no}: {name}")
        found.extend(f"{path.name}:{n}: P8" for n in two_step_lines(text))
    return sorted(found)


def two_step_lines(text: str) -> list[int]:
    """Return the lines that join the project folder to a name taken from a helper call."""
    lines: list[int] = []
    for assigned in re.finditer(ASSIGNED, text, re.MULTILINE):
        rest_start = assigned.end()
        end = re.search(FUNCTION_END, text[rest_start:])
        rest = text[rest_start : rest_start + end.start()] if end else text[rest_start:]
        join = re.search(
            rf"\b(?:project|project_dir|PROJECT_DIR)\s*/\s*[^\n]*\b{assigned.group(1)}\b", rest
        )
        if join:
            lines.append(text.count("\n", 0, rest_start + join.start()) + 1)
    return lines


# --- landing_paths.landing and project_path ---------------------------------------------------


def test_landing_puts_a_relative_data_folder_under_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "data-x")
    folders = landing("company", tmp_path)
    assert folders.raw == tmp_path / "data-x" / "company" / "raw"
    assert folders.parquet == tmp_path / "data-x" / "company" / "parquet"


def test_landing_returns_an_absolute_data_folder_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "elsewhere"
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(elsewhere))
    folders = landing("company", tmp_path / "project")
    assert folders.raw == elsewhere / "company" / "raw"
    assert folders.parquet == elsewhere / "company" / "parquet"


def test_project_path_joins_a_relative_path_and_keeps_an_absolute_one(tmp_path: Path) -> None:
    assert project_path(Path("a/b"), tmp_path) == tmp_path / "a" / "b"
    assert project_path(tmp_path / "x" / "y", tmp_path / "project") == tmp_path / "x" / "y"


def test_project_path_does_not_resolve_links(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    assert project_path(Path("a"), link) == tmp_path / "link" / "a"
    assert project_path(Path("a"), link) != tmp_path / "real" / "a"


def test_landing_refuses_an_unknown_data_set(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Data set must be one of"):
        landing("nope", tmp_path)


def test_landing_refuses_an_empty_data_folder_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "")
    with pytest.raises(ConfigError, match="OPENRCT2_DATA_DIR"):
        landing("company", tmp_path)


def test_landing_reads_the_environment_on_every_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "data-a")
    assert landing("company", tmp_path).raw == tmp_path / "data-a" / "company" / "raw"
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "data-b")
    assert landing("company", tmp_path).raw == tmp_path / "data-b" / "company" / "raw"


# --- the guard scanner, on planted copies in a temporary tree ---------------------------------

CLEAN = "def read(path):\n    return path\n"
PLANTED = {
    "P1": (
        "planted.py",
        "def _absolute(path, project_dir):\n    return path\n",
        ["planted.py:1: P1"],
    ),
    "P3": (
        "planted.py",
        "def f(folder, project_dir):\n"
        "    return folder if folder.is_absolute() else project_dir / folder\n",
        # The same line also joins the project folder with a ``folder``.
        ["planted.py:2: P3", "planted.py:2: P6"],
    ),
    "P4": (
        "planted.py",
        "def f(path, project_dir):\n"
        "    if not path.is_absolute():\n"
        "        path = project_dir / path\n"
        "    return path\n",
        ["planted.py:2: P4"],
    ),
    "P5": (
        "planted.py",
        "def f(path, project_dir):\n"
        "    if path.is_absolute():\n"
        "        return path\n"
        "    return project_dir / path\n",
        ["planted.py:2: P5"],
    ),
    "P6 parquet": (
        "planted.py",
        "def f(project_dir, data_set):\n    x = project_dir / landing_dirs(data_set).parquet\n",
        ["planted.py:2: P6"],
    ),
    "P6 root": (
        "planted.py",
        "def f(project_dir):\n    root = project_dir / data_root()\n",
        ["planted.py:2: P6"],
    ),
    "P7 import": (
        "planted.py",
        "from openrct2_analytics.ingest.play_status import (\n    landing,\n    read_status,\n)\n",
        ["planted.py:1: P7c"],
    ),
    "P7 call": (
        "planted.py",
        "def f(project_dir):\n    return play_status.landing('company', project_dir)\n",
        ["planted.py:2: P7a"],
    ),
    "P7 def": (
        "planted.py",
        "def landing(data_set, project_dir):\n    return data_set\n",
        ["planted.py:1: P7b"],
    ),
    "P3 split": (
        "planted.py",
        "def f(a, b):\n    return (\n        a\n        if a.is_absolute()\n"
        "        else b / a\n    )\n",
        ["planted.py:4: P3"],
    ),
    "P8 two-step": (
        "planted.py",
        "def f(project_dir, data_set):\n"
        "    configured = landing_dirs(data_set).parquet\n"
        "    parquet_dir = (project_dir / configured).resolve()\n"
        "    return parquet_dir\n",
        ["planted.py:3: P8"],
    ),
}
ALLOWED = f"def archive_dir(backup, project):\n{ALLOWED_LINE}\n"


def plant(tmp_path: Path, name: str, text: str) -> Path:
    """Write one clean file and one file ``name`` holding ``text``; return the tree."""
    (tmp_path / "clean.py").write_text(CLEAN, encoding="utf-8")
    (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_scan_finds_nothing_in_a_clean_tree(tmp_path: Path) -> None:
    assert scan(plant(tmp_path, "other.py", CLEAN)) == []


@pytest.mark.parametrize("case", PLANTED)
def test_scan_names_the_file_and_line_of_each_planted_copy(tmp_path: Path, case: str) -> None:
    name, text, expected = PLANTED[case]
    assert scan(plant(tmp_path, name, text)) == expected


def test_scan_reports_a_planted_copy_in_a_named_file(tmp_path: Path) -> None:
    text = (
        "def f(path, project_dir):\n    return path if path.is_absolute() else project_dir / path\n"
    )
    assert scan(plant(tmp_path, "results.py", text)) == ["results.py:2: P3"]


def test_scan_passes_a_helper_that_only_resolves(tmp_path: Path) -> None:
    text = "def _resolved(path):\n    return path.resolve()\n"
    assert scan(plant(tmp_path, "other.py", text)) == []


def test_scan_allows_the_one_autopilot_year_line(tmp_path: Path) -> None:
    assert scan(plant(tmp_path, ALLOWED_FILE, ALLOWED)) == []


def test_scan_fails_a_second_copy_of_the_allowed_line(tmp_path: Path) -> None:
    text = ALLOWED + "\n" + ALLOWED
    assert scan(plant(tmp_path, ALLOWED_FILE, text)) == [f"{ALLOWED_FILE}:5: P3"]


def test_scan_fails_the_allowed_line_in_another_file(tmp_path: Path) -> None:
    assert scan(plant(tmp_path, "other.py", ALLOWED)) == ["other.py:2: P3"]


def test_scan_skips_landing_paths_itself(tmp_path: Path) -> None:
    text = "def f(p, d):\n    return p if p.is_absolute() else d / p\n"
    assert scan(plant(tmp_path, "landing_paths.py", text)) == []


def test_p3_matches_the_shared_module_itself() -> None:
    # A broken pattern would pass the guard silently; the module's own join must match P3.
    source = (INGEST_DIR / "landing_paths.py").read_text(encoding="utf-8")
    assert re.search(PATTERNS["P3"], source, re.MULTILINE)


def test_the_allowed_line_is_in_autopilot_year_exactly_once() -> None:
    lines = (INGEST_DIR / ALLOWED_FILE).read_text(encoding="utf-8").splitlines()
    assert lines.count(ALLOWED_LINE) == 1


def test_the_real_source_tree_holds_no_second_copy_of_the_join() -> None:
    assert scan(PACKAGE_DIR) == []

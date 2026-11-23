"""Behavioral tests for scripts/check_docs.py, on real temporary git repos."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import check_docs

MAKEFILE = ".PHONY: check\n\ncheck: # The gate.\n\tpytest\n\nsetup:\n\ttrue\n"
MARKER_LINE = f"# {check_docs.PLACEHOLDER_MARKER}: replace this example.\n"
# The fresh template's placeholder golden examples, one per kind rule.
EXAMPLES = {
    "src/pkg/example.py": (
        f'"""Example logic."""\n\n{MARKER_LINE}from pkg import helpers\n\nVALUE = 1\n'
    ),
    "tests/test_example.py": (
        f'"""Example test."""\n\n{MARKER_LINE}\ndef test_value() -> None:\n    pass\n'
    ),
    "web/App.test.tsx": f"{MARKER_LINE.replace('#', '//')}it('renders', () => {{}});\n",
}
LOGIC_ROW, TEST_ROW, TSX_TEST_ROW = EXAMPLES
SUPPORT = frozenset({"__init__.py", "conftest.py"})
FINGERPRINTS = frozenset(check_docs.fingerprint(text) for text in EXAMPLES.values())


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def point_golden_at(root: Path, *paths: str) -> None:
    rows = "".join(f"| Example | `{rel}` | 20 lines | Judgment only |\n" for rel in paths)
    write(
        root,
        "docs/CONVENTIONS.md",
        "## 5. Golden examples\n\n| Kind | File | Cap | Check |\n|---|---|---|---|\n"
        f"{rows}\n## 6. Names\n",
    )


def make_repo(root: Path) -> Path:
    """Build a minimal fresh-from-template repo whose docs are all valid."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    write(root, ".gitignore", "scratch/\n")
    write(root, "Makefile", MAKEFILE)
    write(root, "src/pkg/__init__.py", '"""Package."""\n')
    write(root, "tests/__init__.py", "")
    for rel, text in EXAMPLES.items():
        write(root, rel, text)
    write(root, "README.md", "Run `make check`.\n")
    write(root, "CLAUDE.md", "Run `make check`. Code lives in `src/`.\n")
    write(root, "ARCHITECTURE.md", "See `src/pkg/example.py`.\n")
    point_golden_at(root, *EXAMPLES)
    return root


def problems(root: Path) -> list[str]:
    return check_docs.find_problems(root, support=SUPPORT, fingerprints=FINGERPRINTS)


def still_placeholder(golden: str, real: str) -> str:
    return (
        f"docs/CONVENTIONS.md: golden example {golden} is still the template's placeholder, "
        f"but {real} is real code of the same kind. Point section 5 at a real file."
    )


def test_fresh_repo_with_placeholder_examples_passes(tmp_path: Path) -> None:
    assert problems(make_repo(tmp_path)) == []


def test_dead_path_in_claude_md_fails(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    write(root, "CLAUDE.md", "Imitate `src/app/gone.py` and `docs/missing/`.\n")

    assert problems(root) == [
        "CLAUDE.md: names `src/app/gone.py`, which does not exist.",
        "CLAUDE.md: names `docs/missing/`, which does not exist.",
    ]


def test_missing_make_target_fails(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    write(root, "ARCHITECTURE.md", "Run `make deploy` then `make check`.\n")

    assert problems(root) == [
        "ARCHITECTURE.md: names `make deploy`, which is not a Makefile target."
    ]


def test_skipped_spans_are_never_checked(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    outside = tmp_path.parent / "elsewhere.md"
    write(
        root,
        "CLAUDE.md",
        "`~/.claude/rules/x.md` `https://example.com/a/b` `/health` "
        f"`{outside}` `scratch/notes.md` `ruff check src/` `docs/adr/<n>.md` "
        "`tests/**` `make -n setup` `app.config` `make` and make sure.\n",
    )

    assert problems(root) == []


@pytest.mark.parametrize("span", ["and/or", "a/b", "origin/main", "application/json", "YYYY/MM/DD"])
def test_prose_with_a_slash_is_not_a_path(tmp_path: Path, span: str) -> None:
    root = make_repo(tmp_path)
    write(root, "CLAUDE.md", f"Use `{span}` here.\n")

    assert problems(root) == []


def test_absolute_path_inside_the_repo_is_checked(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    write(root, "CLAUDE.md", f"`{root / 'src' / 'gone.py'}`\n")

    assert problems(root) == ["CLAUDE.md: names `src/gone.py`, which does not exist."]


def test_golden_example_over_its_cap_fails(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    write(root, "src/pkg/real.py", "x = 1\n" * 21)
    point_golden_at(root, "src/pkg/real.py")

    assert problems(root) == [
        "docs/CONVENTIONS.md: golden example src/pkg/real.py is 21 lines, over its cap of 20."
    ]


def test_second_module_in_the_examples_own_folder_fails(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    write(root, "src/pkg/pricing.py", "RATE = 2\n")

    assert problems(root) == [still_placeholder(LOGIC_ROW, "src/pkg/pricing.py")]


def test_module_in_a_subfolder_is_another_kind(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    write(root, "src/pkg/domain/pricing.py", "RATE = 2\n")

    assert problems(root) == []


def test_pointing_the_row_at_real_code_passes_again(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    write(root, "src/pkg/pricing.py", "RATE = 2\n")
    point_golden_at(root, "src/pkg/pricing.py", TEST_ROW, TSX_TEST_ROW)

    assert problems(root) == []


def test_code_of_another_suffix_does_not_count(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    write(root, "src/pkg/report.sql", "select 1;\n")

    assert problems(root) == []


def test_real_test_anywhere_under_the_test_folder_fails(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    write(root, "tests/unit/test_pricing.py", "def test_rate() -> None:\n    pass\n")

    assert problems(root) == [still_placeholder(TEST_ROW, "tests/unit/test_pricing.py")]


def test_test_helpers_and_conftest_are_not_tests(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    write(root, "tests/conftest.py", "import pytest\n")
    write(root, "tests/helpers.py", "ONE = 1\n")
    write(root, "src/pkg/test_inline.py", "def test_x() -> None:\n    pass\n")

    assert problems(root) == []


def test_component_without_a_test_does_not_fail_the_test_row(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    write(root, "web/components/Foo.tsx", "export const Foo = () => null;\n")

    assert problems(root) == []


def test_real_component_test_fails_the_test_row(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    write(root, "web/components/Foo.test.tsx", "it('works', () => {});\n")

    assert problems(root) == [still_placeholder(TSX_TEST_ROW, "web/components/Foo.test.tsx")]


def test_deleting_only_the_marker_still_reads_as_the_placeholder(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    unmarked = EXAMPLES[LOGIC_ROW].replace(MARKER_LINE, "")
    # A package rename changes only the import line, which the fingerprint ignores.
    write(root, LOGIC_ROW, unmarked.replace("from pkg import", "from renamed import"))
    write(root, "src/pkg/pricing.py", "RATE = 2\n")

    assert problems(root) == [still_placeholder(LOGIC_ROW, "src/pkg/pricing.py")]


def test_marked_example_that_was_edited_fails(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    write(root, LOGIC_ROW, EXAMPLES[LOGIC_ROW] + "RATE = 2\n")

    assert problems(root) == [
        f"docs/CONVENTIONS.md: golden example {LOGIC_ROW} carries "
        f"{check_docs.PLACEHOLDER_MARKER} but no longer matches the template's example. "
        "Finish replacing it, delete the marker line, and point section 5 at real code. "
        "(In the template itself, update TEMPLATE_EXAMPLE_FINGERPRINTS in scripts/check_docs.py.)"
    ]


def test_missing_golden_section_and_missing_doc_fail(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    write(root, "docs/CONVENTIONS.md", "No table here.\n")
    (root / "ARCHITECTURE.md").unlink()

    assert problems(root) == [
        "ARCHITECTURE.md: missing.",
        "docs/CONVENTIONS.md: no '## 5. Golden examples' section.",
    ]


def test_outside_a_git_repo_the_error_surfaces(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    write(tmp_path, "CLAUDE.md", "`src/x.py`\n")

    with pytest.raises(RuntimeError, match="git check-ignore failed"):
        problems(tmp_path)


def test_main_exits_nonzero_and_reports(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_repo(tmp_path)
    write(root, "CLAUDE.md", "`src/gone.py`\n")

    assert check_docs.main([str(root)]) == 1
    assert "src/gone.py" in capsys.readouterr().err

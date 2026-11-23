"""Fail when the docs name something that does not exist, or a golden example has decayed.

It reads the code spans (text in backticks) of DOC_FILES and checks that:
- every in-repo path exists. A span is a path when it has a `/`, no spaces or
  placeholder characters, and either ends in `/`, has a file suffix, or starts
  with a name that exists at the repo root. It skips `~/` paths, URLs, absolute
  paths outside the repo, and gitignored paths;
- every `make <target>` names a target defined in the Makefile;
- every golden example in the CONVENTIONS "## 5. Golden examples" table is
  within its line cap, and is real code once the project has real code of
  the same kind (see check_golden).

It checks only that named things exist, never that the prose around them is true.

Usage: python scripts/check_docs.py [ROOT]    (ROOT defaults to the repo root)
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import re
import subprocess
import sys
from collections.abc import Sequence, Set
from pathlib import Path

from check_file_sizes import count_lines

DOC_FILES = ("README.md", "CLAUDE.md", "ARCHITECTURE.md", "docs/CONVENTIONS.md")
CONVENTIONS = "docs/CONVENTIONS.md"
GOLDEN_HEADING = "## 5. Golden examples"
PLACEHOLDER_MARKER = "TEMPLATE-EXAMPLE"
# Code files both templates ship beside their golden examples. A file with one
# of these names never counts as the project's own code.
TEMPLATE_SUPPORT_FILES = frozenset(
    {
        "__init__.py",
        "conftest.py",
        "config.py",
        "main.tsx",
        "types.gen.ts",
        "test_check_docs.py",
        "test_check_file_sizes.py",
    }
)
# fingerprint() of each golden example both templates ship. When you edit a
# template example, replace its entry: the check fails while a file that
# carries the marker matches no entry.
TEMPLATE_EXAMPLE_FINGERPRINTS = frozenset(
    {
        # template-python-service
        "719fbe213c42df30c20b1700de38a2aef65fad3dd353e2a24f2c0fd7d8a635cc",  # example_service.py
        "dc20555d7c11f61fb5e9e49406675f05cbcfdd487380621a9eafe06a8f7a2507",  # test_example_service
        # template-web-app
        "0104b8200151ba839aea7444ac4d7bb151f9c9ee336ae602d3173a6738e45056",  # app/main.py
        "b21d64966990df3a6f1e68fc54c9303eee1fa272c0abf292e2b8109caf51c215",  # app/schemas.py
        "b51c07fe4315b8a0996ec03869b09982319cc0dd4d468db0bb394886f7663260",  # tests/test_api.py
        "871b9b4321ebb29a98eff6fa7bb0f98f42a05832385cede32590db390c5895c7",  # src/api/client.ts
        "83bf0b8aad445c63ea8ce79117facacfba800b8c1af8bb9da3be4eb8b0d2211b",  # src/App.tsx
        "1d82396756b2b8797d9e9fa2a2bfec7d465786dc89d91f9072f485c5fbe3005f",  # src/App.test.tsx
    }
)

CODE_SPAN = re.compile(r"`([^`\n]+)`")
MAKE_TARGET = re.compile(r"^([A-Za-z0-9][\w.-]*)\s*:(?!=)", re.MULTILINE)
MAKE_CALL = re.compile(r"^make\s+([A-Za-z0-9][\w.-]*)")
NOT_A_PATH = re.compile(r"[\s<>*{}$|]")
CAP = re.compile(r"(\d+)")
# Test-file name patterns. A golden test example is compared only with tests.
TEST_PATTERNS = ("test_*.py", "*.test.ts", "*.test.tsx")
# Golden-example table columns: Kind | File | Cap | Check.
FILE_COLUMN = 1
CAP_COLUMN = 2


def doc_path(root: Path, span: str) -> str | None:
    """Return the in-repo path a code span names, relative to root, or None if it names none."""
    if "/" not in span or NOT_A_PATH.search(span) or "://" in span or span.startswith("~"):
        return None
    rel = span
    if span.startswith("/"):
        resolved, base = Path(span).resolve(), root.resolve()
        if not resolved.is_relative_to(base):
            return None
        rel = resolved.relative_to(base).as_posix() + ("/" if span.endswith("/") else "")
    last = rel.rstrip("/").rsplit("/", 1)[-1]
    if rel.endswith("/") or Path(last).suffix or (root / rel.split("/", 1)[0]).exists():
        return rel
    return None  # Prose such as `and/or` or `origin/main`, not a path.


def gitignored(root: Path, paths: Sequence[str]) -> set[str]:
    """Return the subset of paths that git ignores in the repo at root."""
    if not paths:
        return set()
    result = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        cwd=root,
        input="\n".join(paths),
        capture_output=True,
        text=True,
        check=False,
    )
    # Exit 0 means some paths are ignored and 1 means none are; anything else is an error.
    if result.returncode not in (0, 1):
        raise RuntimeError(f"git check-ignore failed in {root}: {result.stderr.strip()}")
    return set(result.stdout.splitlines())


def make_targets(root: Path) -> set[str]:
    """Return the targets defined in the Makefile at root, or none if it is missing."""
    makefile = root / "Makefile"
    if not makefile.exists():
        return set()
    return set(MAKE_TARGET.findall(makefile.read_text(encoding="utf-8")))


def fingerprint(text: str) -> str:
    """Return a SHA-256 of text without its blank, import, and marker lines.

    Renaming the package changes only import lines, and deleting the marker
    removes only its own line, so neither changes the fingerprint.
    """
    kept = [
        stripped
        for line in text.splitlines()
        if (stripped := line.strip())
        and PLACEHOLDER_MARKER not in stripped
        and not stripped.startswith(("import ", "from "))
    ]
    return hashlib.sha256("\n".join(kept).encode()).hexdigest()


def is_placeholder(text: str, fingerprints: Set[str]) -> bool:
    """Return whether a file is still a template example, marked or not."""
    return PLACEHOLDER_MARKER in text or fingerprint(text) in fingerprints


def test_pattern(name: str) -> str | None:
    """Return the TEST_PATTERNS entry a file name matches, or None for a non-test file."""
    return next((p for p in TEST_PATTERNS if fnmatch.fnmatch(name, p)), None)


def real_code_beside(root: Path, rel: str, support: Set[str], fingerprints: Set[str]) -> str | None:
    """Return a project file of the golden example's kind, if one exists.

    A test example's kind is its test-name pattern, anywhere under its folder.
    Any other example's kind is a non-test file with its suffix in its own
    folder only, so code in a subfolder such as `domain/` is a different kind.
    Template support files and other placeholders are not project code.
    """
    golden = root / rel
    pattern = test_pattern(golden.name)
    if pattern is not None:
        candidates = golden.parent.rglob(pattern)
    else:
        candidates = (
            path
            for path in golden.parent.glob(f"*{golden.suffix}")
            if test_pattern(path.name) is None
        )
    for path in sorted(candidates):
        if path == golden or path.name in support or not path.is_file():
            continue
        if not is_placeholder(path.read_text(encoding="utf-8"), fingerprints):
            return path.relative_to(root).as_posix()
    return None


def golden_examples(root: Path, conventions: str) -> list[tuple[str, int]] | None:
    """Return (path, line cap) for each file in the golden-example table, or None if absent."""
    start = conventions.find(GOLDEN_HEADING)
    if start == -1:
        return None
    section = conventions[start + len(GOLDEN_HEADING) :].split("\n## ", 1)[0]
    examples: list[tuple[str, int]] = []
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not line.startswith("|") or len(cells) <= CAP_COLUMN:
            continue
        cap = CAP.match(cells[CAP_COLUMN])
        if cap is None:
            continue  # The header and separator rows have no number in the cap column.
        examples.extend(
            (rel, int(cap.group(1)))
            for span in CODE_SPAN.findall(cells[FILE_COLUMN])
            if (rel := doc_path(root, span))
        )
    return examples


def check_golden(root: Path, text: str, support: Set[str], fingerprints: Set[str]) -> list[str]:
    """Return problems with the golden examples listed in the conventions text.

    A golden example that is still the template's placeholder passes until the
    project has real code of the same kind (see real_code_beside); then the
    section 5 row must point at real code. A file that still carries the marker
    but no longer matches the template's example has been half-replaced.
    """
    examples = golden_examples(root, text)
    if examples is None:
        return [f"{CONVENTIONS}: no '{GOLDEN_HEADING}' section."]
    problems: list[str] = []
    for rel, cap in examples:
        path = root / rel
        if not path.is_file():
            continue  # A missing path is already reported by the path check.
        lines = count_lines(path)
        if lines > cap:
            problems.append(
                f"{CONVENTIONS}: golden example {rel} is {lines} lines, over its cap of {cap}."
            )
        content = path.read_text(encoding="utf-8")
        if PLACEHOLDER_MARKER in content and fingerprint(content) not in fingerprints:
            problems.append(
                f"{CONVENTIONS}: golden example {rel} carries {PLACEHOLDER_MARKER} but no "
                "longer matches the template's example. Finish replacing it, delete the "
                "marker line, and point section 5 at real code. (In the template itself, "
                "update TEMPLATE_EXAMPLE_FINGERPRINTS in scripts/check_docs.py.)"
            )
        elif is_placeholder(content, fingerprints) and (
            real := real_code_beside(root, rel, support, fingerprints)
        ):
            problems.append(
                f"{CONVENTIONS}: golden example {rel} is still the template's placeholder, "
                f"but {real} is real code of the same kind. Point section 5 at a real file."
            )
    return problems


def find_problems(
    root: Path,
    support: Set[str] = TEMPLATE_SUPPORT_FILES,
    fingerprints: Set[str] = TEMPLATE_EXAMPLE_FINGERPRINTS,
) -> list[str]:
    """Return one message per missing path, missing make target, or decayed golden example."""
    problems: list[str] = []
    targets = make_targets(root)
    for doc in DOC_FILES:
        doc_file = root / doc
        if not doc_file.exists():
            problems.append(f"{doc}: missing.")
            continue
        text = doc_file.read_text(encoding="utf-8")
        spans = CODE_SPAN.findall(text)
        paths = [rel for span in spans if (rel := doc_path(root, span))]
        ignored = gitignored(root, paths)
        problems.extend(
            f"{doc}: names `{rel}`, which does not exist."
            for rel in paths
            if rel not in ignored and not (root / rel).exists()
        )
        problems.extend(
            f"{doc}: names `make {call.group(1)}`, which is not a Makefile target."
            for span in spans
            if (call := MAKE_CALL.match(span)) and call.group(1) not in targets
        )
        if doc == CONVENTIONS:
            problems.extend(check_golden(root, text, support, fingerprints))
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    """Check the docs and return a process exit code."""
    parser = argparse.ArgumentParser(description="Fail on docs that name missing things.")
    parser.add_argument(
        "root", nargs="?", type=Path, default=Path(__file__).resolve().parent.parent
    )
    args = parser.parse_args(argv)
    problems = find_problems(args.root)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"check_docs: {len(problems)} problem(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

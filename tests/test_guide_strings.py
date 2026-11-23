"""Every code span on the built player guide is pinned to the code that prints it (spec R17, R18).

`tests/guide_strings.toml` holds one row per quoted string. The site is built once; each negative
case starts from the valid built page and rows and changes exactly one thing.
"""

from __future__ import annotations

import copy
import html
import re
import tomllib
from html.parser import HTMLParser
from typing import Any

import pytest

from tests.page_check_support import render_page
from tests.site_fixtures import ROOT, write_set

ROWS = ROOT / "tests" / "guide_strings.toml"
Rows = list[dict[str, Any]]


class _Page(HTMLParser):
    """Collect the text of each `<code>` element and the whole page text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.codes: list[str] = []
        self.text: list[str] = []
        self._open: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "code":
            self._open = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "code" and self._open is not None:
            self.codes.append(_collapse("".join(self._open)))
            self._open = None

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self._open is not None:
            self._open.append(data)


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _rows() -> Rows:
    rows: Rows = tomllib.loads(ROWS.read_text())["row"]
    return rows


def problems(rows: Rows, page_html: str) -> list[str]:
    """Return one message per broken pin: a quote without a row, or a row without its quote."""
    page = _Page()
    page.feed(page_html)
    page_text = _collapse(" ".join(page.text))
    found: list[str] = []
    shown = {_collapse(entry) for row in rows for entry in row["shown"]}
    for code in dict.fromkeys(page.codes):
        if code not in shown:
            found.append(f"code span {code!r} has no row")
    for row in rows:
        if ("source" in row) == ("outside" in row):
            found.append(f"row {row['id']}: needs exactly one of source and outside")
            continue
        for entry in row["shown"]:
            if _collapse(entry) not in page_text:
                found.append(f"row {row['id']}: shown {entry!r} is not on the guide")
        if "source" in row:
            source = (ROOT / row["source"]).read_text()
            for phrase in row["phrases"]:
                if phrase not in source:
                    found.append(f"row {row['id']}: phrase {phrase!r} is not in {row['source']}")
    return found


@pytest.fixture(scope="module")
def guide_html(tmp_path_factory: pytest.TempPathFactory) -> str:
    work = tmp_path_factory.mktemp("guide-strings")
    site = render_page(write_set("empty", work / "served"), work)
    return (site / "guide" / "index.html").read_text()


def _new_problems(rows: Rows, page_html: str, built: str) -> list[str]:
    """Return the problems of one changed input that the valid built page and table do not have."""
    valid = problems(_rows(), built)
    return [found for found in problems(rows, page_html) if found not in valid]


def _row(rows: Rows, row_id: str) -> dict[str, Any]:
    return next(row for row in rows if row["id"] == row_id)


def test_the_built_guide_and_the_table_agree(guide_html: str) -> None:
    assert problems(_rows(), guide_html) == []


def test_a_code_span_with_no_row_fails(guide_html: str) -> None:
    page = guide_html.replace("</main>", "<p><code>brew uninstall node</code></p></main>")
    assert _new_problems(_rows(), page, guide_html) == [
        "code span 'brew uninstall node' has no row"
    ]


def test_a_shown_text_missing_from_the_guide_fails(guide_html: str) -> None:
    rows = copy.deepcopy(_rows())
    _row(rows, "make-setup")["shown"].append("make nothing")
    assert _new_problems(rows, guide_html, guide_html) == [
        "row make-setup: shown 'make nothing' is not on the guide"
    ]


def test_a_phrase_missing_from_its_source_fails(guide_html: str) -> None:
    rows = copy.deepcopy(_rows())
    _row(rows, "make-setup")["phrases"] = ["setup: a target that does not exist"]
    assert _new_problems(rows, guide_html, guide_html) == [
        "row make-setup: phrase 'setup: a target that does not exist' is not in Makefile"
    ]


def test_a_row_with_both_a_source_and_an_outside_tool_fails(guide_html: str) -> None:
    rows = copy.deepcopy(_rows())
    _row(rows, "make-setup")["outside"] = "make"
    assert _new_problems(rows, guide_html, guide_html) == [
        "row make-setup: needs exactly one of source and outside"
    ]


def test_a_row_with_neither_a_source_nor_an_outside_tool_fails(guide_html: str) -> None:
    rows = copy.deepcopy(_rows())
    del _row(rows, "git-clone")["outside"]
    assert _new_problems(rows, guide_html, guide_html) == [
        "row git-clone: needs exactly one of source and outside"
    ]


def test_the_doctor_line_the_guide_shows_is_the_line_doctor_prints(guide_html: str) -> None:
    # Literals copied from scripts/doctor.py; the producer file is read, not the table.
    line = "doctor: the Python environment is whole."
    assert line in _collapse(html.unescape(guide_html))
    assert f'print("{line}", file=stream)' in (ROOT / "scripts" / "doctor.py").read_text()
    row = _row(_rows(), "doctor-whole")
    assert row["shown"] == [line]
    assert row["source"] == "scripts/doctor.py"


def test_the_node_row_pins_the_version_ci_uses() -> None:
    row = _row(_rows(), "node-version")
    assert row["source"] == ".github/workflows/ci.yml"
    assert row["phrases"] == ['node-version: "24"']
    assert 'node-version: "24"' in (ROOT / ".github/workflows/ci.yml").read_text()


_STEP_SECTION = re.compile(
    r'<section class="(?:guide-step|guide-sign-in)" id="([^"]+)">(.*?)</section>', re.DOTALL
)
# Every fenced block in a step or sign-in section is a command the player pastes. A fenced block
# renders as one code element whose text ends in the fence's newline.
_COMMAND_BLOCK = re.compile(r'<pre><code class="language-zsh">(.*?)\n</code></pre>', re.DOTALL)


def test_the_install_commands_are_every_command_block_of_the_steps_in_order(
    guide_html: str,
) -> None:
    steps = [
        (step_id, html.unescape(code))
        for step_id, body in _STEP_SECTION.findall(guide_html)
        for code in _COMMAND_BLOCK.findall(body)
    ]
    assert steps == [
        ("step-dev-tools", "xcode-select --install"),
        (
            "step-homebrew",
            '/bin/bash -c "$(curl -fsSL '
            'https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"',
        ),
        (
            "step-homebrew-path",
            "echo 'eval \"$(/opt/homebrew/bin/brew shellenv)\"' >> ~/.zprofile && "
            'eval "$(/opt/homebrew/bin/brew shellenv)"',
        ),
        ("step-tools", "brew install node@24 direnv uv"),
        (
            "step-node-path",
            "echo 'export PATH=\"/usr/local/opt/node@24/bin:$PATH\"' >> ~/.zshrc",
        ),
        (
            "step-node-path",
            "echo 'export PATH=\"/opt/homebrew/opt/node@24/bin:$PATH\"' >> ~/.zshrc",
        ),
        ("step-direnv-hook", "echo 'eval \"$(direnv hook zsh)\"' >> ~/.zshrc"),
        ("step-check-tools", "node --version && uv --version && direnv version"),
        ("step-sign-in", "brew install gh"),
        ("step-sign-in", "gh auth login"),
        (
            "step-clone",
            "git clone https://github.com/jcabiles/openrct2-analytics.git ~/openrct2-analytics",
        ),
        ("step-cd", "cd ~/openrct2-analytics"),
        ("step-setup", "make setup"),
        ("step-direnv-allow", "direnv allow"),
        ("step-launcher", "make launcher"),
    ]


def _unfenced_command_wrappers(page_html: str) -> list[str]:
    """Return one message per `.step-command` that is not only fenced command blocks."""
    found = []
    for step_id, body in _STEP_SECTION.findall(page_html):
        for _, inner in re.findall(r'<(div|p) class="step-command">(.*?)</\1>', body, re.DOTALL):
            if not _COMMAND_BLOCK.search(inner) or _COMMAND_BLOCK.sub("", inner).strip():
                found.append(
                    f"{step_id}: a .step-command is not only fenced command blocks: {inner!r}"
                )
    return found


def test_every_step_command_wrapper_holds_only_fenced_blocks(guide_html: str) -> None:
    assert _unfenced_command_wrappers(guide_html) == []


def test_an_extra_sign_in_command_wrapper_with_inline_code_fails(guide_html: str) -> None:
    opening = '<section class="guide-sign-in" id="step-sign-in">'
    assert opening in guide_html
    page = guide_html.replace(
        opening, opening + '<div class="step-command"><code>make setup</code></div>', 1
    )
    assert _unfenced_command_wrappers(page) == [
        "step-sign-in: a .step-command is not only fenced command blocks: '<code>make setup</code>'"
    ]


def test_every_step_reference_names_a_step_the_guide_has(guide_html: str) -> None:
    page = _Page()
    page.feed(guide_html)
    text = _collapse(" ".join(page.text))
    assert re.findall(r"Step (\d+): ", text) == [str(number) for number in range(1, 14)]
    titled = set(re.findall(r"Step (\d+): ", text))
    referenced = {n for pair in re.findall(r"Steps? (\d+)(?: and (\d+))?", text) for n in pair if n}
    assert referenced <= titled


def test_the_repair_is_on_the_guide_once(guide_html: str) -> None:
    page = _Page()
    page.feed(guide_html)
    assert page.codes.count("rm -rf .venv && make setup") == 1
    assert _collapse(" ".join(page.text)).count("rm -rf .venv") == 1


def test_no_row_points_at_agents_md_and_only_the_game_version_points_at_the_readme() -> None:
    sources = {row["id"]: row["source"] for row in _rows() if "source" in row}
    assert "AGENTS.md" not in sources.values()
    assert [row_id for row_id, source in sources.items() if source == "README.md"] == [
        "openrct2-version"
    ]

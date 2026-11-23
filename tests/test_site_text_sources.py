"""Page text sources (R20): templates hold markup and short labels; modules hold no prose.

Prose lives in the story files' passages and the figure registry. In every `.njk` under `site/`,
after removing Nunjucks tags, HTML comments and `<script>` and `<style>` contents, a text run or an
`aria-label`, `title` or `alt` value of four or more words fails; so does a quoted string of four
or more words inside a Nunjucks tag, which the tag removal would otherwise hide. In every module the
page loads (`.mjs` under `site/assets/` outside `vendor/`), a string literal of four or more words
fails, except the message of a thrown `Error` and the two W3C namespace strings.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from tests.site_fixtures import ROOT

WORD = re.compile(r"[A-Za-z'’-]+")
LIMIT = 4
_NUNJUCKS = re.compile(r"\{#.*?#\}|\{%.*?%\}|\{\{.*?\}\}", re.DOTALL)
_COMMENT = re.compile(r"\{#.*?#\}", re.DOTALL)
_TAG = re.compile(r"\{%.*?%\}|\{\{.*?\}\}", re.DOTALL)
_TAG_STRING = re.compile(r""""((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)'""")
_HIDDEN = re.compile(
    r"<!--.*?-->|<script\b.*?</script>|<style\b.*?</style>", re.DOTALL | re.IGNORECASE
)
_ATTRIBUTE = re.compile(r"""\b(?:aria-label|title|alt)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_STRING = re.compile(
    r"""//[^\n]*|/\*.*?\*/"""
    r"""|(?P<string>"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`)""",
    re.DOTALL,
)
_THROWN = re.compile(r"throw\s+new\s+Error\s*\(\s*$")
_NAMESPACES = {"http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink"}
# Module literals exempt from the four-word limit, as (path under site/, literal with quotes).
EXEMPT_STRINGS: set[tuple[str, str]] = set()


def _words(text: str) -> int:
    return len(WORD.findall(text))


def template_prose(site: Path) -> list[str]:
    """Return every text run or labelling attribute of four or more words in the templates."""
    found = []
    for path in sorted(site.rglob("*.njk")):
        relative = path.relative_to(site).as_posix()
        if relative.startswith(("_site/", "_data/")):
            continue
        markup = _HIDDEN.sub(" ", _NUNJUCKS.sub(" ", path.read_text()))
        for match in _ATTRIBUTE.finditer(markup):
            value = match.group(1) or match.group(2) or ""
            if _words(value) >= LIMIT:
                found.append(f"{relative}: attribute {value!r}")
        for run in re.split(r"<[^>]*>", markup):
            if _words(run) >= LIMIT:
                found.append(f"{relative}: text {' '.join(run.split())!r}")
    return found


def tag_prose(site: Path) -> list[str]:
    """Return every quoted string of four or more words inside a `{% %}` or `{{ }}` tag."""
    found = []
    for path in sorted(site.rglob("*.njk")):
        relative = path.relative_to(site).as_posix()
        if relative.startswith(("_site/", "_data/")):
            continue
        for tag in _TAG.finditer(_COMMENT.sub(" ", path.read_text())):
            for match in _TAG_STRING.finditer(tag.group()):
                value = match.group(1) or match.group(2) or ""
                if _words(value) >= LIMIT:
                    found.append(f"{relative}: tag string {value!r}")
    return found


def module_prose(site: Path) -> list[str]:
    """Return every string literal of four or more words in the modules the page loads."""
    found = []
    for path in sorted((site / "assets").rglob("*.mjs")):
        relative = path.relative_to(site).as_posix()
        if relative.startswith("assets/vendor/"):
            continue
        text = path.read_text()
        for token in _STRING.finditer(text):
            string = token.group("string")
            if string is None or _THROWN.search(text[: token.start()]):
                continue
            literal = re.sub(r"\$\{[^}]*\}", " ", string[1:-1])
            if (relative, string) in EXEMPT_STRINGS:
                continue
            if string[1:-1] not in _NAMESPACES and _words(literal) >= LIMIT:
                found.append(f"{relative}: string {string!r}")
    return found


def test_templates_and_modules_hold_no_prose() -> None:
    assert template_prose(ROOT / "site") == []
    assert tag_prose(ROOT / "site") == []
    assert module_prose(ROOT / "site") == []


def _copy_site(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    shutil.copytree(ROOT / "site", site, ignore=shutil.ignore_patterns("_site", "_data"))
    return site


def test_a_sentence_planted_in_a_section_template_fails(tmp_path: Path) -> None:
    site = _copy_site(tmp_path)
    template = site / "_includes/enterprise.njk"
    template.write_text(template.read_text() + "<p>Parks open in spring.</p>\n")
    assert template_prose(site) == ["_includes/enterprise.njk: text 'Parks open in spring.'"]


def test_a_sentence_planted_in_a_label_attribute_fails(tmp_path: Path) -> None:
    site = _copy_site(tmp_path)
    template = site / "_includes/story.njk"
    template.write_text(template.read_text() + '<div aria-label="the board meeting steps"></div>\n')
    assert template_prose(site) == ["_includes/story.njk: attribute 'the board meeting steps'"]


def test_a_sentence_planted_in_a_template_tag_fails(tmp_path: Path) -> None:
    site = _copy_site(tmp_path)
    template = site / "_includes/extract.njk"
    template.write_text(template.read_text() + '{% set x = "this is a long sentence" %}{{ x }}\n')
    assert tag_prose(site) == ["_includes/extract.njk: tag string 'this is a long sentence'"]


def test_a_sentence_planted_in_a_module_fails_and_an_error_message_does_not(
    tmp_path: Path,
) -> None:
    site = _copy_site(tmp_path)
    module = site / "assets/js/story.mjs"
    module.write_text(
        module.read_text()
        + 'export const note = "parks open in spring";\n'
        + 'export const fail = () => { throw new Error("the rows are missing here"); };\n'
    )
    assert module_prose(site) == ["assets/js/story.mjs: string '\"parks open in spring\"'"]


def test_every_exempt_literal_is_still_in_its_file() -> None:
    stale = [
        f"{relative}: {literal}"
        for relative, literal in sorted(EXEMPT_STRINGS)
        if literal not in (ROOT / "site" / relative).read_text()
    ]
    assert stale == []

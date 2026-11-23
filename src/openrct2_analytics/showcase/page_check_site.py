"""Site-wide page-check rules: network bans, local scripts, lookups, figure regions, literals.

These rules read every built `.mjs` module outside `assets/vendor/`, the built `.css`, and the
figure regions of `index.html`. `page_check.py` calls `check_site` once the page-level checks pass.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

from openrct2_analytics.showcase.page_check_text import (
    CLOCKS,
    FIGURE_PENDING,
    MODULE_NUMBER_ALLOWLIST,
)

LARGE_COUNT = 1000
YEARS = (1900, 2099)
DOM_HELPERS = "assets/js/dom.mjs"
_VOID = {"meta", "link", "img", "br", "hr", "input", "source", "wbr", "col", "area", "base"}
# The W3C SVG and XLink namespace strings are identifiers, not network addresses.
_NAMESPACES = {"http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink"}
_REMOTE_CSS = re.compile(r"""(?:url\(|@import)\s*['"]?\s*(?:https?:|[/\\]{2})""", re.IGNORECASE)
_LOOKUP = re.compile(
    r"\.(?P<method>getElementById|querySelectorAll|querySelector|closest|matches)\s*\("
    r"|(?<![\w$.])(?P<helper>\$\$?)\s*\("
)
_LITERAL_ARGUMENT = re.compile(r"""\s*(?:'(?P<single>[^'\\]*)'|"(?P<double>[^"\\]*)")\s*[,)]""")
_TOKEN = re.compile(
    r"""//[^\n]*|/\*.*?\*/"""
    r"""|(?P<string>"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`)"""
    r"""|(?<![\w$.])(?P<number>\d[\d_]*\.?\d*(?:[eE][+-]?\d+)?|\.\d+)""",
    re.DOTALL,
)
_STRING_FIGURE = re.compile(
    r"""\$\s*\d|\d{1,3}(?:,\d{3})+|(?<!\d)(?:19|20)\d{2}(?!\d)""",
)
_PARK_ID = re.compile(r"k\d{13}-[A-Za-z0-9]{6}")


class PageCheckFailed(Exception):
    """The built page does not meet the showcase contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PageCheckFailed(message)


def _is_remote(value: str, prefixes: tuple[str, ...]) -> bool:
    """Read a URL the way a browser does: trimmed, scheme in any case, backslash as slash."""
    return value.strip().lower().replace("\\", "/").startswith(prefixes)


_PUBLIC_REPO = "https://github.com/jcabiles/openrct2-analytics"
_PUBLIC_LINKS = {"https://github.com/jcabiles", _PUBLIC_REPO}
_PUBLIC_BLOB = f"{_PUBLIC_REPO}/blob/main/"
_BLOB_PATH = re.compile(r"[\w./#~-]+")


def is_public_link(tag: str, attribute: str, value: str) -> bool:
    """The one exception to the no-remote-URL rule: an `<a href>` to the repository or its author.

    The value must match exactly (no trimming, no other case). The path after `blob/main/` takes no
    `%` (a browser decodes `%2e%2e` to `..`) and no `.` or `..` segment, so it cannot climb out.
    """
    if tag != "a" or attribute != "href":
        return False
    if value in _PUBLIC_LINKS:
        return True
    rest = value.removeprefix(_PUBLIC_BLOB)
    if rest == value or _BLOB_PATH.fullmatch(rest) is None:
        return False
    return not {".", ".."} & set(rest.split("#")[0].split("/"))


class _Figure:
    def __init__(self, state: str | None) -> None:
        self.state = state
        self.body: list[str] | None = None
        self.unit: list[str] | None = None


class _SiteParser(HTMLParser):
    """Collect ids, classes, scripts, `*-data` blocks and figure regions of the built page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.classes: set[str] = set()
        self.scripts: list[tuple[str | None, str | None, str]] = []
        self.json_blocks: dict[str, str] = {}
        self.figures: list[_Figure] = []
        self.unit_parts: list[list[str]] = []
        self._frames: list[tuple[str, list[list[str]], _Figure | None]] = []
        self._script: tuple[str | None, str | None, str | None, list[str]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        self.ids.update(filter(None, [values.get("id")]))
        self.classes.update(values.get("class", "").split())
        captures: list[list[str]] = []
        figure = None
        if "data-figure" in values:
            figure = _Figure(values.get("data-figure-state"))
            self.figures.append(figure)
        owner = figure or next((f[2] for f in reversed(self._frames) if f[2] is not None), None)
        if "data-figure-body" in values and owner is not None:
            owner.body = []
            captures.append(owner.body)
        if "data-figure-unit" in values:
            unit: list[str] = []
            self.unit_parts.append(unit)
            captures.append(unit)
            if owner is not None:
                owner.unit = unit
        if tag not in _VOID:
            self._frames.append((tag, captures, figure))
        if tag == "script":
            self._script = (values.get("src"), values.get("type"), values.get("id"), [])

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script is not None:
            src, kind, block_id, parts = self._script
            text = "".join(parts)
            self.scripts.append((src, kind, text))
            if block_id is not None:
                self.json_blocks[block_id] = text
            self._script = None
        if any(frame[0] == tag for frame in self._frames):
            while self._frames.pop()[0] != tag:
                pass

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script[3].append(data)
        for _, captures, _ in self._frames:
            for parts in captures:
                parts.append(data)

    @property
    def units(self) -> list[str]:
        return [" ".join("".join(parts).split()) for parts in self.unit_parts]


def _built_modules(site: Path) -> list[Path]:
    return sorted(
        path
        for path in site.rglob("*.mjs")
        if "assets/vendor" not in path.relative_to(site).as_posix()
    )


def _relative(site: Path, path: Path) -> str:
    return path.relative_to(site).as_posix()


def _check_no_remote_text(site: Path) -> None:
    """PC2: no string literal in a built module and no CSS `url(` names another host."""
    for module in _built_modules(site):
        for token in _TOKEN.finditer(module.read_text()):
            string = token.group("string")
            if string is None:
                continue
            literal = string[1:-1].strip()
            _require(
                literal in _NAMESPACES or not _is_remote(literal, ("http:", "https:", "//")),
                f"module URL: {_relative(site, module)} holds a remote string literal ({literal})",
            )
    for sheet in sorted(site.rglob("*.css")):
        if "assets/vendor" in _relative(site, sheet):
            continue
        _require(
            not _REMOTE_CSS.search(sheet.read_text()),
            f"stylesheet URL: {_relative(site, sheet)} names another host in url() or @import",
        )


def _import_specifiers(module: str) -> list[str]:
    code = _TOKEN.sub(lambda m: m.group(0) if m.lastgroup else " ", module)
    patterns = (r"\bimport\s*['\"]([^'\"]+)['\"]", r"\bfrom\s*['\"]([^'\"]+)['\"]")
    return [specifier for pattern in patterns for specifier in re.findall(pattern, code)]


def _is_site_file(site: Path, base: Path, relative: str) -> bool:
    target = (base / relative).resolve()
    return target.is_file() and site.resolve() in target.parents


def _check_scripts(site: Path, parser: _SiteParser, expected: list[str]) -> None:
    """PC12: every other script is a local file, every static import resolves, no inline code."""
    for src, kind, _ in parser.scripts:
        if src is None:
            _require(
                kind == "application/json",
                "inline script: only application/json blocks may sit in the page",
            )
        elif src not in expected:
            _require(
                not _is_remote(src, ("http:", "https:", "//", "/"))
                and _is_site_file(site, site, src),
                f"script source: {src} is not a file in the built site",
            )
    for module in _built_modules(site):
        for specifier in _import_specifiers(module.read_text()):
            _require(
                _is_site_file(site, module.parent, specifier),
                f"import: {specifier} in {_relative(site, module)} is not a file in the built site",
            )


def check_module_network(module: Path, label: str) -> None:
    """Fail when a module fetches, requests, dynamically imports or imports a remote address."""
    text = module.read_text()
    _require(
        not re.search(r"\bfetch\s*\(|XMLHttpRequest|\bimport\s*\(", text),
        f"{label}: fetch, XMLHttpRequest, and dynamic import are forbidden",
    )
    for specifier in _import_specifiers(text):
        _require(
            not _is_remote(specifier, ("http:", "https:", "//")),
            f"{label} URL: import specifier is not local ({specifier})",
        )


def check_chart_module(module_path: Path) -> None:
    """PC13 (chart module): names only its two elements and loads nothing remote."""
    module = module_path.read_text()
    literal_ids = re.findall(r"getElementById\(\s*['\"]([^'\"]*)['\"]\s*\)", module)
    _require(
        set(literal_ids) == {"park-month-data", "park-month-chart"}
        and len(literal_ids) == len(re.findall(r"getElementById\b", module))
        and not re.search(r"querySelector|getElementsBy", module),
        "chart module: must name exactly park-month-data and park-month-chart",
    )
    check_module_network(module_path, "chart module")


def _check_lookups(site: Path, parser: _SiteParser) -> None:
    """PC13: element lookups take string literals that name an id or class of the built page."""
    for module in _built_modules(site):
        label = _relative(site, module)
        text = module.read_text()
        check_module_network(module, f"module {label}")
        for match in _LOOKUP.finditer(text):
            line_start = text.rfind("\n", 0, match.start()) + 1
            line_end = text.find("\n", match.start())
            line = text[line_start : len(text) if line_end == -1 else line_end]
            if label == DOM_HELPERS and re.match(
                r"\s*(?:export\s+)?(?:const|function)\s+\$\$?(?=[\s=(])", line
            ):
                continue
            argument = _LITERAL_ARGUMENT.match(text, match.end())
            _require(
                argument is not None,
                f"module {label}: an element lookup takes a computed value, not a string literal",
            )
            assert argument is not None
            selector = argument.group("single") or argument.group("double") or ""
            if match.group("method") == "getElementById":
                ids, classes = [selector], []
            else:
                bare = re.sub(r"\[[^\]]*\]", "", selector)
                ids, classes = re.findall(r"#([\w-]+)", bare), re.findall(r"\.([\w-]+)", bare)
            for name in ids:
                _require(name in parser.ids, f"module {label}: id {name} is not in the built page")
            for name in classes:
                _require(
                    name in parser.classes, f"module {label}: class {name} is not in the built page"
                )


def _check_data_blocks(parser: _SiteParser, served_dir: Path) -> None:
    """PC3: each `*-data` block other than park-month-data equals its served file's rows."""
    for block, text in parser.json_blocks.items():
        if not block.endswith("-data") or block == "park-month-data":
            continue
        label = block.removesuffix("-data").replace("-", "_")
        path = served_dir / f"{label}.json"
        _require(path.is_file(), f"embedded {block}: served {label}.json is missing")
        try:
            embedded = json.loads(text, parse_float=Decimal, parse_int=Decimal)
            served = json.loads(path.read_text(), parse_float=Decimal, parse_int=Decimal)
        except json.JSONDecodeError as error:
            raise PageCheckFailed(f"embedded {block}: invalid JSON ({error})") from error
        _require(
            isinstance(served, dict) and embedded == served.get("rows"),
            f"embedded {block}: differs from served {label}.json",
        )


def _check_units_and_figures(parser: _SiteParser) -> None:
    """PC5 and PC15: unit lines name a unit and a clock; every figure has a state and a body."""
    for unit in parser.units:
        clock = re.search(r"clock:\s*([a-z -]+)", unit)
        _require(
            "unit:" in unit and clock is not None and clock.group(1).strip() in CLOCKS,
            f"figure unit line: needs unit: and a clock: of {', '.join(CLOCKS)} ({unit!r})",
        )
    for figure in parser.figures:
        _require(figure.state in {"live", "pending"}, "figure region: data-figure-state is missing")
        _require(figure.unit is not None, "figure region: the data-figure-unit line is missing")
        if figure.state == "pending":
            body = " ".join("".join(figure.body or []).split()) if figure.body is not None else None
            _require(
                body == FIGURE_PENDING,
                f"pending figure: body must be exactly {FIGURE_PENDING!r}",
            )
            unit = " ".join("".join(figure.unit or []).split())
            _require(
                re.search(r"\b\d{4}\b", unit) is None,
                f"pending figure: the unit line holds a year ({unit!r})",
            )


def _check_invented_text(site: Path, parser: _SiteParser, served_dir: Path) -> None:
    """PC16: no "Illustrative", and every park ID in the built site occurs in the served files."""
    served_text = "".join(path.read_text() for path in sorted(served_dir.glob("*.json")))
    built = [site / "index.html", *_built_modules(site), *sorted(site.rglob("*.css"))]
    for path in built:
        if "assets/vendor" in _relative(site, path):
            continue
        text = path.read_text()
        label = _relative(site, path)
        _require(
            re.search("illustrative", text, re.IGNORECASE) is None,
            f"illustrative copy: {label} holds the word Illustrative",
        )
        for park_id in _PARK_ID.findall(text):
            _require(
                park_id in served_text, f"park ID: {label} holds {park_id}, not in the exports"
            )


def _check_module_literals(site: Path) -> None:
    """PC17: no year, large count or formatted-figure literal outside the per-module allowlist."""
    for module in _built_modules(site):
        label = _relative(site, module)
        allowed = MODULE_NUMBER_ALLOWLIST.get(label, {})
        for token in _TOKEN.finditer(module.read_text()):
            number, string = token.group("number"), token.group("string")
            if number is not None:
                value = float(number.replace("_", ""))
                flagged = value >= LARGE_COUNT or YEARS[0] <= value <= YEARS[1]
                literal = number
            elif string is not None:
                literal = string[1:-1]
                flagged = literal not in _NAMESPACES and _STRING_FIGURE.search(literal) is not None
            else:
                continue
            _require(
                not flagged or literal in allowed,
                f"module literal: {label} holds {literal!r}, which is not in the allowlist",
            )


def check_site(site: Path, served_dir: Path, html: str, expected_sources: list[str]) -> None:
    """Run the site-wide rules over the built `site` and its `index.html` text."""
    parser = _SiteParser()
    parser.feed(html)
    _check_no_remote_text(site)
    _check_data_blocks(parser, served_dir)
    _check_scripts(site, parser, expected_sources)
    _check_lookups(site, parser)
    _check_units_and_figures(parser)
    _check_invented_text(site, parser, served_dir)
    _check_module_literals(site)

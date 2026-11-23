"""Page-check rules for the player guide, `guide/index.html` of the built site.

The guide is static prose: no script, form, image or figure, no dollar amount, only relative links
that resolve inside the built site, one three-part `.guide-step` per required step, and a
`.guide-sign-in` section, when present, with commands and a "you should see" line.
`page_check.check_page` calls `check_guide` after `check_site`.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from openrct2_analytics.showcase.page_check_site import (
    _VOID,
    PageCheckFailed,
    _is_remote,
    _require,
    is_public_link,
)

GUIDE = "guide/index.html"
REQUIRED_SECTIONS = ("install", "how-it-works", "fix-a-problem")
REQUIRED_STEPS: tuple[str, ...] = (
    "step-dev-tools",
    "step-homebrew",
    "step-homebrew-path",
    "step-tools",
    "step-node-path",
    "step-direnv-hook",
    "step-check-tools",
    "step-clone",
    "step-cd",
    "step-setup",
    "step-direnv-allow",
    "step-launcher",
)
_BANNED = {"script", "img", "picture", "video"}
_FORM = {"form", "input", "select", "textarea", "button"}
_MONEY = re.compile(r"\$\s*\d")
_PLACEHOLDER = re.compile(r"<[A-Za-z]")
_ELEMENT_NAMES = (
    "a abbr address article aside audio b base bdi bdo blockquote body br canvas caption cite code "
    "col colgroup data datalist dd del details dfn dialog div dl dt em embed fieldset figcaption "
    "figure footer form h1 h2 h3 h4 h5 h6 head header hgroup hr html i iframe img input ins kbd "
    "label legend li link main map mark menu meta meter nav noscript object ol optgroup option "
    "output p picture pre progress q rp rt ruby s samp script search section select slot small "
    "source span strong style sub summary sup svg table tbody td template textarea tfoot th thead "
    "time title tr track u ul var video wbr button"
)
_ELEMENTS = frozenset(_ELEMENT_NAMES.split())


class _Step:
    def __init__(self, step_id: str | None) -> None:
        self.step_id = step_id
        self.commands = 0
        self.command_codes: list[list[str]] = []
        self.sees: list[list[str]] = []
        self.fixes: list[list[str]] = []


class _GuideParser(HTMLParser):
    """Collect links, ids, sections, forbidden elements, steps and text outside code spans."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str, str]] = []
        self.anchors: list[str] = []
        self.ids: set[str] = set()
        self.sections: set[str] = set()
        self.tags: set[str] = set()
        self.figure = False
        self.text: list[str] = []
        self.prose: list[str] = []
        self.steps: list[_Step] = []
        self.sign_ins: list[_Step] = []
        self._frames: list[tuple[str, str | None, list[str] | None]] = []
        self._step: _Step | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        self.tags.add(tag)
        self.ids.update(filter(None, [values.get("id")]))
        self.links += [(tag, name, values[name]) for name in ("src", "href") if name in values]
        if tag == "a" and "href" in values:
            self.anchors.append(values["href"])
        self.figure = self.figure or "data-figure" in values
        classes = values.get("class", "").split()
        if tag == "section" and values.get("id"):
            self.sections.add(values["id"])
        role: str | None = None
        buffer: list[str] | None = None
        if tag == "section" and ("guide-step" in classes or "guide-sign-in" in classes):
            role = "step"
            self._step = _Step(values.get("id"))
            (self.steps if "guide-step" in classes else self.sign_ins).append(self._step)
        elif self._step is not None:
            in_command = "step-command" in classes or any(f[1] == "command" for f in self._frames)
            if "step-command" in classes:
                role, buffer = "command", []
                self._step.commands += 1
            if tag == "code" and in_command:
                buffer = []
                self._step.command_codes.append(buffer)
            for name, bucket in (("step-see", self._step.sees), ("step-fix", self._step.fixes)):
                if name in classes:
                    role, buffer = name, []
                    bucket.append(buffer)
        if tag not in _VOID:
            self._frames.append((tag, role, buffer))

    def handle_endtag(self, tag: str) -> None:
        if not any(frame[0] == tag for frame in self._frames):
            return
        while True:
            _, role, _ = frame = self._frames.pop()
            if role == "step":
                self._step = None
            if frame[0] == tag:
                break

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if not any(frame[0] == "code" for frame in self._frames):
            self.prose.append(data)
        for _, _, buffer in self._frames:
            if buffer is not None:
                buffer.append(data)


def _filled(parts: list[str]) -> bool:
    return bool("".join(parts).strip())


def _check_links(site: Path, parser: _GuideParser) -> None:
    """R5 and R19: every link is relative and names a file, a folder with index.html, or an id."""
    page = (site / GUIDE).resolve()
    for tag, attr, value in parser.links:
        if is_public_link(tag, attr, value):
            continue
        _require(
            not _is_remote(value, ("http:", "https:", "//", "/")),
            f"guide page URL: {attr} starts with a forbidden root or host ({value})",
        )
        link = urlsplit(value.strip())
        _require(
            not link.scheme,
            f"guide link: {value} has a scheme; only relative links are allowed",
        )
        if not link.path:
            target = page
        else:
            target = page.parent.joinpath(unquote(link.path)).resolve()
            if target.is_dir():
                target = target / "index.html"
            _require(
                target.is_file() and site.resolve() in target.parents,
                f"guide link: {value} does not resolve to a file in the built site",
            )
        # The ids of another page are not read; a link to it passes when its file exists.
        _require(
            not link.fragment or target != page or link.fragment in parser.ids,
            f"guide link: #{link.fragment} is not an id on the page",
        )


def _check_home_link(parser: _GuideParser) -> None:
    """R6: the guide links back to the home page with an `<a href="../">`."""
    _require(
        any(value.strip() == "../" for value in parser.anchors),
        'guide home link: a link with href="../" is missing',
    )


def _check_static(parser: _GuideParser) -> None:
    """R2 and R3: no figure region, script, image, form or dollar amount."""
    _require(not parser.figure, "guide figure: a data-figure region is not allowed")
    for tag in sorted(parser.tags & _BANNED):
        raise PageCheckFailed(f"guide element: <{tag}> is not allowed")
    for tag in sorted(parser.tags & _FORM):
        raise PageCheckFailed(f"guide form: <{tag}> is not allowed")
    money = _MONEY.search(" ".join(parser.text))
    _require(money is None, f"guide money: text holds a dollar amount ({money and money.group()})")


def _check_steps(parser: _GuideParser) -> None:
    """R8 and R19: the step IDs are the required ones in order; each step has three parts."""
    ids = tuple(step.step_id or "" for step in parser.steps)
    _require(ids == REQUIRED_STEPS, f"guide steps: ids {list(ids)} differ from {REQUIRED_STEPS}")
    for step in parser.steps:
        codes = [code for code in step.command_codes if _filled(code)]
        _require(
            step.commands == 1 and len(step.command_codes) == 1 and len(codes) == 1,
            f"guide step {step.step_id}: needs exactly one .step-command with one non-empty code",
        )
        _require(
            "<" not in "".join(codes[0]),
            f"guide step {step.step_id}: the .step-command holds a < placeholder",
        )
        _require(
            len(step.sees) == 1 and _filled(step.sees[0]),
            f"guide step {step.step_id}: needs exactly one non-empty .step-see",
        )
        _require(
            any(_filled(fix) for fix in step.fixes),
            f"guide step {step.step_id}: needs at least one non-empty .step-fix",
        )


def _check_sign_ins(parser: _GuideParser) -> None:
    """The optional sign-in section has non-empty commands without a placeholder, and one "see"."""
    for step in parser.sign_ins:
        _require(
            step.commands >= 1
            and len(step.command_codes) == step.commands
            and all(_filled(code) for code in step.command_codes),
            f"guide sign-in {step.step_id}: needs at least one .step-command, "
            "each with non-empty code",
        )
        _require(
            all("<" not in "".join(code) for code in step.command_codes),
            f"guide sign-in {step.step_id}: the .step-command holds a < placeholder",
        )
        _require(
            len(step.sees) == 1 and _filled(step.sees[0]),
            f"guide sign-in {step.step_id}: needs exactly one non-empty .step-see",
        )


def _check_placeholders(parser: _GuideParser) -> None:
    """R10: a placeholder sits in a code span; elsewhere it would be an unknown tag or a bare <."""
    unknown = sorted(parser.tags - _ELEMENTS)
    _require(
        not unknown, f"guide placeholder: <{unknown[:1] and unknown[0]}> is not an HTML element"
    )
    bare = _PLACEHOLDER.search("".join(parser.prose))
    _require(
        bare is None, f"guide placeholder: text outside a code span holds {bare and bare.group()!r}"
    )


def check_guide(site: Path) -> None:
    """Fail when `guide/index.html` of the built `site` breaks a guide rule."""
    page = site / GUIDE
    _require(page.is_file(), f"guide page: {GUIDE} is missing")
    parser = _GuideParser()
    parser.feed(page.read_text())
    _check_links(site, parser)
    _check_home_link(parser)
    _check_static(parser)
    for section in REQUIRED_SECTIONS:
        _require(section in parser.sections, f"guide section: {section} is missing")
    _check_steps(parser)
    _check_sign_ins(parser)
    _check_placeholders(parser)

"""Pin the site's rules: colours live in tokens.css, light only, no width query below a phone."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SITE = Path(__file__).resolve().parents[1] / "site"
CSS_DIR = SITE / "assets" / "css"
TOKENS = CSS_DIR / "tokens.css"
FAVICON = SITE / "assets" / "favicon.svg"

SCOPE_SUFFIXES = {".css", ".mjs", ".njk"}
EXCLUDED_DIRS = {"_site", "_data", "node_modules"}
FONT_AND_IMAGE_SUFFIXES = {
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".ico", ".bmp", ".svg",
}  # fmt: skip

# The five seed colours of the palette block: primary, accent, blue, card stock, ink.
SEED_COLOURS = ("#C4161C", "#F7C21B", "#3E8EDE", "#E8B23A", "#3B2412")

COLOUR_LITERAL = re.compile(
    r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![0-9A-Za-z_-])"
    r"|(?<![\w-])(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\("
    r"|color-mix\("
)


# A max-width media feature: only inside an @media prelude, not the max-width property.
MEDIA_PRELUDE = re.compile(r"@media\b([^{}]*)")
MAX_WIDTH_QUERY = re.compile(r"\(\s*max-width\s*:\s*([^)]*)\)")


def _files(suffixes: set[str]) -> list[Path]:
    return sorted(
        path
        for path in SITE.rglob("*")
        if path.is_file()
        and path.suffix in suffixes
        and not EXCLUDED_DIRS & set(path.relative_to(SITE).parts)
    )


def _rel(path: Path) -> str:
    return path.relative_to(SITE).as_posix()


def test_tokens_file_holds_the_five_seed_colours() -> None:
    assert TOKENS.is_file(), "site/assets/css/tokens.css is missing"
    text = TOKENS.read_text(encoding="utf-8").upper()
    missing = [seed for seed in SEED_COLOURS if seed not in text]
    assert not missing, f"tokens.css lacks seed colours {missing}"


def test_tokens_file_names_the_favicon_exception() -> None:
    assert "favicon.svg" in TOKENS.read_text(encoding="utf-8")


def test_colour_literals_and_color_mix_live_only_in_tokens_css() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _files(SCOPE_SUFFIXES):
        if path == TOKENS:
            continue
        found = COLOUR_LITERAL.findall(path.read_text(encoding="utf-8"))
        if found:
            offenders[_rel(path)] = found
    assert not offenders, f"colour literals outside tokens.css: {offenders}"


def test_favicon_is_the_one_svg_with_colour_literals() -> None:
    with_literals = sorted(
        _rel(path)
        for path in SITE.rglob("*.svg")
        if not EXCLUDED_DIRS & set(path.relative_to(SITE).parts)
        and COLOUR_LITERAL.search(path.read_text(encoding="utf-8"))
    )
    assert with_literals == ["assets/favicon.svg"]
    assert FAVICON.is_file()


def test_no_font_or_image_file_is_added() -> None:
    found = sorted(
        _rel(path)
        for path in SITE.rglob("*")
        if path.is_file()
        and path.suffix.lower() in FONT_AND_IMAGE_SUFFIXES
        and not EXCLUDED_DIRS & set(path.relative_to(SITE).parts)
    )
    assert found == ["assets/favicon.svg"]


def _max_width_px(value: str) -> float:
    """Convert a max-width query value to px (em and rem at 16 px); fail on anything else."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)(px|em|rem)\s*", value)
    assert match, f"max-width query value {value!r} is not a plain px, em or rem length"
    number, unit = float(match.group(1)), match.group(2)
    return number if unit == "px" else number * 16


def _max_width_values(css: str) -> list[str]:
    return [
        width
        for prelude in MEDIA_PRELUDE.findall(css)
        for width in MAX_WIDTH_QUERY.findall(f"@media{prelude}")
    ]


MIN_PHONE_WIDTH_PX = 320


def _assert_width_queries_reach_phones_only(css: str, name: str) -> None:
    """A max-width query below the smallest phone width would style a screen nobody has."""
    for width in _max_width_values(css):
        assert _max_width_px(width) >= MIN_PHONE_WIDTH_PX, (
            f"{name}: max-width {width} is below {MIN_PHONE_WIDTH_PX}px"
        )


def test_max_width_queries_convert_em_and_rem_and_reject_other_units() -> None:
    assert _max_width_px("1099px") == 1099
    assert _max_width_px("50em") == 800
    assert _max_width_px("64rem") == 1024
    with pytest.raises(AssertionError):
        _max_width_px("50vw")


@pytest.mark.parametrize(
    ("css", "accepted"),
    [
        ("@media (max-width : 300px) { .x {} }", False),
        ("@media (min-width: 1200px) and (max-width: 319px) { .x {} }", False),
        ("@media (max-width: 1200px), (max-width: 200px) { .x {} }", False),
        ("@media (max-width:320px) { .x {} }", True),
        ("@media (max-width : 40em) { .x {} }", True),
        ("@media (max-width:1099px) { .x {} }", True),
    ],
)
def test_every_max_width_feature_is_checked(css: str, accepted: bool) -> None:
    if accepted:
        _assert_width_queries_reach_phones_only(css, "memory.css")
    else:
        with pytest.raises(AssertionError, match="below 320px"):
            _assert_width_queries_reach_phones_only(css, "memory.css")


def _has_phone_width_rule(css_dir: Path) -> bool:
    """True when some stylesheet in `css_dir` has a max-width query below 1024 px."""
    return any(
        _max_width_px(width) < 1024
        for sheet in sorted(css_dir.glob("*.css"))
        for width in _max_width_values(sheet.read_text(encoding="utf-8"))
    )


def test_site_stylesheets_keep_phone_width_rules() -> None:
    assert _has_phone_width_rule(CSS_DIR), (
        "no max-width query below 1024px: the phone layout is gone"
    )


def test_stylesheets_are_light_only_and_width_queries_stay_at_phone_size_or_above() -> None:
    sheets = sorted(CSS_DIR.glob("*.css"))
    assert sheets, "no stylesheets under site/assets/css"
    for sheet in sheets:
        text = sheet.read_text(encoding="utf-8")
        assert "prefers-color-scheme" not in text, sheet.name
        assert 'data-theme="dark"' not in text, sheet.name
        assert "fonts.googleapis" not in text, sheet.name
        _assert_width_queries_reach_phones_only(text, sheet.name)


def test_kept_rules_are_present() -> None:
    all_css = "\n".join(path.read_text(encoding="utf-8") for path in CSS_DIR.glob("*.css"))
    assert "@media (max-width:1099px)" in (CSS_DIR / "nav.css").read_text(encoding="utf-8")
    assert all_css.count("prefers-reduced-motion: reduce") == 3

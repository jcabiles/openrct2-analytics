"""One failing case per guide page-check rule (R19); each starts from the valid page."""

from __future__ import annotations

from pathlib import Path

import pytest

from openrct2_analytics.showcase import page_check_guide
from openrct2_analytics.showcase.page_check_guide import check_guide
from openrct2_analytics.showcase.page_check_site import PageCheckFailed
from tests.page_check_support import GUIDE_PAGE, GUIDE_STEPS, _run, _site
from tests.test_guide_strings import guide_html  # noqa: F401  (the one built guide, reused)

SECTION = '<section id="install"><p>Before you start.</p></section>'
STEP_PARTS = {
    "command": '<p class="step-command"><code>make setup</code></p>',
    "see": '<p class="step-see">Doctor reports the environment whole.</p>',
    "fix": '<p class="step-fix">If a tool is missing, open a new window.</p>',
}
STEP_IDS = ("step-one", "step-two")
SIGN_IN_COMMAND = '<div class="step-command"><pre><code>gh auth login</code></pre></div>'
SIGN_IN_SEE = '<div class="step-see"><p>You should see: Logged in as your name.</p></div>'
SIGN_IN = (
    '<section class="guide-sign-in" id="step-sign-in">'
    '<div class="step-command"><pre><code>brew install gh</code></pre></div>'
    f"{SIGN_IN_COMMAND}{SIGN_IN_SEE}</section>"
)


def _guide(tmp_path: Path, old: str, new: str) -> Path:
    """Return a built site whose guide page has `old` replaced by `new`."""
    site, _ = _site(tmp_path)
    page = site / "guide/index.html"
    assert old in GUIDE_PAGE
    page.write_text(GUIDE_PAGE.replace(old, new))
    return site


def _with(tmp_path: Path, extra: str) -> Path:
    return _guide(tmp_path, SECTION, SECTION + extra)


def _with_steps(tmp_path: Path, steps: str) -> Path:
    """Return a built site whose twelve fixture steps are replaced by `steps`."""
    return _guide(tmp_path, GUIDE_STEPS, steps)


def _step(step_id: str, **parts: str) -> str:
    body = "".join(parts.get(name, text) for name, text in STEP_PARTS.items())
    return f'<section class="guide-step" id="{step_id}">{body}</section>'


def _fails(site: Path, message: str) -> None:
    with pytest.raises(PageCheckFailed) as error:
        check_guide(site)
    assert str(error.value) == message


def test_the_valid_guide_page_passes_and_the_page_check_runs_it(tmp_path: Path) -> None:
    site, served = _site(tmp_path)
    assert (site / "index.html").is_file()
    check_guide(site)
    assert _run(site, served) == 0


def test_the_page_check_reports_a_guide_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site, served = _site(tmp_path)
    (site / "guide/index.html").unlink()
    assert _run(site, served) == 1
    out = capsys.readouterr().out
    assert "page check failed: guide page: guide/index.html is missing" in out


def test_a_missing_guide_file_fails(tmp_path: Path) -> None:
    site, _ = _site(tmp_path)
    (site / "guide/index.html").unlink()
    _fails(site, "guide page: guide/index.html is missing")


@pytest.mark.parametrize("replacement", ["", '<a href="#main">Home</a>'])
def test_a_guide_without_the_home_link_fails(tmp_path: Path, replacement: str) -> None:
    site = _guide(tmp_path, '<a href="../">Home</a>', replacement)
    _fails(site, 'guide home link: a link with href="../" is missing')


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("href", "http://example.org"),
        ("href", "https://example.org"),
        ("href", "HTTPS://example.org"),
        ("href", "//example.org"),
        ("href", "/guide/"),
        ("href", " /guide/"),
        ("href", "\\guide"),
        ("src", "//example.org/x.css"),
    ],
)
def test_a_remote_or_rooted_link_fails(tmp_path: Path, attribute: str, value: str) -> None:
    element = f'<link {attribute}="{value}">'
    site = _with(tmp_path, element)
    _fails(site, f"guide page URL: {attribute} starts with a forbidden root or host ({value})")


def test_a_relative_link_to_a_missing_file_fails(tmp_path: Path) -> None:
    site = _with(tmp_path, '<a href="missing.html">x</a>')
    _fails(site, "guide link: missing.html does not resolve to a file in the built site")


def test_a_link_to_the_site_root_fails_without_its_index_page(tmp_path: Path) -> None:
    site, _ = _site(tmp_path)
    (site / "index.html").unlink()
    _fails(site, "guide link: ../ does not resolve to a file in the built site")


def test_a_link_to_an_id_the_page_lacks_fails(tmp_path: Path) -> None:
    site = _with(tmp_path, '<a href="#nowhere">x</a>')
    _fails(site, "guide link: #nowhere is not an id on the page")


def test_a_link_to_an_id_the_page_holds_passes(tmp_path: Path) -> None:
    check_guide(_with(tmp_path, '<a href="#install">x</a>'))


def test_a_link_to_the_guide_file_with_an_id_the_page_lacks_fails(tmp_path: Path) -> None:
    site = _with(tmp_path, '<a href="index.html#nowhere">x</a>')
    _fails(site, "guide link: #nowhere is not an id on the page")


def test_a_link_to_the_guide_file_with_an_id_the_page_holds_passes(tmp_path: Path) -> None:
    check_guide(_with(tmp_path, '<a href="index.html#install">x</a>'))


def test_a_link_with_a_scheme_fails(tmp_path: Path) -> None:
    site = _with(tmp_path, '<a href="mailto:#main">x</a>')
    _fails(site, "guide link: mailto:#main has a scheme; only relative links are allowed")


def test_a_stylesheet_link_to_the_site_root_is_not_the_home_link(tmp_path: Path) -> None:
    site = _guide(tmp_path, '<a href="../">Home</a>', '<link rel="stylesheet" href="../">')
    _fails(site, 'guide home link: a link with href="../" is missing')


def test_an_anchor_to_the_site_root_is_the_home_link(tmp_path: Path) -> None:
    check_guide(_guide(tmp_path, '<a href="../">Home</a>', '<a class="home" href="../">Home</a>'))


def test_a_data_figure_region_fails(tmp_path: Path) -> None:
    site = _with(tmp_path, '<div data-figure="f"></div>')
    _fails(site, "guide figure: a data-figure region is not allowed")


@pytest.mark.parametrize(
    "element",
    ["<script></script>", '<img alt="x">', "<picture></picture>", "<video></video>"],
)
def test_a_script_or_media_element_fails(tmp_path: Path, element: str) -> None:
    site = _with(tmp_path, element)
    tag = element.split(">")[0].lstrip("<").split()[0]
    _fails(site, f"guide element: <{tag}> is not allowed")


@pytest.mark.parametrize("element", ["<form></form>", '<input type="text">'])
def test_a_form_or_form_control_fails(tmp_path: Path, element: str) -> None:
    site = _with(tmp_path, element)
    tag = element.split(">")[0].lstrip("<").split()[0]
    _fails(site, f"guide form: <{tag}> is not allowed")


def test_a_dollar_amount_fails(tmp_path: Path) -> None:
    site = _with(tmp_path, "<p>It costs $12.</p>")
    _fails(site, "guide money: text holds a dollar amount ($1)")


def test_a_company_date_passes(tmp_path: Path) -> None:
    check_guide(_with(tmp_path, "<p>The company starts on 1 March 2000.</p>"))


def test_a_missing_required_section_fails(tmp_path: Path) -> None:
    site = _guide(tmp_path, 'id="install"', 'id="other"')
    _fails(site, "guide section: install is missing")


def test_a_missing_how_it_works_section_fails(tmp_path: Path) -> None:
    site = _guide(tmp_path, 'id="how-it-works"', 'id="other"')
    _fails(site, "guide section: how-it-works is missing")


def test_a_missing_help_section_fails(tmp_path: Path) -> None:
    site = _guide(tmp_path, 'id="fix-a-problem"', 'id="other"')
    _fails(site, "guide section: fix-a-problem is missing")


def test_a_valid_sign_in_section_passes(tmp_path: Path) -> None:
    check_guide(_with(tmp_path, SIGN_IN))


def test_a_sign_in_command_with_no_code_fails(tmp_path: Path) -> None:
    site = _with(tmp_path, SIGN_IN.replace("<code>gh auth login</code>", "<code></code>"))
    _fails(
        site,
        "guide sign-in step-sign-in: needs at least one .step-command, each with non-empty code",
    )


def test_a_sign_in_command_with_a_placeholder_fails(tmp_path: Path) -> None:
    site = _with(
        tmp_path,
        SIGN_IN.replace(
            "<code>gh auth login</code>", "<code>gh auth login --hostname &lt;host&gt;</code>"
        ),
    )
    _fails(site, "guide sign-in step-sign-in: the .step-command holds a < placeholder")


def test_a_sign_in_without_the_you_should_see_line_fails(tmp_path: Path) -> None:
    site = _with(tmp_path, SIGN_IN.replace(SIGN_IN_SEE, ""))
    _fails(site, "guide sign-in step-sign-in: needs exactly one non-empty .step-see")


def test_step_ids_that_differ_from_the_required_ones_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(page_check_guide, "REQUIRED_STEPS", STEP_IDS)
    site = _with_steps(tmp_path, _step("step-one") + _step("step-three"))
    _fails(
        site,
        "guide steps: ids ['step-one', 'step-three'] differ from ('step-one', 'step-two')",
    )


REAL_STEP_IDS = (
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


def test_the_required_steps_are_the_twelve_install_steps_in_order() -> None:
    assert page_check_guide.REQUIRED_STEPS == REAL_STEP_IDS


def test_a_guide_without_the_first_install_step_fails(tmp_path: Path) -> None:
    site = _guide(tmp_path, '<section class="guide-step" id="step-dev-tools">', "<section>")
    _fails(
        site,
        f"guide steps: ids {list(REAL_STEP_IDS[1:])} differ from {REAL_STEP_IDS}",
    )


def test_install_steps_out_of_order_fail(tmp_path: Path) -> None:
    swapped = (
        GUIDE_STEPS.replace("step-homebrew-path", "step-x")
        .replace('id="step-homebrew"', 'id="step-homebrew-path"')
        .replace("step-x", "step-homebrew")
    )
    site = _with_steps(tmp_path, swapped)
    ids = list(REAL_STEP_IDS)
    ids[1], ids[2] = ids[2], ids[1]
    _fails(site, f"guide steps: ids {ids} differ from {REAL_STEP_IDS}")


def test_steps_with_the_required_ids_in_order_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(page_check_guide, "REQUIRED_STEPS", STEP_IDS)
    check_guide(_with_steps(tmp_path, _step("step-one") + _step("step-two")))


@pytest.mark.parametrize(
    ("part", "message"),
    [
        ("command", "needs exactly one .step-command with one non-empty code"),
        ("see", "needs exactly one non-empty .step-see"),
        ("fix", "needs at least one non-empty .step-fix"),
    ],
)
def test_a_step_missing_a_part_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, part: str, message: str
) -> None:
    monkeypatch.setattr(page_check_guide, "REQUIRED_STEPS", ("step-one",))
    site = _with_steps(tmp_path, _step("step-one", **{part: ""}))
    _fails(site, f"guide step step-one: {message}")


def test_a_step_command_with_a_placeholder_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(page_check_guide, "REQUIRED_STEPS", ("step-one",))
    command = '<p class="step-command"><code>cd &lt;folder&gt;</code></p>'
    site = _with_steps(tmp_path, _step("step-one", command=command))
    _fails(site, "guide step step-one: the .step-command holds a < placeholder")


def test_a_placeholder_in_prose_fails(tmp_path: Path) -> None:
    site = _with(tmp_path, "<p>Open <repo folder> now.</p>")
    _fails(site, "guide placeholder: <repo> is not an HTML element")


def test_an_escaped_placeholder_in_prose_fails(tmp_path: Path) -> None:
    site = _with(tmp_path, "<p>Open &lt;id&gt; now.</p>")
    _fails(site, "guide placeholder: text outside a code span holds '<i'")


def test_a_placeholder_in_a_code_span_passes(tmp_path: Path) -> None:
    check_guide(_with(tmp_path, "<p>Use <code>&lt;id&gt;</code> here.</p>"))


def _built_section(page: str, start: str, end: str) -> str:
    """Return the built guide html between the markers `start` and `end`."""
    return page.split(start, 1)[1].split(end, 1)[0]


def test_the_built_clone_step_names_the_green_code_button(
    guide_html: str,  # noqa: F811
) -> None:
    clone = _built_section(guide_html, 'id="step-clone"', 'id="step-cd"')
    assert "green Code button" in clone


def test_the_built_clone_step_names_the_https_address(
    guide_html: str,  # noqa: F811
) -> None:
    clone = _built_section(guide_html, 'id="step-clone"', 'id="step-cd"')
    assert "HTTPS" in clone


def test_the_built_install_prerequisites_name_the_game_files(
    guide_html: str,  # noqa: F811
) -> None:
    install = _built_section(guide_html, 'id="install"', 'id="step-dev-tools"')
    assert "RollerCoaster Tycoon 2" in install

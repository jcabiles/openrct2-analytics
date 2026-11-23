"""The public-preview exception to the no-remote-URL page rule: one case per allowlist item."""

from __future__ import annotations

from pathlib import Path

import pytest

from openrct2_analytics.showcase.page_check_guide import check_guide
from openrct2_analytics.showcase.page_check_site import PageCheckFailed
from tests.page_check_support import _html_append, _run, _site
from tests.test_showcase_page_check_guide import SECTION, _guide

REPO = "https://github.com/jcabiles/openrct2-analytics"
ALLOWED = [
    pytest.param("https://github.com/jcabiles", id="author profile"),
    pytest.param(REPO, id="repository"),
    pytest.param(f"{REPO}/blob/main/docs/review-catches.md#5-x", id="file on the main branch"),
]
# (tag, attribute, value) that must stay refused, each differing from a valid page in one thing.
REFUSED = [
    pytest.param(("script", "src", REPO), id="repository URL in a src"),
    pytest.param(("link", "href", REPO), id="repository URL on a link href"),
    pytest.param(("a", "href", "https://github.com/someoneelse"), id="another account"),
    pytest.param(("a", "href", f"{REPO}.evil.test/x"), id="look-alike host"),
    pytest.param(("a", "href", "http://github.com/jcabiles"), id="http scheme"),
    pytest.param(("a", "href", "//github.com/jcabiles"), id="protocol-relative"),
    pytest.param(("a", "href", f"{REPO}/blob/other/x"), id="another branch"),
    pytest.param(("a", "href", f"{REPO}/blob/main/../../../someoneelse"), id="path climbing out"),
    pytest.param(
        ("a", "href", f"{REPO}/blob/main/%2e%2e/%2e%2e/%2e%2e/%2e%2e/x"), id="encoded climb"
    ),
    pytest.param(("a", "href", f"{REPO}/blob/main/./README.md"), id="dot segment"),
    pytest.param(("a", "href", f"{REPO}/blob/main/"), id="empty file path"),
    pytest.param(("a", "href", "https://github.com/JCABILES"), id="other case"),
    pytest.param(("a", "href", "HTTPS://github.com/jcabiles"), id="scheme in capitals"),
    pytest.param(("a", "href", "https://github.com/jcabiles/"), id="trailing slash"),
    pytest.param(("a", "href", " https://github.com/jcabiles"), id="leading space"),
]


def _element(tag: str, attribute: str, value: str) -> str:
    return f'<{tag} {attribute}="{value}"></{tag}>'


@pytest.mark.parametrize("url", ALLOWED)
def test_the_page_allows_an_anchor_to_the_public_url(tmp_path: Path, url: str) -> None:
    site, served = _site(tmp_path)
    _html_append(_element("a", "href", url))(site, served)
    assert _run(site, served) == 0


@pytest.mark.parametrize("case", REFUSED)
def test_the_page_refuses_any_other_remote_url(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: tuple[str, str, str]
) -> None:
    tag, attribute, value = case
    site, served = _site(tmp_path)
    _html_append(_element(tag, attribute, value))(site, served)
    assert _run(site, served) == 1
    message = f"page URL: {attribute} starts with a forbidden root or host ({value})"
    assert f"page check failed: {message}" in capsys.readouterr().out


@pytest.mark.parametrize("url", ALLOWED)
def test_the_guide_allows_an_anchor_to_the_public_url(tmp_path: Path, url: str) -> None:
    site = _guide(tmp_path, SECTION, SECTION + _element("a", "href", url))
    check_guide(site)


@pytest.mark.parametrize("case", REFUSED)
def test_the_guide_refuses_any_other_remote_url(tmp_path: Path, case: tuple[str, str, str]) -> None:
    tag, attribute, value = case
    # A guide has no script element (a separate rule), so a src is planted on a link.
    tag = "link" if tag == "script" else tag
    site = _guide(tmp_path, SECTION, SECTION + _element(tag, attribute, value))
    with pytest.raises(PageCheckFailed) as error:
        check_guide(site)
    assert str(error.value) == (
        f"guide page URL: {attribute} starts with a forbidden root or host ({value})"
    )

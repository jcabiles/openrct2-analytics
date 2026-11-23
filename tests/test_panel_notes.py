"""Panel notes (R14): the six "not recorded" lines and the riders note on the rendered page.

The real site is built over the committed sample `site/_data/`, then each line is counted in its
department view. A line missing, doubled or moved to another view fails.
"""

from __future__ import annotations

import re

import pytest

from tests.page_check_support import ROOT, render_page

FINANCE_LINES = (
    "Profit after depreciation and tax: the game does not record it.",
    "Admission price: not shown; entry is free on the captured parks, which charge per ride.",
)
OPERATIONS_LINES = (
    "Time between failures: the game does not record it.",
    "Time to repair: the game does not record it.",
    "Hourly ride capacity: the game does not record it.",
    "Staff hours: the game does not record it.",
)
RIDERS_NOTE = (
    "Riders: the game counts a guest on leaving the ride, and also counts each on-ride photo sold."
)


@pytest.fixture(scope="module")
def page(tmp_path_factory: pytest.TempPathFactory) -> str:
    work = tmp_path_factory.mktemp("panel-notes")
    site = render_page(ROOT / "site/_data", work)
    return (site / "index.html").read_text()


def _view_html(page: str, name: str) -> str:
    """Return the markup of one department view, up to the next view or the footer."""
    match = re.search(rf'id="view-{name}".*?(?=id="view-|<footer)', page, re.DOTALL)
    assert match, name
    return match.group()


def _view(page: str, name: str) -> str:
    """Return the text of one department view, tags removed and white space collapsed."""
    return _text(_view_html(page, name))


def _region(page: str, name: str, start: str, end: str) -> str:
    """Return the text of a view from the figure `start` up to the figure `end`."""
    match = re.search(
        rf'data-figure="{start}".*?(?=data-figure="{end}")', _view_html(page, name), re.DOTALL
    )
    assert match, (start, end)
    return _text(match.group())


def _text(html: str) -> str:
    return " ".join(re.sub(r"<[^>]*>", " ", html).split())


@pytest.mark.parametrize("line", FINANCE_LINES, ids=[line.split(":")[0] for line in FINANCE_LINES])
def test_finance_line_appears_once_in_the_finance_view(page: str, line: str) -> None:
    assert _view(page, "fin").count(line) == 1
    assert _view(page, "ops").count(line) == 0


@pytest.mark.parametrize(
    "line", OPERATIONS_LINES, ids=[line.split(":")[0] for line in OPERATIONS_LINES]
)
def test_operations_line_appears_once_in_the_operations_view(page: str, line: str) -> None:
    assert _view(page, "ops").count(line) == 1
    assert _view(page, "fin").count(line) == 0


def test_riders_note_appears_once_in_the_operations_riders_region(page: str) -> None:
    region = _region(page, "ops", "ops-riders", "ops-guardrails")
    assert region.count(RIDERS_NOTE) == 1
    assert _view(page, "ops").count(RIDERS_NOTE) == 1


def test_riders_note_appears_once_in_the_attractions_rating_region(page: str) -> None:
    region = _region(page, "attr", "attr-rating", "attr-age")
    assert region.count(RIDERS_NOTE) == 1
    assert _view(page, "attr").count(RIDERS_NOTE) == 1


def test_no_operations_figure_heading_holds_the_word_open(page: str) -> None:
    headings = [_text(h) for h in re.findall(r"<h3>(.*?)<span", _view_html(page, "ops"), re.DOTALL)]
    assert len(headings) == 4
    assert not [h for h in headings if re.search(r"\bopen\b", h, re.IGNORECASE)]


def test_the_mockups_combined_sentences_are_gone(page: str) -> None:
    assert "Real parks also track" not in page

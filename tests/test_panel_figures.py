"""Panel wiring (R11, R16): the six served department panels render their export column.

The real site is built over the committed sample `site/_data/`. Each expected value is copied
from the sample row it comes from, not computed. The two panels with no export stay pending.
"""

from __future__ import annotations

import re

import pytest

from tests.page_check_support import ROOT, render_page


@pytest.fixture(scope="module")
def page(tmp_path_factory: pytest.TempPathFactory) -> str:
    work = tmp_path_factory.mktemp("panel-figures")
    site = render_page(ROOT / "site/_data", work)
    return (site / "index.html").read_text()


def _state(page: str, figure_id: str) -> str:
    match = re.search(rf'data-figure="{figure_id}" data-figure-state="(\w+)"', page)
    assert match, figure_id
    return match.group(1)


def _rows(page: str, figure_id: str) -> list[list[str]]:
    table = re.search(rf'<table id="{figure_id}-table".*?</table>', page, re.DOTALL)
    assert table, figure_id
    rows = re.findall(r"<tr>(.*?)</tr>", table.group(), re.DOTALL)
    return [[" ".join(c.split()) for c in re.findall(r"<td>(.*?)</td>", row)] for row in rows[1:]]


# (figure, row count in the sample export it reads, one sample row as shown)
LIVE_PANELS = [
    pytest.param(
        "fin-mix",
        3,
        [
            "Park 1",
            "Mar 2000",
            "$6,060.00",
            "$1,221.80",
            "$229.00",
            "$0.00",
            "80.68",
            "16.27",
            "3.05",
            "0.00",
        ],  # fmt: skip
        id="revenue mix",
    ),
    pytest.param(
        "ops-availability",
        28,
        ["Park 1", "Wooden Wild Mouse 1", "Apr 2000", "94.41"],
        id="availability by ride",
    ),
    pytest.param(
        "ops-waits",
        20,
        ["Park 1", "Enterprise 1", "Mar 2000", "6"],
        id="longest line by ride",
    ),
    pytest.param(
        "ops-riders",
        28,
        ["Park 1", "Wooden Roller Coaster 1", "Mar 2000", "260"],
        id="riders per ride by month",
    ),
    pytest.param(
        "attr-rating",
        7,
        ["Park 1", "Enterprise 1", "2000", "512", "65"],
        id="riders against guest rating",
    ),
    pytest.param(
        "attr-age",
        7,
        ["Park 1", "Maze 1", "2000", "51", "75"],
        id="ride age",
    ),
]


@pytest.mark.parametrize(("figure_id", "count", "row"), LIVE_PANELS)
def test_served_panel_is_live_and_renders_its_export_column(
    page: str, figure_id: str, count: int, row: list[str]
) -> None:
    assert _state(page, figure_id) == "live"
    rows = _rows(page, figure_id)
    assert len(rows) == count
    assert row in rows


def test_longest_line_panel_keeps_only_the_five_busiest_rides(page: str) -> None:
    names = {row[1] for row in _rows(page, "ops-waits")}
    assert len(names) == 5
    assert not names & {"Wooden Wild Mouse 1", "Looping Roller Coaster 1"}


@pytest.mark.parametrize("figure_id", ["fin-visits", "fin-price"])
def test_held_back_panel_still_renders_as_pending(page: str, figure_id: str) -> None:
    assert _state(page, figure_id) == "pending"
    body = re.search(
        rf'data-figure="{figure_id}".*?data-figure-body[^>]*>(.*?)</div>', page, re.DOTALL
    )
    assert body
    assert body.group(1).strip() == "figure pending"

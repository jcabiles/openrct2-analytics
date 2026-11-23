"""The shared page shell shows a switch for Sandbox parks and reads it from the address only.

Every page runs in the smoke script's stand-in for the browser, over a data file built from a
planted warehouse; the labels come from a planted JSON file or from a served page.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from datetime import tzinfo
from pathlib import Path
from typing import Any

import pytest

from openrct2_analytics.config import LandingDirs
from openrct2_analytics.ingest import dashboard
from tests.dashboard_unfiled_support import _page
from tests.dashboard_unfiled_support import landing as landing  # noqa: F401  (pytest fixture)
from tests.test_dashboard import APP, SMOKE, _ready
from tests.test_dashboard_data import Options
from tests.test_dashboard_sandbox import ONLY_P1, PRACTICE, R1
from tests.test_dashboard_sandbox_server import LABELS, _r1_board, _script_labels

PAGES = ["executive", "finance", "attractions", "pricing", "operations"]
BAZAAR = {"s1": "Bumbly Bazaar (Nov 15, 3:42 pm)", "s2": "Bumbly Bazaar (Nov 15, 4:10 pm)"}
LEFT_OUT = "The All parks figures leave out these Sandbox parks:"
INCLUDED = "The All parks figures include these Sandbox parks:"
EMPTY = (
    "No company park has a closed month yet. Sandbox parks are left out of All parks; "
    "choose Included under Sandbox parks to see them."
)
ONLY_SANDBOX: Options = {"parks": (("s1", "Bumbly Bazaar"),), "notes": (PRACTICE,)}
LATE: Options = {**R1, "starts": (6, 3, 3)}
GAP: Options = {**R1, "gaps": ((5,),)}
GAP_FIRST: Options = {**R1, "gaps": ((3,),)}
GAP_LAST: Options = {**R1, "gaps": ((10,),)}
PRIOR_GAP: Options = {**R1, "gaps": ((5,),), "gap_years": (2001,)}
ALL_LABELS = [[97.5, "Mar"], [188.5, "Apr"], [279.5, "May"], [370.5, "Jun"], [461.5, "Jul"],
              [552.5, "Aug"], [643.5, "Sep"], [734.5, "Oct"]]  # fmt: skip
OLD_EMPTY = (
    "No monthly statement is in the working copy yet. The pages fill in once the first game "
    "month closes and make after-play DATA_SET=company has run."
)
NO_CLOSED_MONTH: Options = {"gaps": ((3, 4, 5, 6, 7, 8, 9, 10),)}
NO_PARKS: Options = {"parks": ()}
BUILD_REVERSED: Options = {
    "parks": (("p1", "Alpha Park"), ("s2", "Bumbly Bazaar"), ("s1", "Bumbly Bazaar")),
    "notes": ("", PRACTICE, PRACTICE),
}
# Company: October 2001 and March 2002 only; the Sandbox park also holds March 2001.
NO_PAIR: Options = {
    "starts": (10, 3),
    "gaps": ((4, 5, 6, 7, 8, 9, 10), ()),
    "gap_years": (2002,),
    "parks": (("p1", "Alpha Park"), ("s1", "Bumbly Bazaar")),
    "notes": ("", PRACTICE),
}
ONE_EACH: Options = {
    "parks": (("p1", "Alpha Park"), ("s1", "Bumbly Bazaar")),
    "notes": ("", PRACTICE),
}


def _smoke(
    tmp_path: Path,
    options: Options,
    *flags: str,
    labels: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Run the five pages over the data file built from ``options``."""
    board = _ready(tmp_path, **options)
    board.refresh()
    assert board.current is not None, board.problem
    return _run(board, tmp_path, flags, labels)


def _run(
    board: dashboard.Dashboard,
    tmp_path: Path,
    flags: tuple[str, ...],
    labels: dict[str, str] | None,
) -> dict[str, dict[str, Any]]:
    assert board.current is not None
    site = board.current.site
    labels_flag: list[str] = []
    if labels is not None:
        file = tmp_path / "labels.json"
        file.write_text(json.dumps(labels))
        labels_flag = [f"--labels={file}"]
    result = subprocess.run(
        ["node", str(SMOKE), str(site), str(site / dashboard.DATA_FILE), *flags, *labels_flag],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    pages: dict[str, dict[str, Any]] = json.loads(result.stdout)
    return pages


def _note(heading: str, *labels: str) -> str:
    return "\n".join([heading, *labels])


def test_the_app_keeps_no_stored_state() -> None:
    forbidden = (
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "history.",
        "window.name",
        "indexedDB",
    )
    found = [
        (path.name, word)
        for path in sorted(APP.iterdir())
        if path.is_file()
        for word in forbidden
        if word in path.read_text()
    ]

    assert found == []


def test_the_included_state_comes_from_the_query(tmp_path: Path) -> None:
    pages = _smoke(tmp_path, R1, "--sandbox", labels=BAZAAR)

    assert pages["executive"]["sample"].startswith("Sample: 3 parks, one player,")
    assert pages["finance"]["tabs"] == [
        "executive.html?sandbox=shown",
        "finance.html?sandbox=shown",
        "attractions.html?sandbox=shown",
        "pricing.html?sandbox=shown",
        "operations.html?sandbox=shown",
    ]
    assert pages["finance"]["sandbox_pressed"] == "Included"
    assert pages["finance"]["sandbox_note"] == _note(INCLUDED, *BAZAAR.values())
    assert "Sandbox parks" in pages["finance"]["text"]


def test_the_default_state_leaves_the_sandbox_parks_out(tmp_path: Path) -> None:
    pages = _smoke(tmp_path, R1, labels=BAZAAR)

    assert pages["executive"]["sample"].startswith("Sample: 1 park, one player,")
    assert pages["executive"]["sandbox_pressed"] == "Left out"
    assert pages["executive"]["tabs"][1] == "finance.html"


def test_a_hand_typed_with_sandbox_park_is_not_a_route(tmp_path: Path) -> None:
    pages = _smoke(tmp_path, R1, "--park=with_sandbox", labels=BAZAAR)

    assert pages["executive"]["sample"].startswith("Sample: 1 park, one player,")
    assert pages["executive"]["sandbox_pressed"] == "Left out"
    assert pages["executive"]["tabs"][1] == "finance.html"


def test_the_switch_round_trips_through_clicks_and_the_picker(tmp_path: Path) -> None:
    pages = _smoke(tmp_path, R1, "--follow", labels=BAZAAR)

    assert [len(page["hops"]) for page in pages.values()] == [5] * 5
    included, tab, left_out, park, back = pages["executive"]["hops"]
    assert included["search"] == "?sandbox=shown"
    assert included["sandbox_pressed"] == "Included"
    assert included["sandbox_note"] == _note(INCLUDED, *BAZAAR.values())
    assert (tab["page"], tab["search"]) == ("finance", "?sandbox=shown")
    assert tab["sandbox_pressed"] == "Included"
    assert left_out["search"] == ""
    assert left_out["sandbox_pressed"] == "Left out"
    assert park["search"] == "?park=s2"
    assert park["sandbox_note"] == ""
    assert park["sandbox_pressed"] is None
    assert park["tabs"] == [
        f"{page}.html?park=s2"
        for page in ("executive", "finance", "attractions", "pricing", "operations")
    ]
    assert park["sample"].startswith("Sample: 1 park, one player,")
    assert back["search"] == ""
    assert back["sandbox_pressed"] == "Left out"
    assert back["sandbox_note"] == _note(LEFT_OUT, *BAZAAR.values())


@pytest.mark.parametrize(
    "labels",
    [
        BAZAAR,
        {"s1": "s1 (first-played date unavailable)", "s2": "s2 (first-played date unavailable)"},
    ],
)
def test_the_switch_is_on_every_page_and_names_the_hidden_parks(
    tmp_path: Path, labels: dict[str, str]
) -> None:
    pages = _smoke(tmp_path, R1, labels=labels)

    assert list(pages) == PAGES
    lines = [page["sandbox_note"].split("\n")[1:] for page in pages.values()]
    assert lines == [list(labels.values())] * 5
    assert len(set(lines[0])) == 2
    assert [page["sandbox_note"].split("\n")[0] for page in pages.values()] == [LEFT_OUT] * 5
    assert [page["sandbox_pressed"] for page in pages.values()] == ["Left out"] * 5


def test_the_served_labels_reach_the_switch_note(
    tmp_path: Path, landing: LandingDirs, fixed_local_zone: Callable[[tzinfo], None]
) -> None:
    board = _r1_board(tmp_path, fixed_local_zone, landing)
    served = _script_labels(_page(board))

    pages = _run(board, tmp_path, ("--sandbox",), served)

    assert served == LABELS
    assert pages["pricing"]["sandbox_note"].split("\n")[1:] == [
        "Bumbly Bazaar (Oct 17, 12:00 pm)",
        "Bumbly Bazaar (Oct 17, 1:30 pm)",
    ]


def test_a_park_view_has_no_switch(tmp_path: Path) -> None:
    pages = _smoke(tmp_path, R1, "--park=p1", labels=BAZAAR)

    assert pages["executive"]["sandbox_note"] == ""
    assert pages["executive"]["sandbox_pressed"] is None


def test_no_switch_is_drawn_without_a_sandbox_park(tmp_path: Path) -> None:
    pages = _smoke(tmp_path, ONLY_P1, "--sandbox")

    assert pages["executive"]["sandbox_note"] == ""
    assert pages["executive"]["sandbox_pressed"] is None
    assert pages["executive"]["tabs"][1] == "finance.html"


def test_a_lone_company_park_address_shows_the_all_parks_view(tmp_path: Path) -> None:
    pages = _smoke(tmp_path, ONLY_P1, "--park=p1")

    assert pages["executive"]["sample"].startswith("Sample: 1 park, one player,")
    assert pages["executive"]["tabs"][1] == "finance.html"


def test_only_sandbox_parks_gives_the_company_empty_sentence(tmp_path: Path) -> None:
    labels = {"s1": "Bumbly Bazaar (Nov 15, 3:42 pm)"}
    hidden = _smoke(tmp_path / "a", ONLY_SANDBOX, labels=labels)["executive"]
    shown = _smoke(tmp_path / "b", ONLY_SANDBOX, "--sandbox", labels=labels)["executive"]
    picker = _smoke(tmp_path / "c", ONE_EACH, labels=labels)["executive"]["picker"]

    assert hidden["finding"] == EMPTY
    assert hidden["picker"] == ["All parks", "Bumbly Bazaar"]
    assert hidden["sandbox_note"] == _note(LEFT_OUT, labels["s1"])
    assert hidden["sandbox_pressed"] == "Left out"
    assert shown["finding"] != EMPTY
    assert shown["finding"].startswith("2002 closed with")
    assert picker == ["All parks", "Alpha Park", "Bumbly Bazaar"]


def test_a_company_park_with_no_closed_month_keeps_the_old_empty_sentence(tmp_path: Path) -> None:
    executive = _smoke(tmp_path, NO_CLOSED_MONTH)["executive"]

    assert executive["finding"] == OLD_EMPTY
    assert executive["sandbox_note"] == ""
    assert executive["sandbox_pressed"] is None


def test_no_registered_park_keeps_the_old_empty_sentence(tmp_path: Path) -> None:
    executive = _smoke(tmp_path, NO_PARKS)["executive"]

    assert executive["finding"] == OLD_EMPTY
    assert executive["sandbox_note"] == ""
    assert executive["sandbox_pressed"] is None


def test_the_switch_note_lists_sandbox_parks_in_build_order(tmp_path: Path) -> None:
    executive = _smoke(tmp_path, BUILD_REVERSED, labels=BAZAAR)["executive"]

    assert executive["sandbox_note"] == _note(LEFT_OUT, BAZAAR["s2"], BAZAAR["s1"])


def test_finance_disables_the_year_earlier_comparison_when_no_month_has_a_match(
    tmp_path: Path,
) -> None:
    pages = _smoke(tmp_path, NO_PAIR, labels={"s1": BAZAAR["s1"]})

    assert pages["finance"]["yoy_disabled"] is True
    assert pages["executive"]["yoy_disabled"] is None


def test_finance_enables_the_year_earlier_comparison_when_a_month_has_a_match(
    tmp_path: Path,
) -> None:
    hidden = _smoke(tmp_path / "a", R1, labels=BAZAAR)["finance"]
    shown = _smoke(tmp_path / "b", NO_PAIR, "--sandbox", labels={"s1": BAZAAR["s1"]})["finance"]

    assert hidden["yoy_disabled"] is False
    assert shown["yoy_disabled"] is False


def test_a_year_change_moves_the_totals_and_the_cursor_with_the_controls(tmp_path: Path) -> None:
    switch = _smoke(tmp_path, LATE, labels=BAZAAR)["executive"]["year_switch"]

    assert switch["through"] == "June"
    assert switch["kpi_values"] == ["$0.3K", "$0.8K", "40", "$1.0K"]
    assert switch["cursor_x"] == 416  # the end of June: 52 + 91 * 4


def _executive(tmp_path: Path, options: Options) -> dict[str, Any]:
    """The Executive readings by company year, Sandbox hidden."""
    executive: dict[str, Any] = _smoke(tmp_path, options, labels=BAZAAR)["executive"]["executive"]
    return executive


def _month(year: dict[str, Any], chip: str) -> dict[str, Any]:
    (month,) = [m for m in year["months"] if m["chip"] == chip]
    assert isinstance(month, dict)
    return month


def test_executive_labels_a_late_start_by_its_company_month(tmp_path: Path) -> None:
    year = _executive(tmp_path, LATE)["2001"]

    assert year["executive_months"] == ["All", "Jun", "Jul", "Aug", "Sep"]
    assert year["months"][1]["chip"] == "Jun"
    assert year["months"][1]["through"] == "June"
    assert year["months"][1]["cash_label"] == "Cash in bank, end of June"
    assert _month(year, "All")["cash_label"] == "Cash in bank, end of October"
    assert [m["through"] for m in year["months"]] == [
        "October",
        "June",
        "July",
        "August",
        "September",
    ]


def test_executive_keeps_an_interior_gap_in_its_month(tmp_path: Path) -> None:
    executive = _executive(tmp_path, GAP)
    first, second = executive["2001"], executive["2002"]

    assert first["executive_months"] == ["All", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep"]
    assert second["executive_months"] == first["executive_months"]
    assert _month(first, "Apr")["cash_label"] == "Cash in bank, end of April"
    assert _month(first, "Jun")["cash_label"] == "Cash in bank, end of June"
    assert _month(second, "Jun")["kpi_deltas"][3] == "▲ $0.0K more than end of June 2001"
    assert _month(second, "Jun")["kpi_deltas"][0] == "▼ $0.0K (5%) less than 2001 to June"


def test_the_year_with_a_gap_is_not_a_closed_season(tmp_path: Path) -> None:
    gap = _executive(tmp_path / "a", GAP)["2002"]
    closed = _executive(tmp_path / "b", PRIOR_GAP)["2002"]

    assert _month(gap, "All")["finding"] == (
        "By the end of October 2002 the company had made $1.7K operating profit, "
        "$0.4K ahead of 2001 at the same point."
    )
    assert "closed" not in _month(gap, "All")["finding"]
    assert gap["race_desc"].endswith(
        "2001 stands at $1,251 through October; 2002 stands at $1,650 through October."
    )
    assert _month(closed, "All")["finding"] == (
        "2002 closed with $1.8K operating profit, 44% more than 2001. "
        "Its lead grew through the season to $0.5K."
    )
    assert closed["race_desc"].endswith(
        "2001 stands at $1,251 through October; 2002 closed at $1,800."
    )


def test_executive_places_every_chart_bar_and_label_by_company_month(tmp_path: Path) -> None:
    late = _executive(tmp_path / "a", LATE)
    gap = _executive(tmp_path / "b", GAP)
    first, second = late["2001"], late["2002"]

    assert first["race_months"] == ALL_LABELS
    assert first["race_values"] == [
        [370.5, "$0.3K"], [461.5, "$0.4K"], [552.5, "$0.1K"], [643.5, "$0.1K"], [734.5, "$0.0K"]
    ]  # fmt: skip
    assert first["year_labels"] == [
        "Company year 2001, operating profit $950 through October",
        "Company year 2002, operating profit $1,800",
    ]
    assert first["race_desc"].endswith(
        "2001 stands at $950 through October; 2002 closed at $1,800."
    )
    assert _month(first, "Jun")["kpi_values"] == ["$0.3K", "$0.8K", "40", "$1.0K"]
    assert _month(first, "Aug")["kpi_values"][0:3] == ["$0.8K", "$2.3K", "120"]
    assert _month(first, "Jun")["finding"] == (
        "By the end of June 2001 the company had made $0.3K operating profit in its first season. "
        "There is no earlier year to compare."
    )
    assert (
        _month(second, "Jun")["lead_title"] == "What separates 2002 from 2001 through June: +$0.4K"
    )
    assert _month(second, "Jun")["lead_rows"][1] == "+$1,320"
    assert _month(second, "Jun")["finding"] == (
        "By the end of June 2002 the company had made $0.7K operating profit, "
        "$0.4K ahead of 2001 at the same point. The season closed at $1.8K."
    )
    assert _month(second, "Apr")["event"] == "▲ April 2002: marketing campaign paid, $100."
    assert gap["2001"]["race_months"] == ALL_LABELS
    assert gap["2001"]["race_values"] == [
        [97.5, "$0.1K"], [188.5, "$0.2K"], [370.5, "$0.3K"], [461.5, "$0.4K"],
        [552.5, "$0.1K"], [643.5, "$0.1K"], [734.5, "$0.0K"],
    ]  # fmt: skip
    assert _month(gap["2001"], "Jun")["kpi_values"][0:3] == ["$0.6K", "$2.1K", "120"]
    assert _month(gap["2001"], "Jun")["through"] == "June"
    assert gap["2001"]["race_desc"].endswith(
        "2001 stands at $1,251 through October; 2002 stands at $1,650 through October."
    )  # noqa: E501


def test_executive_prior_year_bar_is_the_same_company_month(tmp_path: Path) -> None:
    late = _executive(tmp_path / "a", LATE)["2002"]
    gap = _executive(tmp_path / "b", PRIOR_GAP)["2002"]

    assert late["race_prior_x"] == [347.5, 438.5, 529.5, 620.5, 711.5]
    assert _month(late, "Mar")["kpi_deltas"][0] == "▲ $0.4K more than 2001 to March"
    assert _month(late, "Mar")["kpi_deltas"][3] == "No March last year to compare"
    assert _month(late, "Jun")["kpi_deltas"][3] == "▲ $0.0K more than end of June 2001"
    assert gap["race_prior_x"] == [74.5, 165.5, 347.5, 438.5, 529.5, 620.5, 711.5]
    assert [x for x, _ in gap["race_values"]][2] == 279.5
    assert _month(gap, "May")["kpi_deltas"][0] == "▲ $0.2K (66%) more than 2001 to May"
    assert _month(gap, "May")["kpi_deltas"][3] == "No May last year to compare"
    assert _month(gap, "Jun")["kpi_deltas"][3] == "▲ $0.0K more than end of June 2001"


def test_the_game_year_note_lists_only_the_parks_in_view(tmp_path: Path) -> None:
    hidden = _smoke(tmp_path / "a", R1, labels=BAZAAR)["executive"]
    shown = _smoke(tmp_path / "b", R1, "--sandbox", labels=BAZAAR)["executive"]

    assert hidden["opened_note"] == "Alpha Park: Company year 2002 = game year 2"
    assert shown["opened_note"].split("\n") == [
        "Alpha Park: Company year 2002 = game year 2",
        "Bumbly Bazaar: Company year 2002 = game year 2",
        "Bumbly Bazaar: Company year 2002 = game year 2",
    ]


def test_the_first_season_cash_tile_still_says_there_is_no_earlier_year(tmp_path: Path) -> None:
    first = _executive(tmp_path, LATE)["2001"]

    assert _month(first, "Jun")["kpi_deltas"][3] == "No earlier year to compare"


def test_executive_sparklines_place_each_month_in_its_company_month_slot(tmp_path: Path) -> None:
    gap = _executive(tmp_path, GAP)["2001"]
    june = _month(gap, "Jun")["sparks"]
    last = _month(gap, "All")["sparks"]
    seven = [1, 13, 37, 49, 61, 73, 85]  # Mar, Apr, Jun to Oct: May's slot (25) stays empty

    for tile in (0, 3):
        assert [x for x, _ in june[tile]] == seven
        assert [x for x, _ in last[tile]] == seven
    assert [fill for _, fill in june[0]] == [
        "#118dff", "#118dff", "#12239e", "#d2d0ce", "#d2d0ce", "#d2d0ce", "#d2d0ce"
    ]  # fmt: skip
    assert [fill for _, fill in last[0]] == ["#118dff"] * 6 + ["#12239e"]


def test_executive_highlights_the_bar_of_the_shown_company_month(tmp_path: Path) -> None:
    gap = _executive(tmp_path, GAP)["2001"]

    assert _month(gap, "Apr")["race_lit_x"] == [188.5]
    assert _month(gap, "Jun")["race_lit_x"] == [370.5]
    assert _month(gap, "Aug")["race_lit_x"] == [552.5]


def _steps(year: dict[str, Any]) -> dict[tuple[str, int], str]:
    return {(s["from"], s["delta"]): s["lands"] for s in year["slider_steps"]}


def test_a_slider_step_forward_crosses_a_gap_month(tmp_path: Path) -> None:
    steps = _steps(_executive(tmp_path, GAP)["2001"])

    assert steps[("April", 1)] == "June"


def test_a_slider_step_back_crosses_a_gap_month(tmp_path: Path) -> None:
    steps = _steps(_executive(tmp_path, GAP)["2001"])

    assert steps[("June", -1)] == "April"


def test_a_slider_step_between_two_present_months_moves_one_month(tmp_path: Path) -> None:
    steps = _steps(_executive(tmp_path, GAP)["2001"])

    assert steps[("June", 1)] == "July"
    assert steps[("July", -1)] == "June"


def test_a_slider_step_off_the_first_or_last_month_stays_in_range(tmp_path: Path) -> None:
    first = _steps(_executive(tmp_path / "a", GAP_FIRST)["2001"])
    last = _steps(_executive(tmp_path / "b", GAP_LAST)["2001"])

    assert first[("April", -1)] == "April"
    assert first[("April", 1)] == "May"
    assert last[("September", -1)] == "August"
    assert last[("September", 1)] == "September"
    assert last[("August", 1)] == "September"

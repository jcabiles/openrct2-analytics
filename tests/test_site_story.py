"""The board meeting (T6a): its steps follow the exports, and its source holds no made-up fact.

Step 1 is live from the month rows, step 2 only with two or more company-year rows, and steps 3
and 4 are pending in every build. The story's months, years and parks come from export rows.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from tests.page_check_support import render_page
from tests.site_fixtures import NUMBERED_PARKS, ROOT, SETS, Rows, fixture_rows, usd, write_set

SCRIPT = """
import { closedYears, firstParkMonths } from "./site/assets/js/rows/story.mjs";
let input = "";
for await (const chunk of process.stdin) input += chunk;
const exports = JSON.parse(input);
const out = { first: firstParkMonths(exports), years: closedYears(exports) };
process.stdout.write(JSON.stringify(out));
"""
CHART_SCRIPT = """
let input = "";
for await (const chunk of process.stdin) input += chunk;
const exports = JSON.parse(input);
const drawn = [];
const stub = {
  clientWidth: 800,
  replaceChildren() {},
  insertBefore() {},
  firstChild: null,
  classList: { add() {}, toggle() {} },
  dataset: {},
  querySelector: () => stub,
  querySelectorAll: () => [],
};
stub.parentElement = stub;
globalThis.document = {
  documentElement: stub,
  getElementById: (id) => ({
    textContent: JSON.stringify(id === "park-data" ? exports.park : exports.park_month),
  }),
  querySelector: () => stub,
  querySelectorAll: () => [],
};
globalThis.getComputedStyle = () => ({ getPropertyValue: (name) => name });
globalThis.ResizeObserver = class { observe() {} };
globalThis.IntersectionObserver = class { observe() {} };
globalThis.matchMedia = () => ({ matches: false, addEventListener() {} });
globalThis.Plot = {
  plot: (options) => (drawn.push(options), {}),
  barY: (data) => ({ data }),
  ruleY: () => ({}),
};
const { init } = await import("./site/assets/js/story.mjs");
init();
process.stdout.write(JSON.stringify(drawn.map((options) => options.marks[0].data)));
"""
STORY_FILES = (
    "site/_includes/story.njk",
    "site/assets/js/story.mjs",
    "site/assets/js/rows/story.mjs",
    "site/figures/story.mjs",
    "docs/showcase/story/the-analytics-strategy.md",
)
TYPED_IN = ("All 16 months", "Mar 2000 to Oct 2001", "Company year 2001", "Park 2", "2000 2001")
MADE_UP = ("llustrative", "board-meeting ticket", "ehearsal", "two company years")


def _rows(exports: Rows) -> Rows:
    done = subprocess.run(
        ["node", "--input-type=module", "-e", SCRIPT],
        cwd=ROOT,
        input=json.dumps(exports),
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    result: Rows = json.loads(done.stdout)
    return result


def _two_year(name: str) -> Rows:
    exports = fixture_rows(name)
    second = dict(exports["company_year"][0], company_year=2001, operating_profit=4444.44)
    return {**exports, "company_year": [*exports["company_year"], second]}


def _regions(site: Path) -> dict[str, tuple[str, str]]:
    """Return each story figure region's state and body text, by id."""
    html = (site / "index.html").read_text()
    pattern = re.compile(
        r'data-figure="(story-[a-z0-9-]+)" data-figure-state="(\w+)"'
        r".*?data-figure-body>(.*?)</(?:p|div)>",
        re.DOTALL,
    )
    return {
        match.group(1): (match.group(2), " ".join(match.group(3).split()))
        for match in pattern.finditer(html)
    }


def _build(tmp_path: Path, exports: Rows | None, name: str) -> Path:
    served = write_set(name, tmp_path / "served")
    if exports is not None:
        # A second company year, written over the set's file with the same columns.
        path = served / "company_year.json"
        document = json.loads(path.read_text())
        document["rows"] = exports["company_year"]
        path.write_text(json.dumps(document, indent=2) + "\n")
    return render_page(served, tmp_path)


@pytest.mark.parametrize("name", SETS[1:], ids=SETS[1:])
def test_first_park_rows_hold_one_park_in_export_order(name: str) -> None:
    exports = fixture_rows(name)
    first = _rows(exports)["first"]
    park_id = exports["park_month"][0]["park_id"]
    assert first == [
        {
            "park_id": row["park_id"],
            "park_number": 1,
            "month": row["statement_company_date"],
            "operating_profit": row["operating_profit"],
        }
        for row in exports["park_month"]
        if row["park_id"] == park_id
    ]


def test_year_rows_need_two_company_years() -> None:
    assert _rows(fixture_rows("empty")) == {"first": [], "years": []}
    assert _rows(fixture_rows("A"))["years"] == []
    years = _rows(_two_year("A"))["years"]
    assert [row["company_year"] for row in years] == [2000, 2001]


def test_empty_build_reads_figure_pending_in_every_story_region(tmp_path: Path) -> None:
    regions = _regions(_build(tmp_path, None, "empty"))
    assert set(regions) == {
        "story-step-1", "story-step-2", "story-step-3", "story-step-4",
        "story-stage-first", "story-stage-later",
    }  # fmt: skip
    assert all(value == ("pending", "figure pending") for value in regions.values()), regions


def test_one_year_build_has_step_one_live_and_steps_two_to_four_pending(tmp_path: Path) -> None:
    exports = fixture_rows("A")
    first = exports["park_month"][0]["park_id"]
    site = _build(tmp_path, None, "A")
    regions = _regions(site)
    assert regions["story-step-1"][0] == "live"
    assert regions["story-stage-first"][0] == "live"
    for figure_id in ("story-step-2", "story-step-3", "story-step-4", "story-stage-later"):
        assert regions[figure_id] == ("pending", "figure pending"), figure_id
    values = [
        usd(float(r["operating_profit"])) for r in exports["park_month"] if r["park_id"] == first
    ]
    assert all(value in regions["story-step-1"][1] for value in values)
    assert "Park 1 opened in Mar 2000" in regions["story-step-1"][1]


def test_two_year_build_makes_step_two_live_from_the_year_rows(tmp_path: Path) -> None:
    exports = _two_year("B")
    regions = _regions(_build(tmp_path, exports, "B"))
    assert regions["story-step-2"][0] == "live"
    first, last = exports["company_year"][0], exports["company_year"][-1]
    assert regions["story-step-2"][1] == (
        f"Operating profit went from {usd(float(first['operating_profit']))} in company year "
        f"{first['company_year']} to {usd(float(last['operating_profit']))} in company year "
        f"{last['company_year']}."
    )
    assert regions["story-step-3"] == ("pending", "figure pending")
    assert regions["story-step-4"] == ("pending", "figure pending")


def test_steps_advance_through_intersection_observer_only() -> None:
    module = (ROOT / "site/assets/js/story.mjs").read_text()
    assert "new IntersectionObserver(" in module
    code = re.sub(r"//[^\n]*", "", module)
    assert not re.search(r"scroll|gsap|lenis|import .* from \"(?!\.)", code, re.IGNORECASE)


@pytest.mark.parametrize("path", STORY_FILES)
def test_story_sources_hold_no_typed_in_period_or_made_up_wording(path: str) -> None:
    text = (ROOT / path).read_text()
    for phrase in (*TYPED_IN, *MADE_UP):
        assert phrase not in text, (path, phrase)


def _stage_mounts(site: Path) -> tuple[list[str], str]:
    """Return every stage-chart mount tag in the page, and the stage-first region's markup."""
    html = (site / "index.html").read_text()
    tags = re.findall(r'<div class="chart" id="stage-chart"[^>]*>', html)
    start = html.index('data-figure="story-stage-first"')
    return tags, html[start : html.index('data-stage="later"', start)]


def _mount_closes_region(tag: str, region: str) -> bool:
    """The mount follows the body paragraph and is the last thing before the region closes."""
    pattern = r"data-figure-body>[^<]*</p>\s*" + re.escape(tag) + r"</div>\s*</div>"
    return re.search(pattern, region) is not None


def test_empty_build_has_one_hidden_stage_mount_inside_its_pending_region(tmp_path: Path) -> None:
    site = _build(tmp_path, None, "empty")
    tags, region = _stage_mounts(site)
    assert len(tags) == 1 and " hidden" in tags[0], tags
    assert _mount_closes_region(tags[0], region), region
    assert _regions(site)["story-stage-first"] == ("pending", "figure pending")


def test_one_year_build_has_one_visible_stage_mount_inside_its_region(tmp_path: Path) -> None:
    tags, region = _stage_mounts(_build(tmp_path, None, "A"))
    assert len(tags) == 1 and "hidden" not in tags[0], tags
    assert _mount_closes_region(tags[0], region), region


def test_story_chart_draws_the_lowest_numbered_parks_months() -> None:
    exports = fixture_rows("numbered")
    done = subprocess.run(
        ["node", "--input-type=module", "-e", CHART_SCRIPT],
        cwd=ROOT,
        input=json.dumps(exports),
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    # Park 1 is ID 2, the last park by ID and by first month; its three months are drawn.
    park_one = NUMBERED_PARKS[1]
    expected = [
        {
            "park_id": row["park_id"],
            "park_number": 1,
            "month": row["statement_company_date"],
            "operating_profit": row["operating_profit"],
        }
        for row in exports["park_month"]
        if row["park_id"] == park_one
    ]
    assert len(expected) == 3
    assert json.loads(done.stdout) == [expected]

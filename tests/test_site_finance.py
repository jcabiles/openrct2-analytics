"""The Finance view (T7): its legend region, the pending label, and the profit chart's wiring.

The page is built over the empty, A and B fixture sets for the legend and the pending label. The
browser modules run under Node with a stub page and a stub Plot that records each draw, so the desk
change, the park filter and the park colour order are checked on real module code.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.page_check_support import render_page
from tests.site_fixtures import NUMBERED_PARKS, ROOT, SETS, fixture_rows, write_set

PENDING = "figure pending"
SCRIPT = """
import { desk } from "./site/assets/js/data.mjs";
import { deskParks } from "./site/assets/js/rows/insights.mjs";
let input = "";
for await (const chunk of process.stdin) input += chunk;
const exports = JSON.parse(input);

const draws = [];
const emptyLabel = { hidden: true };
const page = new EventTarget();
page.documentElement = {};
page.getElementById = (id) =>
  id === "park-month-data"
    ? { textContent: JSON.stringify(exports.park_month) }
    : id === "park-data"
      ? { textContent: JSON.stringify(exports.park) }
      : { clientWidth: 800, replaceChildren() {} };
page.querySelector = () => emptyLabel;
globalThis.document = page;
globalThis.getComputedStyle = () => ({ getPropertyValue: (name) => name });
globalThis.ResizeObserver = class { observe() {} };
globalThis.Plot = {
  plot: (options) => (draws.push(options), {}),
  stackY: (options) => options,
  barY: (data, options) => ({ data, options }),
  ruleY: () => ({}),
};

const { init } = await import("./site/assets/js/finance.mjs");
const { setPark, setRange, selectedMonths } = await import("./site/assets/js/insights.mjs");
const parks = deskParks(exports).map((park) => park.park_id);
const last = new Set(exports.park_month.map((row) => row.statement_company_date)).size - 1;
desk.range = [0, last];
desk.park = "all";
init();

const snapshot = (label) => {
  const draw = draws.at(-1);
  return {
    label,
    drawn: draws.length,
    months: selectedMonths(),
    domain: draw.x.domain,
    colours: draw.color.domain,
    range: draw.color.range,
    parkIds: [...new Set(draw.marks[0].data.map((row) => row.park_id))],
    rows: draw.marks[0].data.length,
    pendingHidden: emptyLabel.hidden,
  };
};
const steps = [snapshot("loaded")];
setPark(parks.at(-1));
steps.push(snapshot("last park"));
setRange(0, 1);
steps.push(snapshot("first two months"));
process.stdout.write(JSON.stringify({ parks, steps }));
"""


def _legend_and_label(html: str) -> tuple[re.Match[str] | None, bool, bool]:
    legend = re.search(
        r'data-figure="fin-legend" data-figure-state="(\w+)".*?data-figure-body>(.*?)</div>',
        html,
        re.DOTALL,
    )
    label = re.search(r"<p[^>]*data-finance-empty[^>]*>(.*?)</p>", html, re.DOTALL)
    return legend, label is not None and PENDING in label.group(1), bool(label)


@pytest.mark.parametrize("name", SETS, ids=SETS)
def test_legend_region_follows_the_parks_and_the_pending_label_exists(
    name: str, tmp_path: Path
) -> None:
    site = render_page(write_set(name, tmp_path / "served"), tmp_path)
    legend, label_pending, label_exists = _legend_and_label((site / "index.html").read_text())
    assert legend is not None
    state, body = legend.group(1), legend.group(2)
    assert label_exists and label_pending
    if name == "empty":
        assert state == "pending"
        assert PENDING in body
        assert "<li>" not in body
        return
    parks = {row["park_id"] for row in fixture_rows(name)["park_month"]}
    assert state == "live"
    assert body.count("<li>") == len(parks) == 2
    assert [f"Park {n}" for n in (1, 2)] == re.findall(
        r'</span>(Park \d+)(?:<i class="vh">,</i>)?</li>', body
    )


def test_finance_view_renders_every_carried_passage(tmp_path: Path) -> None:
    passage_ids = (
        "fin-profit-desc",
        "fin-visits-desc",
        "fin-price-desc",
        "fin-price-cap",
        "fin-stalls-cap",
        "fin-mix-cap",
        "fin-gap",
    )
    story = (ROOT / "docs/showcase/story/the-analytics-strategy.md").read_text()
    markers = list(re.finditer(r"<!-- passage: ([a-z0-9-]+) -->", story))
    passages: dict[str, str] = {}
    for index, marker in enumerate(markers):
        if marker.group(1) not in passage_ids:
            continue
        end = markers[index + 1].start() if index + 1 < len(markers) else len(story)
        passages[marker.group(1)] = story[marker.end() : end].strip()

    site = render_page(write_set("A", tmp_path / "served"), tmp_path)
    page = (site / "index.html").read_text()
    rendered_text = re.sub(r"<[^>]+>", "", page)
    rendered_text = re.sub(r"\s+", " ", rendered_text)
    for passage_id in passage_ids:
        passage = passages.get(passage_id, "")
        assert passage, passage_id
        normalized = re.sub(r"[\\*_`~]", "", passage)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        assert normalized in rendered_text, passage_id


def _run(name: str) -> dict[str, Any]:
    done = subprocess.run(
        ["node", "--input-type=module", "-e", SCRIPT],
        cwd=ROOT,
        input=json.dumps(fixture_rows(name)),
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    result: dict[str, Any] = json.loads(done.stdout)
    return result


def test_desk_change_redraws_the_chart_for_the_selected_months_and_park() -> None:
    result = _run("B")
    parks = result["parks"]
    loaded, last_park, early = result["steps"]
    assert isinstance(parks, list) and len(parks) == 2
    assert loaded["parkIds"] == parks and loaded["pendingHidden"] is True
    # A park choice redraws, and only that park's rows reach the chart.
    assert last_park["drawn"] == loaded["drawn"] + 1
    assert last_park["parkIds"] == [parks[-1]]
    assert last_park["domain"] == last_park["months"]
    # A range change redraws for exactly the selected months; the late park has none in them.
    assert early["drawn"] == last_park["drawn"] + 1
    assert early["months"] == early["domain"] and len(early["months"]) == 2
    assert early["rows"] == 0 and early["pendingHidden"] is False


def test_chart_park_colours_follow_the_desk_park_order() -> None:
    result = _run("numbered")
    # The desk lists parks by their park number, and the chart colours follow that list.
    expected = [row["park_id"] for row in fixture_rows("numbered")["park"]]
    assert result["parks"] == expected
    for step in result["steps"]:
        assert step["colours"] == expected


def test_chart_and_legend_colours_follow_park_number_with_no_park_one_rows() -> None:
    result = _run("numbered-no-park-one")
    # Park 1 has no month rows, so Park 2 takes the first colour and Park 3 the second (spec R21).
    expected = [NUMBERED_PARKS[0], NUMBERED_PARKS[2]]
    assert result["parks"] == expected
    for step in result["steps"]:
        assert step["colours"] == expected
        assert step["range"] == ["--p1", "--p2"]

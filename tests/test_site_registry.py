"""Page text comes from the figure registry: the park lines, the desk's data label and the colours.

Each test runs the registry under Node on a fixture set's exports, or builds the page and reads it
back, so a sentence moved into a template, a park left without a colour or a park-order change
shows up as a failure.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from tests.page_check_support import render_page
from tests.site_fixtures import (
    NUMBERED_PARKS,
    ROOT,
    Rows,
    fixture_rows,
    write_set,
)

REGISTRY_SCRIPT = """
import { figure } from "./site/figures.mjs";
let input = "";
for await (const chunk of process.stdin) input += chunk;
const exports = JSON.parse(input);
const out = {};
for (const id of ["park-openings", "desk-play", "desk-park", "story-step-1"]) {
  const view = figure(id, exports);
  out[id] = {
    rows: view.rows,
    sentence: view.sentence,
    lines: id === "park-openings" ? view.rows.map((_, i) => view.line(view.rows, i)) : null,
  };
}
process.stdout.write(JSON.stringify(out));
"""


def registry(exports: Rows) -> dict[str, Any]:
    """Return the park-openings, desk-play, desk-park and story-step-1 views, run under Node."""
    done = subprocess.run(
        ["node", "--input-type=module", "-e", REGISTRY_SCRIPT],
        cwd=ROOT,
        input=json.dumps(exports),
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    result: dict[str, Any] = json.loads(done.stdout)
    return result


def _region_text(html: str, figure_id: str) -> str:
    match = re.search(
        rf'data-figure="{figure_id}".*?data-figure-body[^>]*>(.*?)</ol>',
        html,
        re.DOTALL,
    )
    assert match, figure_id
    return " ".join(re.sub(r"<[^>]*>", " ", match.group(1)).split())


def test_park_opening_lines_come_from_the_registry(tmp_path: Path) -> None:
    exports = fixture_rows("A")
    lines = registry(exports)["park-openings"]["lines"]
    assert lines == ["Park 1 opened in Mar 2000.", "Park 2 opened in Aug 2000."]
    html = (render_page(write_set("A", tmp_path / "served"), tmp_path) / "index.html").read_text()
    assert _region_text(html, "park-openings") == " ".join(lines)


def test_enterprise_template_renders_the_registry_line_only() -> None:
    template = (ROOT / "site/_includes/enterprise.njk").read_text()
    assert "parksFig.line(parksFig.rows, loop.index0)" in template
    assert "opened in" not in template
    assert "opens in" not in template


def test_the_desk_label_says_data_shown() -> None:
    sentence = registry(fixture_rows("A"))["desk-play"]["sentence"]
    assert sentence == "Data shown: Park 1, Park 2, company years 2000 to 2001"


CHART_SCRIPT = """
import { deskParks } from "./site/assets/js/rows/insights.mjs";
let input = "";
for await (const chunk of process.stdin) input += chunk;
const exports = JSON.parse(input);
const rows = exports.park_month;
let captured = null;
globalThis.document = {
  documentElement: {},
  getElementById: (id) =>
    id === "park-month-data"
      ? { textContent: JSON.stringify(rows) }
      : { clientWidth: 600, replaceChildren: () => {} },
};
globalThis.getComputedStyle = () => ({ getPropertyValue: (name) => name });
globalThis.ResizeObserver = class { observe() {} };
globalThis.Plot = {
  plot: (options) => { captured = options; return {}; },
  barY: () => ({}),
  stackY: (options) => options,
  ruleY: () => ({}),
};
const { redrawParkMonthChart } = await import("./site/assets/park-month-chart.mjs");
const parks = deskParks(exports).map((park) => park.park_id);
redrawParkMonthChart(null, "all", parks);
process.stdout.write(JSON.stringify({ parks, color: captured.color }));
"""


# By ID the parks run 1, 2, 3; by their first company month they run 1, 3, 2; by `park_number` they
# run 2, 1, 3. The site follows the number.
_NUMBER_ORDER = [NUMBERED_PARKS[1], NUMBERED_PARKS[0], NUMBERED_PARKS[2]]


def test_desk_parks_follow_park_number_not_first_month_or_id() -> None:
    rows = registry(fixture_rows("numbered"))["desk-park"]["rows"]
    assert [row["park_id"] for row in rows] == _NUMBER_ORDER
    assert [row["park_number"] for row in rows] == [1, 2, 3]
    assert [row["first_month"] for row in rows] == ["2000-08-01", "2000-03-01", "2000-05-01"]


def test_park_opening_rows_follow_park_number_not_first_month_or_id() -> None:
    views = registry(fixture_rows("numbered"))
    rows = views["park-openings"]["rows"]
    assert [(row["park_id"], row["park_number"]) for row in rows] == list(
        zip(_NUMBER_ORDER, [1, 2, 3], strict=True)
    )
    assert views["park-openings"]["lines"] == [
        "Park 1 opened in Aug 2000.",
        "Park 2 opened in Mar 2000.",
        "Park 3 opened in May 2000.",
    ]
    assert views["desk-play"]["sentence"] == (
        "Data shown: Park 1, Park 2, Park 3, company year 2000"
    )


def test_first_park_months_follow_park_number_not_first_month_or_id() -> None:
    views = registry(fixture_rows("numbered"))
    rows = views["story-step-1"]["rows"]
    assert {(row["park_id"], row["park_number"]) for row in rows} == {(_NUMBER_ORDER[0], 1)}
    assert views["story-step-1"]["sentence"].startswith(
        "Park 1 opened in Aug 2000. Its months so far: Aug 2000 "
    )


def test_every_park_in_the_chart_domain_has_a_range_colour() -> None:
    done = subprocess.run(
        ["node", "--input-type=module", "-e", CHART_SCRIPT],
        cwd=ROOT,
        input=json.dumps(fixture_rows("numbered")),
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    chart = json.loads(done.stdout)
    assert len(chart["color"]["domain"]) == 3
    assert chart["color"]["domain"] == chart["parks"] == _NUMBER_ORDER
    assert chart["color"]["range"] == ["--p1", "--p2", "--rep"]


def test_every_legend_swatch_class_has_a_css_rule_and_parks_past_two_share_one(
    tmp_path: Path,
) -> None:
    html = (
        render_page(write_set("numbered", tmp_path / "served"), tmp_path) / "index.html"
    ).read_text()
    legend = re.search(r'data-figure="fin-legend".*?</ul>', html, re.DOTALL)
    assert legend
    classes = re.findall(r'class="sw (\w+)"', legend.group())
    assert classes == ["p1", "p2", "rep"]
    opening = re.search(r'data-figure="park-openings".*?</ol>', html, re.DOTALL)
    assert opening
    assert re.findall(r'class="sw (\w+)"', opening.group()) == classes
    css = (ROOT / "site/assets/css/insights.css").read_text()
    tokens = (ROOT / "site/assets/css/tokens.css").read_text()
    for name in classes:
        assert re.search(rf"\.sw\.{name}\s*\{{", css), name
        assert f"--{name}:" in tokens, name

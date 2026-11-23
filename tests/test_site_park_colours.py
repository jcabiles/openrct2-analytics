"""Park labels and colours by park number (R20, R21): panel rows, the legend and the sort order.

The panel row functions run under Node over the `numbered-no-park-one` set, where Park 1 has no
rows, so a label made from position (Park 1, Park 2) differs from the label made from the
exported number (Park 2, Park 3).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from tests.page_check_support import render_page
from tests.site_fixtures import NUMBERED_PARKS, ROOT, Rows, fixture_rows, write_set

PANEL_SCRIPT = """
import * as panels from "./site/assets/js/rows/panels.mjs";
let input = "";
for await (const chunk of process.stdin) input += chunk;
const exports = JSON.parse(input);
const labels = (rows) => rows.map((row) => row.park);
process.stdout.write(
  JSON.stringify({
    mix: labels(panels.revenueMixRows(exports)),
    availability: labels(panels.availabilityRows(exports)),
    riders: labels(panels.ridersRows(exports)),
    waits: labels(panels.longestLineRows(exports)),
    rideYears: labels(panels.rideYearRows(exports)),
  }),
);
"""
DESK_SCRIPT = """
import { deskParks } from "./site/assets/js/rows/insights.mjs";
let input = "";
for await (const chunk of process.stdin) input += chunk;
process.stdout.write(JSON.stringify(deskParks(JSON.parse(input)).map((park) => park.park_id)));
"""
# Park 2 and Park 3 of the `numbered-no-park-one` set: IDs 1 and 3. ID 2 is Park 1, with no rows.
SHOWN = (NUMBERED_PARKS[0], NUMBERED_PARKS[2])


def _node(script: str, payload: Rows) -> dict[str, list[str]] | list[str]:
    done = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    result: dict[str, list[str]] | list[str] = json.loads(done.stdout)
    return result


def _panel_exports() -> Rows:
    exports = fixture_rows("numbered-no-park-one")
    exports["park_month_revenue"] = [
        {"park_month_key": f"{park_id}|2000|03", "park_id": park_id, "company_date": "2000-03-01"}
        for park_id in SHOWN
    ]
    exports["ride_month"] = [
        {
            "ride_month_key": f"{park_id}|r|2000|03",
            "ride_key": f"{park_id}|r",
            "park_id": park_id,
            "ride_name": "Ride",
            "company_year": 2000,
            "company_date": "2000-03-01",
        }
        for park_id in SHOWN
    ]
    exports["ride_year"] = [
        {
            "ride_year_key": f"{park_id}|r|2000",
            "ride_key": f"{park_id}|r",
            "park_id": park_id,
            "ride_name": "Ride",
            "company_year": 2000,
            "riders_rank_in_park_year": 1,
        }
        for park_id in SHOWN
    ]
    return exports


def test_panel_rows_label_parks_by_number_with_no_park_one_rows() -> None:
    labels = _node(PANEL_SCRIPT, _panel_exports())
    expected = ["Park 2", "Park 3"]
    assert labels == {
        "mix": expected,
        "availability": expected,
        "riders": expected,
        "waits": expected,
        "rideYears": expected,
    }


def test_finance_legend_swatches_follow_park_number_with_no_park_one_rows(tmp_path: Path) -> None:
    site = render_page(write_set("numbered-no-park-one", tmp_path / "served"), tmp_path)
    html = (site / "index.html").read_text()
    legend = re.search(r'data-figure="fin-legend".*?</ul>', html, re.DOTALL)
    assert legend
    # Park 2 takes the first colour and Park 3 the second (spec R21).
    assert re.findall(r'class="sw (\w+)"></span>(Park \d+)', legend.group()) == [
        ("p1", "Park 2"),
        ("p2", "Park 3"),
    ]


def test_desk_parks_sort_park_numbers_as_numbers() -> None:
    exports = fixture_rows("numbered")
    exports["park"] = [
        {"park_id": NUMBERED_PARKS[0], "park_number": 10},
        {"park_id": NUMBERED_PARKS[1], "park_number": 2},
        {"park_id": NUMBERED_PARKS[2], "park_number": 3},
    ]
    assert _node(DESK_SCRIPT, exports) == [NUMBERED_PARKS[1], NUMBERED_PARKS[2], NUMBERED_PARKS[0]]

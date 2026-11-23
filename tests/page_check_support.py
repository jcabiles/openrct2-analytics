"""Shared fixture builder and fault builders for the page-check tests."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from openrct2_analytics.showcase.page_check import main
from openrct2_analytics.showcase.page_check_guide import REQUIRED_STEPS

ROOT = Path(__file__).resolve().parents[1]
Fault = Callable[[Path, Path], None]

MONTH_TABLE = "month table: "
FIRST_TABLE_ROW = (
    '<tr><th scope="row">Mar 2000 <span>(not checked: first month)</span></th>'
    "<td>$4,073.60</td></tr>"
)
SECOND_TABLE_ROW = '<tr><th scope="row">Apr 2000</th><td>$10,043.60</td></tr>'
PARK_YEAR_ROW = (
    '{"park_year_key":"1|9","park_id":1,"company_year":2000,"statements_kept":3,'
    '"statements_expected":8,"close_status":"open","is_partial_first_season":false,'
    '"months_checked":2,"operating_profit":14117.20}'
)
PARK_YEAR_TABLE_ROW = (
    "<tr><td>2000</td><td>1</td><td>3 of 8</td><td>2</td><td>$14,117.20</td>"
    "<td>not closed</td></tr>"
)
PARK_ROW = '{"park_id":1,"park_number":1}'
COMPANY_YEAR_ROW = (
    '{"company_year":2000,"parks_reporting":2,"parks_partial_first_season":1,'
    '"statements_kept":16,"months_checked":4,"operating_profit":28234.40}'
)
COMPANY_TABLE_ROW = "<tr><td>2000</td><td>2</td><td>1</td><td>4</td><td>$28,234.40</td></tr>"
SAMPLE_RECORD = {"data_set": "sample", "parks": 1, "sessions": 3, "player_played": False}
FIGURE_OPEN = (
    '<span class="fig" data-figure="sample" data-figure-state="{state}">'
    '<span class="vh" data-figure-unit>(unit: sessions; clock: wall-clock hour; '
    "period: {period})</span><span data-figure-body>{body}</span></span>"
)
SAMPLE_SENTENCE = (
    "Sample: the parks listed in the park-years table, 3 headless sessions with no player;"
    " observational."
)
SAMPLE_STATEMENT = (
    '<p data-sample-statement data-data-set="sample" data-parks="1" data-sessions="3" '
    'data-player-played="false">'
    + FIGURE_OPEN.format(state="live", period="this build", body=SAMPLE_SENTENCE)
    + "</p>"
)
EMPTY_STATE = "<p>No company year has closed yet.</p>"
COMPANY_TABLE = (
    "<h2>Closed company years (unit: US dollars; clock: company year)</h2>"
    '<table id="company-year-table"><caption>Closed company years, operating profit in '
    'US dollars</caption><thead><tr><th scope="col">Company year</th>'
    '<th scope="col">Parks reporting</th><th scope="col">Partial first seasons</th>'
    '<th scope="col">Park-months checked</th>'
    '<th scope="col">Operating profit (not yet reconciled)</th></tr></thead><tbody>'
    + COMPANY_TABLE_ROW
    + "</tbody></table>"
)

GUIDE_INSTALL = '<section id="install"><p>Before you start.</p></section>'
GUIDE_HOW = '<section id="how-it-works"><p>How a play works.</p></section>'
GUIDE_HELP = '<section id="fix-a-problem"><p>Find the message you see.</p></section>'
GUIDE_STEPS = "".join(
    f'<section class="guide-step" id="{step_id}">'
    '<p class="step-command"><code>make setup</code></p>'
    '<p class="step-see">Doctor reports the environment whole.</p>'
    '<p class="step-fix">If a tool is missing, open a new window.</p></section>'
    for step_id in REQUIRED_STEPS
)
GUIDE_PAGE = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Guide</title></head>'
    '<body><a href="#main">Skip</a><header><h1>Guide</h1><a href="../">Home</a></header>'
    f'<main id="main">{GUIDE_INSTALL}{GUIDE_STEPS}{GUIDE_HOW}{GUIDE_HELP}</main>'
    "</body></html>"
)


def write_sample_record(served: Path, record: dict[str, object]) -> None:
    """Write a served `sample.json` holding `record`."""
    document = {"name": "sample", "columns": list(record), "rows": [record]}
    (served / "sample.json").write_text(json.dumps(document) + "\n")


def _site(tmp_path: Path) -> tuple[Path, Path]:
    site = tmp_path / "built"
    served = tmp_path / "served"
    for folder in (site / "assets/vendor", served):
        folder.mkdir(parents=True)
    (served / "park_month.json").write_text(
        '{"rows":[{"park_month_key":1,"park_id":1,"statement_company_date":"2000-03-01",'
        '"operating_profit":4073.60},{"park_month_key":2,"park_id":1,'
        '"statement_company_date":"2000-04-01","operating_profit":10043.60}]}\n'
    )
    (served / "park_year.json").write_text('{"rows":[' + PARK_YEAR_ROW + "]}\n")
    (served / "company_year.json").write_text('{"rows":[]}\n')
    (served / "park.json").write_text('{"rows":[' + PARK_ROW + "]}\n")
    write_sample_record(served, SAMPLE_RECORD)
    (site / "index.html").write_text(
        "<h1>Park operating profit by company month</h1>"
        "<p>A company year closes when every park expected in it has all eight monthly "
        "statements, March to October, and a park's partial first season does not hold a "
        "year open; at least one expected park must also be complete.</p>"
        "<p>Operating profit plus capital spending plus interest equals the change in cash "
        "less loan, less the money already booked to the new month, from the previous month, "
        "with no month missing in between.</p>"
        "<p>Each park's first month has no earlier statement to reconcile, so its bar is not "
        "checked.</p>"
        + SAMPLE_STATEMENT
        + EMPTY_STATE
        + "<h2>Park-years (unit: US dollars; clock: company year)</h2>"
        '<table id="park-year-table"><caption>Operating profit per park and company year, '
        "in US dollars</caption>"
        '<thead><tr><th scope="col">Company year</th><th scope="col">Park ID</th>'
        '<th scope="col">Statements kept of expected</th>'
        '<th scope="col">Months checked</th>'
        '<th scope="col">Operating profit (not yet reconciled)</th>'
        '<th scope="col">Status</th></tr></thead><tbody>' + PARK_YEAR_TABLE_ROW + "</tbody></table>"
        "<p>unit: US dollars; clock: company month</p>"
        '<figure id="park-month-chart"></figure>'
        '<table id="park-month-table"><caption>Operating profit by company month, in US dollars'
        "</caption>"
        '<thead><tr><th scope="col">Company month</th>'
        '<th scope="col">Operating profit</th></tr></thead>'
        "<tbody>" + FIRST_TABLE_ROW + SECOND_TABLE_ROW + "</tbody></table>"
        '<script type="application/json" id="park-data">[' + PARK_ROW + "]</script>"
        '<script type="application/json" id="park-month-data">'
        '[{"park_month_key":1,"park_id":1,"statement_company_date":"2000-03-01",'
        '"operating_profit":4073.6},{"park_month_key":2,"park_id":1,'
        '"statement_company_date":"2000-04-01","operating_profit":10043.60}]'
        '</script><script src="assets/vendor/d3.min.js"></script>'
        '<script src="assets/vendor/plot.umd.min.js"></script>'
        '<script type="module" src="assets/park-month-chart.mjs"></script>'
    )
    (site / "guide").mkdir()
    (site / "guide/index.html").write_text(GUIDE_PAGE)
    for path in (
        site / "assets/vendor/d3.min.js",
        site / "assets/vendor/plot.umd.min.js",
    ):
        path.write_text("/* vendored fixture */")
    (site / "assets/park-month-chart.mjs").write_text(
        'const rows = JSON.parse(document.getElementById("park-month-data").textContent);\n'
        'const chart = document.getElementById("park-month-chart");\n'
        "Plot.plot({ marks: [Plot.barY(rows)] }).plot(chart);\n"
    )
    return site, served


def _run(site: Path, served: Path) -> int:
    return main(["--site", str(site), "--served-dir", str(served)])


def _html(old: str, new: str) -> Fault:
    def fault(site: Path, served: Path) -> None:
        page = site / "index.html"
        html = page.read_text()
        assert old in html
        page.write_text(html.replace(old, new))

    return fault


def _html_append(text: str) -> Fault:
    def fault(site: Path, served: Path) -> None:
        page = site / "index.html"
        page.write_text(page.read_text() + text)

    return fault


def _served_park_rows(rows: str) -> Fault:
    def fault(site: Path, served: Path) -> None:
        (served / "park_month.json").write_text('{"rows":[' + rows + "]}\n")

    return fault


def _fails(message: str, fault: Fault, name: str) -> object:
    return pytest.param(fault, message, id=name)


def render_page(served: Path, work: Path) -> Path:
    """Build the real site tree over the `served` files into `work`; return the built site.

    The whole `site/` tree is copied except `_data` and `_site`, then the `served` files are added.

    The same build command `make check` runs, with a temporary input and output folder so the
    committed `site/_data/` is never read or written.
    """
    page_input = work / "site-input"
    shutil.copytree(
        ROOT / "site", page_input, ignore=shutil.ignore_patterns("_data", "_site", "node_modules")
    )
    shutil.copytree(served, page_input / "_data")
    built = work / "built-site"
    done = subprocess.run(
        [
            "npm",
            "run",
            "--silent",
            "site:build",
            "--",
            f"--input={page_input}",
            f"--output={built}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return built


def write_every_status_served_files(served: Path) -> None:
    """Write served files that show every status word and one closed company year."""
    served.mkdir()
    park_years = [
        (2000, 1, 8, "complete"),
        (2000, 2, 3, "partial_first_season"),
        (2001, 1, 2, "open"),
        (2001, 2, 5, "incomplete"),
    ]
    (served / "park_year.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "park_year_key": f"{park}|{year}",
                        "park_id": park,
                        "company_year": year,
                        "statements_kept": kept,
                        "statements_expected": 8,
                        "close_status": status,
                        "is_partial_first_season": status == "partial_first_season",
                        "months_checked": kept - 1,
                        "operating_profit": 100.5,
                    }
                    for year, park, kept, status in park_years
                ]
            }
        )
    )
    (served / "company_year.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "company_year": 2000,
                        "parks_reporting": 2,
                        "parks_partial_first_season": 1,
                        "statements_kept": 11,
                        "months_checked": 9,
                        "operating_profit": 201.0,
                    }
                ]
            }
        )
    )
    (served / "park.json").write_text(
        json.dumps({"rows": [{"park_id": park, "park_number": park} for park in (1, 2)]})
    )
    write_sample_record(
        served, {"data_set": "sample", "parks": 2, "sessions": 3, "player_played": False}
    )
    (served / "park_month.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "park_month_key": number,
                        "park_id": park,
                        "statement_company_date": f"2000-0{number + 2}-01",
                        "operating_profit": 1.5,
                    }
                    for number, park in ((1, 1), (2, 2))
                ]
            }
        )
    )

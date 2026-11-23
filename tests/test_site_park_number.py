"""The site labels parks by the exported `park_number` (R21, R22, R24), never by position.

The park-order tests of R20 sit in `tests/test_site_registry.py`. Here: a park with no month rows
keeps its number while the others keep theirs, a park with month rows and no number stops the
build, and the page check requires the embedded `park` rows and compares them with `park.json`.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from openrct2_analytics.showcase.page_check import main as page_check_main
from tests.page_check_support import render_page
from tests.site_fixtures import NUMBERED_PARKS, ROOT, Rows, fixture_rows, write_set
from tests.test_site_registry import registry

DESK_SCRIPT = """
import { deskParks } from "./site/assets/js/rows/insights.mjs";
let input = "";
for await (const chunk of process.stdin) input += chunk;
process.stdout.write(JSON.stringify(deskParks(JSON.parse(input))));
"""
PARK_ONE = NUMBERED_PARKS[1]


def _desk_parks(exports: Rows) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", "--input-type=module", "-e", DESK_SCRIPT],
        cwd=ROOT,
        input=json.dumps(exports),
        capture_output=True,
        text=True,
        check=False,
    )


def test_enterprise_lines_skip_a_park_without_month_rows_and_keep_the_other_numbers() -> None:
    lines = registry(fixture_rows("numbered-no-park-one"))["park-openings"]["lines"]
    assert lines == ["Park 2 opened in Mar 2000.", "Park 3 opened in May 2000."]


def test_data_shown_names_only_the_parks_that_have_month_rows() -> None:
    sentence = registry(fixture_rows("numbered-no-park-one"))["desk-play"]["sentence"]
    assert sentence == "Data shown: Park 2, Park 3, company year 2000"


def test_park_switch_and_finance_legend_read_park_two_and_park_three_with_no_park_one(
    tmp_path: Path,
) -> None:
    site = render_page(write_set("numbered-no-park-one", tmp_path / "served"), tmp_path)
    html = (site / "index.html").read_text()
    switch = re.search(r"<legend>Park</legend>.*?</fieldset>", html, re.DOTALL)
    legend = re.search(r'data-figure="fin-legend".*?</ul>', html, re.DOTALL)
    assert switch and legend
    assert re.findall(r"<span>(Park \d+)", switch.group()) == ["Park 2", "Park 3"]
    assert re.findall(r"</span>(Park \d+)", legend.group()) == ["Park 2", "Park 3"]
    assert not re.search(r"\bPark 1\b", html)


def test_a_park_with_month_rows_and_no_park_row_stops_the_build_naming_its_id() -> None:
    exports = fixture_rows("numbered")
    exports["park"] = [row for row in exports["park"] if row["park_id"] != PARK_ONE]
    done = _desk_parks(exports)
    assert done.returncode != 0
    assert f"desk parks: park {PARK_ONE} has month rows but no park_number" in done.stderr


def test_a_park_with_month_rows_and_a_null_park_number_stops_the_build_naming_its_id() -> None:
    exports = fixture_rows("numbered")
    for row in exports["park"]:
        if row["park_id"] == PARK_ONE:
            row["park_number"] = None
    done = _desk_parks(exports)
    assert done.returncode != 0
    assert f"desk parks: park {PARK_ONE} has month rows but no park_number" in done.stderr


def test_a_ride_row_of_a_park_with_no_statement_builds_and_shows_only_the_park_with_one(
    tmp_path: Path,
) -> None:
    site = render_page(write_set("ride-row-no-statement", tmp_path / "served"), tmp_path)
    html = (site / "index.html").read_text()
    switch = re.search(r"<legend>Park</legend>.*?</fieldset>", html, re.DOTALL)
    assert switch
    assert re.findall(r"<span>(Park \d+)", switch.group()) == ["Park 2"]
    assert not re.search(r"\bPark 1\b", html)
    assert "Maze 1" not in html


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    work = tmp_path_factory.mktemp("park-number-page")
    served = write_set("A", work / "served")
    return render_page(served, work), served


def _copy(built: tuple[Path, Path], tmp_path: Path) -> tuple[Path, Path]:
    site, served = built
    shutil.copytree(site, tmp_path / "site")
    return tmp_path / "site", served


def test_the_built_page_with_its_park_rows_passes_the_page_check(
    built: tuple[Path, Path], tmp_path: Path
) -> None:
    site, served = _copy(built, tmp_path)
    assert page_check_main(["--site", str(site), "--served-dir", str(served)]) == 0


def test_the_page_check_fails_when_the_park_data_block_is_removed(
    built: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site, served = _copy(built, tmp_path)
    page = site / "index.html"
    html = page.read_text()
    block = re.search(r'<script type="application/json" id="park-data">.*?</script>', html)
    assert block
    page.write_text(html.replace(block.group(), ""))
    assert page_check_main(["--site", str(site), "--served-dir", str(served)]) == 1
    assert (
        "page check failed: embedded rows: park-data element is missing" in capsys.readouterr().out
    )


def test_the_page_check_fails_when_a_park_number_in_the_block_changed(
    built: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site, served = _copy(built, tmp_path)
    page = site / "index.html"
    html = page.read_text()
    block = re.search(r'<script type="application/json" id="park-data">.*?</script>', html)
    assert block and '"park_number":1' in block.group()
    page.write_text(
        html.replace(block.group(), block.group().replace('"park_number":1', '"park_number":9'))
    )
    assert page_check_main(["--site", str(site), "--served-dir", str(served)]) == 1
    assert (
        "page check failed: embedded park-data: differs from served park.json"
        in capsys.readouterr().out
    )


def test_the_page_check_fails_when_park_data_is_a_div_not_a_script_block(
    built: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site, served = _copy(built, tmp_path)
    page = site / "index.html"
    html = page.read_text()
    block = re.search(r'<script type="application/json" id="park-data">(.*?)</script>', html)
    assert block
    page.write_text(html.replace(block.group(), f'<div id="park-data">{block.group(1)}</div>'))
    assert page_check_main(["--site", str(site), "--served-dir", str(served)]) == 1
    assert (
        "page check failed: embedded rows: park-data must be exactly one application/json "
        "script block" in capsys.readouterr().out
    )

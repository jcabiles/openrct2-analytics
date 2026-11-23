"""Case 21: a company build end to end, with the real site build and the real page check."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest import site_company
from openrct2_analytics.ingest import site_company_land as land
from openrct2_analytics.showcase import export, page_check
from tests.test_site_company import REPO, _no_stage, _project, _tree

SUCCESS_LINE = (
    "site-company: exported 8 files from warehouse/company.duckdb to local/site-data/; "
    "built site/_site/"
)


def test_a_company_build_states_its_own_sample_and_lands_every_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, copy_repo_site=True)
    real_check = page_check.check_page
    checked: list[Path] = []

    def spy(site: Path, served: Path) -> None:
        checked.append(served)
        real_check(site, served)

    monkeypatch.setattr(page_check, "check_page", spy)
    committed = _tree(project / "site" / "_data")

    assert site_company.main(["--data-set", "company"], project_dir=project) == 0

    assert capsys.readouterr().out.strip().splitlines()[-1] == SUCCESS_LINE
    assert len(checked) == 1
    exports = project / "local" / "site-data"
    entries = export.load_allowlist(REPO / "site" / "exports.toml")
    assert sorted(path.name for path in exports.iterdir()) == sorted(
        [entry.output for entry in entries] + ["sample.json"]
    )
    connection = duckdb.connect(str(project / "warehouse" / "company.duckdb"), read_only=True)
    try:
        for entry in entries:
            rendered = export.render(entry, export.fetch_rows(connection, entry))
            assert (exports / entry.output).read_text() == rendered
    finally:
        connection.close()
    record = json.loads((exports / "sample.json").read_text())
    assert record["rows"] == [
        {"data_set": "company", "parks": 2, "sessions": 5, "player_played": True}
    ]
    assert (
        len(
            {row["park_id"] for row in json.loads((exports / "park_year.json").read_text())["rows"]}
        )
        == 2
    )

    site = project / "site" / "_site"
    page = (site / "index.html").read_text()
    assert page.count("data-sample-statement") == 1
    assert (
        '<p data-sample-statement data-data-set="company" data-parks="2" data-sessions="5" '
        'data-player-played="true"><span class="fig" data-figure="sample" '
        'data-figure-state="live"><span class="vh" data-figure-unit>(unit: sessions; clock: '
        "wall-clock hour; period: this build)</span><span data-figure-body>Sample: the parks "
        "listed in the park-years table, 5 sessions, at least one with a player; "
        "observational.</span></span></p>"
    ) in page
    assert "p1" in page
    assert (site / land.BUILD_STAMP).read_text().splitlines()[0] == land.STAMP_LINE
    assert land.is_company_build(site)
    assert _tree(project / "site" / "_data") == committed
    _no_stage(project)

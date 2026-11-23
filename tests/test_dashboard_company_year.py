"""The dashboard's company-year data over the real marts, built by dbt from the committed sample."""

from __future__ import annotations

from pathlib import Path

from openrct2_analytics.dashboard import data
from tests import test_dbt_environments as environments
from tests.test_dashboard_data import Figures
from tests.two_park_support import FIRST_PARK, SECOND_PARK, build_two_parks

project = environments.project  # the fixture, re-exported so pytest finds it here


def test_two_parks_share_one_company_year_on_the_real_marts(project: Path, tmp_path: Path) -> None:
    two = build_two_parks(project, tmp_path, "+path:models/marts", second_company_start_year=2000)

    figures: Figures = data.build(two.warehouse)

    assert {park["id"]: park["game_years"] for park in figures["parks"]} == {
        FIRST_PARK: {2000: {"game_year": 9, "from_month": 3}},
        SECOND_PARK: {2000: {"game_year": 9, "from_month": 3}},
    }

"""The dashboard data build refuses park IDs it reserves for aggregate views."""

from __future__ import annotations

from pathlib import Path

import pytest

from openrct2_analytics.dashboard import data
from tests.test_dashboard_data import Figures, make_warehouse


@pytest.mark.parametrize("reserved", ["all", "with_sandbox"])
def test_a_park_id_equal_to_an_aggregate_scope_key_is_refused(
    tmp_path: Path, reserved: str
) -> None:
    warehouse = make_warehouse(tmp_path / "w.duckdb", parks=((reserved, "Alpha Park"),))

    with pytest.raises(
        data.ReservedParkIdError,
        match=f"^park ID '{reserved}' is reserved by the dashboard for an aggregate view$",
    ):
        data.build(warehouse)


def test_ordinary_park_ids_build_beside_the_aggregate_scopes(tmp_path: Path) -> None:
    figures: Figures = data.build(
        make_warehouse(tmp_path / "w.duckdb", parks=(("p1", "Alpha Park"), ("p2", "Beta Park")))
    )

    assert sorted(figures["scopes"]) == ["all", "p1", "p2"]

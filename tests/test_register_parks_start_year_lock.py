"""The start-year check runs again under the landing lock (R10).

A delivery or convert that lands while the lock is being taken is seen by the second check, and
the refusal under the lock is final. The folder tree after the landing is unchanged by the run.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from openrct2_analytics.ingest import lock
from tests.autopilot_fixtures import plant_registry
from tests.test_register_parks import _tree
from tests.test_register_parks_start_year import (
    REQUIRED,
    Company,
    later_year,
    overlap,
    park_one,
    plant,
)
from tests.test_register_parks_start_year import company as company  # noqa: F401  (fixture)


def _land_before_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, landing: Callable[[], None]
) -> dict[str, str]:
    """Hook ``lock.hold_lock`` to run ``landing`` first; the result holds the tree after it."""
    seen: dict[str, str] = {}
    real_hold = lock.hold_lock

    @contextmanager
    def hold_after_landing(path: Path, note: str) -> Iterator[None]:
        landing()
        seen["tree"] = _tree(tmp_path)
        with real_hold(path, note):
            yield

    monkeypatch.setattr(lock, "hold_lock", hold_after_landing)
    return seen


def test_delivery_landing_during_lock_wait_requires_start_year(
    company: Company, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = park_one()
    registry = world["registry"]
    world["registry"] = []
    company.plant(world)

    def deliver() -> None:
        plant_registry(company.root / "company" / "registry" / "v1", registry)

    seen = _land_before_lock(monkeypatch, company.tmp_path, deliver)
    assert company.run("--parks", "park-2:company") == 2
    assert _tree(company.tmp_path) == seen["tree"]
    assert company.out() == (
        f"register refused: start-year-required: {REQUIRED}. Nothing was changed.\n"
    )


def test_convert_landing_during_lock_wait_raises_y(
    company: Company, monkeypatch: pytest.MonkeyPatch
) -> None:
    company.plant(park_one())
    later = later_year(park_one())
    later["registry"] = []

    def convert() -> None:
        plant(company.root, later)

    seen = _land_before_lock(monkeypatch, company.tmp_path, convert)
    assert company.run("--start-year", "2001") == 2
    assert _tree(company.tmp_path) == seen["tree"]
    detail = overlap("2001", "park-1", 2001, "park-2")
    assert company.out() == (
        f"register refused: start-year-overlap: {detail}. Nothing was changed.\n"
    )

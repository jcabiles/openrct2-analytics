"""Behavioral tests for example_service. Real objects only, no mocks."""

from __future__ import annotations

import pytest

from openrct2_analytics.domain.example_service import InvalidOrderError, price_order


def test_price_order_no_discount() -> None:
    assert price_order(unit_price_cents=500, quantity=3) == 1500


def test_price_order_with_discount() -> None:
    # 10 units at 1000 cents = 10000, minus 20% = 8000.
    assert price_order(unit_price_cents=1000, quantity=10, discount_percent=20) == 8000


def test_price_order_full_discount_is_free() -> None:
    assert price_order(unit_price_cents=999, quantity=1, discount_percent=100) == 0


@pytest.mark.parametrize(
    ("unit_price_cents", "quantity", "discount_percent"),
    [
        (0, 1, 0),
        (-5, 1, 0),
        (10, 0, 0),
        (10, -1, 0),
        (10, 1, 101),
        (10, 1, -1),
    ],
)
def test_price_order_rejects_invalid_input(
    unit_price_cents: int, quantity: int, discount_percent: int
) -> None:
    with pytest.raises(InvalidOrderError):
        price_order(
            unit_price_cents=unit_price_cents,
            quantity=quantity,
            discount_percent=discount_percent,
        )

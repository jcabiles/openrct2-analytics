"""Golden-path example: a small, honestly-typed service function.

Errors raise. There is no catch-log-continue here — a caller that wants a
fallback must decide that explicitly, at the call site, with a stated reason.
"""

from __future__ import annotations

MAX_DISCOUNT_PERCENT = 100


class InvalidOrderError(ValueError):
    """Raised when an order cannot be priced."""


def price_order(unit_price_cents: int, quantity: int, discount_percent: int = 0) -> int:
    """Compute the total price of an order, in integer cents.

    Args:
        unit_price_cents: price of a single unit, in cents. Must be positive.
        quantity: number of units. Must be positive.
        discount_percent: percentage discount to apply, 0-100 inclusive.

    Returns:
        The total price in integer cents, after discount, rounded down.

    Raises:
        InvalidOrderError: if any input is out of range.
    """
    if unit_price_cents <= 0:
        raise InvalidOrderError(f"unit_price_cents must be positive, got {unit_price_cents}")
    if quantity <= 0:
        raise InvalidOrderError(f"quantity must be positive, got {quantity}")
    if not 0 <= discount_percent <= MAX_DISCOUNT_PERCENT:
        raise InvalidOrderError(f"discount_percent must be 0-100, got {discount_percent}")

    subtotal = unit_price_cents * quantity
    discount = (subtotal * discount_percent) // 100
    return subtotal - discount

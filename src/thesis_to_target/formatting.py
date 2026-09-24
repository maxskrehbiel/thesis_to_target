"""Money formatting shared by the ledger, exports and brief, rounded half-up from exact values."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# Decimal(float) is the exact binary value, so rounding never depends on how the
# float was printed or on the platform that printed it.


def whole_dollars(value: float) -> int:
    """Round a dollar amount to whole dollars, halves rounding up."""
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def whole_thousands(value: float) -> int:
    """Round a dollar amount to the nearest thousand, halves rounding up.

    Args:
        value: Dollar amount.

    Returns:
        The rounded amount as an integer, e.g. ``682500.0 -> 683000``.
    """
    return int(Decimal(value).quantize(Decimal("1E3"), rounding=ROUND_HALF_UP))


def usd_millions(value: float) -> str:
    """Format a dollar amount in millions with two decimals, e.g. ``"$1.25M"``.

    Args:
        value: Dollar amount.

    Returns:
        The formatted amount, halves rounding up.
    """
    millions = (Decimal(value) / Decimal(1_000_000)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return f"${millions}M"


def usd_thousands(value: float) -> str:
    """Format a dollar amount in whole thousands, e.g. ``"$136k"``."""
    return f"${whole_thousands(value) // 1000}k"

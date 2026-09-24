"""Money formatting rounds half-up from the exact float value."""

from __future__ import annotations

import pytest

from thesis_to_target.formatting import usd_millions, usd_thousands, whole_dollars, whole_thousands


@pytest.mark.parametrize(
    ("value", "dollars", "thousands"),
    [
        (682_500.0, 682_500, 683_000),
        (682_499.5, 682_500, 682_000),
        (1_234.4, 1_234, 1_000),
        (0.5, 1, 0),
    ],
)
def test_whole_amounts_round_half_up(value: float, dollars: int, thousands: int) -> None:
    assert whole_dollars(value) == dollars
    assert whole_thousands(value) == thousands


def test_text_formats() -> None:
    assert usd_millions(1_234_567) == "$1.23M"
    assert usd_millions(1_235_000) == "$1.24M"  # the exact half rounds up, not to even
    assert usd_millions(5_000_000) == "$5.00M"
    assert usd_thousands(135_500) == "$136k"

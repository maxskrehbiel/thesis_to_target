"""Employee-range combination and the log-normal EBITDA probability math."""

from __future__ import annotations

import math

import pytest

from thesis_to_target.config import EstimationConfig
from thesis_to_target.estimate import (
    SizeSignal,
    combine_employee_signals,
    estimate_ebitda,
    lognormal_sf,
    normal_cdf,
    parse_band,
    sigma_from_range,
    signals_from_record,
)
from thesis_to_target.formatting import whole_thousands
from thesis_to_target.models import RawRecord

CFG = EstimationConfig()
Z95 = CFG.interval_z


def test_normal_cdf_reference_values() -> None:
    assert normal_cdf(0.0) == pytest.approx(0.5)
    assert normal_cdf(1.0) == pytest.approx(0.841345, abs=1e-6)
    assert normal_cdf(-Z95) == pytest.approx(0.025, abs=1e-6)


def test_lognormal_survival_function() -> None:
    mu, sigma = math.log(1_000_000), 0.4
    assert lognormal_sf(1_000_000, mu, sigma) == pytest.approx(0.5)
    assert lognormal_sf(math.exp(mu + sigma), mu, sigma) == pytest.approx(0.158655, abs=1e-6)
    values = [lognormal_sf(x, mu, sigma) for x in (2e5, 5e5, 1e6, 2e6, 5e6)]
    assert values == sorted(values, reverse=True)


def test_range_endpoints_become_95_percent_bounds() -> None:
    lo, hi = 500_000.0, 2_000_000.0
    sigma = sigma_from_range(lo, hi, Z95)
    mu = math.log(math.sqrt(lo * hi))
    assert lognormal_sf(lo, mu, sigma) == pytest.approx(0.975, abs=1e-9)
    assert lognormal_sf(hi, mu, sigma) == pytest.approx(0.025, abs=1e-9)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("20-49", (20.0, 49.0)),
        ("10 to 19", (10.0, 19.0)),
        ("500+", (500.0, 1500.0)),
        ("many", None),
        ("9-5", None),
    ],
)
def test_parse_band(label: str, expected: tuple[float, float] | None) -> None:
    assert parse_band(label, CFG.open_band_hi_mult) == expected


def test_signals_from_record_reads_the_standard_vocabulary() -> None:
    record = RawRecord(
        "R-1",
        "web_listing",
        "Braxmoor Fire",
        attributes={
            "employee_band": "20-49",
            "stated_headcount": 30,
            "locations": 2,
            "licensed_technicians": 8,
        },
    )
    by_name = {s.name: s for s in signals_from_record(record, CFG)}
    assert by_name["employee_band"].lo == 20 and by_name["employee_band"].hi == 49
    assert by_name["stated_headcount"].lo == pytest.approx(25.5)
    assert by_name["locations"].hi == pytest.approx(50.0)
    assert by_name["licensed_technicians"].is_floor
    ignored = RawRecord(
        "R-2", "web_listing", "x", attributes={"locations": 1, "stated_headcount": True}
    )
    assert signals_from_record(ignored, CFG) == []


def test_combination_is_a_weighted_geometric_mean() -> None:
    a = SizeSignal("employee_band", 20, 49, 1.0)
    b = SizeSignal("stated_headcount", 25.5, 37.5, 0.9)
    combined = combine_employee_signals([a, b], CFG)
    assert combined is not None
    expected_lo = math.exp((1.0 * math.log(20) + 0.9 * math.log(25.5)) / 1.9)
    assert combined.lo == pytest.approx(expected_lo)
    assert combined.conflicts == ()


def test_disagreeing_signals_widen_to_cover_both() -> None:
    band = SizeSignal("employee_band", 5, 9, 1.0)
    stated = SizeSignal("stated_headcount", 51, 75, 0.9)
    combined = combine_employee_signals([band, stated], CFG)
    assert combined is not None
    assert (combined.lo, combined.hi) == (5, 75)
    assert combined.conflicts


def test_floors_only_raise_the_low_end() -> None:
    band = SizeSignal("employee_band", 5, 9, 1.0)
    floor = SizeSignal("licensed_technicians", 12.5, 40, 0.6, is_floor=True)
    combined = combine_employee_signals([band, floor], CFG)
    assert combined is not None
    assert combined.lo == 12.5 and combined.hi == pytest.approx(12.5 * CFG.floor_hi_mult)
    floor_only = combine_employee_signals([floor], CFG)
    assert floor_only is not None and (floor_only.lo, floor_only.hi) == (12.5, 40)
    assert combine_employee_signals([], CFG) is None


def test_point_inputs_give_the_exact_product_and_the_minimum_sigma() -> None:
    est = estimate_ebitda(
        [SizeSignal("stated_headcount", 20, 20, 1.0)],
        (150_000, 150_000),
        (0.10, 0.10),
        (300_000, 3_000_000),
        CFG,
    )
    assert est is not None
    assert est.ebitda_mid == pytest.approx(300_000)
    assert est.sigma == CFG.min_sigma
    assert est.p_ge_min == pytest.approx(0.5)


def test_endpoint_mode_multiplies_range_ends() -> None:
    signals = [SizeSignal("employee_band", 20, 49, 1.0)]
    rpe, margin, band = (150_000.0, 210_000.0), (0.10, 0.16), (1e6, 5e6)
    wide = estimate_ebitda(signals, rpe, margin, band, EstimationConfig(interval_mode="endpoints"))
    narrow = estimate_ebitda(
        signals, rpe, margin, band, EstimationConfig(interval_mode="independent")
    )
    assert wide is not None and narrow is not None
    assert wide.ebitda_lo == 20 * 150_000 * 0.10
    assert wide.ebitda_hi == pytest.approx(49 * 210_000 * 0.16)
    assert wide.ebitda_mid == pytest.approx(narrow.ebitda_mid)
    assert narrow.sigma < wide.sigma


def test_band_probability_is_consistent() -> None:
    est = estimate_ebitda(
        [SizeSignal("employee_band", 50, 99, 1.0)],
        (150_000, 210_000),
        (0.10, 0.16),
        (1e6, 5e6),
        CFG,
    )
    assert est is not None
    tail_above_max = lognormal_sf(5e6, est.mu, est.sigma)
    assert est.p_in_band == pytest.approx(est.p_ge_min - tail_above_max)
    assert 0.0 <= est.p_in_band <= est.p_ge_min <= 1.0


def test_confidence_grades() -> None:
    rpe, margin, band = (150_000.0, 210_000.0), (0.10, 0.16), (1e6, 5e6)
    three = [
        SizeSignal("employee_band", 20, 49, 1.0),
        SizeSignal("stated_headcount", 25.5, 37.5, 0.9),
        SizeSignal("locations", 12, 50, 0.5),
    ]
    graded = estimate_ebitda(three, rpe, margin, band, CFG)
    single = estimate_ebitda(three[:1], rpe, margin, band, CFG)
    conflict = estimate_ebitda(
        [SizeSignal("employee_band", 5, 9, 1.0), SizeSignal("stated_headcount", 51, 75, 0.9)],
        rpe,
        margin,
        band,
        CFG,
    )
    assert graded is not None and graded.confidence == "high" and graded.n_signals == 3
    assert single is not None and single.confidence == "low"
    assert conflict is not None and conflict.confidence == "low" and conflict.conflicts
    assert estimate_ebitda([], rpe, margin, band, CFG) is None


def test_config_rejects_unknown_interval_mode() -> None:
    with pytest.raises(ValueError, match="interval_mode"):
        EstimationConfig(interval_mode="guess")


def test_endpoint_bounds_are_exact_products() -> None:
    # 35 x 150,000 x 0.13 is exactly 682,500: the bound must land on it, not on
    # exp(log(...)) float noise that rounds differently on different platforms.
    est = estimate_ebitda(
        [SizeSignal("employee_band", 35, 70, 1.0)],
        (150_000, 210_000),
        (0.13, 0.16),
        (1e6, 5e6),
        CFG,
    )
    assert est is not None
    assert est.ebitda_lo == 682_500.0
    assert est.ebitda_hi == 70 * 210_000 * 0.16
    assert whole_thousands(est.ebitda_lo) == 683_000


def test_agreeing_signals_combine_exactly() -> None:
    same = [SizeSignal("employee_band", 20, 49, 1.0), SizeSignal("stated_headcount", 20, 49, 0.9)]
    combined = combine_employee_signals(same, CFG)
    assert combined is not None and (combined.lo, combined.hi) == (20, 49)

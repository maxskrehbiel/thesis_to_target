"""Size estimation: size signals -> employee range -> log-normal EBITDA -> P(EBITDA in band)."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .config import EstimationConfig, SignalRule
from .evidence import EvidenceLedger
from .formatting import usd_millions, usd_thousands, whole_dollars
from .models import Company, EbitdaEstimate, RawRecord
from .thesis import Thesis

_BAND_RE = re.compile(r"^\s*(\d+)\s*(?:-|to)\s*(\d+)\s*$")
_OPEN_BAND_RE = re.compile(r"^\s*(\d+)\s*\+\s*$")
_SIGNAL_CONFIDENCE = {
    "employee_band": "strong",
    "stated_headcount": "strong",
    "locations": "inferred",
    "licensed_technicians": "strong",
}
_RANGE_CONFIDENCE = {"high": "strong", "medium": "inferred", "low": "weak"}
_DEFAULT_TRUST = 0.5


@dataclass(frozen=True)
class SizeSignal:
    """One piece of size evidence expressed as an employee range.

    Attributes:
        name: Signal kind, e.g. ``"employee_band"``.
        lo: Low end of the implied employee range.
        hi: High end of the implied employee range.
        weight: Vote in the combination.
        is_floor: True when the signal only proves a minimum.
        raw_value: The value as reported, for the evidence ledger.
        record_id: Record that reported it.
    """

    name: str
    lo: float
    hi: float
    weight: float
    is_floor: bool = False
    raw_value: str = ""
    record_id: str = ""


@dataclass(frozen=True)
class EmployeeRange:
    """Combined employee range.

    Attributes:
        lo: Low end.
        hi: High end.
        conflicts: Descriptions of signal pairs that disagree.
    """

    lo: float
    hi: float
    conflicts: tuple[str, ...] = ()


def normal_cdf(z: float) -> float:
    """Standard normal cumulative distribution, Phi(z)."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def lognormal_sf(x: float, mu: float, sigma: float) -> float:
    """Probability that a log-normal variable is at least ``x``.

    Args:
        x: Threshold (must be positive).
        mu: Mean of the logarithm.
        sigma: Standard deviation of the logarithm (must be positive).

    Returns:
        ``1 - Phi((ln x - mu) / sigma)``.
    """
    return 1.0 - normal_cdf((math.log(x) - mu) / sigma)


def sigma_from_range(lo: float, hi: float, z: float) -> float:
    """Log-space standard deviation of a range read as a central interval of width ``z``.

    With ``z = 1.96`` the range is treated as the 2.5th to 97.5th percentile.
    """
    return (math.log(hi) - math.log(lo)) / (2.0 * z)


def parse_band(label: str, open_hi_mult: float) -> tuple[float, float] | None:
    """Parse an employee band such as ``"20-49"`` or ``"500+"``.

    Args:
        label: Band label.
        open_hi_mult: Upper end of an open band as a multiple of its floor.

    Returns:
        ``(low, high)``, or ``None`` if the label is not a band.
    """
    closed = _BAND_RE.match(str(label))
    if closed:
        lo, hi = float(closed.group(1)), float(closed.group(2))
        return (lo, hi) if 0 < lo <= hi else None
    open_band = _OPEN_BAND_RE.match(str(label))
    if open_band and float(open_band.group(1)) > 0:
        lo = float(open_band.group(1))
        return lo, lo * open_hi_mult
    return None


def _rule_signal(name: str, value: object, rule: SignalRule, record_id: str) -> SizeSignal | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < rule.min_value:
        return None
    n = float(value)
    return SizeSignal(
        name,
        n * rule.lo_mult,
        n * rule.hi_mult,
        rule.weight,
        rule.is_floor,
        f"{value:g}",
        record_id,
    )


def signals_from_record(record: RawRecord, cfg: EstimationConfig) -> list[SizeSignal]:
    """Turn a record's size attributes into employee-range signals.

    Args:
        record: Source record.
        cfg: Conversion rules.

    Returns:
        Zero or more signals (employee band, stated headcount, locations, licensed staff).
    """
    out: list[SizeSignal] = []
    band = record.attributes.get("employee_band")
    parsed = parse_band(str(band), cfg.open_band_hi_mult) if band else None
    if parsed:
        out.append(
            SizeSignal(
                "employee_band",
                parsed[0],
                parsed[1],
                cfg.band_weight,
                False,
                str(band),
                record.record_id,
            )
        )
    for name, rule in (
        ("stated_headcount", cfg.stated_headcount),
        ("locations", cfg.locations),
        ("licensed_technicians", cfg.licensed_technicians),
    ):
        signal = _rule_signal(name, record.attributes.get(name), rule, record.record_id)
        if signal:
            out.append(signal)
    return out


def _weighted_geometric_mean(values: Sequence[float], weights: Sequence[float]) -> float:
    if all(v == values[0] for v in values):
        return values[0]  # exact, and independent of the platform's exp/log
    total = sum(weights)
    return math.exp(sum(w * math.log(v) for v, w in zip(values, weights, strict=True)) / total)


def _conflicts(ranges: Sequence[SizeSignal], tolerance: float) -> list[str]:
    found = []
    for i, a in enumerate(ranges):
        for b in ranges[i + 1 :]:
            if a.hi * tolerance < b.lo or b.hi * tolerance < a.lo:
                found.append(f"{a.name} {a.lo:.0f}-{a.hi:.0f} vs {b.name} {b.lo:.0f}-{b.hi:.0f}")
    return found


def combine_employee_signals(
    signals: Sequence[SizeSignal], cfg: EstimationConfig
) -> EmployeeRange | None:
    """Combine signals into one employee range.

    Range signals are combined by a weighted mean of their log end-points (a
    weighted geometric mean). If two range signals disagree beyond the tolerance,
    the combined range widens to cover both instead. Floor signals can only raise
    the low end.

    Args:
        signals: Signals for one company.
        cfg: Combination settings.

    Returns:
        The combined range, or ``None`` when there are no signals.
    """
    ranges = [s for s in signals if not s.is_floor]
    floors = [s for s in signals if s.is_floor]
    if not ranges and not floors:
        return None
    conflicts = _conflicts(ranges, cfg.conflict_tolerance)
    if conflicts:
        lo, hi = min(s.lo for s in ranges), max(s.hi for s in ranges)
    elif ranges:
        weights = [s.weight for s in ranges]
        lo = _weighted_geometric_mean([s.lo for s in ranges], weights)
        hi = _weighted_geometric_mean([s.hi for s in ranges], weights)
    else:
        lo, hi = max(f.lo for f in floors), max(f.hi for f in floors)
    for f in floors:
        if f.lo > lo:
            lo = f.lo
            hi = max(hi, f.lo * cfg.floor_hi_mult)
    return EmployeeRange(lo, hi, tuple(conflicts))


def _grade(n_signals: int, spread: float, conflicts: Sequence[str], cfg: EstimationConfig) -> str:
    if conflicts:
        return "low"
    if n_signals >= cfg.high_min_signals and spread <= cfg.high_max_spread:
        return "high"
    if n_signals >= cfg.medium_min_signals and spread <= cfg.medium_max_spread:
        return "medium"
    return "low"


@dataclass(frozen=True)
class LogNormalFit:
    """A log-normal distribution fitted to a product of ranged factors.

    Attributes:
        median: Product of the factors' geometric midpoints.
        mu: ln(median).
        sigma: Log-space standard deviation.
        lo: 2.5th percentile.
        hi: 97.5th percentile.
    """

    median: float
    mu: float
    sigma: float
    lo: float
    hi: float


def fit_lognormal(factors: Sequence[tuple[float, float]], cfg: EstimationConfig) -> LogNormalFit:
    """Fit the log-normal distribution of a product of ``(low, high)`` factors.

    Args:
        factors: Ranges whose product is being estimated.
        cfg: Interval mode, z-width and minimum sigma.

    Returns:
        Median, spread and 95% range.
    """
    median = math.prod(math.sqrt(lo * hi) for lo, hi in factors)
    sigmas = [sigma_from_range(lo, hi, cfg.interval_z) for lo, hi in factors]
    raw = (
        math.sqrt(sum(s * s for s in sigmas)) if cfg.interval_mode == "independent" else sum(sigmas)
    )
    sigma = max(raw, cfg.min_sigma)
    mu = math.log(median)
    if cfg.interval_mode == "endpoints" and raw >= cfg.min_sigma:
        # Mathematically equal to exp(mu -/+ z * sigma). Multiplying the range ends
        # directly keeps the bounds exact, so rounding them never depends on exp/log.
        lo = math.prod(low for low, _ in factors)
        hi = math.prod(high for _, high in factors)
    else:
        lo, hi = math.exp(mu - cfg.interval_z * sigma), math.exp(mu + cfg.interval_z * sigma)
    return LogNormalFit(median, mu, sigma, lo, hi)


def estimate_ebitda(
    signals: Sequence[SizeSignal],
    revenue_per_employee: tuple[float, float],
    margin: tuple[float, float],
    band: tuple[float, float],
    cfg: EstimationConfig,
    *,
    segment: str = "unknown",
    service_mix: str = "unknown",
) -> EbitdaEstimate | None:
    """Estimate EBITDA as a log-normal distribution and score it against the thesis band.

    ``median EBITDA = employee midpoint x revenue-per-employee midpoint x margin midpoint``
    (geometric midpoints). Each input range is read as a central interval, giving a
    log-space sigma per factor; ``"endpoints"`` mode adds them linearly, ``"independent"``
    mode in quadrature. Then ``P(EBITDA >= T) = 1 - Phi((ln T - mu) / sigma)``.

    Args:
        signals: Size signals for one company.
        revenue_per_employee: ``(low, high)`` for the company's segment.
        margin: ``(low, high)`` EBITDA margin for its service mix.
        band: ``(minimum, maximum)`` EBITDA of the thesis.
        cfg: Model settings.
        segment: Segment name, recorded on the result.
        service_mix: Service mix, recorded on the result.

    Returns:
        The estimate, or ``None`` when there are no size signals.
    """
    employees = combine_employee_signals(signals, cfg)
    if employees is None:
        return None
    dist = fit_lognormal(((employees.lo, employees.hi), revenue_per_employee, margin), cfg)
    employees_mid = math.sqrt(employees.lo * employees.hi)
    n_signals = len({s.name for s in signals})
    p_ge_min = lognormal_sf(band[0], dist.mu, dist.sigma)
    return EbitdaEstimate(
        employees_lo=employees.lo,
        employees_hi=employees.hi,
        employees_mid=employees_mid,
        revenue_mid=employees_mid * math.sqrt(revenue_per_employee[0] * revenue_per_employee[1]),
        ebitda_mid=dist.median,
        ebitda_lo=dist.lo,
        ebitda_hi=dist.hi,
        mu=dist.mu,
        sigma=dist.sigma,
        p_ge_min=p_ge_min,
        p_in_band=p_ge_min - lognormal_sf(band[1], dist.mu, dist.sigma),
        confidence=_grade(
            n_signals, math.log(employees.hi / employees.lo), employees.conflicts, cfg
        ),
        n_signals=n_signals,
        conflicts=employees.conflicts,
        segment=segment,
        service_mix=service_mix,
    )


def select_signals(
    records: Sequence[RawRecord], cfg: EstimationConfig, trust: Mapping[str, float]
) -> list[SizeSignal]:
    """Pick one signal of each kind, preferring the most trusted source.

    Args:
        records: A company's source records.
        cfg: Conversion rules.
        trust: Feed name -> trust weight.

    Returns:
        At most one signal per kind (band, stated headcount, locations, licensed staff).
    """
    by_trust = sorted(records, key=lambda r: (-trust.get(r.source, _DEFAULT_TRUST), r.record_id))
    chosen: dict[str, SizeSignal] = {}
    for record in by_trust:
        for signal in signals_from_record(record, cfg):
            chosen.setdefault(signal.name, signal)
    return list(chosen.values())


def _record_signals(
    company_id: str,
    signals: Sequence[SizeSignal],
    records: Sequence[RawRecord],
    ledger: EvidenceLedger,
) -> list[str]:
    source_of = {r.record_id: r.source for r in records}
    return [
        ledger.observed(
            company_id,
            f"size_signal:{s.name}",
            s.raw_value,
            record_ids=[s.record_id],
            source=source_of[s.record_id],
            confidence=_SIGNAL_CONFIDENCE[s.name],
            method="size_signal",
            evidence=f"{s.record_id} reports {s.name.replace('_', ' ')} {s.raw_value} -> "
            f"{'at least ' if s.is_floor else ''}{s.lo:.0f}-{s.hi:.0f} employees "
            f"(weight {s.weight:g})",
        )
        for s in signals
    ]


@dataclass(frozen=True)
class _Assumptions:
    revenue_per_employee: tuple[float, float]
    margin: tuple[float, float]
    segment_claim: str
    mix_claim: str


def _record_estimate(
    company_id: str,
    est: EbitdaEstimate,
    thesis: Thesis,
    ledger: EvidenceLedger,
    signal_claims: Sequence[str],
    assumptions: _Assumptions,
) -> None:
    conflict_note = f"; conflicts: {'; '.join(est.conflicts)}" if est.conflicts else ""
    employees_claim = ledger.derived(
        company_id,
        "employees_range",
        f"{est.employees_lo:.0f}-{est.employees_hi:.0f}",
        depends_on=signal_claims,
        confidence="contradictory" if est.conflicts else _RANGE_CONFIDENCE[est.confidence],
        method="weighted_geometric_mean",
        evidence=f"{est.n_signals} signal(s); midpoint {est.employees_mid:.0f}; "
        f"size confidence {est.confidence}{conflict_note}",
    )
    model_conf = "weak" if est.confidence == "low" else "inferred"
    rpe, margin = assumptions.revenue_per_employee, assumptions.margin
    rpe_mid, margin_mid = math.sqrt(rpe[0] * rpe[1]), math.sqrt(margin[0] * margin[1])
    ebitda_claim = ledger.derived(
        company_id,
        "ebitda_estimate",
        whole_dollars(est.ebitda_mid),
        depends_on=[employees_claim, assumptions.segment_claim, assumptions.mix_claim],
        confidence=model_conf,
        method="lognormal_model",
        evidence=f"{est.employees_mid:.0f} employees x {usd_thousands(rpe_mid)} revenue/employee "
        f"({est.segment}) x {margin_mid:.1%} margin ({est.service_mix}) = "
        f"{usd_millions(est.ebitda_mid)} median; 95% range {usd_millions(est.ebitda_lo)}-"
        f"{usd_millions(est.ebitda_hi)} (sigma {est.sigma:.2f}, {thesis.estimation.interval_mode})",
    )
    lognormal = f"log-normal(mu={est.mu:.2f}, sigma={est.sigma:.2f})"
    low, high = usd_millions(thesis.ebitda_min), usd_millions(thesis.ebitda_max)
    for claim, value, question in (
        ("p_ebitda_ge_min", est.p_ge_min, f"P(EBITDA >= {low})"),
        ("p_ebitda_in_band", est.p_in_band, f"P({low} <= EBITDA <= {high})"),
    ):
        ledger.derived(
            company_id,
            claim,
            round(value, 3),
            depends_on=[ebitda_claim],
            confidence=model_conf,
            method="lognormal_model",
            evidence=f"{lognormal}: {question}",
        )


def estimate_company(
    company: Company,
    records: Sequence[RawRecord],
    thesis: Thesis,
    ledger: EvidenceLedger,
    *,
    trust: Mapping[str, float],
    segment_claim: str,
    mix_claim: str,
    anchor_claim: str,
) -> EbitdaEstimate | None:
    """Estimate one company's EBITDA and record every input and output in the ledger.

    Args:
        company: The resolved company (its fit result must be attached).
        records: Its source records.
        thesis: Supplies revenue per employee, margins and the EBITDA band.
        ledger: Ledger to append to.
        trust: Feed name -> trust; when two records report the same signal the
            more trusted one is used.
        segment_claim: Claim backing the segment.
        mix_claim: Claim backing the service mix.
        anchor_claim: Claim to cite when the company cannot be sized.

    Returns:
        The estimate, or ``None`` when no record carries a size signal.
    """
    signals = select_signals(records, thesis.estimation, trust)
    signal_claims = _record_signals(company.company_id, signals, records, ledger)
    segment = company.fit.segment if company.fit else "unknown"
    mix = company.fit.service_mix if company.fit else "unknown"
    assumptions = _Assumptions(
        thesis.revenue_per_employee(segment), thesis.margin(mix), segment_claim, mix_claim
    )
    est = estimate_ebitda(
        signals,
        assumptions.revenue_per_employee,
        assumptions.margin,
        (thesis.ebitda_min, thesis.ebitda_max),
        thesis.estimation,
        segment=segment,
        service_mix=mix,
    )
    if est is None:
        ledger.derived(
            company.company_id,
            "ebitda_estimate",
            "unsized",
            depends_on=[anchor_claim],
            confidence="weak",
            method="lognormal_model",
            evidence="no size signal in any source record",
        )
        return None
    _record_estimate(company.company_id, est, thesis, ledger, signal_claims, assumptions)
    return est

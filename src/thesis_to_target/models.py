"""Record, company and stage-result types shared by every pipeline stage."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RawRecord:
    """One row from one source, exactly as that source presented it.

    Attributes:
        record_id: Identifier unique across all sources, e.g. ``"REG-0012"``.
        source: Name of the feed the row came from.
        name: Name as printed by the source; may contain a legal suffix or a DBA.
        dba: Separate "doing business as" field, when the source has one.
        city: City as printed by the source.
        state: Two-letter state code.
        zip: ZIP or ZIP+4 code.
        phone: Phone number in any format.
        website: Website URL in any format.
        attributes: Source facts mapped onto the standard vocabulary
            (see :class:`thesis_to_target.sources.SourceAdapter`).
    """

    record_id: str
    source: str
    name: str
    dba: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    phone: str | None = None
    website: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FitResult:
    """Sector-fit classification of one company.

    Attributes:
        tier: ``"A"`` verified, ``"B"`` likely, ``"C"`` name only, ``"D"`` no sector evidence.
        fit_score: Score in [0, 1] derived from the tier.
        segment: Thesis segment with the most keyword evidence, or ``"unknown"``.
        service_mix: ``"recurring_heavy"``, ``"mixed"``, ``"install_heavy"`` or ``"unknown"``.
        residential_only: The company's own text says it serves homeowners only.
        parent_owned: A source lists a parent or controlling owner.
        adjacent_trade: Evidence points to a neighboring trade instead of the thesis sector.
    """

    tier: str
    fit_score: float
    segment: str
    service_mix: str
    residential_only: bool = False
    parent_owned: bool = False
    adjacent_trade: bool = False


@dataclass(frozen=True)
class EbitdaEstimate:
    """Log-normal EBITDA estimate of one company (USD per year).

    Attributes:
        employees_lo: Low end of the combined employee range.
        employees_hi: High end of the combined employee range.
        employees_mid: Geometric midpoint of the employee range.
        revenue_mid: Median revenue implied by the midpoint inputs.
        ebitda_mid: Median EBITDA, ``exp(mu)``.
        ebitda_lo: 2.5th percentile of the fitted distribution.
        ebitda_hi: 97.5th percentile of the fitted distribution.
        mu: Mean of ln(EBITDA).
        sigma: Standard deviation of ln(EBITDA).
        p_ge_min: Probability that EBITDA is at least the thesis minimum.
        p_in_band: Probability that EBITDA falls within the thesis band.
        confidence: ``"high"``, ``"medium"`` or ``"low"``.
        n_signals: Number of distinct size signals used.
        conflicts: Descriptions of size signals that disagree with each other.
        segment: Segment whose revenue-per-employee range was used.
        service_mix: Service mix whose margin range was used.
    """

    employees_lo: float
    employees_hi: float
    employees_mid: float
    revenue_mid: float
    ebitda_mid: float
    ebitda_lo: float
    ebitda_hi: float
    mu: float
    sigma: float
    p_ge_min: float
    p_in_band: float
    confidence: str
    n_signals: int
    conflicts: tuple[str, ...] = ()
    segment: str = "unknown"
    service_mix: str = "unknown"


@dataclass(frozen=True)
class PresenceResult:
    """How visible a company already is to anyone using the large databases.

    Attributes:
        found: Database name -> whether a matching listing was found.
        has_website: Whether any source record carries a company website.
        obviousness: Weighted share of places the company shows up, in [0, 1].
        non_obvious: True when obviousness is below the thesis cut-off.
    """

    found: Mapping[str, bool]
    has_website: bool
    obviousness: float
    non_obvious: bool


@dataclass
class Company:
    """A resolved business assembled from one or more source records.

    Identity fields are set by entity resolution; the optional stage results are
    attached as the pipeline runs.

    Attributes:
        company_id: Stable identifier such as ``"C0007"``.
        name: Operating (display) name chosen by trust-weighted vote.
        legal_name: Registered name with legal suffix, when a source shows one.
        city: City of the winning state's highest-trust record.
        state: State chosen by trust-weighted vote.
        zip: Five-digit ZIP code, when known.
        phone: Ten-digit phone chosen by trust-weighted vote.
        domain: Website host chosen by trust-weighted vote.
        member_ids: Source record ids merged into this company.
        sources: Distinct feeds the company appears in.
        name_variants: Every normalized name the members are known by.
        flags: Data-quality notes, e.g. a low-cohesion cluster.
        fit: Sector-fit classification.
        estimate: EBITDA estimate, ``None`` when no size signal exists.
        presence: Database presence and obviousness.
        exclusions: Reasons the company is out of scope; empty when in scope.
        composite: Composite score (0-100) for in-scope companies.
        rank: Rank among in-scope companies (1 = best).
        tier: ``"Priority"``, ``"Watchlist"`` or ``"Excluded"``.
    """

    company_id: str
    name: str
    legal_name: str | None
    city: str | None
    state: str | None
    zip: str | None
    phone: str | None
    domain: str | None
    member_ids: list[str]
    sources: list[str]
    name_variants: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    fit: FitResult | None = None
    estimate: EbitdaEstimate | None = None
    presence: PresenceResult | None = None
    exclusions: list[str] = field(default_factory=list)
    composite: float | None = None
    rank: int | None = None
    tier: str = "Unranked"

    @property
    def in_scope(self) -> bool:
        """True when no screen excluded the company."""
        return not self.exclusions

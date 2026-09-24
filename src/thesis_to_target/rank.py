"""Scope screens, composite scoring, ranking and tiering of companies."""

from __future__ import annotations

from collections.abc import Sequence

from .config import RankConfig
from .evidence import EvidenceLedger
from .models import Company
from .thesis import Thesis


def _claim_id(ledger: EvidenceLedger, company_id: str, claim: str) -> str:
    found = ledger.last(company_id, claim)
    if found is None:
        raise KeyError(f"{company_id} has no '{claim}' claim to cite")
    return found.claim_id


def screen_company(company: Company, thesis: Thesis, ledger: EvidenceLedger) -> list[str]:
    """Apply the thesis scope screens and record the outcome.

    Screens: geography, sector fit (tier D), homeowner-only businesses and
    companies with a parent owner. Requires the location, fit and presence claims.

    Args:
        company: Company with its fit result attached.
        thesis: Thesis whose geography applies.
        ledger: Ledger to append to.

    Returns:
        Exclusion reasons (also stored on ``company.exclusions``); empty when in scope.
    """
    cid = company.company_id
    reasons: list[str] = []
    deps = [_claim_id(ledger, cid, "location"), _claim_id(ledger, cid, "fit_tier")]
    if not company.state:
        reasons.append("location_unknown")
    elif company.state not in thesis.states:
        reasons.append("out_of_geography")
    fit = company.fit
    if fit is not None:
        if fit.tier == "D":
            reasons.append("adjacent_trade" if fit.adjacent_trade else "no_sector_evidence")
        if fit.residential_only:
            reasons.append("residential_only")
            deps.append(_claim_id(ledger, cid, "residential_only"))
        if fit.parent_owned:
            reasons.append("parent_owned")
            deps.append(_claim_id(ledger, cid, "ownership"))
    company.exclusions = reasons
    ledger.derived(
        cid,
        "screen",
        "excluded: " + ", ".join(reasons) if reasons else "in scope",
        depends_on=deps,
        confidence="inferred",
        method="scope_rules",
        evidence=f"state {company.state or '?'} vs thesis states; "
        f"fit tier {fit.tier if fit else '?'}; "
        + (f"exclusions: {', '.join(reasons)}" if reasons else "passes every screen"),
    )
    return reasons


def evidence_strength(company: Company, cfg: RankConfig) -> float:
    """Blend of source corroboration and size confidence, in [0, 1].

    Args:
        company: Company with its estimate attached.
        cfg: Saturation and confidence credits.

    Returns:
        ``0.5 * min(1, sources / saturation) + 0.5 * size_confidence_credit``.
    """
    corroboration = min(1.0, len(company.sources) / cfg.source_saturation)
    size_credit = (
        cfg.size_confidence_credit.get(company.estimate.confidence, 0.0)
        if company.estimate
        else 0.0
    )
    return 0.5 * corroboration + 0.5 * size_credit


def composite_score(company: Company, cfg: RankConfig) -> tuple[float, dict[str, float]]:
    """Weighted composite (0-100) of band probability, fit, non-obviousness and evidence.

    Args:
        company: Company with fit, estimate and presence attached.
        cfg: Weights.

    Returns:
        The composite score and its four components (each in [0, 1]).
    """
    parts = {
        "p_in_band": company.estimate.p_in_band if company.estimate else 0.0,
        "fit": company.fit.fit_score if company.fit else 0.0,
        "non_obvious": 1.0 - company.presence.obviousness if company.presence else 0.0,
        "evidence": evidence_strength(company, cfg),
    }
    weighted = (
        cfg.weight_p_in_band * parts["p_in_band"]
        + cfg.weight_fit * parts["fit"]
        + cfg.weight_non_obvious * parts["non_obvious"]
        + cfg.weight_evidence * parts["evidence"]
    )
    return 100.0 * weighted / cfg.total_weight, parts


def rank_companies(companies: Sequence[Company], cfg: RankConfig, ledger: EvidenceLedger) -> None:
    """Score, rank and tier every in-scope company; mark the rest Excluded.

    Ties are broken by company id so the order is deterministic.

    Args:
        companies: Screened companies.
        cfg: Weights and tier cut-offs.
        ledger: Ledger to append the composite-score claims to.
    """
    scored: list[tuple[float, Company, dict[str, float]]] = []
    for company in companies:
        if not company.in_scope:
            company.tier, company.rank, company.composite = "Excluded", None, None
            continue
        score, parts = composite_score(company, cfg)
        scored.append((score, company, parts))
    scored.sort(key=lambda item: (-item[0], item[1].company_id))
    for rank, (score, company, parts) in enumerate(scored, start=1):
        p = company.estimate.p_in_band if company.estimate else 0.0
        priority = rank <= cfg.priority_max_rank and p >= cfg.priority_min_p_in_band
        company.rank, company.composite = rank, round(score, 2)
        company.tier = "Priority" if priority else "Watchlist"
        cid = company.company_id
        p_claim = "p_ebitda_in_band" if company.estimate else "ebitda_estimate"
        deps = [
            _claim_id(ledger, cid, c)
            for c in (p_claim, "fit_tier", "obviousness", "entity_resolution")
        ]
        ledger.derived(
            cid,
            "composite_score",
            company.composite,
            depends_on=deps,
            confidence="inferred",
            method="weighted_sum",
            evidence=f"100 x ({cfg.weight_p_in_band:g} x P(in band) {parts['p_in_band']:.2f} "
            f"+ {cfg.weight_fit:g} x fit {parts['fit']:.2f} "
            f"+ {cfg.weight_non_obvious:g} x (1 - obviousness) {parts['non_obvious']:.2f} "
            f"+ {cfg.weight_evidence:g} x evidence {parts['evidence']:.2f}) "
            f"/ {cfg.total_weight:g}; "
            f"rank {rank} of {len(scored)}; tier {company.tier}",
        )

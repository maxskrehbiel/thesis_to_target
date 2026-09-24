"""Scope screens, composite scoring and ranking."""

from __future__ import annotations

from typing import Any

import pytest

from thesis_to_target.config import RankConfig
from thesis_to_target.evidence import EvidenceLedger
from thesis_to_target.models import Company, EbitdaEstimate, FitResult, PresenceResult
from thesis_to_target.pipeline import RunResult
from thesis_to_target.rank import composite_score, evidence_strength, rank_companies, screen_company
from thesis_to_target.thesis import Thesis


def _estimate(p_in_band: float, confidence: str = "medium") -> EbitdaEstimate:
    return EbitdaEstimate(
        30, 60, 42, 7e6, 1.2e6, 0.8e6, 1.9e6, 14.0, 0.3, p_in_band, p_in_band, confidence, 2
    )


def _company(
    cid: str,
    state: str = "IL",
    tier: str = "A",
    p: float = 0.8,
    obvious: float = 0.0,
    **fit_flags: bool,
) -> Company:
    company = Company(
        cid, f"Firm {cid}", None, None, state, None, None, None, [f"R-{cid}"], ["a", "b"]
    )
    company.fit = FitResult(
        tier, {"A": 1.0, "B": 0.75, "C": 0.4, "D": 0.0}[tier], "sprinkler", "mixed", **fit_flags
    )
    company.estimate = _estimate(p)
    company.presence = PresenceResult({"db": obvious > 0}, False, obvious, obvious < 0.3)
    return company


def _seed_claims(ledger: EvidenceLedger, company: Company, *, extra: tuple[str, ...] = ()) -> None:
    cid = company.company_id
    base = ledger.observed(
        cid,
        "location",
        "IL",
        evidence="e",
        source="s",
        record_ids=company.member_ids,
        confidence="strong",
    )
    for claim in ("fit_tier", "p_ebitda_in_band", "obviousness", "entity_resolution", *extra):
        ledger.derived(cid, claim, "x", evidence="e", depends_on=[base], confidence="inferred")


@pytest.mark.parametrize(
    ("kwargs", "reasons"),
    [
        ({}, []),
        ({"state": "TX"}, ["out_of_geography"]),
        ({"state": ""}, ["location_unknown"]),
        ({"tier": "D"}, ["no_sector_evidence"]),
        ({"tier": "D", "adjacent_trade": True}, ["adjacent_trade"]),
        ({"residential_only": True}, ["residential_only"]),
        ({"parent_owned": True}, ["parent_owned"]),
    ],
)
def test_screens(demo_thesis: Thesis, kwargs: dict[str, Any], reasons: list[str]) -> None:
    company = _company("C1", **kwargs)
    ledger = EvidenceLedger()
    _seed_claims(ledger, company, extra=("residential_only", "ownership"))
    assert screen_company(company, demo_thesis, ledger) == reasons
    assert company.in_scope is (not reasons)
    screen = ledger.last("C1", "screen")
    assert screen is not None and (screen.value == "in scope") is (not reasons)


def test_evidence_strength_and_composite() -> None:
    cfg = RankConfig()
    company = _company("C1", p=0.8, obvious=0.35)
    assert evidence_strength(company, cfg) == pytest.approx(0.5 * 2 / 3 + 0.5 * 0.65)
    score, parts = composite_score(company, cfg)
    expected = 100 * (0.45 * 0.8 + 0.25 * 1.0 + 0.20 * 0.65 + 0.10 * parts["evidence"]) / 1.0
    assert score == pytest.approx(expected)
    unsized = _company("C2")
    unsized.estimate = None
    assert composite_score(unsized, cfg)[1]["p_in_band"] == 0.0


def test_ranking_is_deterministic_and_tiers_respect_cutoffs() -> None:
    cfg = RankConfig(priority_max_rank=2, priority_min_p_in_band=0.5)
    companies = [
        _company("C3", p=0.9),
        _company("C1", p=0.9),
        _company("C2", p=0.3),
        _company("C4", state="TX"),
    ]
    companies[3].exclusions = ["out_of_geography"]
    ledger = EvidenceLedger()
    for c in companies:
        _seed_claims(ledger, c)
    rank_companies(companies, cfg, ledger)
    by_id = {c.company_id: c for c in companies}
    assert (by_id["C1"].rank, by_id["C3"].rank, by_id["C2"].rank) == (1, 2, 3)
    assert [by_id[c].tier for c in ("C1", "C3", "C2", "C4")] == [
        "Priority",
        "Priority",
        "Watchlist",
        "Excluded",
    ]
    assert by_id["C4"].rank is None and by_id["C4"].composite is None
    assert ledger.last("C1", "composite_score") is not None


def test_demo_ranks_are_contiguous(demo_run: RunResult) -> None:
    ranked = demo_run.ranked()
    assert [c.rank for c in ranked] == list(range(1, len(ranked) + 1))
    scores = [c.composite for c in ranked]
    assert scores == sorted(scores, reverse=True)
    assert all(c.in_scope for c in ranked)
    priority = [c for c in ranked if c.tier == "Priority"]
    cfg = demo_run.thesis.ranking
    assert all(c.rank is not None and c.rank <= cfg.priority_max_rank for c in priority)
    assert all(c.estimate and c.estimate.p_in_band >= cfg.priority_min_p_in_band for c in priority)

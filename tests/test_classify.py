"""Fit tiers, segment and service-mix inference, and the optional model hook."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

import pytest

from thesis_to_target.classify import (
    FitClaims,
    classify_company,
    find_keywords,
    keyword_pattern,
    load_hook,
)
from thesis_to_target.errors import HookError
from thesis_to_target.evidence import EvidenceLedger
from thesis_to_target.models import Company, FitResult, RawRecord
from thesis_to_target.normalize import name_variants
from thesis_to_target.thesis import Thesis


def _classify(
    thesis: Thesis, name: str, attrs: list[dict[str, Any]], hook: Any = None
) -> tuple[FitResult, FitClaims, EvidenceLedger]:
    records = [
        RawRecord(
            f"R-{i}",
            "web_listing" if "services" in a else "business_registry",
            name,
            state="IL",
            attributes=a,
        )
        for i, a in enumerate(attrs)
    ]
    company = Company(
        "C1", name, None, None, "IL", None, None, None, [r.record_id for r in records], ["x"]
    )
    company.name_variants = name_variants(name)
    ledger = EvidenceLedger()
    anchor = ledger.observed(
        "C1",
        "name",
        name,
        evidence="e",
        source="s",
        record_ids=company.member_ids,
        confidence="strong",
    )
    fit, claims = classify_company(company, records, thesis, ledger, anchor_claim=anchor, hook=hook)
    return fit, claims, ledger


def test_keyword_pattern_handles_plurals_and_boundaries() -> None:
    assert keyword_pattern("sprinkler").search("fire sprinklers installed")
    assert not keyword_pattern("fire").search("firewood delivery")
    assert find_keywords("Fire Alarm monitoring", ["fire alarm", "sprinkler"]) == ["fire alarm"]


def test_sector_license_gives_tier_a(demo_thesis: Thesis) -> None:
    license_attrs = {"license_type": "Fire Sprinkler Contractor", "license_status": "Active"}
    fit, claims, ledger = _classify(demo_thesis, "Braxmoor Group", [license_attrs])
    assert fit.tier == "A" and fit.fit_score == 1.0
    tier = ledger.get(claims.fit_tier)
    assert "sector license" in tier.evidence and tier.confidence == "strong"


def test_naics_plus_service_keywords_gives_tier_a(demo_thesis: Thesis) -> None:
    fit, *_ = _classify(
        demo_thesis,
        "Braxmoor Group",
        [{"naics": "541350"}, {"services": ["fire safety inspections"]}],
    )
    assert fit.tier == "A"


def test_service_keywords_alone_give_tier_b(demo_thesis: Thesis) -> None:
    fit, *_ = _classify(
        demo_thesis, "Braxmoor Group", [{"services": ["fire alarm inspection", "alarm monitoring"]}]
    )
    assert fit.tier == "B"
    assert fit.segment == "alarm"
    assert fit.service_mix == "recurring_heavy"


def test_name_only_gives_tier_c(demo_thesis: Thesis) -> None:
    fit, *_ = _classify(demo_thesis, "Braxmoor Fire Protection", [{}])
    assert fit.tier == "C" and fit.fit_score == pytest.approx(0.4)


def test_adjacent_trade_gives_tier_d(demo_thesis: Thesis) -> None:
    fit, _, ledger = _classify(
        demo_thesis,
        "Braxmoor Mechanical",
        [{"naics": "238220"}, {"services": ["furnace repair", "air conditioning installation"]}],
    )
    assert fit.tier == "D" and fit.adjacent_trade
    assert ledger.last("C1", "adjacent_trade") is not None


def test_no_evidence_gives_tier_d(demo_thesis: Thesis) -> None:
    fit, *_ = _classify(demo_thesis, "Braxmoor Group", [{"naics": "561720"}])
    assert fit.tier == "D" and not fit.adjacent_trade


def test_residential_and_parent_flags(demo_thesis: Thesis) -> None:
    fit, *_ = _classify(
        demo_thesis,
        "Braxmoor Sprinkler",
        [
            {"services": ["residential fire sprinklers", "serving homeowners"]},
            {"parent_entity": "Parent Entity 01 (synthetic)"},
        ],
    )
    assert fit.residential_only and fit.parent_owned


@pytest.mark.parametrize(
    ("services", "mix"),
    [
        (
            ["fire sprinkler installation", "new construction", "design-build installation"],
            "install_heavy",
        ),
        (["sprinkler inspection", "annual testing", "scheduled maintenance"], "recurring_heavy"),
        (["sprinkler inspection", "fire sprinkler installation"], "mixed"),
        (["fire sprinklers"], "unknown"),
    ],
)
def test_service_mix(demo_thesis: Thesis, services: list[str], mix: str) -> None:
    fit, *_ = _classify(demo_thesis, "Braxmoor Group", [{"services": services}])
    assert fit.service_mix == mix


class FakeHook:
    """Stands in for a model call: returns a fixed verdict and records its inputs."""

    def __init__(self, verdict: Mapping[str, Any]) -> None:
        self.verdict = verdict
        self.calls: list[Mapping[str, Any]] = []

    def __call__(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append(payload)
        return {"in_sector": self.verdict}


def _hook_returning(verdict: Mapping[str, Any]) -> FakeHook:
    return FakeHook(verdict)


def test_hook_with_verified_quote_upgrades_unevidenced_company(demo_thesis: Thesis) -> None:
    hook = _hook_returning({"value": True, "evidence": "braxmoor fire"})
    fit, _, ledger = _classify(demo_thesis, "Braxmoor Fire", [{}], hook=hook)
    assert fit.tier == "B"
    model = ledger.last("C1", "model_in_sector")
    assert model is not None and model.confidence == "inferred"
    assert hook.calls and hook.calls[0]["company_id"] == "C1"


def test_hook_with_unverifiable_quote_is_recorded_but_ignored(demo_thesis: Thesis) -> None:
    hook = _hook_returning({"value": True, "evidence": "a quote that is not in the text"})
    fit, _, ledger = _classify(demo_thesis, "Braxmoor Fire", [{}], hook=hook)
    assert fit.tier == "D"
    model = ledger.last("C1", "model_in_sector")
    assert model is not None and model.confidence == "weak"


def test_hook_is_not_consulted_for_verified_companies(demo_thesis: Thesis) -> None:
    hook = _hook_returning({"value": False, "evidence": ""})
    _classify(demo_thesis, "Braxmoor Group", [{"license_type": "Fire Alarm Contractor"}], hook=hook)
    assert hook.calls == []


def test_malformed_hook_output_raises(demo_thesis: Thesis) -> None:
    with pytest.raises(HookError, match="must return"):
        _classify(demo_thesis, "Braxmoor Fire", [{}], hook=lambda payload: {"in_sector": "yes"})
    with pytest.raises(HookError, match="must return"):
        _classify(demo_thesis, "Braxmoor Fire", [{}], hook=lambda payload: "yes")


def test_hook_failures_keep_their_own_exception(demo_thesis: Thesis) -> None:
    def broken(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        raise RuntimeError("model unavailable")

    with pytest.raises(RuntimeError, match="model unavailable"):
        _classify(demo_thesis, "Braxmoor Fire", [{}], hook=broken)


def test_load_hook() -> None:
    assert callable(load_hook("math:sqrt"))
    with pytest.raises(HookError, match="look like"):
        load_hook("math.sqrt")
    with pytest.raises(HookError, match="cannot import"):
        load_hook("math:no_such_function")
    with pytest.raises(HookError, match="not callable"):
        load_hook("math:pi")


def test_hook_is_off_by_default(demo_thesis: Thesis) -> None:
    assert demo_thesis.classify.llm_hook_enabled is False
    with pytest.raises(ValueError, match="no llm_hook"):
        dataclasses.replace(demo_thesis.classify, llm_hook_enabled=True)

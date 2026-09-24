"""Presence lookups and the obviousness score."""

from __future__ import annotations

import pytest

from thesis_to_target.config import PresenceConfig, ResolveConfig
from thesis_to_target.evidence import EvidenceLedger
from thesis_to_target.models import Company
from thesis_to_target.normalize import name_variants
from thesis_to_target.presence import (
    Listing,
    ListingIndexChecker,
    assess_presence,
    obviousness_score,
)

LISTINGS = [
    Listing("DB-1", "Braxmoor Fire Prot., Inc.", "IL"),
    Listing("DB-2", "Quenholt Fire Alarm", "OH"),
    Listing("DB-3", "Pellstead Sprinkler", "IL"),
]


def _company(name: str, state: str, domain: str | None = None) -> Company:
    company = Company("C1", name, None, None, state, None, None, domain, ["R1"], ["web_listing"])
    company.name_variants = name_variants(name)
    return company


def test_listing_checker_matches_within_state_only(fire_cfg: ResolveConfig) -> None:
    checker = ListingIndexChecker("db", 0.5, LISTINGS, resolve_cfg=fire_cfg)
    hit = checker.lookup(_company("Braxmoor Fire Protection", "IL"))
    assert hit.found and hit.listing_id == "DB-1" and hit.score == 100
    assert not checker.lookup(_company("Quenholt Fire Alarm", "IL")).found
    miss = checker.lookup(_company("Veltmere Fire Protection", "IL"))
    assert not miss.found and miss.listing_id is None and miss.score < 90


def test_obviousness_score() -> None:
    weights = {"a": 0.35, "b": 0.30, "c": 0.25}
    assert obviousness_score({"a": False, "b": False, "c": False}, weights, False, 0.10) == 0.0
    assert obviousness_score(
        {"a": True, "b": True, "c": True}, weights, True, 0.10
    ) == pytest.approx(1.0)
    assert obviousness_score(
        {"a": True, "b": False, "c": False}, weights, False, 0.10
    ) == pytest.approx(0.35)
    assert obviousness_score({}, {}, False, 0.0) == 0.0


def test_assess_presence_records_claims_and_flags(fire_cfg: ResolveConfig) -> None:
    ledger = EvidenceLedger()
    anchor = ledger.observed(
        "C1",
        "entity_resolution",
        "1",
        evidence="e",
        source="s",
        record_ids=["R1"],
        confidence="strong",
    )
    checkers = [
        ListingIndexChecker("db_a", 0.35, LISTINGS, resolve_cfg=fire_cfg),
        ListingIndexChecker("db_b", 0.30, [], resolve_cfg=fire_cfg),
    ]
    hidden = assess_presence(
        _company("Veltmere Fire Protection", "IL"),
        checkers,
        PresenceConfig(),
        ledger,
        website_claim=None,
        anchor_claim=anchor,
    )
    assert hidden.non_obvious and hidden.obviousness == 0.0
    assert ledger.last("C1", "presence:db_a") is not None
    listed = assess_presence(
        _company("Braxmoor Fire Protection", "IL", "braxmoorfire.example"),
        checkers,
        PresenceConfig(),
        ledger,
        website_claim=anchor,
        anchor_claim=anchor,
    )
    assert not listed.non_obvious and listed.found == {"db_a": True, "db_b": False}
    assert listed.obviousness == pytest.approx((0.35 + 0.10) / 0.75)
    found = [c for c in ledger if c.claim == "presence:db_a" and c.value == "found"]
    assert found and found[0].confidence == "confirmed" and found[0].external_ref == "DB-1"

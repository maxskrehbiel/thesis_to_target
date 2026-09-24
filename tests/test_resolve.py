"""Entity resolution: pair scoring, blocking, clustering, adjudication and canonical records."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from thesis_to_target.config import ResolveConfig
from thesis_to_target.errors import ConfigError
from thesis_to_target.models import RawRecord
from thesis_to_target.resolve import (
    UnionFind,
    block_keys,
    name_similarity,
    prepare_record,
    resolve,
    score_pair,
)

RecordFactory = Callable[..., RawRecord]
TRUST = {
    "business_registry": 0.9,
    "state_license": 0.85,
    "trade_association": 0.7,
    "web_listing": 0.6,
}


def test_name_similarity_ignores_shared_industry_words(fire_cfg: ResolveConfig) -> None:
    generic = fire_cfg.generic_tokens
    assert name_similarity("braxmoor fire protection", "braxmoor fire protection", generic) == 100
    assert name_similarity("braxmoor fire protection", "quenholt fire protection", generic) < 60
    assert name_similarity("brxamoor fire protection", "braxmoor fire protection", generic) > 92
    assert name_similarity("", "braxmoor", generic) == 0


def test_industry_words_only_count_as_generic_when_the_thesis_says_so(
    fire_cfg: ResolveConfig,
) -> None:
    pair = ("braxmoor fire protection", "quenholt fire protection")
    assert name_similarity(*pair) > name_similarity(*pair, fire_cfg.generic_tokens)


def _decide(
    make_record: RecordFactory, cfg: ResolveConfig, a: dict[str, Any], b: dict[str, Any]
) -> str:
    ra, rb = make_record("A-1", **a), make_record("B-1", **b)
    return score_pair(prepare_record(ra, cfg), prepare_record(rb, cfg), cfg).decision


def test_score_pair_decisions(make_record: RecordFactory, fire_cfg: ResolveConfig) -> None:
    full = {"name": "Braxmoor Fire Protection"}
    phone = {"phone": "217-555-0142"}
    assert (
        _decide(make_record, fire_cfg, {"name": "BRAXMOOR FIRE PROTECTION, INC."}, full) == "merge"
    )
    assert _decide(make_record, fire_cfg, {"name": "Braxmoor Fire"}, full) == "review"
    assert (
        _decide(make_record, fire_cfg, {"name": "Braxmoor Fire", **phone}, {**full, **phone})
        == "merge"
    )
    assert _decide(make_record, fire_cfg, {**full, "state": "OH"}, full) == "review"
    shared_line = {"name": "Quenholt Extinguisher Service", **phone}
    assert _decide(make_record, fire_cfg, shared_line, {**full, **phone}) == "reject"


def test_score_pair_orders_ids_and_explains_itself(
    make_record: RecordFactory, fire_cfg: ResolveConfig
) -> None:
    ra = make_record(
        "Z-9", "Braxmoor Fire", website="https://www.braxmoorfire.example/", zip="61204"
    )
    rb = make_record(
        "A-1", "Braxmoor Fire Protection", website="braxmoorfire.example", zip="61204-0001"
    )
    ps = score_pair(prepare_record(ra, fire_cfg), prepare_record(rb, fire_cfg), fire_cfg)
    assert (ps.a, ps.b) == ("A-1", "Z-9")
    assert ps.reasons == ["name 85", "same website", "same ZIP"]
    assert ps.decision == "merge"


def test_block_keys_cover_contacts_names_and_prefixes(
    make_record: RecordFactory, fire_cfg: ResolveConfig
) -> None:
    record = make_record(
        "A-1", "Braxmoor Fire", phone="217-555-0142", website="braxmoor.example", zip="61204"
    )
    keys = block_keys(prepare_record(record, fire_cfg), fire_cfg)
    assert keys == [
        "phone:2175550142",
        "web:braxmoor.example",
        "zip:61204",
        "full:braxmoor fire",
        "tok:IL:braxmoor",
        "pre:IL:bra",
    ]


@pytest.fixture
def messy(make_record: RecordFactory) -> list[RawRecord]:
    return [
        # Braxmoor: registry name, license roll and a web listing with a typo and the same phone.
        make_record("REG-1", "BRAXMOOR FIRE PROTECTION, INC.", "business_registry", zip="61204"),
        make_record("LIC-1", "Braxmoor Fire Prot.", "state_license", phone="217-555-0142"),
        make_record(
            "WEB-1",
            "Braxmoor Fire Protecton",
            phone="(217) 555-0142",
            website="braxmoorfire.example",
        ),
        # Quenholt: holding-company registry name with the operating name as a DBA.
        make_record(
            "REG-2", "Ostrvane Holdings, LLC", "business_registry", dba="Quenholt Fire Alarm"
        ),
        make_record("WEB-2", "Quenholt Fire Alarm", phone="309-555-0101"),
        # Look-alikes that must stay apart.
        make_record("WEB-3", "Braxmoor Mechanical", phone="217-555-0199", zip="61204"),
        make_record("REG-3", "Braxmoor Fire Protection Inc", "business_registry", state="OH"),
        make_record("WEB-4", "Pellstead Extinguisher Service", phone="309-555-0101"),
        # A truncated name with no shared contact detail: goes to review, not merged.
        make_record("REG-4", "Veltmere Fire Sprinkler LLC", "business_registry"),
        make_record("WEB-5", "Veltmere Fire"),
    ]


def _clusters(records: list[RawRecord], cfg: ResolveConfig, **kwargs: Any) -> set[frozenset[str]]:
    return {frozenset(c.member_ids) for c in resolve(records, cfg, TRUST, **kwargs).companies}


def test_resolve_builds_expected_clusters(messy: list[RawRecord], fire_cfg: ResolveConfig) -> None:
    assert _clusters(messy, fire_cfg) == {
        frozenset({"REG-1", "LIC-1", "WEB-1"}),
        frozenset({"REG-2", "WEB-2"}),
        frozenset({"WEB-3"}),
        frozenset({"REG-3"}),
        frozenset({"WEB-4"}),
        frozenset({"REG-4"}),
        frozenset({"WEB-5"}),
    }


def test_resolve_review_queue_and_record_coverage(
    messy: list[RawRecord], fire_cfg: ResolveConfig
) -> None:
    result = resolve(messy, fire_cfg, TRUST)
    queued = {(p.a, p.b) for p in result.review_queue}
    assert ("REG-1", "REG-3") in queued  # same name, different state
    assert ("REG-4", "WEB-5") in queued  # truncated name, nothing else shared
    members = sorted(m for c in result.companies for m in c.member_ids)
    assert members == sorted(r.record_id for r in messy)
    assert set(result.record_to_company) == {r.record_id for r in messy}


def test_canonical_record_prefers_trusted_operating_name(
    messy: list[RawRecord], fire_cfg: ResolveConfig
) -> None:
    by_member = {m: c for c in resolve(messy, fire_cfg, TRUST).companies for m in c.member_ids}
    brax = by_member["REG-1"]
    assert brax.name == "Braxmoor Fire Protection"
    assert brax.legal_name == "Braxmoor Fire Protection, Inc."
    assert brax.phone == "2175550142" and brax.domain == "braxmoorfire.example"
    assert brax.sources == ["business_registry", "state_license", "web_listing"]
    quen = by_member["REG-2"]
    assert quen.name == "Quenholt Fire Alarm"
    assert quen.legal_name == "Ostrvane Holdings, LLC"


def test_company_ids_do_not_depend_on_input_order(
    messy: list[RawRecord], fire_cfg: ResolveConfig
) -> None:
    first = resolve(messy, fire_cfg, TRUST)
    second = resolve(list(reversed(messy)), fire_cfg, TRUST)
    assert [(c.company_id, c.member_ids) for c in first.companies] == [
        (c.company_id, c.member_ids) for c in second.companies
    ]


def test_adjudications_override_automatic_decisions(
    messy: list[RawRecord], fire_cfg: ResolveConfig
) -> None:
    merged = _clusters(messy, fire_cfg, adjudications={("WEB-5", "REG-4"): "merge"})
    assert frozenset({"REG-4", "WEB-5"}) in merged
    rejected = {
        ("REG-1", "LIC-1"): "reject",
        ("LIC-1", "WEB-1"): "reject",
        ("REG-1", "WEB-1"): "reject",
    }
    split = _clusters(messy, fire_cfg, adjudications=rejected)
    assert {frozenset({"REG-1"}), frozenset({"LIC-1"}), frozenset({"WEB-1"})} <= split


def test_chained_cluster_is_flagged_for_low_cohesion(
    make_record: RecordFactory, fire_cfg: ResolveConfig
) -> None:
    records = [
        make_record(
            "REG-1", "Ostrvane Holdings LLC dba Braxmoor Fire Protection", "business_registry"
        ),
        make_record("WEB-1", "Ostrvane Holdings"),
        make_record("WEB-2", "Braxmoor Fire Protection"),
    ]
    (company,) = resolve(records, fire_cfg, TRUST).companies
    assert company.flags and company.flags[0].startswith("low_cohesion")


def test_duplicate_record_ids_are_rejected(make_record: RecordFactory) -> None:
    with pytest.raises(ConfigError, match="unique"):
        resolve([make_record("A", "Braxmoor"), make_record("A", "Quenholt")])


def test_oversized_blocks_are_skipped(make_record: RecordFactory) -> None:
    records = [make_record(f"W-{i}", f"Firm{i} Alarm", phone="217-555-0100") for i in range(4)]
    result = resolve(records, ResolveConfig(max_block_size=3))
    assert not any("same phone" in p.reasons for p in result.pair_scores)


def test_union_find_groups() -> None:
    uf = UnionFind(["c", "b", "a", "d"])
    uf.union("c", "b")
    uf.union("b", "a")
    assert uf.find("c") == "a"
    assert sorted(uf.groups()) == [["a", "b", "c"], ["d"]]

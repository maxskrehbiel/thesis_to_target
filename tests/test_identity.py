"""Identity claims: name, location, merge trail, legal name and website."""

from __future__ import annotations

from thesis_to_target.config import ResolveConfig
from thesis_to_target.evidence import EvidenceLedger
from thesis_to_target.identity import record_identity_claims
from thesis_to_target.models import Company, RawRecord
from thesis_to_target.resolve import resolve


def test_identity_claims_cite_member_records(fire_cfg: ResolveConfig) -> None:
    records = [
        RawRecord(
            "REG-1",
            "business_registry",
            "BRAXMOOR FIRE PROTECTION, INC.",
            state="IL",
            city="ASHDALE",
        ),
        RawRecord(
            "WEB-1",
            "web_listing",
            "Braxmoor Fire Protection",
            state="IL",
            website="braxmoor.example",
        ),
    ]
    result = resolve(records, fire_cfg, {"business_registry": 0.9, "web_listing": 0.6})
    (company,) = result.companies
    ledger = EvidenceLedger()
    ids = record_identity_claims(
        company, records, result.merge_edges[company.company_id], ledger, fire_cfg
    )
    name = ledger.get(ids.name)
    assert name.value == "Braxmoor Fire Protection" and name.confidence == "confirmed"
    assert "spelled 'Braxmoor Fire Protection' in WEB-1" in name.evidence
    assert ledger.get(ids.location).value == "Ashdale, IL"
    assert ledger.get(ids.resolution).evidence.startswith("merged pairs: REG-1~WEB-1")
    assert ids.legal_name is not None and ledger.get(ids.legal_name).record_ids == ("REG-1",)
    assert ids.website is not None and ledger.get(ids.website).record_ids == ("WEB-1",)


def test_identity_claims_without_state_legal_name_or_website() -> None:
    record = RawRecord("WEB-9", "web_listing", "Veltmere Fire", state=None)
    company = Company(
        "C0001", "Veltmere Fire", None, None, None, None, None, None, ["WEB-9"], ["web_listing"]
    )
    ledger = EvidenceLedger()
    ids = record_identity_claims(company, [record], [], ledger, ResolveConfig())
    assert (
        ledger.get(ids.location).value == "unknown"
        and ledger.get(ids.location).confidence == "weak"
    )
    assert "no other record scored" in ledger.get(ids.resolution).evidence
    assert ids.legal_name is None and ids.website is None


def test_long_merge_trails_are_summarized(fire_cfg: ResolveConfig) -> None:
    records = [
        RawRecord(
            f"WEB-{i}", "web_listing", "Braxmoor Fire Protection", state="IL", phone="217-555-0142"
        )
        for i in range(5)
    ]
    result = resolve(records, fire_cfg)
    (company,) = result.companies
    ledger = EvidenceLedger()
    ids = record_identity_claims(
        company, records, result.merge_edges[company.company_id], ledger, fire_cfg
    )
    assert "+5 more" in ledger.get(ids.resolution).evidence  # 10 merged pairs, 5 shown

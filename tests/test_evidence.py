"""Evidence-ledger rules: each write-time rule and each verify-time rule has its own test."""

from __future__ import annotations

import pytest

from thesis_to_target.errors import LedgerError
from thesis_to_target.evidence import EvidenceLedger, render_value
from thesis_to_target.models import Company, RawRecord
from thesis_to_target.pipeline import RunResult, required_claims


def _company(cid: str, members: list[str]) -> Company:
    return Company(
        cid, "Braxmoor Fire", None, None, "IL", None, None, None, members, ["web_listing"]
    )


COMPANIES = {"C1": _company("C1", ["R1", "R2"]), "C2": _company("C2", ["R3"])}
RECORDS = {rid: RawRecord(rid, "web_listing", "x") for rid in ("R1", "R2", "R3")}


def _observed(
    ledger: EvidenceLedger, cid: str = "C1", rid: str = "R1", confidence: str = "strong"
) -> str:
    return ledger.observed(
        cid, "name", "x", evidence="e", source="s", record_ids=[rid], confidence=confidence
    )


def test_claim_ids_are_sequential_per_company() -> None:
    ledger = EvidenceLedger()
    a = _observed(ledger)
    b = _observed(ledger, "C2", "R3")
    c = ledger.derived("C1", "fit_tier", "A", evidence="e", depends_on=[a], confidence="inferred")
    assert (a, b, c) == ("C1.01", "C2.01", "C1.02")
    assert [x.claim_id for x in ledger] == ["C1.01", "C2.01", "C1.02"] and len(ledger) == 3
    assert [x.claim_id for x in ledger.for_company("C1")] == ["C1.01", "C1.02"]
    last = ledger.last("C1", "fit_tier")
    assert last is not None and last.claim_id == "C1.02"
    assert ledger.last("C1", "nothing") is None and ledger.for_company("C9") == []


def test_rule_confidence_must_be_a_known_level() -> None:
    with pytest.raises(LedgerError, match="unknown confidence"):
        _observed(EvidenceLedger(), confidence="certain")


def test_rule_evidence_text_is_required() -> None:
    with pytest.raises(LedgerError, match="no evidence"):
        EvidenceLedger().observed(
            "C1", "name", "x", evidence="  ", source="s", record_ids=["R1"], confidence="strong"
        )


def test_rule_observed_claims_cite_a_record() -> None:
    with pytest.raises(LedgerError, match="cites no source record"):
        EvidenceLedger().observed(
            "C1", "name", "x", evidence="e", source="s", record_ids=[], confidence="strong"
        )


def test_rule_external_claims_cite_a_reference() -> None:
    with pytest.raises(LedgerError, match="no reference"):
        EvidenceLedger().external(
            "C1",
            "presence:db",
            "found",
            evidence="e",
            source="db",
            external_ref="",
            confidence="strong",
        )


def test_rule_derived_claims_cite_inputs() -> None:
    with pytest.raises(LedgerError, match="cites no input"):
        EvidenceLedger().derived(
            "C1", "fit_tier", "A", evidence="e", depends_on=[], confidence="weak"
        )


def test_rule_derived_inputs_must_already_exist() -> None:
    with pytest.raises(LedgerError, match="unknown claim"):
        EvidenceLedger().derived(
            "C1", "fit_tier", "A", evidence="e", depends_on=["C1.07"], confidence="weak"
        )


def test_rule_derived_inputs_must_be_about_the_same_company() -> None:
    ledger = EvidenceLedger()
    other = _observed(ledger, "C2", "R3")
    with pytest.raises(LedgerError, match="of another company"):
        ledger.derived("C1", "fit_tier", "A", evidence="e", depends_on=[other], confidence="weak")


def test_rule_derived_claims_are_no_stronger_than_their_best_input() -> None:
    ledger = EvidenceLedger()
    weak = _observed(ledger, confidence="weak")
    with pytest.raises(LedgerError, match="stronger than any input"):
        ledger.derived(
            "C1", "fit_tier", "A", evidence="e", depends_on=[weak], confidence="inferred"
        )
    clash = _observed(ledger, confidence="contradictory")
    with pytest.raises(LedgerError, match="stronger than any input"):
        ledger.derived("C1", "size", 1, evidence="e", depends_on=[clash], confidence="inferred")
    assert ledger.derived("C1", "size", 1, evidence="e", depends_on=[clash], confidence="weak")


def test_sound_ledger_verifies() -> None:
    ledger = EvidenceLedger()
    name = ledger.observed(
        "C1", "name", "x", evidence="e", source="s", record_ids=["R1", "R2"], confidence="confirmed"
    )
    look = ledger.external(
        "C1",
        "presence:db",
        "not found",
        evidence="e",
        source="db",
        external_ref="q",
        confidence="inferred",
    )
    ledger.derived(
        "C1", "obviousness", 0.0, evidence="e", depends_on=[name, look], confidence="inferred"
    )
    assert ledger.verify(COMPANIES, RECORDS, {"C1": ["name", "obviousness"]}) == []


def test_verify_claims_must_be_about_an_existing_company() -> None:
    ledger = EvidenceLedger()
    _observed(ledger, "C9")
    assert ledger.verify(COMPANIES, RECORDS) == [
        "C9: 1 claim(s) about a company that does not exist"
    ]


def test_verify_cited_records_must_exist() -> None:
    ledger = EvidenceLedger()
    _observed(ledger, "C1", "R7")
    assert ledger.verify(COMPANIES, RECORDS) == ["C1.01: cites unknown record R7"]


def test_verify_cited_records_must_belong_to_the_company() -> None:
    ledger = EvidenceLedger()
    _observed(ledger, "C1", "R3")
    assert ledger.verify(COMPANIES, RECORDS) == ["C1.01: cites record R3 of another company"]


def test_verify_exported_companies_carry_their_required_claims() -> None:
    ledger = EvidenceLedger()
    _observed(ledger)
    problems = ledger.verify(COMPANIES, RECORDS, {"C1": ["name", "fit_tier"], "C2": ["name"]})
    assert problems == [
        "C1: exported without ledger backing for ['fit_tier']",
        "C2: exported without ledger backing for ['name']",
    ]


def test_render_value() -> None:
    assert render_value(None) == ""
    assert render_value(True) == "yes"
    assert render_value(0.123456) == "0.1235"
    assert render_value(1234567.0) == "1,234,567"
    assert render_value(["a", 2]) == "a; 2"
    assert render_value({"k": False}) == "k=no"


def test_demo_ledger_is_complete_and_traceable(demo_run: RunResult) -> None:
    ledger, records = demo_run.ledger, {r.record_id: r for r in demo_run.records}
    companies = {c.company_id: c for c in demo_run.companies}
    assert (
        ledger.verify(
            companies, records, {c.company_id: required_claims(c) for c in demo_run.companies}
        )
        == []
    )
    for claim in ledger:
        if claim.kind == "observed":
            assert set(claim.record_ids) <= set(companies[claim.company_id].member_ids)
    rows = ledger.rows({c.company_id: c.name for c in demo_run.companies})
    assert len(rows) == len(ledger) and rows[0]["company"]

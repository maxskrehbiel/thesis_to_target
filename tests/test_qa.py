"""Grading against ground truth and the demo's pass marks."""

from __future__ import annotations

import dataclasses

import pytest

from thesis_to_target.models import Company, EbitdaEstimate, PresenceResult
from thesis_to_target.qa import EntityTruth, QaThresholds, check_report, pairwise_metrics, qa_report


def test_pairwise_metrics() -> None:
    truth = {"r1": "F1", "r2": "F1", "r3": "F2"}
    perfect = pairwise_metrics({"r1": "C1", "r2": "C1", "r3": "C2"}, truth)
    assert (perfect.precision, perfect.recall, perfect.f1) == (1.0, 1.0, 1.0)
    assert (perfect.records, perfect.true_entities, perfect.resolved_entities) == (3, 2, 2)
    lumped = pairwise_metrics({"r1": "C1", "r2": "C1", "r3": "C1"}, truth)
    assert lumped.precision == pytest.approx(1 / 3, abs=1e-4) and lumped.recall == 1.0
    split = pairwise_metrics({"r1": "C1", "r2": "C2", "r3": "C3"}, truth)
    assert split.recall == 0.0 and split.f1 == 0.0


def _company(
    cid: str, members: list[str], p_in_band: float, lo: float, hi: float, found: bool
) -> Company:
    company = Company(cid, cid, None, None, "IL", None, None, None, members, ["web_listing"])
    company.estimate = EbitdaEstimate(
        10, 20, 14, 2e6, 1e6, lo, hi, 13.8, 0.3, p_in_band, p_in_band, "medium", 1
    )
    company.presence = PresenceResult({"db": found}, False, 0.0, True)
    return company


def test_qa_report_grades_each_company_against_its_owner() -> None:
    companies = [
        _company("C1", ["r1", "r2"], 0.9, 1.0e6, 3.0e6, found=True),
        _company("C2", ["r3"], 0.2, 0.2e6, 0.8e6, found=False),
    ]
    truth = {"r1": "F1", "r2": "F1", "r3": "F2"}
    facts = {"F1": EntityTruth(2.0e6, {"db": True}), "F2": EntityTruth(0.9e6, {"db": True})}
    report = qa_report(companies, {"r1": "C1", "r2": "C1", "r3": "C2"}, truth, facts, (1e6, 5e6))
    assert report.ebitda_graded == 2
    assert report.interval_coverage == 0.5  # F2's true 0.9M lies outside C2's 0.2M-0.8M range
    assert report.mean_p_in_band == 0.55 and report.share_in_band == 0.5
    assert report.brier_score == pytest.approx(((0.9 - 1) ** 2 + 0.2**2) / 2, abs=1e-3)
    assert (report.presence_checked, report.presence_agreement) == (2, 0.5)


def test_qa_report_skips_companies_without_known_facts() -> None:
    companies = [_company("C1", ["r1"], 0.9, 1e6, 3e6, found=True)]
    report = qa_report(companies, {"r1": "C1"}, {"r1": "F1"}, {}, (1e6, 5e6))
    assert (
        report.ebitda_graded == 0
        and report.interval_coverage is None
        and report.presence_agreement is None
    )


def test_check_report_pass_and_fail() -> None:
    companies = [_company("C1", ["r1", "r2"], 0.9, 1.0e6, 3.0e6, found=True)]
    truth, facts = {"r1": "F1", "r2": "F1"}, {"F1": EntityTruth(2.0e6, {"db": True})}
    good = qa_report(companies, {"r1": "C1", "r2": "C1"}, truth, facts, (1e6, 5e6))
    checks = check_report(good)
    assert [c.name for c in checks] == [
        "resolution precision",
        "resolution recall",
        "EBITDA 95% range coverage",
        "P(in band) calibration gap",
        "presence agreement",
    ]
    assert all(c.passed for c in checks)
    strict = check_report(good, QaThresholds(max_calibration_gap=0.05))
    assert [c.name for c in strict if not c.passed] == ["P(in band) calibration gap"]
    empty = dataclasses.replace(good, interval_coverage=None, mean_p_in_band=None)
    failed = {c.name for c in check_report(empty) if not c.passed}
    assert failed == {"EBITDA 95% range coverage", "P(in band) calibration gap"}

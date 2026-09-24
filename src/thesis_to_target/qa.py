"""Grading a run against labeled ground truth: resolution, EBITDA calibration and presence."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .models import Company


@dataclass(frozen=True)
class EntityTruth:
    """Known facts about one true entity, for grading.

    Attributes:
        ebitda: True annual EBITDA, USD.
        listed_in: Database name -> whether the entity is truly listed there.
    """

    ebitda: float
    listed_in: Mapping[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolutionMetrics:
    """Pairwise agreement between a clustering and the true entities.

    Attributes:
        records: Records graded.
        true_entities: Distinct true entities among them.
        resolved_entities: Distinct predicted companies among them.
        precision: Share of predicted same-company pairs that are truly the same.
        recall: Share of truly-same pairs that were predicted as the same company.
        f1: Harmonic mean of precision and recall.
    """

    records: int
    true_entities: int
    resolved_entities: int
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True)
class QaReport:
    """Grades of a run against ground truth.

    Attributes:
        resolution: Pairwise entity-resolution metrics.
        ebitda_graded: In-scope companies with an estimate that were graded.
        interval_coverage: Share whose true EBITDA lies inside the reported 95% range.
        mean_p_in_band: Mean predicted P(EBITDA in band).
        share_in_band: Share whose true EBITDA is in the band.
        brier_score: Mean squared error of P(in band) against the true outcome.
        presence_checked: Presence flags graded.
        presence_agreement: Share of presence flags that match the truth.
    """

    resolution: ResolutionMetrics
    ebitda_graded: int
    interval_coverage: float | None
    mean_p_in_band: float | None
    share_in_band: float | None
    brier_score: float | None
    presence_checked: int
    presence_agreement: float | None


def _same_pairs(ids: Sequence[str], labels: Mapping[str, str]) -> set[tuple[str, str]]:
    groups: dict[str, list[str]] = {}
    for rid in ids:
        groups.setdefault(labels[rid], []).append(rid)
    return {
        (m[i], m[j]) for m in groups.values() for i in range(len(m)) for j in range(i + 1, len(m))
    }


def pairwise_metrics(
    record_to_company: Mapping[str, str], truth: Mapping[str, str]
) -> ResolutionMetrics:
    """Grade a clustering against known true entity ids.

    Args:
        record_to_company: Predicted record id -> company id.
        truth: Record id -> true entity id.

    Returns:
        Record and entity counts plus pairwise precision, recall and F1.
    """
    ids = sorted(set(record_to_company) & set(truth))
    predicted, actual = _same_pairs(ids, record_to_company), _same_pairs(ids, truth)
    hits = len(predicted & actual)
    precision = hits / len(predicted) if predicted else 1.0
    recall = hits / len(actual) if actual else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return ResolutionMetrics(
        records=len(ids),
        true_entities=len({truth[r] for r in ids}),
        resolved_entities=len({record_to_company[r] for r in ids}),
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
    )


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def qa_report(
    companies: Sequence[Company],
    record_to_company: Mapping[str, str],
    truth: Mapping[str, str],
    entity_truth: Mapping[str, EntityTruth],
    band: tuple[float, float],
) -> QaReport:
    """Grade a finished run against ground truth.

    Each company is graded against the true entity that owns most of its records.

    Args:
        companies: Resolved companies with stage results attached.
        record_to_company: Record id -> company id.
        truth: Record id -> true entity id.
        entity_truth: True entity id -> known facts.
        band: ``(minimum, maximum)`` EBITDA of the thesis.

    Returns:
        Resolution, EBITDA-calibration and presence-accuracy grades.
    """
    coverage: list[float] = []
    predicted: list[float] = []
    actual: list[float] = []
    agreement: list[float] = []
    for company in companies:
        owner = Counter(truth[r] for r in company.member_ids if r in truth).most_common(1)
        facts = entity_truth.get(owner[0][0]) if owner else None
        if facts is None:
            continue
        if company.presence:
            agreement.extend(
                float(found == facts.listed_in.get(db, False))
                for db, found in company.presence.found.items()
            )
        est = company.estimate
        if est is None or not company.in_scope:
            continue
        coverage.append(float(est.ebitda_lo <= facts.ebitda <= est.ebitda_hi))
        predicted.append(est.p_in_band)
        actual.append(float(band[0] <= facts.ebitda <= band[1]))
    brier = [(p - a) ** 2 for p, a in zip(predicted, actual, strict=True)]
    return QaReport(
        resolution=pairwise_metrics(record_to_company, truth),
        ebitda_graded=len(coverage),
        interval_coverage=_mean(coverage),
        mean_p_in_band=_mean(predicted),
        share_in_band=_mean(actual),
        brier_score=_mean(brier),
        presence_checked=len(agreement),
        presence_agreement=_mean(agreement),
    )


@dataclass(frozen=True)
class QaThresholds:
    """Pass marks the demo holds its own output to (synthetic ground truth only).

    Attributes:
        min_precision: Lowest acceptable pairwise resolution precision.
        min_recall: Lowest acceptable pairwise resolution recall.
        min_interval_coverage: Lowest acceptable share of true EBITDA inside the 95% range.
        max_calibration_gap: Largest acceptable gap between mean P(in band) and the
            observed share in band.
        min_presence_agreement: Lowest acceptable share of correct presence flags.
    """

    min_precision: float = 0.95
    min_recall: float = 0.90
    min_interval_coverage: float = 0.80
    max_calibration_gap: float = 0.15
    min_presence_agreement: float = 0.90


@dataclass(frozen=True)
class CheckResult:
    """One pass/fail check of a run against ground truth.

    Attributes:
        name: What was checked.
        value: Measured value, or ``None`` when nothing could be graded.
        requirement: The pass mark, in words.
        passed: Whether the value meets the pass mark.
    """

    name: str
    value: float | None
    requirement: str
    passed: bool


def _at_least(name: str, value: float | None, floor: float) -> CheckResult:
    return CheckResult(name, value, f">= {floor:.2f}", value is not None and value >= floor)


def check_report(report: QaReport, thresholds: QaThresholds | None = None) -> list[CheckResult]:
    """Compare a QA report with the pass marks.

    Args:
        report: Grades of a run.
        thresholds: Pass marks; defaults to :class:`QaThresholds`.

    Returns:
        One result per check, in a fixed order.
    """
    t = thresholds or QaThresholds()
    gap = None
    if report.mean_p_in_band is not None and report.share_in_band is not None:
        gap = round(abs(report.mean_p_in_band - report.share_in_band), 3)
    return [
        _at_least("resolution precision", report.resolution.precision, t.min_precision),
        _at_least("resolution recall", report.resolution.recall, t.min_recall),
        _at_least("EBITDA 95% range coverage", report.interval_coverage, t.min_interval_coverage),
        CheckResult(
            "P(in band) calibration gap",
            gap,
            f"<= {t.max_calibration_gap:.2f}",
            gap is not None and gap <= t.max_calibration_gap,
        ),
        _at_least("presence agreement", report.presence_agreement, t.min_presence_agreement),
    ]

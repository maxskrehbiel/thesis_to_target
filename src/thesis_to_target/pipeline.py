"""Runs every stage in order over injected sources and collects what exporters need."""

from __future__ import annotations

import csv
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .classify import ClassifierHook, classify_company, load_hook
from .errors import ConfigError, LedgerError
from .estimate import estimate_company
from .evidence import EvidenceLedger
from .identity import record_identity_claims
from .models import Company, RawRecord
from .presence import PresenceChecker, assess_presence
from .qa import EntityTruth, QaReport, qa_report
from .rank import rank_companies, screen_company
from .resolve import PairScore, ResolveResult, resolve
from .sources import SourceAdapter
from .thesis import Thesis

logger = logging.getLogger(__name__)

#: P(EBITDA in band) at or above which the funnel counts a company as "likely in band".
LIKELY_IN_BAND = 0.5
# Ledger violations shown in the error message before it is truncated.
_PROBLEMS_SHOWN = 20
# fmt: off
_ALWAYS_REQUIRED = (
    "name", "location", "entity_resolution", "fit_tier", "segment", "service_mix",
    "ebitda_estimate", "obviousness", "screen",
)
# fmt: on
_SIZED_REQUIRED = ("employees_range", "p_ebitda_ge_min", "p_ebitda_in_band")


@dataclass(frozen=True)
class Funnel:
    """Counts at each step from raw records to Priority targets.

    Attributes:
        records_by_feed: Feed name -> records pulled.
        raw_records: Records pulled from all feeds.
        companies: Companies after entity resolution.
        review_pairs: Record pairs left for human review.
        in_geography: Companies located in the thesis states.
        in_sector: Companies in the thesis states with any sector evidence (fit tier A to C).
        in_scope: Companies passing every screen.
        sized: In-scope companies with at least one size signal.
        likely_in_band: In-scope companies with P(EBITDA in band) >= 0.5.
        non_obvious: In-scope companies flagged non-obvious.
        priority: Companies in the Priority tier.
    """

    records_by_feed: Mapping[str, int]
    raw_records: int
    companies: int
    review_pairs: int
    in_geography: int
    in_sector: int
    in_scope: int
    sized: int
    likely_in_band: int
    non_obvious: int
    priority: int


@dataclass(frozen=True)
class RunResult:
    """Everything one pipeline run produced.

    Attributes:
        thesis: The thesis that was run.
        records: Every raw record pulled.
        companies: Resolved companies with stage results attached.
        ledger: The evidence ledger.
        review_queue: Record pairs left for human review.
        funnel: Stage counts.
        qa: Grades against ground truth, when every source supplies it.
        synthetic: True when every source serves generated data; drives output labels.
    """

    thesis: Thesis
    records: list[RawRecord]
    companies: list[Company]
    ledger: EvidenceLedger
    review_queue: list[PairScore]
    funnel: Funnel
    qa: QaReport | None
    synthetic: bool

    def ranked(self) -> list[Company]:
        """In-scope companies in rank order."""
        return sorted((c for c in self.companies if c.rank is not None), key=lambda c: c.rank or 0)


def required_claims(company: Company) -> list[str]:
    """Claim names that must exist for a company before its row can be exported."""
    needed = list(_ALWAYS_REQUIRED)
    if company.estimate is not None:
        needed += _SIZED_REQUIRED
    if company.rank is not None:
        needed.append("composite_score")
    return needed


def load_adjudications(path: str | Path) -> dict[tuple[str, str], str]:
    """Read human review decisions from a review-queue CSV.

    Args:
        path: CSV with ``record_a``, ``record_b`` and ``decision`` columns;
            rows whose decision is not ``merge`` or ``reject`` are ignored.

    Returns:
        ``(record_a, record_b) -> decision``.

    Raises:
        ConfigError: If the file is missing or lacks the required columns.
    """
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"adjudications file not found: {path}")
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    try:
        return {
            (row["record_a"], row["record_b"]): row["decision"].strip().lower()
            for row in rows
            if (row["decision"] or "").strip().lower() in ("merge", "reject")
        }
    except KeyError as exc:
        raise ConfigError(
            f"adjudications file needs columns record_a, record_b, decision; missing {exc}"
        ) from exc


def _funnel(
    records_by_feed: Mapping[str, int], resolution: ResolveResult, thesis: Thesis
) -> Funnel:
    companies = resolution.companies
    in_geo = [c for c in companies if c.state in thesis.states]
    scoped = [c for c in companies if c.in_scope]
    return Funnel(
        records_by_feed=dict(records_by_feed),
        raw_records=sum(records_by_feed.values()),
        companies=len(companies),
        review_pairs=len(resolution.review_queue),
        in_geography=len(in_geo),
        in_sector=sum(1 for c in in_geo if c.fit and c.fit.tier != "D"),
        in_scope=len(scoped),
        sized=sum(1 for c in scoped if c.estimate),
        likely_in_band=sum(
            1 for c in scoped if c.estimate and c.estimate.p_in_band >= LIKELY_IN_BAND
        ),
        non_obvious=sum(1 for c in scoped if c.presence and c.presence.non_obvious),
        priority=sum(1 for c in companies if c.tier == "Priority"),
    )


def _fetch(
    thesis: Thesis, sources: Sequence[SourceAdapter]
) -> tuple[list[RawRecord], dict[str, int]]:
    records: list[RawRecord] = []
    records_by_feed: dict[str, int] = {}
    for source in sources:
        fetched = source.fetch(thesis)
        records_by_feed[source.feed] = len(fetched)
        records.extend(fetched)
        logger.info("fetched %d records from %s", len(fetched), source.feed)
    return records, records_by_feed


def _grade(
    sources: Sequence[SourceAdapter], thesis: Thesis, resolution: ResolveResult
) -> QaReport | None:
    """Grade the run when every source can say which records truly belong together."""
    truth: dict[str, str] = {}
    entities: dict[str, EntityTruth] = {}
    for source in sources:
        labels = source.ground_truth()
        if labels is None:
            return None
        truth.update(labels)
        entities.update(source.entity_truth() or {})
    band = (thesis.ebitda_min, thesis.ebitda_max)
    return qa_report(resolution.companies, resolution.record_to_company, truth, entities, band)


@dataclass(frozen=True)
class _Context:
    thesis: Thesis
    ledger: EvidenceLedger
    checkers: Sequence[PresenceChecker]
    hook: ClassifierHook | None


def _assess(
    company: Company,
    members: Sequence[RawRecord],
    resolution: ResolveResult,
    context: _Context,
) -> None:
    thesis, ledger = context.thesis, context.ledger
    edges = resolution.merge_edges.get(company.company_id, [])
    identity = record_identity_claims(company, members, edges, ledger, thesis.resolve)
    company.fit, fit_claims = classify_company(
        company, members, thesis, ledger, anchor_claim=identity.name, hook=context.hook
    )
    company.estimate = estimate_company(
        company,
        members,
        thesis,
        ledger,
        trust=thesis.source_trust(),
        segment_claim=fit_claims.segment,
        mix_claim=fit_claims.service_mix,
        anchor_claim=identity.resolution,
    )
    company.presence = assess_presence(
        company,
        context.checkers,
        thesis.presence,
        ledger,
        website_claim=identity.website,
        anchor_claim=identity.resolution,
    )
    screen_company(company, thesis, ledger)


def run_pipeline(
    thesis: Thesis,
    sources: Sequence[SourceAdapter],
    presence_checkers: Sequence[PresenceChecker],
    adjudications: Mapping[tuple[str, str], str] | None = None,
) -> RunResult:
    """Run fetch -> resolve -> classify -> estimate -> presence -> screen -> rank.

    Args:
        thesis: Validated thesis.
        sources: Source adapters to pull records from.
        presence_checkers: One checker per database in the obviousness score.
        adjudications: Optional human decisions for review-queue pairs.

    Returns:
        Companies with every stage result attached, the ledger and the funnel.

    Raises:
        LedgerError: If the finished ledger fails verification.
    """
    records, records_by_feed = _fetch(thesis, sources)
    resolution = resolve(records, thesis.resolve, thesis.source_trust(), adjudications)
    hook = (
        load_hook(thesis.classify.llm_hook)
        if thesis.classify.llm_hook_enabled and thesis.classify.llm_hook
        else None
    )
    context = _Context(thesis, EvidenceLedger(), presence_checkers, hook)
    by_id = {r.record_id: r for r in records}
    for company in resolution.companies:
        _assess(company, [by_id[m] for m in company.member_ids], resolution, context)
    rank_companies(resolution.companies, thesis.ranking, context.ledger)

    companies = {c.company_id: c for c in resolution.companies}
    required = {c.company_id: required_claims(c) for c in resolution.companies}
    problems = context.ledger.verify(companies, by_id, required)
    if problems:
        raise LedgerError(
            "evidence ledger failed verification: " + "; ".join(problems[:_PROBLEMS_SHOWN])
        )

    funnel = _funnel(records_by_feed, resolution, thesis)
    logger.info(
        "ledger holds %d claims; %d companies in scope", len(context.ledger), funnel.in_scope
    )
    return RunResult(
        thesis=thesis,
        records=records,
        companies=resolution.companies,
        ledger=context.ledger,
        review_queue=resolution.review_queue,
        funnel=funnel,
        qa=_grade(sources, thesis, resolution),
        synthetic=bool(sources) and all(s.synthetic for s in sources),
    )

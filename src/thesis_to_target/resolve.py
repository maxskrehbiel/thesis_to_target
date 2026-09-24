"""Entity resolution: block, score and cluster messy source records into companies."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TypeVar

from rapidfuzz import fuzz

from .config import BUSINESS_GENERIC_TOKENS, ResolveConfig
from .errors import ConfigError
from .models import Company, RawRecord
from .normalize import (
    clean_display_name,
    distinctive_tokens,
    has_legal_suffix,
    name_variants,
    normalize_domain,
    normalize_name,
    normalize_phone,
    split_dba,
    zip5,
)

logger = logging.getLogger(__name__)

_T = TypeVar("_T")
_DEFAULT_TRUST = 0.5
_MAX_SCORE = 100.0  # every pair score lives on a 0-100 scale


@dataclass(frozen=True)
class PreparedRecord:
    """A record with its matching keys precomputed.

    Attributes:
        record: The original record.
        variants: Normalized names (legal, alias, DBA).
        phone: Ten-digit phone or ``None``.
        domain: Website host or ``None``.
        state: Upper-case state code or ``None``.
        zip5: Five-digit ZIP or ``None``.
    """

    record: RawRecord
    variants: tuple[str, ...]
    phone: str | None
    domain: str | None
    state: str | None
    zip5: str | None

    @property
    def record_id(self) -> str:
        """Id of the underlying record."""
        return self.record.record_id


@dataclass
class PairScore:
    """Score and decision for one candidate record pair.

    Attributes:
        a: Lower record id of the pair.
        b: Higher record id of the pair.
        score: Final score (0-100) after contact bonuses and state penalty.
        name_score: Name similarity (0-100) of the best-matching variants.
        name_a: Variant of ``a`` that matched best.
        name_b: Variant of ``b`` that matched best.
        reasons: Plain-language contributions to the score.
        decision: ``"merge"``, ``"review"`` or ``"reject"``.
    """

    a: str
    b: str
    score: float
    name_score: float
    name_a: str
    name_b: str
    reasons: list[str]
    decision: str


@dataclass(frozen=True)
class ResolveResult:
    """Output of :func:`resolve`.

    Attributes:
        companies: One entry per resolved business.
        pair_scores: Every candidate pair that was scored.
        review_queue: Pairs in the review band that ended up in different companies.
        record_to_company: Record id -> company id.
        merge_edges: Company id -> the merged pairs that built it.
    """

    companies: list[Company]
    pair_scores: list[PairScore]
    review_queue: list[PairScore]
    record_to_company: dict[str, str]
    merge_edges: dict[str, list[PairScore]] = field(default_factory=dict)


class UnionFind:
    """Disjoint-set forest with path compression and deterministic roots."""

    def __init__(self, ids: Iterable[str]) -> None:
        """Start with every id in its own set."""
        self._parent: dict[str, str] = {i: i for i in ids}

    def find(self, x: str) -> str:
        """Return the root of ``x``'s set."""
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        """Merge the sets containing ``a`` and ``b``; the smaller id becomes the root."""
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            ra, rb = min(ra, rb), max(ra, rb)
            self._parent[rb] = ra

    def groups(self) -> list[list[str]]:
        """Return every set as a sorted list of ids."""
        out: dict[str, list[str]] = {}
        for x in self._parent:
            out.setdefault(self.find(x), []).append(x)
        return [sorted(members) for members in out.values()]


def name_similarity(
    a: str,
    b: str,
    generic_tokens: frozenset[str] = BUSINESS_GENERIC_TOKENS,
    distinctive_slack: float = 15.0,
) -> float:
    """Score two normalized names on 0-100.

    The score is the mean of rapidfuzz ``token_sort_ratio`` (order-insensitive
    edit similarity) and ``token_set_ratio`` (tolerant of extra words), capped at
    the similarity of the non-generic tokens plus ``distinctive_slack`` so that
    shared industry words alone cannot make two firms look alike.

    Args:
        a: First normalized name.
        b: Second normalized name.
        generic_tokens: Words ignored for the distinctiveness cap.
        distinctive_slack: Allowed excess over the distinctive-token score.

    Returns:
        Similarity between 0 and 100.
    """
    if not a or not b:
        return 0.0
    score = 0.5 * fuzz.token_sort_ratio(a, b) + 0.5 * fuzz.token_set_ratio(a, b)
    da, db = distinctive_tokens(a, generic_tokens), distinctive_tokens(b, generic_tokens)
    if da and db:
        distinct = fuzz.token_set_ratio(" ".join(da), " ".join(db))
        score = min(score, distinct + distinctive_slack)
    return float(score)


def best_name_similarity(
    variants_a: Sequence[str], variants_b: Sequence[str], cfg: ResolveConfig
) -> tuple[float, str, str]:
    """Return the best score over all variant pairs and the variants that produced it."""
    best = (0.0, "", "")
    for va in variants_a:
        for vb in variants_b:
            s = name_similarity(va, vb, cfg.generic_tokens, cfg.distinctive_slack)
            if s > best[0]:
                best = (s, va, vb)
    return best


def prepare_record(record: RawRecord, cfg: ResolveConfig) -> PreparedRecord:
    """Precompute the normalized keys of one record."""
    return PreparedRecord(
        record=record,
        variants=tuple(name_variants(record.name, record.dba, cfg.abbreviations)),
        phone=normalize_phone(record.phone),
        domain=normalize_domain(record.website),
        state=(record.state or "").strip().upper() or None,
        zip5=zip5(record.zip),
    )


def block_keys(p: PreparedRecord, cfg: ResolveConfig) -> list[str]:
    """Return the blocking keys of a record.

    Two records are compared only if they share at least one key: phone, website,
    ZIP, identical normalized name, or (state, first distinctive token) and
    (state, its first letters).
    """
    keys: list[str] = []
    if p.phone:
        keys.append(f"phone:{p.phone}")
    if p.domain:
        keys.append(f"web:{p.domain}")
    if p.zip5:
        keys.append(f"zip:{p.zip5}")
    state = p.state or "??"
    for variant in p.variants:
        keys.append(f"full:{variant}")
        lead = (distinctive_tokens(variant, cfg.generic_tokens) or variant.split())[0]
        keys.append(f"tok:{state}:{lead}")
        keys.append(f"pre:{state}:{lead[: cfg.prefix_length]}")
    return list(dict.fromkeys(keys))


def _decide(score: float, cfg: ResolveConfig) -> str:
    if score >= cfg.merge_threshold:
        return "merge"
    if score >= cfg.review_threshold:
        return "review"
    return "reject"


def score_pair(pa: PreparedRecord, pb: PreparedRecord, cfg: ResolveConfig) -> PairScore:
    """Score one candidate pair and decide merge / review / reject.

    Args:
        pa: First record.
        pb: Second record.
        cfg: Thresholds and adjustments.

    Returns:
        The pair score, with ``a`` and ``b`` ordered by record id.
    """
    if pb.record_id < pa.record_id:
        pa, pb = pb, pa
    name_score, va, vb = best_name_similarity(pa.variants, pb.variants, cfg)
    adjustments = [
        (bool(pa.phone and pa.phone == pb.phone), cfg.phone_bonus, "same phone"),
        (bool(pa.domain and pa.domain == pb.domain), cfg.website_bonus, "same website"),
        (bool(pa.zip5 and pa.zip5 == pb.zip5), cfg.zip_bonus, "same ZIP"),
        (
            bool(pa.state and pb.state and pa.state != pb.state),
            -cfg.state_mismatch_penalty,
            "different state",
        ),
    ]
    score = name_score + sum(points for applies, points, _ in adjustments if applies)
    score = max(0.0, min(_MAX_SCORE, score))
    reasons = [f"name {name_score:.0f}", *(label for applies, _, label in adjustments if applies)]
    return PairScore(
        a=pa.record_id,
        b=pb.record_id,
        score=round(score, 1),
        name_score=round(name_score, 1),
        name_a=va,
        name_b=vb,
        reasons=reasons,
        decision=_decide(score, cfg),
    )


def _weighted_vote(values: Iterable[tuple[_T | None, float]]) -> _T | None:
    """Value with the highest summed weight; ties go to the first seen."""
    totals: dict[_T, float] = {}
    for value, weight in values:
        if value:
            totals[value] = totals.get(value, 0.0) + weight
    if not totals:
        return None
    return max(totals, key=lambda v: totals[v])


def operating_name(record: RawRecord) -> str:
    """The name a record says the business trades under (DBA field, alias, or the name)."""
    primary, alias = split_dba(record.name)
    return record.dba or alias or primary


def _display_name(
    ordered: Sequence[PreparedRecord], trust: Mapping[str, float], cfg: ResolveConfig
) -> str:
    texts: dict[str, list[str]] = {}
    votes: list[tuple[str | None, float]] = []
    for p in ordered:
        spelled = operating_name(p.record)
        key = normalize_name(spelled, cfg.abbreviations)
        if key:
            votes.append((key, trust.get(p.record.source, _DEFAULT_TRUST)))
            texts.setdefault(key, []).append(spelled)
    best_key = _weighted_vote(votes)
    if not best_key:
        return clean_display_name(ordered[0].record.name)
    # Prefer spellings without abbreviation periods, then the longest, then mixed case.
    cleaned = [(clean_display_name(t, drop_legal_suffix=True), t) for t in texts[best_key]]
    return min(cleaned, key=lambda pair: (pair[0].count("."), -len(pair[0]), pair[1].isupper()))[0]


def _legal_name(ordered: Sequence[PreparedRecord]) -> str | None:
    for p in ordered:
        primary = split_dba(p.record.name)[0]
        if has_legal_suffix(primary):
            return clean_display_name(primary)
    return None


def build_company(
    company_id: str,
    members: Sequence[PreparedRecord],
    trust: Mapping[str, float],
    cfg: ResolveConfig,
) -> Company:
    """Choose canonical values for one cluster by trust-weighted vote.

    Args:
        company_id: Id to assign.
        members: Prepared records in the cluster.
        trust: Feed name -> trust weight.
        cfg: Supplies the abbreviation map used to compare name spellings.

    Returns:
        The resolved company (stage results not yet attached).
    """

    def weight(p: PreparedRecord) -> float:
        return trust.get(p.record.source, _DEFAULT_TRUST)

    ordered = sorted(members, key=lambda p: (-weight(p), p.record_id))
    state = _weighted_vote((p.state, weight(p)) for p in ordered)
    in_state = [p for p in ordered if p.state == state] or ordered
    return Company(
        company_id=company_id,
        name=_display_name(ordered, trust, cfg),
        legal_name=_legal_name(ordered),
        city=next((clean_display_name(p.record.city) for p in in_state if p.record.city), None),
        state=state,
        zip=next((p.zip5 for p in in_state if p.zip5), None),
        phone=_weighted_vote((p.phone, weight(p)) for p in ordered),
        domain=_weighted_vote((p.domain, weight(p)) for p in ordered),
        member_ids=sorted(p.record_id for p in members),
        sources=sorted({p.record.source for p in members}),
        name_variants=list(dict.fromkeys(v for p in ordered for v in p.variants)),
    )


def _score_blocks(prepared: Mapping[str, PreparedRecord], cfg: ResolveConfig) -> list[PairScore]:
    blocks: dict[str, list[str]] = {}
    for p in prepared.values():
        for key in block_keys(p, cfg):
            blocks.setdefault(key, []).append(p.record_id)
    seen: set[tuple[str, str]] = set()
    scores: list[PairScore] = []
    for key, members in blocks.items():
        if len(members) > cfg.max_block_size:
            logger.warning("skipping oversized block %s (%d records)", key, len(members))
            continue
        for i, first in enumerate(members):
            for second in members[i + 1 :]:
                a, b = min(first, second), max(first, second)
                if a != b and (a, b) not in seen:
                    seen.add((a, b))
                    scores.append(score_pair(prepared[a], prepared[b], cfg))
    return scores


def _apply_adjudications(
    scores: list[PairScore],
    prepared: Mapping[str, PreparedRecord],
    adjudications: Mapping[tuple[str, str], str],
    cfg: ResolveConfig,
) -> None:
    verdicts = {
        (min(a, b), max(a, b)): v for (a, b), v in adjudications.items() if v in ("merge", "reject")
    }
    for ps in scores:
        verdict = verdicts.pop((ps.a, ps.b), None)
        if verdict:
            ps.decision = verdict
            ps.reasons.append(f"adjudicated: {verdict}")
    for (a, b), verdict in verdicts.items():
        if verdict == "merge" and a in prepared and b in prepared:
            ps = score_pair(prepared[a], prepared[b], cfg)
            ps.decision = "merge"
            ps.reasons.append("adjudicated: merge")
            scores.append(ps)


def _flag_low_cohesion(
    companies: Sequence[Company], prepared: Mapping[str, PreparedRecord], cfg: ResolveConfig
) -> None:
    # Union-find is transitive: A~B and B~C joins A with C even if they look nothing
    # alike. Flag clusters whose weakest member pair is poor so a person checks them.
    for company in companies:
        if len(company.member_ids) < 3:
            continue
        members = [prepared[m] for m in company.member_ids]
        weakest = min(
            best_name_similarity(x.variants, y.variants, cfg)[0]
            for i, x in enumerate(members)
            for y in members[i + 1 :]
        )
        if weakest < cfg.cohesion_floor:
            company.flags.append(f"low_cohesion({weakest:.0f})")


def resolve(
    records: Sequence[RawRecord],
    cfg: ResolveConfig | None = None,
    trust: Mapping[str, float] | None = None,
    adjudications: Mapping[tuple[str, str], str] | None = None,
) -> ResolveResult:
    """Cluster records into companies.

    Args:
        records: Records from every source; ids must be unique.
        cfg: Resolution thresholds and vocabulary; defaults to :class:`ResolveConfig`.
        trust: Feed name -> trust weight used to pick canonical values.
        adjudications: ``(record_a, record_b) -> "merge" | "reject"`` decisions
            from human review; they override the automatic decision.

    Returns:
        Companies, all scored pairs, and the unresolved review queue.

    Raises:
        ConfigError: If two records share an id.
    """
    cfg = cfg or ResolveConfig()
    trust = trust or {}
    prepared = {r.record_id: prepare_record(r, cfg) for r in records}
    if len(prepared) != len(records):
        raise ConfigError("record_id values must be unique across all sources")

    scores = _score_blocks(prepared, cfg)
    _apply_adjudications(scores, prepared, adjudications or {}, cfg)
    uf = UnionFind(prepared)
    for ps in scores:
        if ps.decision == "merge":
            uf.union(ps.a, ps.b)

    companies: list[Company] = []
    record_to_company: dict[str, str] = {}
    for idx, member_ids in enumerate(sorted(uf.groups()), start=1):
        company = build_company(f"C{idx:04d}", [prepared[m] for m in member_ids], trust, cfg)
        companies.append(company)
        record_to_company.update(dict.fromkeys(member_ids, company.company_id))
    _flag_low_cohesion(companies, prepared, cfg)

    merge_edges: dict[str, list[PairScore]] = {}
    for ps in scores:
        if ps.decision == "merge":
            merge_edges.setdefault(record_to_company[ps.a], []).append(ps)
    review_queue = [
        ps
        for ps in scores
        if ps.decision == "review" and record_to_company[ps.a] != record_to_company[ps.b]
    ]
    logger.info(
        "resolved %d records into %d companies (%d pairs scored, %d for review)",
        len(records),
        len(companies),
        len(scores),
        len(review_queue),
    )
    return ResolveResult(companies, scores, review_queue, record_to_company, merge_edges)

"""Identity claims for a resolved company: name, location, merge trail, legal name, website."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .config import ResolveConfig
from .evidence import EvidenceLedger
from .models import Company, RawRecord
from .normalize import (
    clean_display_name,
    name_variants,
    normalize_domain,
    normalize_name,
    split_dba,
)
from .resolve import PairScore, operating_name

# Merge pairs listed in the evidence text before it is summarized as "+N more".
_EDGES_SHOWN = 5


@dataclass(frozen=True)
class IdentityClaims:
    """Ledger ids of the identity claims recorded for one company.

    Attributes:
        name: Claim backing the display name.
        location: Claim backing city and state.
        resolution: Claim describing which records were merged and why.
        legal_name: Claim backing the legal name, if any.
        website: Claim backing the website host, if any.
    """

    name: str
    location: str
    resolution: str
    legal_name: str | None = None
    website: str | None = None


def _feeds(records: Sequence[RawRecord]) -> str:
    return ", ".join(sorted({r.source for r in records}))


def _grade(records: Sequence[RawRecord]) -> str:
    """Two independent feeds agreeing make a fact confirmed; one makes it strong."""
    return "confirmed" if len({r.source for r in records}) >= 2 else "strong"


def _name_claim(
    company: Company, members: Sequence[RawRecord], ledger: EvidenceLedger, cfg: ResolveConfig
) -> str:
    key = normalize_name(company.name, cfg.abbreviations)
    named = [r for r in members if key in name_variants(r.name, r.dba, cfg.abbreviations)]
    named = named or list(members)
    # Cite a record that prints the name exactly as displayed, else one that does after cleanup.
    exact = [r for r in named if operating_name(r) == company.name]
    cleaned = [
        r
        for r in named
        if clean_display_name(operating_name(r), drop_legal_suffix=True) == company.name
    ]
    spelled = (exact or cleaned or named)[0]
    return ledger.observed(
        company.company_id,
        "name",
        company.name,
        source=_feeds(named),
        record_ids=[r.record_id for r in named],
        confidence=_grade(named),
        evidence=f"operating name chosen by trust-weighted vote over {len(members)} record(s); "
        f"spelled '{operating_name(spelled)}' in {spelled.record_id}",
    )


def _location_claim(company: Company, members: Sequence[RawRecord], ledger: EvidenceLedger) -> str:
    located = [r for r in members if company.state and (r.state or "").upper() == company.state]
    if not located:
        return ledger.observed(
            company.company_id,
            "location",
            "unknown",
            source=_feeds(members),
            record_ids=[r.record_id for r in members],
            confidence="weak",
            evidence="no member record carries a state",
        )
    return ledger.observed(
        company.company_id,
        "location",
        f"{company.city or '?'}, {company.state}",
        source=_feeds(located),
        record_ids=[r.record_id for r in located],
        confidence=_grade(located),
        evidence=f"{len(located)} of {len(members)} record(s) place the company in {company.state}",
    )


def _resolution_claim(
    company: Company,
    members: Sequence[RawRecord],
    edges: Sequence[PairScore],
    ledger: EvidenceLedger,
) -> str:
    if edges:
        shown = "; ".join(f"{e.a}~{e.b} ({', '.join(e.reasons)})" for e in edges[:_EDGES_SHOWN])
        more = f"; +{len(edges) - _EDGES_SHOWN} more" if len(edges) > _EDGES_SHOWN else ""
        evidence = f"merged pairs: {shown}{more}"
    else:
        evidence = "no other record scored at or above the merge threshold"
    if company.flags:
        evidence += f"; flags: {', '.join(company.flags)}"
    return ledger.observed(
        company.company_id,
        "entity_resolution",
        f"{len(members)} record(s) from {len(company.sources)} source(s)",
        source=_feeds(members),
        record_ids=[r.record_id for r in members],
        confidence="weak" if company.flags else "strong",
        evidence=evidence,
        method="entity_resolution",
    )


def _legal_name_claim(
    company: Company, members: Sequence[RawRecord], ledger: EvidenceLedger
) -> str | None:
    if not company.legal_name:
        return None
    printed = [r for r in members if clean_display_name(split_dba(r.name)[0]) == company.legal_name]
    backing = printed or list(members)
    return ledger.observed(
        company.company_id,
        "legal_name",
        company.legal_name,
        source=_feeds(backing),
        record_ids=[r.record_id for r in backing],
        confidence=_grade(backing),
        evidence=f"name with legal suffix as printed in {backing[0].record_id}",
    )


def _website_claim(
    company: Company, members: Sequence[RawRecord], ledger: EvidenceLedger
) -> str | None:
    if not company.domain:
        return None
    sited = [r for r in members if normalize_domain(r.website) == company.domain]
    return ledger.observed(
        company.company_id,
        "website",
        company.domain,
        source=_feeds(sited),
        record_ids=[r.record_id for r in sited],
        confidence=_grade(sited),
        evidence=f"website listed in {len(sited)} record(s)",
    )


def record_identity_claims(
    company: Company,
    members: Sequence[RawRecord],
    edges: Sequence[PairScore],
    ledger: EvidenceLedger,
    cfg: ResolveConfig,
) -> IdentityClaims:
    """Write the identity claims of one resolved company.

    Args:
        company: The resolved company.
        members: Its source records.
        edges: Merged pairs that built the cluster.
        ledger: Ledger to append to.
        cfg: Supplies the abbreviation map used to match name spellings.

    Returns:
        The ids of the claims written.
    """
    return IdentityClaims(
        name=_name_claim(company, members, ledger, cfg),
        location=_location_claim(company, members, ledger),
        resolution=_resolution_claim(company, members, edges, ledger),
        legal_name=_legal_name_claim(company, members, ledger),
        website=_website_claim(company, members, ledger),
    )

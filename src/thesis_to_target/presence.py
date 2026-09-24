"""Presence lookups against large commercial databases and the obviousness score."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .config import PresenceConfig, ResolveConfig
from .evidence import EvidenceLedger
from .models import Company, PresenceResult
from .normalize import normalize_name
from .resolve import name_similarity


@dataclass(frozen=True)
class Listing:
    """One company listing inside a database.

    Attributes:
        listing_id: Database-specific id.
        name: Company name as listed.
        state: Two-letter state code, if listed.
    """

    listing_id: str
    name: str
    state: str | None


@dataclass(frozen=True)
class PresenceHit:
    """Result of looking one company up in one database.

    Attributes:
        database: Database name.
        found: Whether a listing matched above the threshold.
        listing_id: Matching listing id, if found.
        listed_name: Matching listing name, if found.
        score: Best name score seen (0-100), matched or not.
        query: What was looked up.
    """

    database: str
    found: bool
    listing_id: str | None
    listed_name: str | None
    score: float
    query: str


class PresenceChecker(ABC):
    """Answers whether a company already appears in one database."""

    def __init__(self, database: str, weight: float) -> None:
        """Configure the checker.

        Args:
            database: Database name.
            weight: Weight of this database in the obviousness score.
        """
        self.database = database
        self.weight = weight

    @abstractmethod
    def lookup(self, company: Company) -> PresenceHit:
        """Look a resolved company up in the database."""


class ListingIndexChecker(PresenceChecker):
    """Fuzzy-matches a company against in-memory listings from the same state."""

    def __init__(
        self,
        database: str,
        weight: float,
        listings: Iterable[Listing],
        *,
        threshold: float = 90.0,
        resolve_cfg: ResolveConfig | None = None,
    ) -> None:
        """Index the listings by state.

        Args:
            database: Database name.
            weight: Weight in the obviousness score.
            listings: Every listing the database holds.
            threshold: Name score (0-100) needed to call a listing a match.
            resolve_cfg: Supplies the vocabulary, generic tokens and slack for name scoring.
        """
        super().__init__(database, weight)
        self.threshold = threshold
        self._cfg = resolve_cfg or ResolveConfig()
        self._by_state: dict[str, list[tuple[str, Listing]]] = {}
        for listing in listings:
            key = (listing.state or "").upper()
            self._by_state.setdefault(key, []).append(
                (normalize_name(listing.name, self._cfg.abbreviations), listing)
            )

    def lookup(self, company: Company) -> PresenceHit:
        """Return the best-scoring same-state listing and whether it clears the threshold."""
        best_score, best = 0.0, None
        for variant in company.name_variants:
            for norm, listing in self._by_state.get((company.state or "").upper(), []):
                score = name_similarity(
                    variant, norm, self._cfg.generic_tokens, self._cfg.distinctive_slack
                )
                if score > best_score:
                    best_score, best = score, listing
        found = best is not None and best_score >= self.threshold
        return PresenceHit(
            database=self.database,
            found=found,
            listing_id=best.listing_id if found and best else None,
            listed_name=best.name if found and best else None,
            score=round(best_score, 1),
            query=f"{company.name} ({company.state or '?'})",
        )


def obviousness_score(
    found: Mapping[str, bool], weights: Mapping[str, float], has_website: bool, web_weight: float
) -> float:
    """Weighted share of places a company already shows up.

    Args:
        found: Database -> found flag.
        weights: Database -> weight.
        has_website: Whether the company has its own website.
        web_weight: Weight of having a website.

    Returns:
        A value in [0, 1]; 0 when the total weight is zero.
    """
    total = sum(weights.get(db, 0.0) for db in found) + web_weight
    if total <= 0:
        return 0.0
    hit = sum(weights.get(db, 0.0) for db, f in found.items() if f) + (
        web_weight if has_website else 0.0
    )
    return hit / total


def _record_hit(
    company_id: str, hit: PresenceHit, cfg: PresenceConfig, ledger: EvidenceLedger
) -> str:
    if hit.found:
        confidence = "confirmed" if hit.score >= cfg.confirmed_score else "strong"
        evidence = f"listing {hit.listing_id} '{hit.listed_name}' matched at {hit.score:.0f}"
    else:
        confidence = "inferred"  # absence is harder to prove than presence
        evidence = (
            f"no same-state listing reached {cfg.match_threshold:.0f}; best score {hit.score:.0f}"
        )
    return ledger.external(
        company_id,
        f"presence:{hit.database}",
        "found" if hit.found else "not found",
        evidence=evidence,
        source=hit.database,
        confidence=confidence,
        external_ref=hit.listing_id or f"query: {hit.query}",
        method="fuzzy_name_match",
    )


def assess_presence(
    company: Company,
    checkers: Sequence[PresenceChecker],
    cfg: PresenceConfig,
    ledger: EvidenceLedger,
    *,
    website_claim: str | None,
    anchor_claim: str,
) -> PresenceResult:
    """Look a company up in every database and record the obviousness score.

    Args:
        company: The resolved company.
        checkers: One checker per database.
        cfg: Thresholds and the website weight.
        ledger: Ledger to append to.
        website_claim: Claim id backing the company's website, if it has one.
        anchor_claim: Claim to cite when no other input exists.

    Returns:
        Presence flags, obviousness and the non-obvious flag.
    """
    found: dict[str, bool] = {}
    deps: list[str] = []
    for checker in checkers:
        hit = checker.lookup(company)
        found[checker.database] = hit.found
        deps.append(_record_hit(company.company_id, hit, cfg, ledger))
    if website_claim:
        deps.append(website_claim)
    has_website = company.domain is not None
    weights = {c.database: c.weight for c in checkers}
    score = obviousness_score(found, weights, has_website, cfg.web_presence_weight)
    non_obvious = score < cfg.non_obvious_below
    terms = [f"{weights[db]:.2f}x{db}({int(flag)})" for db, flag in found.items()]
    terms.append(f"{cfg.web_presence_weight:.2f}x website({int(has_website)})")
    ledger.derived(
        company.company_id,
        "obviousness",
        round(score, 3),
        depends_on=deps or [anchor_claim],
        confidence="inferred",
        method="weighted_presence",
        evidence=f"({' + '.join(terms)}) / total weight = {score:.2f}; "
        f"{'non-obvious' if non_obvious else 'obvious'} (cut-off {cfg.non_obvious_below:.2f})",
    )
    return PresenceResult(
        found=found, has_website=has_website, obviousness=score, non_obvious=non_obvious
    )

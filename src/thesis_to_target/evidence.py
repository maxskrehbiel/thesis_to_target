"""Append-only evidence ledger: every claim with its value, evidence, source and confidence."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from .errors import LedgerError
from .models import Company, RawRecord

CONFIDENCE_LEVELS = ("confirmed", "strong", "inferred", "weak", "contradictory")
# Lower number = stronger. "contradictory" sits outside the scale on purpose.
_STRENGTH = {"confirmed": 0, "strong": 1, "inferred": 2, "weak": 3}
# Floats at least this large are rendered as whole numbers with thousands separators.
_WHOLE_NUMBER_FROM = 1000


@dataclass(frozen=True)
class Claim:
    """One row of the ledger: Claim -> Value -> Evidence -> Source -> Confidence.

    Attributes:
        claim_id: Deterministic id, ``"<company_id>.<n>"``.
        company_id: Company the claim is about.
        claim: Claim name, e.g. ``"fit_tier"``.
        value: The claimed value.
        evidence: Human-readable justification (a quote or a computation).
        source: Feed, database or ``"derived"``.
        confidence: One of :data:`CONFIDENCE_LEVELS`.
        kind: ``"observed"``, ``"external"`` or ``"derived"``.
        method: How the claim was produced (``"source_field"``, ``"keyword_rule"`` ...).
        record_ids: Source records backing an observed claim.
        depends_on: Claim ids a derived claim was computed from.
        external_ref: Reference for an external lookup.
    """

    claim_id: str
    company_id: str
    claim: str
    value: Any
    evidence: str
    source: str
    confidence: str
    kind: str
    method: str
    record_ids: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    external_ref: str | None = None


def render_value(value: Any) -> str:
    """Render a claim value as stable, human-readable text.

    Args:
        value: Any claim value.

    Returns:
        Booleans as yes/no, floats to four significant digits (or as whole numbers
        with thousands separators when large), sequences joined with ``"; "``.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:,.0f}" if abs(value) >= _WHOLE_NUMBER_FROM else f"{value:.4g}"
    if isinstance(value, list | tuple):
        return "; ".join(render_value(v) for v in value)
    if isinstance(value, Mapping):
        return "; ".join(f"{k}={render_value(v)}" for k, v in value.items())
    return str(value)


class EvidenceLedger:
    """Append-only store of :class:`Claim` rows.

    Rules checked when a claim is written: the confidence is a known level; the
    evidence text is not empty; an observed claim cites at least one record; an
    external claim cites a reference; a derived claim cites earlier claims about the
    same company and is no more confident than the strongest of them. Rules that need
    the resolved companies and records are checked by :meth:`verify`.
    """

    def __init__(self) -> None:
        """Create an empty ledger."""
        self._claims: list[Claim] = []
        self._by_id: dict[str, Claim] = {}
        self._by_company: dict[str, list[Claim]] = {}
        self._latest: dict[tuple[str, str], Claim] = {}

    def _check_inputs(
        self, company_id: str, claim: str, confidence: str, depends_on: tuple[str, ...]
    ) -> None:
        if not depends_on:
            raise LedgerError(f"derived claim '{claim}' for {company_id} cites no input claims")
        strongest: int | None = None
        for dep in depends_on:
            parent = self._by_id.get(dep)
            if parent is None:
                raise LedgerError(f"derived claim '{claim}' depends on unknown claim '{dep}'")
            if parent.company_id != company_id:
                raise LedgerError(
                    f"derived claim '{claim}' for {company_id} cites {dep} of another company"
                )
            if parent.confidence in _STRENGTH:
                s = _STRENGTH[parent.confidence]
                strongest = s if strongest is None else min(strongest, s)
        ceiling = _STRENGTH["weak"] if strongest is None else strongest
        if confidence in _STRENGTH and _STRENGTH[confidence] < ceiling:
            raise LedgerError(
                f"derived claim '{claim}' for {company_id} is '{confidence}', "
                "stronger than any input"
            )

    def _add(
        self,
        *,
        company_id: str,
        claim: str,
        value: Any,
        evidence: str,
        source: str,
        confidence: str,
        kind: str,
        method: str,
        record_ids: Iterable[str] = (),
        depends_on: Iterable[str] = (),
        external_ref: str | None = None,
    ) -> str:
        if confidence not in CONFIDENCE_LEVELS:
            raise LedgerError(f"unknown confidence '{confidence}' (allowed: {CONFIDENCE_LEVELS})")
        if not evidence.strip():
            raise LedgerError(f"claim '{claim}' for {company_id} has no evidence text")
        record_tuple, depends_tuple = tuple(record_ids), tuple(depends_on)
        if kind == "observed" and not record_tuple:
            raise LedgerError(f"observed claim '{claim}' for {company_id} cites no source record")
        if kind == "external" and not external_ref:
            raise LedgerError(f"external claim '{claim}' for {company_id} has no reference")
        if kind == "derived":
            self._check_inputs(company_id, claim, confidence, depends_tuple)
        history = self._by_company.setdefault(company_id, [])
        row = Claim(
            claim_id=f"{company_id}.{len(history) + 1:02d}",
            company_id=company_id,
            claim=claim,
            value=value,
            evidence=evidence.strip(),
            source=source,
            confidence=confidence,
            kind=kind,
            method=method,
            record_ids=record_tuple,
            depends_on=depends_tuple,
            external_ref=external_ref,
        )
        self._claims.append(row)
        self._by_id[row.claim_id] = row
        history.append(row)
        self._latest[(company_id, claim)] = row
        return row.claim_id

    def observed(
        self,
        company_id: str,
        claim: str,
        value: Any,
        *,
        evidence: str,
        source: str,
        record_ids: Iterable[str],
        confidence: str,
        method: str = "source_field",
    ) -> str:
        """Record a fact stated by one or more source records.

        Args:
            company_id: Company the claim is about.
            claim: Claim name.
            value: Claimed value.
            evidence: Quote or description of what the records say.
            source: Feed name(s) the records came from.
            record_ids: Ids of the records that state the fact.
            confidence: One of :data:`CONFIDENCE_LEVELS`.
            method: How the fact was read.

        Returns:
            The new claim id.

        Raises:
            LedgerError: If no record is cited, the evidence is empty or the confidence is unknown.
        """
        return self._add(
            company_id=company_id,
            claim=claim,
            value=value,
            evidence=evidence,
            source=source,
            confidence=confidence,
            kind="observed",
            method=method,
            record_ids=record_ids,
        )

    def external(
        self,
        company_id: str,
        claim: str,
        value: Any,
        *,
        evidence: str,
        source: str,
        external_ref: str,
        confidence: str,
        method: str = "lookup",
    ) -> str:
        """Record the result of a lookup outside the record set.

        Args:
            company_id: Company the claim is about.
            claim: Claim name.
            value: Claimed value.
            evidence: What the lookup found (or did not find).
            source: Database looked up.
            external_ref: Listing id or query string.
            confidence: One of :data:`CONFIDENCE_LEVELS`.
            method: How the lookup was done.

        Returns:
            The new claim id.

        Raises:
            LedgerError: If no reference is given, the evidence is empty or the
                confidence is unknown.
        """
        return self._add(
            company_id=company_id,
            claim=claim,
            value=value,
            evidence=evidence,
            source=source,
            confidence=confidence,
            kind="external",
            method=method,
            external_ref=external_ref,
        )

    def derived(
        self,
        company_id: str,
        claim: str,
        value: Any,
        *,
        evidence: str,
        depends_on: Iterable[str],
        confidence: str,
        method: str = "rule",
    ) -> str:
        """Record a conclusion computed from earlier claims about the same company.

        Args:
            company_id: Company the claim is about.
            claim: Claim name.
            value: Computed value.
            evidence: The computation or rule, in words.
            depends_on: Ids of the claims used.
            confidence: One of :data:`CONFIDENCE_LEVELS`; may not be stronger than the
                strongest input.
            method: Rule or model that produced it.

        Returns:
            The new claim id.

        Raises:
            LedgerError: If an input is missing or belongs to another company, or the
                confidence is stronger than every input.
        """
        return self._add(
            company_id=company_id,
            claim=claim,
            value=value,
            evidence=evidence,
            source="derived",
            confidence=confidence,
            kind="derived",
            method=method,
            depends_on=depends_on,
        )

    def __len__(self) -> int:
        """Number of claims."""
        return len(self._claims)

    def __iter__(self) -> Iterator[Claim]:
        """Iterate claims in insertion order."""
        return iter(self._claims)

    def get(self, claim_id: str) -> Claim:
        """Return one claim by id.

        Raises:
            KeyError: If the id does not exist.
        """
        return self._by_id[claim_id]

    def for_company(self, company_id: str) -> list[Claim]:
        """Return every claim about one company, in insertion order."""
        return list(self._by_company.get(company_id, ()))

    def last(self, company_id: str, claim: str) -> Claim | None:
        """Return the most recent claim of a given name about a company, if any."""
        return self._latest.get((company_id, claim))

    def verify(
        self,
        companies: Mapping[str, Company],
        records: Mapping[str, RawRecord],
        required: Mapping[str, Iterable[str]] | None = None,
    ) -> list[str]:
        """Check the rules that need the resolved companies and records.

        Every claim must be about an existing company; every record an observed claim
        cites must exist and belong to that company; and each company in ``required``
        must carry the named claims, so no exported value lacks ledger backing.

        Args:
            companies: Company id -> company.
            records: Record id -> record.
            required: Company id -> claim names that must exist.

        Returns:
            Human-readable violations; an empty list means the ledger is sound.
        """
        problems: list[str] = []
        for company_id, claims in self._by_company.items():
            company = companies.get(company_id)
            if company is None:
                problems.append(
                    f"{company_id}: {len(claims)} claim(s) about a company that does not exist"
                )
                continue
            members = set(company.member_ids)
            for c in claims:
                for rid in c.record_ids:
                    if rid not in records:
                        problems.append(f"{c.claim_id}: cites unknown record {rid}")
                    elif rid not in members:
                        problems.append(f"{c.claim_id}: cites record {rid} of another company")
        for company_id, needed in (required or {}).items():
            present = {c.claim for c in self._by_company.get(company_id, ())}
            missing = sorted(set(needed) - present)
            if missing:
                problems.append(f"{company_id}: exported without ledger backing for {missing}")
        return problems

    def rows(self, names: Mapping[str, str] | None = None) -> list[dict[str, str]]:
        """Flatten the ledger into export rows.

        Args:
            names: Optional company id -> display name, added as a column.

        Returns:
            One dict of strings per claim, in insertion order.
        """
        names = names or {}
        return [
            {
                "claim_id": c.claim_id,
                "company_id": c.company_id,
                "company": names.get(c.company_id, ""),
                "claim": c.claim,
                "value": render_value(c.value),
                "evidence": c.evidence,
                "source": c.source,
                "confidence": c.confidence,
                "kind": c.kind,
                "method": c.method,
                "record_ids": " ".join(c.record_ids),
                "depends_on": " ".join(c.depends_on),
                "external_ref": c.external_ref or "",
            }
            for c in self._claims
        ]

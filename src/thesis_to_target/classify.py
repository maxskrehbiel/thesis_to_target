"""Sector-fit classification from license, NAICS and keyword evidence, plus an optional hook."""

from __future__ import annotations

import functools
import importlib
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .errors import HookError
from .evidence import EvidenceLedger
from .models import Company, FitResult, RawRecord
from .thesis import Thesis

#: A model-classification function: receives a company payload, returns field verdicts.
ClassifierHook = Callable[[Mapping[str, Any]], Mapping[str, Any]]

TIER_LABELS = {"A": "verified", "B": "likely", "C": "name only", "D": "no sector evidence"}
_TEXT_FIELDS = ("services", "listing_category")
# Characters of a model quote copied into the evidence text.
_QUOTE_CHARS = 120


@dataclass(frozen=True)
class TextSnippet:
    """A piece of company text and where it came from.

    Attributes:
        record_id: Source record id.
        source: Feed name.
        field: Record field the text came from.
        text: The text.
    """

    record_id: str
    source: str
    field: str
    text: str


@dataclass(frozen=True)
class FitClaims:
    """Ledger ids of the classification claims for one company.

    Attributes:
        fit_tier: Claim backing the fit tier.
        segment: Claim backing the segment.
        service_mix: Claim backing the service mix.
    """

    fit_tier: str
    segment: str
    service_mix: str


@dataclass
class _Evidence:
    """Everything the tier, segment and mix rules read, with the claims that back it."""

    anchor: str
    snippets: list[TextSnippet]
    service_text: str
    all_text: str
    names: str
    naics_hit: bool = False
    sector_licenses: list[TextSnippet] = field(default_factory=list)
    parent_owned: bool = False
    claims: dict[str, str] = field(default_factory=dict)


@dataclass
class _TierCall:
    tier: str
    reasons: list[str]
    deps: list[str]
    adjacent: bool = False
    adjacent_keywords: list[str] = field(default_factory=list)


@functools.cache
def keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Compile a whole-phrase, case-insensitive pattern that also accepts a plural ending.

    Args:
        keyword: Lower-case phrase, e.g. ``"fire alarm"``.

    Returns:
        A compiled regular expression.
    """
    body = r"\s+".join(re.escape(part) for part in keyword.split())
    return re.compile(rf"(?<![a-z0-9]){body}(?:s|es)?(?![a-z0-9])", flags=re.IGNORECASE)


def find_keywords(text: str, keywords: Iterable[str]) -> list[str]:
    """Return the keywords that occur in ``text``, in the order given."""
    return [k for k in keywords if keyword_pattern(k).search(text)]


def collect_text(records: Sequence[RawRecord]) -> list[TextSnippet]:
    """Gather the service, category and license text of a company's records."""
    snippets: list[TextSnippet] = []
    for r in records:
        for field_name in _TEXT_FIELDS:
            value = r.attributes.get(field_name)
            if isinstance(value, list | tuple):
                value = "; ".join(str(v) for v in value)
            if value:
                snippets.append(TextSnippet(r.record_id, r.source, field_name, str(value)))
        if r.attributes.get("license_type"):
            snippets.append(
                TextSnippet(
                    r.record_id, r.source, "license_type", str(r.attributes["license_type"])
                )
            )
    return snippets


def load_hook(spec: str) -> ClassifierHook:
    """Import a model-classification function from ``"package.module:function"``.

    Args:
        spec: Import path.

    Returns:
        The callable.

    Raises:
        HookError: If the path is malformed or does not resolve to a callable.
    """
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise HookError(f"llm_hook must look like 'package.module:function', got '{spec}'")
    try:
        target = getattr(importlib.import_module(module_name), attr)
    except (ImportError, AttributeError) as exc:
        raise HookError(f"cannot import llm_hook '{spec}': {exc}") from exc
    if not callable(target):
        raise HookError(f"llm_hook '{spec}' is not callable")
    hook: ClassifierHook = target
    return hook


def _feeds(items: Iterable[TextSnippet | RawRecord]) -> str:
    return ", ".join(sorted({i.source for i in items}))


def _record_naics(
    ev: _Evidence,
    company_id: str,
    records: Sequence[RawRecord],
    thesis: Thesis,
    ledger: EvidenceLedger,
) -> None:
    coded = [r for r in records if r.attributes.get("naics")]
    if not coded:
        return
    codes = sorted({str(r.attributes["naics"]) for r in coded})
    ev.naics_hit = any(code.startswith(prefix) for code in codes for prefix in thesis.naics)
    ev.claims["naics"] = ledger.observed(
        company_id,
        "naics_code",
        codes,
        source=_feeds(coded),
        record_ids=[r.record_id for r in coded],
        confidence="confirmed",
        evidence=f"NAICS {', '.join(codes)} ({'in' if ev.naics_hit else 'not in'} thesis list)",
    )


def _record_licenses(
    ev: _Evidence,
    company_id: str,
    records: Sequence[RawRecord],
    thesis: Thesis,
    ledger: EvidenceLedger,
) -> None:
    licenses = [s for s in ev.snippets if s.field == "license_type"]
    if not licenses:
        return
    ev.sector_licenses = [s for s in licenses if find_keywords(s.text, thesis.include_keywords)]
    by_id = {r.record_id: r for r in records}
    status = {
        s.record_id: str(by_id[s.record_id].attributes.get("license_status", "unknown"))
        for s in licenses
    }
    ev.claims["license"] = ledger.observed(
        company_id,
        "license",
        [f"{s.text} ({status[s.record_id]})" for s in licenses],
        source=_feeds(licenses),
        record_ids=[s.record_id for s in licenses],
        confidence="confirmed" if "Active" in status.values() else "strong",
        evidence="; ".join(
            f"{s.record_id}: '{s.text}', status {status[s.record_id]}" for s in licenses
        ),
    )


def _record_services(ev: _Evidence, company_id: str, ledger: EvidenceLedger) -> None:
    services = [s for s in ev.snippets if s.field in _TEXT_FIELDS]
    if not services:
        return
    record_ids = sorted({s.record_id for s in services})
    ev.claims["services"] = ledger.observed(
        company_id,
        "services_listed",
        sorted({s.text for s in services}),
        source=_feeds(services),
        record_ids=record_ids,
        confidence="strong",
        evidence=f"service and category text from {len(record_ids)} record(s)",
    )


def _record_ownership(
    ev: _Evidence, company_id: str, records: Sequence[RawRecord], ledger: EvidenceLedger
) -> None:
    parents = [r for r in records if r.attributes.get("parent_entity")]
    if not parents:
        return
    ev.parent_owned = True
    ev.claims["ownership"] = ledger.observed(
        company_id,
        "ownership",
        "parent-owned",
        source=_feeds(parents),
        record_ids=[r.record_id for r in parents],
        confidence="confirmed",
        evidence="; ".join(
            f"{r.record_id} lists parent entity '{r.attributes['parent_entity']}'" for r in parents
        ),
    )


def _gather_evidence(
    company: Company,
    records: Sequence[RawRecord],
    thesis: Thesis,
    ledger: EvidenceLedger,
    anchor: str,
) -> _Evidence:
    snippets = collect_text(records)
    ev = _Evidence(
        anchor=anchor,
        snippets=snippets,
        service_text=" | ".join(s.text for s in snippets if s.field in _TEXT_FIELDS).lower(),
        all_text=" | ".join(s.text for s in snippets).lower(),
        names=" | ".join(company.name_variants),
    )
    _record_naics(ev, company.company_id, records, thesis, ledger)
    _record_licenses(ev, company.company_id, records, thesis, ledger)
    _record_services(ev, company.company_id, ledger)
    _record_ownership(ev, company.company_id, records, ledger)
    return ev


def _decide_tier(ev: _Evidence, thesis: Thesis) -> _TierCall:
    """Apply the tier rules in order, strongest evidence first."""
    text_kw = find_keywords(ev.service_text, thesis.include_keywords)
    name_kw = find_keywords(ev.names, thesis.include_keywords)
    adjacent_kw = find_keywords(ev.service_text, thesis.adjacent_keywords)
    adjacent = bool(adjacent_kw) and not text_kw and not ev.sector_licenses
    c = ev.claims
    if ev.sector_licenses:
        return _TierCall("A", [f"sector license '{ev.sector_licenses[0].text}'"], [c["license"]])
    if ev.naics_hit and text_kw:
        return _TierCall(
            "A", [f"in-thesis NAICS and service keywords {text_kw}"], [c["naics"], c["services"]]
        )
    if adjacent:
        return _TierCall(
            "D", [f"adjacent-trade keywords {adjacent_kw}"], [c["services"]], True, adjacent_kw
        )
    if text_kw:
        return _TierCall("B", [f"service keywords {text_kw}"], [c["services"]])
    if ev.naics_hit and name_kw:
        return _TierCall(
            "B", [f"in-thesis NAICS and name keywords {name_kw}"], [c["naics"], ev.anchor]
        )
    if name_kw:
        return _TierCall("C", [f"name keywords {name_kw}"], [ev.anchor])
    if ev.naics_hit:
        return _TierCall("C", ["in-thesis NAICS only"], [ev.anchor, c["naics"]])
    return _TierCall("D", ["no license, NAICS or keyword evidence"], [ev.anchor])


def _ask_hook(
    hook: ClassifierHook, company: Company, ev: _Evidence, ledger: EvidenceLedger
) -> tuple[bool, str]:
    """Call the hook and record its verdict.

    Returns:
        Whether the verdict is in-sector with a verified quote, and the claim id written.
    """
    corpus = " ".join([*company.name_variants, *(s.text for s in ev.snippets)])
    payload = {"company_id": company.company_id, "name": company.name, "text": corpus}
    # The hook is the caller's own code: its exceptions propagate with their traceback.
    answer = hook(payload)
    verdict = answer.get("in_sector") if isinstance(answer, Mapping) else None
    if not isinstance(verdict, Mapping) or not isinstance(verdict.get("value"), bool):
        raise HookError("llm_hook must return {'in_sector': {'value': bool, 'evidence': str}}")
    quote = str(verdict.get("evidence", "")).strip()
    # A model claim is only as good as its quote: unverifiable quotes are recorded as weak.
    verified = bool(quote) and quote.lower() in corpus.lower()
    claim_id = ledger.derived(
        company.company_id,
        "model_in_sector",
        verdict["value"],
        depends_on=[ev.claims.get("services", ev.anchor)],
        confidence="inferred" if verified else "weak",
        method="model_hook",
        evidence=f"quote {'found' if verified else 'NOT found'} in company text: "
        f"'{quote[:_QUOTE_CHARS]}'",
    )
    return bool(verdict["value"]) and verified, claim_id


def _record_tier(company_id: str, call: _TierCall, ledger: EvidenceLedger) -> str:
    confidence = {
        "A": "strong",
        "B": "inferred",
        "C": "weak",
        "D": "inferred" if call.adjacent else "weak",
    }
    tier_id = ledger.derived(
        company_id,
        "fit_tier",
        call.tier,
        depends_on=list(dict.fromkeys(call.deps)),
        confidence=confidence[call.tier],
        method="keyword_rule",
        evidence=f"{call.tier} ({TIER_LABELS[call.tier]}): " + "; ".join(call.reasons),
    )
    return tier_id


def _record_flags(
    company_id: str, ev: _Evidence, call: _TierCall, thesis: Thesis, ledger: EvidenceLedger
) -> bool:
    """Record adjacent-trade and homeowner-only findings; return the homeowner-only flag."""
    if call.adjacent:
        ledger.derived(
            company_id,
            "adjacent_trade",
            True,
            depends_on=[ev.claims["services"]],
            confidence="inferred",
            method="keyword_rule",
            evidence=f"service text matches {call.adjacent_keywords} and no sector keyword",
        )
    residential = find_keywords(ev.service_text, thesis.residential_only_keywords)
    if residential:
        ledger.derived(
            company_id,
            "residential_only",
            True,
            depends_on=[ev.claims["services"]],
            confidence="inferred",
            method="keyword_rule",
            evidence=f"service text matches {residential}",
        )
    return bool(residential)


def _record_segment(
    company_id: str, ev: _Evidence, thesis: Thesis, ledger: EvidenceLedger
) -> tuple[str, str]:
    scores: dict[str, float] = {}
    for key, seg in thesis.segments.items():
        if key != "unknown":
            text_hits = len(find_keywords(ev.all_text, seg.keywords))
            name_hits = len(find_keywords(ev.names, seg.keywords))
            scores[key] = text_hits + thesis.classify.name_hit_weight * name_hits
    best = max(scores.values(), default=0.0)
    segment = (
        next((k for k, v in scores.items() if v == best), "unknown") if best > 0 else "unknown"
    )
    # A segment read only from the company's name is graded weak.
    from_text = any(find_keywords(ev.all_text, seg.keywords) for seg in thesis.segments.values())
    text_deps = [ev.claims[k] for k in ("services", "license") if k in ev.claims]
    shown = ", ".join(f"{k} {v:g}" for k, v in scores.items() if v > 0) or "none"
    claim = ledger.derived(
        company_id,
        "segment",
        segment,
        depends_on=[*text_deps, ev.anchor],
        confidence="inferred" if best > 0 and from_text else "weak",
        method="keyword_count",
        evidence=f"segment keyword hits: {shown}",
    )
    return segment, claim


def _record_mix(
    company_id: str, ev: _Evidence, thesis: Thesis, ledger: EvidenceLedger, fit_claim: str
) -> tuple[str, str]:
    recurring = find_keywords(ev.service_text, thesis.recurring_keywords)
    install = find_keywords(ev.service_text, thesis.install_keywords)
    r, i, k = len(recurring), len(install), thesis.classify.mix_dominance
    if r + i == 0:
        mix = "unknown"
    elif r >= k * i:
        mix = "recurring_heavy"
    elif i >= k * r:
        mix = "install_heavy"
    else:
        mix = "mixed"
    claim = ledger.derived(
        company_id,
        "service_mix",
        mix,
        depends_on=[ev.claims.get("services", fit_claim)],
        confidence="inferred" if mix != "unknown" else "weak",
        method="keyword_count",
        evidence=f"recurring terms {recurring or 'none'} vs install terms {install or 'none'}",
    )
    return mix, claim


def classify_company(
    company: Company,
    records: Sequence[RawRecord],
    thesis: Thesis,
    ledger: EvidenceLedger,
    *,
    anchor_claim: str,
    hook: ClassifierHook | None = None,
) -> tuple[FitResult, FitClaims]:
    """Classify sector fit, segment and service mix, recording every step in the ledger.

    Tier rules, strongest first: **A** a sector license, or an in-thesis NAICS code
    plus sector keywords in the company's own service text; **B** sector keywords
    in service text, or NAICS plus a sector word in the name; **C** only the name
    or only the NAICS code points to the sector; **D** nothing does, or the text
    points to an adjacent trade instead. The optional hook is consulted only for
    tiers C and D and can lift a company to B with a quote found in its own text.

    Args:
        company: The resolved company.
        records: Its source records.
        thesis: Keywords, NAICS codes and segment definitions.
        ledger: Ledger to append to.
        anchor_claim: Claim to cite when no other evidence exists (the name claim).
        hook: Optional model-classification function.

    Returns:
        The fit result and the ids of its key claims.
    """
    cid = company.company_id
    ev = _gather_evidence(company, records, thesis, ledger, anchor_claim)
    call = _decide_tier(ev, thesis)
    if hook is not None and call.tier in ("C", "D") and not call.adjacent:
        accepted, model_claim = _ask_hook(hook, company, ev, ledger)
        if accepted:
            call = _TierCall(
                "B",
                [*call.reasons, "model hook: in-sector with a verified quote"],
                [*call.deps, model_claim],
            )
    fit_claim = _record_tier(cid, call, ledger)
    residential = _record_flags(cid, ev, call, thesis, ledger)
    segment, segment_claim = _record_segment(cid, ev, thesis, ledger)
    mix, mix_claim = _record_mix(cid, ev, thesis, ledger, fit_claim)
    result = FitResult(
        tier=call.tier,
        fit_score=thesis.classify.tier_fit_score[call.tier],
        segment=segment,
        service_mix=mix,
        residential_only=residential,
        parent_owned=ev.parent_owned,
        adjacent_trade=call.adjacent,
    )
    return result, FitClaims(fit_claim, segment_claim, mix_claim)

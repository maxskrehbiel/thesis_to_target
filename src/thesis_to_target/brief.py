"""Markdown target brief: thesis, funnel, top targets and the evidence behind them."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .evidence import Claim, EvidenceLedger
from .formatting import usd_millions
from .models import Company
from .pipeline import Funnel, RunResult
from .qa import QaReport

# Companies profiled in detail below the target table.
_PROFILES = 3
_TOP_HEADER = (
    "| Rank | Tier | Company | State | Fit | Segment | EBITDA median (95% range) "
    "| P(in band) | Non-obvious | Sources |"
)
_TOP_RULE = "| ---: | --- | --- | --- | --- | --- | --- | ---: | --- | ---: |"
_PROFILE_CLAIMS = (
    ("Fit", "fit_tier"),
    ("Size", "ebitda_estimate"),
    ("P(EBITDA in band)", "p_ebitda_in_band"),
    ("Visibility", "obviousness"),
    ("Assembled from", "entity_resolution"),
)
_METHOD_NOTES = [
    "EBITDA median = employee-range midpoint x segment revenue per employee x service-mix "
    "margin. Uncertainty is log-normal, so each company carries P(EBITDA in band) rather "
    "than a point guess.",
    "",
    "Obviousness is the weighted share of large commercial databases (and the open web) "
    "that already list a company; non-obvious targets are the ones a database-only search misses.",
    "",
    "Every number above traces to `evidence_ledger.csv` "
    "(Claim, Value, Evidence, Source, Confidence).",
]


def _cell(text: str) -> str:
    return text.replace("|", "/")


def _target_row(c: Company) -> str:
    est, fit, presence = c.estimate, c.fit, c.presence
    if est:
        low, high = usd_millions(est.ebitda_lo), usd_millions(est.ebitda_hi)
        size = f"{usd_millions(est.ebitda_mid)} ({low} to {high})"
    else:
        size = "unsized"
    p = f"{est.p_in_band:.2f}" if est else "n/a"
    hidden = "yes" if presence and presence.non_obvious else "no"
    return (
        f"| {c.rank} | {c.tier} | {c.name} | {c.state} | {fit.tier if fit else '?'} | "
        f"{fit.segment if fit else '?'} | {size} | {p} | {hidden} | {len(c.sources)} |"
    )


def _header(result: RunResult) -> list[str]:
    t = result.thesis
    feeds = ", ".join(f"{s.feed} (trust {s.trust:g})" for s in t.sources)
    databases = ", ".join(p.database for p in t.presence_databases) or "none"
    if result.synthetic:
        origin = (
            f"Synthetic demonstration. Every company, source record, database listing and number "
            f"below was generated from seed {t.synthetic.seed}; no real business is described."
        )
    else:
        origin = "Built from the records supplied by the configured source adapters."
    return [
        f"# Target brief: {t.name}",
        "",
        f"> {origin}",
        "",
        "## Thesis",
        "",
        t.description,
        "",
        "| Parameter | Value |",
        "| --- | --- |",
        f"| EBITDA band | {usd_millions(t.ebitda_min)} to {usd_millions(t.ebitda_max)} |",
        f"| Geography | {', '.join(t.states)} |",
        f"| Sources | {feeds} |",
        f"| Presence checked in | {databases} |",
        "",
    ]


def _funnel_table(f: Funnel) -> list[str]:
    per_feed = ", ".join(f"{k} {v}" for k, v in f.records_by_feed.items())
    rows = [
        (f"Raw records ({per_feed})", f.raw_records),
        ("Companies after entity resolution", f.companies),
        ("Record pairs left for human review", f.review_pairs),
        ("In thesis geography", f.in_geography),
        ("In geography with sector evidence (fit tier A to C)", f.in_sector),
        ("In scope after all screens", f.in_scope),
        ("In scope and sized", f.sized),
        ("In scope with P(EBITDA in band) >= 0.5", f.likely_in_band),
        ("In scope and non-obvious", f.non_obvious),
        ("Priority tier", f.priority),
    ]
    return [
        "## Funnel",
        "",
        "| Step | Count |",
        "| --- | ---: |",
        *(f"| {k} | {v} |" for k, v in rows),
        "",
    ]


def _profile_row(label: str, claim: Claim | None) -> str:
    if claim is None:
        return f"| {label} | no claim recorded | | |"
    return f"| {label} | {_cell(claim.evidence)} | {claim.confidence} | `{claim.claim_id}` |"


def _profiles(ranked: Sequence[Company], ledger: EvidenceLedger) -> list[str]:
    lines = ["## Target profiles", ""]
    for c in ranked[:_PROFILES]:
        cid = c.company_id
        claims = ledger.for_company(cid)
        lines += [
            f"### {c.rank}. {c.name} ({cid}), {c.city}, {c.state}",
            "",
            "| Aspect | Evidence | Confidence | Claim |",
            "| --- | --- | --- | --- |",
            *(_profile_row(label, ledger.last(cid, name)) for label, name in _PROFILE_CLAIMS),
            "",
            f"Full trail: claims `{claims[0].claim_id}` to `{claims[-1].claim_id}` "
            "in `evidence_ledger.csv`.",
            "",
        ]
    return lines


def _open_items(result: RunResult) -> list[str]:
    flagged = [c.name for c in result.companies if c.flags]
    unsized = sum(1 for c in result.companies if c.in_scope and c.estimate is None)
    noun = "company" if unsized == 1 else "companies"
    return [
        "## Open items",
        "",
        f"- {result.funnel.review_pairs} record pair(s) in `review_queue.csv` "
        "await a merge/reject decision.",
        f"- {unsized} in-scope {noun} could not be sized (no size signal in any record).",
        f"- Clusters flagged for low cohesion: {', '.join(flagged) if flagged else 'none'}.",
        "",
    ]


def _qa_section(qa: QaReport, synthetic: bool) -> list[str]:
    res = qa.resolution
    scope = "These numbers describe synthetic data only." if synthetic else ""
    return [
        "## QA against ground truth",
        "",
        f"Graded against the ground truth the sources supplied. {scope}".strip(),
        "",
        "| Check | Result |",
        "| --- | --- |",
        f"| Entity resolution, pairwise precision | {res.precision:.3f} |",
        f"| Entity resolution, pairwise recall | {res.recall:.3f} |",
        f"| Records / true firms / resolved companies | {res.records} / {res.true_entities} / "
        f"{res.resolved_entities} |",
        f"| True EBITDA inside the reported 95% range | {qa.interval_coverage} "
        f"of {qa.ebitda_graded} graded |",
        f"| Mean P(in band) vs observed share in band | {qa.mean_p_in_band} "
        f"vs {qa.share_in_band} |",
        f"| Brier score of P(in band) | {qa.brier_score} |",
        f"| Presence flags agreeing with truth | {qa.presence_agreement} "
        f"of {qa.presence_checked} |",
        "",
    ]


def render_brief(result: RunResult) -> str:
    """Render the markdown brief for a finished run.

    Args:
        result: A finished pipeline run.

    Returns:
        Markdown text ending in a newline.
    """
    t = result.thesis
    ranked = result.ranked()
    lines = [
        *_header(result),
        *_funnel_table(result.funnel),
        f"## Top {min(t.brief_top_n, len(ranked))} targets",
        "",
        _TOP_HEADER,
        _TOP_RULE,
        *(_target_row(c) for c in ranked[: t.brief_top_n]),
        "",
        *_profiles(ranked, result.ledger),
        *_open_items(result),
        *(_qa_section(result.qa, result.synthetic) if result.qa is not None else []),
        "## Method notes",
        "",
        *_METHOD_NOTES,
        "",
    ]
    return "\n".join(lines)


def write_brief(result: RunResult, out_dir: str | Path) -> Path:
    """Write ``target_brief.md`` into ``out_dir`` and return its path."""
    path = Path(out_dir) / "target_brief.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_brief(result), encoding="utf-8", newline="\n")
    return path

"""End-to-end runs over injected sources, graded against the synthetic ground truth."""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import pytest

from thesis_to_target.errors import ConfigError, LedgerError
from thesis_to_target.models import RawRecord
from thesis_to_target.pipeline import RunResult, load_adjudications, required_claims, run_pipeline
from thesis_to_target.sources import SourceAdapter
from thesis_to_target.synthetic import build_world
from thesis_to_target.thesis import Thesis

Runner = Callable[..., RunResult]
PACKAGE = Path(__file__).resolve().parents[1] / "src" / "thesis_to_target"


def test_funnel_narrows_step_by_step(demo_run: RunResult) -> None:
    f = demo_run.funnel
    assert f.raw_records == sum(f.records_by_feed.values()) == len(demo_run.records)
    assert f.companies == len(demo_run.companies)
    assert f.companies >= f.in_geography >= f.in_sector >= f.in_scope >= f.sized >= f.likely_in_band
    assert f.non_obvious <= f.in_scope
    assert f.priority <= min(f.in_scope, demo_run.thesis.ranking.priority_max_rank)
    assert f.review_pairs == len(demo_run.review_queue)
    ranked = demo_run.ranked()
    assert len(ranked) == f.in_scope and sum(c.tier == "Priority" for c in ranked) == f.priority


def test_resolution_matches_ground_truth(demo_run: RunResult) -> None:
    assert demo_run.qa is not None and demo_run.synthetic
    res = demo_run.qa.resolution
    assert res.precision >= 0.95 and res.recall >= 0.90
    assert res.records == len(demo_run.records)


def test_planted_look_alikes_stay_apart(demo_run: RunResult) -> None:
    world = build_world(demo_run.thesis.synthetic)
    cores = Counter(f.core for f in world.firms)
    assert any(n > 1 for n in cores.values())  # the world does contain look-alikes
    for company in demo_run.companies:
        firms = {world.truth[r] for r in company.member_ids}
        assert len(firms) == 1, f"{company.company_id} merged distinct firms {sorted(firms)}"


def test_estimates_are_calibrated_on_synthetic_truth(demo_run: RunResult) -> None:
    qa = demo_run.qa
    assert qa is not None and qa.ebitda_graded > 10
    assert qa.interval_coverage is not None and qa.interval_coverage >= 0.8
    assert qa.mean_p_in_band is not None and qa.share_in_band is not None
    assert abs(qa.mean_p_in_band - qa.share_in_band) < 0.15
    assert qa.presence_agreement is not None and qa.presence_agreement >= 0.9


def test_every_exported_company_has_its_claims(demo_run: RunResult) -> None:
    for company in demo_run.companies:
        present = {c.claim for c in demo_run.ledger.for_company(company.company_id)}
        assert set(required_claims(company)) <= present
        if company.in_scope:
            assert company.tier in ("Priority", "Watchlist") and company.rank is not None
        else:
            assert company.tier == "Excluded" and company.rank is None and company.composite is None


def test_runs_are_deterministic(demo_thesis: Thesis, demo_run: RunResult, runner: Runner) -> None:
    again = runner(demo_thesis)
    assert [(c.company_id, c.rank, c.composite) for c in again.companies] == [
        (c.company_id, c.rank, c.composite) for c in demo_run.companies
    ]
    assert [c.evidence for c in again.ledger] == [c.evidence for c in demo_run.ledger]


def test_adjudications_round_trip(
    tmp_path: Path, demo_thesis: Thesis, demo_run: RunResult, runner: Runner
) -> None:
    pair = demo_run.review_queue[0]
    sheet = tmp_path / "review.csv"
    sheet.write_text(
        f"record_a,record_b,decision\n{pair.a},{pair.b},merge\nX-1,X-2,maybe\n", encoding="utf-8"
    )
    decisions = load_adjudications(sheet)
    assert decisions == {(pair.a, pair.b): "merge"}
    rerun = runner(demo_thesis, decisions)
    owner = {m: c.company_id for c in rerun.companies for m in c.member_ids}
    assert owner[pair.a] == owner[pair.b]
    assert len(rerun.companies) == len(demo_run.companies) - 1


def test_adjudication_file_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_adjudications(tmp_path / "missing.csv")
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b,decision\n1,2,merge\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="needs columns"):
        load_adjudications(bad)


def test_broken_ledger_stops_the_run(
    monkeypatch: pytest.MonkeyPatch, demo_thesis: Thesis, runner: Runner
) -> None:
    monkeypatch.setattr(
        "thesis_to_target.pipeline.required_claims", lambda company: ["claim_nobody_writes"]
    )
    with pytest.raises(LedgerError, match="failed verification"):
        runner(demo_thesis)


class UnlabeledFeed(SourceAdapter):
    """A source with no ground truth, like any real feed."""

    def fetch(self, thesis: Thesis) -> list[RawRecord]:
        return [RawRecord("U-1", self.feed, "Braxmoor Fire Protection", state="IL")]


def test_sources_without_ground_truth_get_no_qa_and_no_synthetic_label(demo_thesis: Thesis) -> None:
    result = run_pipeline(demo_thesis, [UnlabeledFeed("feed")], [])
    assert result.qa is None and not result.synthetic
    assert [c.name for c in result.companies] == ["Braxmoor Fire Protection"]


def test_core_pipeline_never_imports_the_generator() -> None:
    core = [p for p in PACKAGE.glob("*.py") if p.name not in {"registry.py", "cli.py"}]
    for path in core:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not any("synthetic" in m for m in modules), path.name

"""Markdown target brief."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from thesis_to_target.brief import render_brief, write_brief
from thesis_to_target.pipeline import RunResult


def test_brief_is_labeled_and_cites_the_ledger(demo_run: RunResult) -> None:
    text = render_brief(demo_run)
    assert "> Synthetic demonstration." in text
    assert "## Funnel" in text and "## QA against ground truth" in text
    top = demo_run.ranked()[0]
    assert f"| 1 | {top.tier} | {top.name} |" in text
    assert f"`{top.company_id}.01`" in text
    assert "- **" not in text  # no bold lead-in bullets
    assert text.endswith("\n") and "\r" not in text


def test_brief_for_labeled_real_sources(demo_run: RunResult) -> None:
    text = render_brief(dataclasses.replace(demo_run, synthetic=False))
    assert "Synthetic demonstration" not in text and "configured source adapters" in text
    assert "synthetic data only" not in text


def test_brief_without_ground_truth(demo_run: RunResult) -> None:
    text = render_brief(dataclasses.replace(demo_run, qa=None))
    assert "## QA against ground truth" not in text


def test_write_brief_uses_relative_names_only(tmp_path: Path, demo_run: RunResult) -> None:
    path = write_brief(demo_run, tmp_path)
    content = path.read_text(encoding="utf-8")
    assert path.name == "target_brief.md"
    assert str(tmp_path) not in content and "\\" not in content

"""Shared fixtures: the packaged demo thesis, one cached demo run and a record factory."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from thesis_to_target.config import ResolveConfig
from thesis_to_target.models import RawRecord
from thesis_to_target.pipeline import RunResult, run_pipeline
from thesis_to_target.registry import build_adapters, build_presence_checkers
from thesis_to_target.thesis import Thesis, load_demo_thesis

RecordFactory = Callable[..., RawRecord]
Runner = Callable[..., RunResult]


def run_thesis(
    thesis: Thesis, adjudications: dict[tuple[str, str], str] | None = None
) -> RunResult:
    """Run a thesis with the adapters and checkers it names."""
    return run_pipeline(
        thesis, build_adapters(thesis), build_presence_checkers(thesis), adjudications
    )


@pytest.fixture(scope="session")
def runner() -> Runner:
    """Run a thesis end to end with the components it names."""
    return run_thesis


@pytest.fixture(scope="session")
def demo_thesis() -> Thesis:
    return load_demo_thesis()


@pytest.fixture(scope="session")
def demo_run(demo_thesis: Thesis) -> RunResult:
    return run_thesis(demo_thesis)


@pytest.fixture(scope="session")
def fire_cfg(demo_thesis: Thesis) -> ResolveConfig:
    """Resolution config carrying the demo thesis's industry vocabulary."""
    return demo_thesis.resolve


@pytest.fixture
def make_record() -> RecordFactory:
    def factory(record_id: str, name: str, source: str = "web_listing", **fields: Any) -> RawRecord:
        fields.setdefault("state", "IL")
        return RawRecord(record_id=record_id, source=source, name=name, **fields)

    return factory

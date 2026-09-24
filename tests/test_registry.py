"""Plugging in a custom source adapter and presence checker."""

from __future__ import annotations

import dataclasses

import pytest

from thesis_to_target.models import Company, RawRecord
from thesis_to_target.pipeline import run_pipeline
from thesis_to_target.presence import PresenceChecker, PresenceHit
from thesis_to_target.registry import (
    UnknownComponentError,
    build_adapters,
    build_presence_checkers,
    register_adapter,
    register_presence,
)
from thesis_to_target.sources import SourceAdapter
from thesis_to_target.thesis import PresenceSpec, SourceSpec, Thesis


class InlineAdapter(SourceAdapter):
    """A two-record feed, standing in for any real source."""

    def fetch(self, thesis: Thesis) -> list[RawRecord]:
        return [
            RawRecord(
                "IN-1",
                self.feed,
                "Braxmoor Fire Protection, Inc.",
                state="IL",
                attributes={"license_type": "Fire Sprinkler Contractor", "employee_band": "50-99"},
            ),
            RawRecord(
                "IN-2", self.feed, "Braxmoor Fire Protection", state="IL", phone="217-555-0142"
            ),
        ]


class NeverListed(PresenceChecker):
    def lookup(self, company: Company) -> PresenceHit:
        return PresenceHit(self.database, False, None, None, 0.0, company.name)


def test_custom_components_run_end_to_end(demo_thesis: Thesis) -> None:
    register_adapter("inline", InlineAdapter)
    register_presence("never", lambda thesis, spec: NeverListed(spec.database, spec.weight))
    thesis = dataclasses.replace(
        demo_thesis,
        sources=(SourceSpec("inline", "inline_feed", 0.8),),
        presence_databases=(PresenceSpec("never", "db_x", 0.5),),
    )
    assert [a.feed for a in build_adapters(thesis)] == ["inline_feed"]
    assert [c.database for c in build_presence_checkers(thesis)] == ["db_x"]
    result = run_pipeline(thesis, build_adapters(thesis), build_presence_checkers(thesis))
    assert result.qa is None and not result.synthetic  # an unlabeled source gets no grading
    (company,) = result.companies
    assert company.fit is not None and company.fit.tier == "A"
    assert company.presence is not None and company.presence.non_obvious


def test_unknown_components_are_rejected(demo_thesis: Thesis) -> None:
    with pytest.raises(UnknownComponentError, match="unknown source adapter"):
        build_adapters(dataclasses.replace(demo_thesis, sources=(SourceSpec("nope", "f"),)))
    with pytest.raises(UnknownComponentError, match="unknown presence checker"):
        build_presence_checkers(
            dataclasses.replace(demo_thesis, presence_databases=(PresenceSpec("nope", "d", 1),))
        )

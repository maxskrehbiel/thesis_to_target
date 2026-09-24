"""Thesis loading and validation."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from thesis_to_target.config import SyntheticSettings
from thesis_to_target.errors import ConfigError, ThesisError
from thesis_to_target.thesis import (
    Thesis,
    demo_thesis_text,
    load_demo_thesis,
    load_thesis,
    thesis_from_mapping,
)


@pytest.fixture
def raw() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(demo_thesis_text())
    return data


def test_demo_thesis_ships_as_package_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # works from any directory
    thesis = load_demo_thesis()
    assert thesis.name.startswith("Commercial fire")
    text = demo_thesis_text()
    assert "\r" not in text and text.endswith("\n")
    copy_path = tmp_path / "thesis.yaml"
    copy_path.write_text(text, encoding="utf-8", newline="\n")
    assert load_thesis(copy_path) == thesis


def test_example_thesis_loads(demo_thesis: Thesis) -> None:
    assert demo_thesis.ebitda_min == 1_000_000 and demo_thesis.ebitda_max == 5_000_000
    assert "IL" in demo_thesis.states and "TX" not in demo_thesis.states
    assert demo_thesis.source_trust()["business_registry"] == 0.9
    assert demo_thesis.revenue_per_employee("sprinkler") == (150_000, 210_000)
    assert (
        demo_thesis.revenue_per_employee("no_such_segment")
        == demo_thesis.segments["unknown"].revenue_per_employee
    )
    assert demo_thesis.margin("no_such_mix") == demo_thesis.margins["unknown"]
    assert demo_thesis.estimation.interval_mode == "endpoints"
    assert [p.database for p in demo_thesis.presence_databases] == [
        "commercial_db_a",
        "commercial_db_b",
        "investor_db",
    ]


def test_with_synthetic_overrides(demo_thesis: Thesis) -> None:
    changed = demo_thesis.with_synthetic(seed=7, n_firms=30)
    assert (changed.synthetic.seed, changed.synthetic.n_firms) == (7, 30)
    assert demo_thesis.synthetic.seed == 42
    with pytest.raises(ConfigError, match="n_firms"):
        demo_thesis.with_synthetic(n_firms=3)
    with pytest.raises(ConfigError, match="seed"):
        SyntheticSettings(seed=-1)


def _mutated(raw: dict[str, Any], path: list[str], value: Any) -> dict[str, Any]:
    data = copy.deepcopy(raw)
    node = data
    for key in path[:-1]:
        node = node[key]
    if value is None:
        node.pop(path[-1])
    else:
        node[path[-1]] = value
    return data


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (["thesis"], None, "missing required field"),
        (["size", "ebitda_max"], 500_000, "ebitda_min < ebitda_max"),
        (["geography", "states"], ["Illinois"], "two-letter"),
        (["industry", "segments", "unknown"], None, "'unknown' fallback"),
        (
            ["industry", "segments", "alarm", "revenue_per_employee"],
            [200_000, 100_000],
            "low <= high",
        ),
        (["industry", "service_mix", "ebitda_margin", "mixed"], None, "must define 'mixed'"),
        (["industry", "service_mix", "ebitda_margin", "mixed"], [0.5, 1.5], "fraction below 1"),
        (["sources"], [{"adapter": "synthetic"}], "needs 'adapter' and 'feed'"),
        (
            ["sources"],
            [{"adapter": "synthetic", "feed": "x"}, {"adapter": "synthetic", "feed": "x"}],
            "only be listed once",
        ),
        (["sources"], [{"adapter": "synthetic", "feed": "x", "trust": 2}], "trust must be between"),
        (["resolve", "merge_threshold"], 50, "review_threshold <= merge_threshold"),
        (["resolve", "no_such_knob"], 1, "resolve"),
        (["estimation", "interval_mode"], "guess", "interval_mode"),
        (["ranking", "weights"], {"fit": -1}, "non-negative"),
        (
            ["presence", "databases"],
            [{"checker": "synthetic"}],
            "needs checker, database and weight",
        ),
        (
            ["presence", "databases"],
            [{"checker": "synthetic", "database": "d", "weight": -1}],
            "non-negative",
        ),
        (["classify", "llm_hook"], {"enabled": True}, "no llm_hook"),
        (["industry", "include_keywords"], "fire", "must be a list"),
        (["size", "ebitda_min"], "one million", "invalid value"),
        (["output", "brief_top_n"], 0, "brief_top_n"),
        (["resolve", "extra_abbreviations"], ["prot"], "must be a mapping"),
    ],
)
def test_invalid_theses_are_rejected(
    raw: dict[str, Any], path: list[str], value: Any, message: str
) -> None:
    with pytest.raises(ThesisError, match=message):
        thesis_from_mapping(_mutated(raw, path, value))


def test_nested_overrides_and_industry_vocabulary(raw: dict[str, Any]) -> None:
    data = _mutated(raw, ["estimation", "stated_headcount"], {"lo_mult": 0.9})
    data = _mutated(data, ["resolve", "extra_generic_tokens"], ["Protective Services"])
    data = _mutated(data, ["resolve", "extra_abbreviations"], {"PROTV": "Protective"})
    thesis = thesis_from_mapping(data)
    assert thesis.estimation.stated_headcount.lo_mult == 0.9
    assert thesis.estimation.stated_headcount.hi_mult == 1.25
    assert "protective service" in thesis.resolve.generic_tokens
    assert thesis.resolve.abbreviations["protv"] == "protective"
    assert thesis.resolve.abbreviations["svcs"] == "service"  # business defaults are kept


def test_demo_thesis_carries_its_industry_vocabulary(demo_thesis: Thesis) -> None:
    assert {"fire", "sprinkler", "protection"} <= demo_thesis.resolve.generic_tokens
    assert demo_thesis.resolve.abbreviations["prot"] == "protection"


def test_file_errors(tmp_path: Path) -> None:
    with pytest.raises(ThesisError, match="not found"):
        load_thesis(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("thesis: [unclosed", encoding="utf-8")
    with pytest.raises(ThesisError, match="not valid YAML"):
        load_thesis(bad)
    with pytest.raises(ThesisError, match="mapping"):
        thesis_from_mapping(["not", "a", "mapping"])

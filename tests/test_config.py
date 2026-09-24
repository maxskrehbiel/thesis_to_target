"""Validation in every stage-configuration dataclass."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from thesis_to_target.config import (
    ClassifyConfig,
    EstimationConfig,
    PresenceConfig,
    RankConfig,
    ResolveConfig,
    SignalRule,
    SyntheticSettings,
)
from thesis_to_target.errors import ConfigError


def test_defaults_are_valid() -> None:
    for cls in (
        ResolveConfig,
        EstimationConfig,
        PresenceConfig,
        RankConfig,
        ClassifyConfig,
        SyntheticSettings,
    ):
        cls()
    assert RankConfig().total_weight == pytest.approx(1.0)
    assert EstimationConfig().interval_mode == "endpoints"


@pytest.mark.parametrize(
    ("build", "message"),
    [
        (lambda: ResolveConfig(review_threshold=95, merge_threshold=90), "review_threshold"),
        (lambda: ResolveConfig(merge_threshold=101), "merge_threshold <= 100"),
        (lambda: ResolveConfig(max_block_size=1), "max_block_size"),
        (lambda: ResolveConfig(prefix_length=0), "prefix_length"),
        (lambda: SignalRule(2.0, 1.0, 0.5), "lo_mult <= hi_mult"),
        (lambda: SignalRule(1.0, 2.0, 0.0), "weight > 0"),
        (lambda: EstimationConfig(interval_mode="guess"), "interval_mode"),
        (lambda: EstimationConfig(min_sigma=0), "min_sigma"),
        (lambda: PresenceConfig(non_obvious_below=1.5), "non_obvious_below"),
        (lambda: PresenceConfig(web_presence_weight=-0.1), "web_presence_weight"),
        (lambda: RankConfig(weight_fit=-1), "non-negative"),
        (lambda: RankConfig(0, 0, 0, 0), "not all zero"),
        (lambda: RankConfig(priority_min_p_in_band=2), "priority_min_p_in_band"),
        (lambda: RankConfig(priority_max_rank=0), "priority_max_rank"),
        (lambda: ClassifyConfig(tier_fit_score={"A": 1.0}), "tiers A, B, C and D"),
        (lambda: ClassifyConfig(mix_dominance=0.5), "mix_dominance"),
        (lambda: ClassifyConfig(llm_hook_enabled=True), "no llm_hook"),
        (lambda: SyntheticSettings(n_firms=5), "n_firms"),
        (lambda: SyntheticSettings(seed=-3), "seed"),
    ],
)
def test_invalid_values_raise_config_error(build: Callable[[], Any], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        build()

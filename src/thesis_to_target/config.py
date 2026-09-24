"""Tunable parameters for every pipeline stage, as frozen dataclasses with documented defaults."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .errors import ConfigError
from .normalize import BUSINESS_ABBREVIATIONS

#: Normalized business words that carry no identity on their own, in any industry.
#: A thesis adds its own industry words (see ``resolve.extra_generic_tokens``).
# fmt: off
BUSINESS_GENERIC_TOKENS: frozenset[str] = frozenset({
    "service", "system", "solutions", "group", "contractor", "company", "holdings",
    "enterprises", "associates", "brothers", "partners", "industries", "national",
    "international", "technology", "management", "equipment",
})
# fmt: on

INTERVAL_MODES = ("independent", "endpoints")
FIT_TIERS = ("A", "B", "C", "D")


def _require_fraction(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ConfigError(f"{name} must be between 0 and 1, got {value}")


@dataclass(frozen=True)
class ResolveConfig:
    """Entity-resolution scoring on a 0-100 scale, plus the name vocabulary.

    Attributes:
        merge_threshold: Pair score at or above which two records are merged.
        review_threshold: Pair score at or above which an unmerged pair is queued for review.
        phone_bonus: Points added when both records carry the same phone number.
        website_bonus: Points added when both records carry the same website host.
        zip_bonus: Points added when both records share a five-digit ZIP code.
        state_mismatch_penalty: Points removed when the records name different states.
        distinctive_slack: How far the name score may exceed the score of the
            non-generic tokens alone.
        cohesion_floor: Clusters whose weakest member pair scores below this are flagged.
        max_block_size: Blocks larger than this are skipped, e.g. a shared call-center line.
        prefix_length: Letters of the first distinctive token used as a blocking key.
        generic_tokens: Normalized words ignored when judging distinctiveness.
        abbreviations: Token -> canonical token map applied during name normalization.
    """

    merge_threshold: float = 92.0
    review_threshold: float = 80.0
    phone_bonus: float = 8.0
    website_bonus: float = 8.0
    zip_bonus: float = 3.0
    state_mismatch_penalty: float = 15.0
    distinctive_slack: float = 15.0
    cohesion_floor: float = 70.0
    max_block_size: int = 200
    prefix_length: int = 3
    generic_tokens: frozenset[str] = BUSINESS_GENERIC_TOKENS
    abbreviations: Mapping[str, str] = field(default_factory=lambda: dict(BUSINESS_ABBREVIATIONS))

    def __post_init__(self) -> None:
        if not 0 <= self.review_threshold <= self.merge_threshold <= 100:
            raise ConfigError("need 0 <= review_threshold <= merge_threshold <= 100")
        if self.max_block_size < 2 or self.prefix_length < 1:
            raise ConfigError("max_block_size must be >= 2 and prefix_length >= 1")


@dataclass(frozen=True)
class SignalRule:
    """Conversion of one kind of size evidence into an employee range.

    Attributes:
        lo_mult: Multiplier applied to the reported number for the low end.
        hi_mult: Multiplier applied to the reported number for the high end.
        weight: Vote of this signal when several signals are combined.
        is_floor: True when the signal only proves a minimum size.
        min_value: Reported values below this are ignored as uninformative.
    """

    lo_mult: float
    hi_mult: float
    weight: float
    is_floor: bool = False
    min_value: float = 1.0

    def __post_init__(self) -> None:
        if not 0 < self.lo_mult <= self.hi_mult or self.weight <= 0:
            raise ConfigError("a size-signal rule needs 0 < lo_mult <= hi_mult and weight > 0")


@dataclass(frozen=True)
class EstimationConfig:
    """Employee-range combination and the log-normal EBITDA model.

    Attributes:
        interval_mode: ``"endpoints"`` treats (low x low x low, high x high x high) as the
            95% EBITDA range; ``"independent"`` adds the three factor uncertainties in
            quadrature, which is narrower.
        interval_z: Every input range is read as a central interval of this z-width
            (1.96 = 95%).
        min_sigma: Floor on the log-space standard deviation, so no estimate is
            ever presented as near-certain.
        band_weight: Vote of a reported employee band such as ``"20-49"``.
        open_band_hi_mult: Upper end of an open band ``"500+"`` as a multiple of its floor.
        stated_headcount: Rule for a headcount a company states about itself.
        locations: Rule for the number of operating locations.
        licensed_technicians: Rule for the count of licensed individuals (a floor).
        floor_hi_mult: When a floor lifts the low end, the high end is at least this
            multiple of the floor.
        conflict_tolerance: Two ranges conflict when one's low end exceeds the other's
            high end by more than this factor.
        high_min_signals: Independent signals needed for "high" confidence.
        high_max_spread: Maximum ln(high / low) of the employee range for "high".
        medium_min_signals: Independent signals needed for "medium" confidence.
        medium_max_spread: Maximum ln(high / low) of the employee range for "medium".
    """

    interval_mode: str = "endpoints"
    interval_z: float = 1.959963984540054
    min_sigma: float = 0.15
    band_weight: float = 1.0
    open_band_hi_mult: float = 3.0
    stated_headcount: SignalRule = field(default_factory=lambda: SignalRule(0.85, 1.25, 0.9))
    locations: SignalRule = field(default_factory=lambda: SignalRule(6.0, 25.0, 0.5, min_value=2))
    licensed_technicians: SignalRule = field(
        default_factory=lambda: SignalRule(1.25, 4.0, 0.6, is_floor=True, min_value=2)
    )
    floor_hi_mult: float = 1.5
    conflict_tolerance: float = 1.25
    high_min_signals: int = 3
    high_max_spread: float = 1.2
    medium_min_signals: int = 2
    medium_max_spread: float = 2.0

    def __post_init__(self) -> None:
        if self.interval_mode not in INTERVAL_MODES:
            raise ConfigError(f"interval_mode must be one of {INTERVAL_MODES}")
        if self.interval_z <= 0 or self.min_sigma <= 0:
            raise ConfigError("interval_z and min_sigma must be positive")


@dataclass(frozen=True)
class PresenceConfig:
    """Presence lookups and the obviousness score.

    Attributes:
        match_threshold: Name score (0-100) needed to call a database listing a match.
        confirmed_score: Name score at or above which a match is recorded as confirmed.
        web_presence_weight: Weight of "has its own website" in the obviousness score.
        non_obvious_below: Companies with obviousness below this are flagged non-obvious.
    """

    match_threshold: float = 90.0
    confirmed_score: float = 95.0
    web_presence_weight: float = 0.10
    non_obvious_below: float = 0.30

    def __post_init__(self) -> None:
        _require_fraction("non_obvious_below", self.non_obvious_below)
        if self.web_presence_weight < 0:
            raise ConfigError("web_presence_weight must be non-negative")


@dataclass(frozen=True)
class RankConfig:
    """Composite score weights and tier cut-offs.

    Attributes:
        weight_p_in_band: Weight of P(EBITDA within the thesis band).
        weight_fit: Weight of the sector-fit score.
        weight_non_obvious: Weight of (1 - obviousness).
        weight_evidence: Weight of evidence strength (corroboration and size confidence).
        priority_max_rank: Only ranks up to this can be tiered Priority.
        priority_min_p_in_band: Minimum P(EBITDA in band) for the Priority tier.
        source_saturation: Number of distinct sources that earns full corroboration credit.
        size_confidence_credit: Evidence credit per size-confidence grade.
    """

    weight_p_in_band: float = 0.45
    weight_fit: float = 0.25
    weight_non_obvious: float = 0.20
    weight_evidence: float = 0.10
    priority_max_rank: int = 12
    priority_min_p_in_band: float = 0.40
    source_saturation: int = 3
    size_confidence_credit: Mapping[str, float] = field(
        default_factory=lambda: {"high": 1.0, "medium": 0.65, "low": 0.35}
    )

    def __post_init__(self) -> None:
        weights = (
            self.weight_p_in_band,
            self.weight_fit,
            self.weight_non_obvious,
            self.weight_evidence,
        )
        if any(w < 0 for w in weights) or sum(weights) <= 0:
            raise ConfigError("ranking weights must be non-negative and not all zero")
        _require_fraction("priority_min_p_in_band", self.priority_min_p_in_band)
        if self.priority_max_rank < 1 or self.source_saturation < 1:
            raise ConfigError("priority_max_rank and source_saturation must be >= 1")

    @property
    def total_weight(self) -> float:
        """Sum of the four composite weights."""
        return (
            self.weight_p_in_band + self.weight_fit + self.weight_non_obvious + self.weight_evidence
        )


@dataclass(frozen=True)
class ClassifyConfig:
    """Fit-tier scores and the optional model-classification hook.

    Attributes:
        tier_fit_score: Fit score (0-1) awarded to each tier.
        name_hit_weight: Weight of a segment keyword found only in the name,
            relative to one found in the company's own service text.
        mix_dominance: One revenue type must outnumber the other by this factor
            for a "recurring_heavy" or "install_heavy" call; otherwise "mixed".
        llm_hook_enabled: Whether to call an external classification function.
        llm_hook: Import path ``"package.module:function"`` of that function.
    """

    tier_fit_score: Mapping[str, float] = field(
        default_factory=lambda: {"A": 1.0, "B": 0.75, "C": 0.4, "D": 0.0}
    )
    name_hit_weight: float = 0.5
    mix_dominance: float = 2.0
    llm_hook_enabled: bool = False
    llm_hook: str | None = None

    def __post_init__(self) -> None:
        if set(self.tier_fit_score) != set(FIT_TIERS):
            raise ConfigError("tier_fit_score must define tiers A, B, C and D")
        if self.mix_dominance < 1:
            raise ConfigError("mix_dominance must be at least 1")
        if self.llm_hook_enabled and not self.llm_hook:
            raise ConfigError("llm_hook_enabled is true but no llm_hook import path is set")


@dataclass(frozen=True)
class SyntheticSettings:
    """Seed and size of the synthetic world used by the synthetic source adapter.

    Attributes:
        seed: Random seed; the same seed always produces the same world.
        n_firms: Number of base firms before hard-negative look-alikes are added. The
            upper limit depends on the generator's fixed name and phone pools and is
            checked when the world is built.
    """

    seed: int = 42
    n_firms: int = 60

    def __post_init__(self) -> None:
        if self.seed < 0:
            raise ConfigError("seed must be non-negative")
        if self.n_firms < 10:
            raise ConfigError("n_firms must be at least 10")

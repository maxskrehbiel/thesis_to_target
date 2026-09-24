"""Load and validate an investment thesis from YAML into frozen configuration objects."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import yaml

from .config import (
    ClassifyConfig,
    EstimationConfig,
    PresenceConfig,
    RankConfig,
    ResolveConfig,
    SyntheticSettings,
)
from .errors import ThesisError, ThesisToTargetError
from .normalize import normalize_name

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

    _D = TypeVar("_D", bound=DataclassInstance)

SERVICE_MIXES = ("recurring_heavy", "mixed", "install_heavy", "unknown")
#: Package resource holding the demo thesis that ``thesis_to_target demo`` runs.
DEMO_THESIS_RESOURCE = "resources/demo_thesis.yaml"
_STATE_CODE_LENGTH = 2


@dataclass(frozen=True)
class Segment:
    """One sub-sector of the thesis with its own economics.

    Attributes:
        name: Segment key, e.g. ``"sprinkler"``.
        keywords: Phrases whose presence points to this segment.
        revenue_per_employee: ``(low, high)`` annual revenue per employee, USD.
    """

    name: str
    keywords: tuple[str, ...]
    revenue_per_employee: tuple[float, float]


@dataclass(frozen=True)
class SourceSpec:
    """One entry of the thesis ``sources`` list.

    Attributes:
        adapter: Registered adapter name.
        feed: Feed name, unique across the thesis.
        trust: Weight of this feed when records disagree (0-1).
        options: Extra keyword options passed to the adapter.
    """

    adapter: str
    feed: str
    trust: float = 0.5
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PresenceSpec:
    """One database the obviousness score checks.

    Attributes:
        checker: Registered presence-checker name.
        database: Database name.
        weight: Weight of this database in the obviousness score.
    """

    checker: str
    database: str
    weight: float


@dataclass(frozen=True)
class Thesis:
    """A validated investment thesis and every stage configuration it implies.

    Attributes:
        name: Short thesis title.
        description: One-paragraph description.
        naics: NAICS codes (or prefixes) that count as in-sector.
        include_keywords: Phrases that indicate the thesis sector.
        adjacent_keywords: Phrases that indicate a neighboring, out-of-thesis trade.
        residential_only_keywords: Phrases that indicate a homeowner-only business.
        segments: Segment definitions, always including ``"unknown"``.
        recurring_keywords: Phrases that indicate recurring (inspection/service) revenue.
        install_keywords: Phrases that indicate project (installation) revenue.
        margins: Service mix -> ``(low, high)`` EBITDA margin.
        ebitda_min: Lower edge of the target EBITDA band, USD.
        ebitda_max: Upper edge of the target EBITDA band, USD.
        states: Two-letter state codes in scope.
        sources: Feeds to pull records from.
        presence_databases: Databases checked for the obviousness score.
        synthetic: Seed and size of the synthetic world.
        resolve: Entity-resolution configuration.
        estimation: EBITDA-estimation configuration.
        presence: Presence and obviousness configuration.
        ranking: Composite score and tier configuration.
        classify: Fit-tier scores and optional model hook.
        brief_top_n: Rows shown in the markdown brief's target table.
    """

    name: str
    description: str
    naics: tuple[str, ...]
    include_keywords: tuple[str, ...]
    adjacent_keywords: tuple[str, ...]
    residential_only_keywords: tuple[str, ...]
    segments: Mapping[str, Segment]
    recurring_keywords: tuple[str, ...]
    install_keywords: tuple[str, ...]
    margins: Mapping[str, tuple[float, float]]
    ebitda_min: float
    ebitda_max: float
    states: tuple[str, ...]
    sources: tuple[SourceSpec, ...]
    presence_databases: tuple[PresenceSpec, ...] = ()
    synthetic: SyntheticSettings = field(default_factory=SyntheticSettings)
    resolve: ResolveConfig = field(default_factory=ResolveConfig)
    estimation: EstimationConfig = field(default_factory=EstimationConfig)
    presence: PresenceConfig = field(default_factory=PresenceConfig)
    ranking: RankConfig = field(default_factory=RankConfig)
    classify: ClassifyConfig = field(default_factory=ClassifyConfig)
    brief_top_n: int = 10

    def source_trust(self) -> dict[str, float]:
        """Map each feed name to its trust weight."""
        return {s.feed: s.trust for s in self.sources}

    def revenue_per_employee(self, segment: str) -> tuple[float, float]:
        """Revenue-per-employee range of a segment, falling back to ``"unknown"``."""
        seg = self.segments.get(segment) or self.segments["unknown"]
        return seg.revenue_per_employee

    def margin(self, service_mix: str) -> tuple[float, float]:
        """EBITDA-margin range of a service mix, falling back to ``"unknown"``."""
        return self.margins.get(service_mix) or self.margins["unknown"]

    def with_synthetic(self, *, seed: int | None = None, n_firms: int | None = None) -> Thesis:
        """Return a copy with the synthetic seed and/or size overridden."""
        changes: dict[str, int] = {}
        if seed is not None:
            changes["seed"] = seed
        if n_firms is not None:
            changes["n_firms"] = n_firms
        return dataclasses.replace(self, synthetic=dataclasses.replace(self.synthetic, **changes))


def _mapping(raw: Any, where: str) -> Mapping[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ThesisError(f"{where} must be a mapping")
    return raw


def _required(raw: Mapping[str, Any], key: str, where: str) -> Any:
    value = raw.get(key)
    if value is None or value == "" or value == []:
        raise ThesisError(f"missing required field: {where}.{key}")
    return value


def _strings(raw: Any, where: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        raise ThesisError(f"{where} must be a list")
    return tuple(str(item).lower().strip() for item in raw)


def _range(raw: Any, where: str) -> tuple[float, float]:
    if not isinstance(raw, Sequence) or isinstance(raw, str) or len(raw) != 2:
        raise ThesisError(f"{where}: expected [low, high], got {raw!r}")
    lo, hi = float(raw[0]), float(raw[1])
    if not 0 < lo <= hi:
        raise ThesisError(f"{where}: need 0 < low <= high, got [{lo}, {hi}]")
    return lo, hi


def _override(default: _D, raw: Mapping[str, Any], where: str) -> _D:
    try:
        return dataclasses.replace(default, **dict(raw))
    except (TypeError, ValueError) as exc:
        raise ThesisError(f"{where}: {exc}") from exc


def _segments(raw: Mapping[str, Any]) -> dict[str, Segment]:
    segments: dict[str, Segment] = {}
    for seg_name, seg in _mapping(
        _required(raw, "segments", "industry"), "industry.segments"
    ).items():
        where = f"industry.segments.{seg_name}"
        spec = _mapping(seg, where)
        segments[str(seg_name)] = Segment(
            name=str(seg_name),
            keywords=_strings(spec.get("keywords"), f"{where}.keywords"),
            revenue_per_employee=_range(
                spec.get("revenue_per_employee"), f"{where}.revenue_per_employee"
            ),
        )
    if "unknown" not in segments:
        raise ThesisError("industry.segments must include an 'unknown' fallback segment")
    return segments


def _margins(raw: Mapping[str, Any]) -> dict[str, tuple[float, float]]:
    margin_raw = _mapping(_required(raw, "ebitda_margin", "industry.service_mix"), "ebitda_margin")
    margins = {
        str(k): _range(v, f"industry.service_mix.ebitda_margin.{k}") for k, v in margin_raw.items()
    }
    for key in SERVICE_MIXES:
        if key not in margins:
            raise ThesisError(f"industry.service_mix.ebitda_margin must define '{key}'")
    for key, (_lo, hi) in margins.items():
        if hi >= 1:
            raise ThesisError(f"margin for '{key}' must be a fraction below 1, got {hi}")
    return margins


def _sources(raw: Any) -> tuple[SourceSpec, ...]:
    if not isinstance(raw, Sequence) or isinstance(raw, str) or not raw:
        raise ThesisError("sources must be a non-empty list")
    specs = []
    for i, item in enumerate(raw):
        entry = dict(_mapping(item, f"sources[{i}]"))
        try:
            adapter, feed = str(entry.pop("adapter")), str(entry.pop("feed"))
        except KeyError as exc:
            raise ThesisError(f"sources[{i}] needs 'adapter' and 'feed'") from exc
        trust = float(entry.pop("trust", 0.5))
        if not 0 <= trust <= 1:
            raise ThesisError(f"sources[{i}].trust must be between 0 and 1")
        specs.append(SourceSpec(adapter=adapter, feed=feed, trust=trust, options=entry))
    feeds = [s.feed for s in specs]
    if len(feeds) != len(set(feeds)):
        raise ThesisError("each source feed may only be listed once")
    return tuple(specs)


def _presence(raw: Mapping[str, Any]) -> tuple[tuple[PresenceSpec, ...], PresenceConfig]:
    settings = dict(raw)
    specs = []
    for i, item in enumerate(settings.pop("databases", None) or []):
        entry = _mapping(item, f"presence.databases[{i}]")
        try:
            spec = PresenceSpec(
                str(entry["checker"]), str(entry["database"]), float(entry["weight"])
            )
        except KeyError as exc:
            raise ThesisError(
                f"presence.databases[{i}] needs checker, database and weight"
            ) from exc
        if spec.weight < 0:
            raise ThesisError(f"presence.databases[{i}].weight must be non-negative")
        specs.append(spec)
    return tuple(specs), _override(PresenceConfig(), settings, "presence")


def _resolve(raw: Mapping[str, Any]) -> ResolveConfig:
    settings = dict(raw)
    extra_tokens = _strings(
        settings.pop("extra_generic_tokens", None), "resolve.extra_generic_tokens"
    )
    extra_abbrev = _mapping(
        settings.pop("extra_abbreviations", None), "resolve.extra_abbreviations"
    )
    cfg = _override(ResolveConfig(), settings, "resolve")
    abbreviations = {
        **cfg.abbreviations,
        **{str(k).lower().strip(): str(v).lower().strip() for k, v in extra_abbrev.items()},
    }
    # Generic tokens are compared after normalization, so normalize them the same way.
    tokens = {normalize_name(t, abbreviations) for t in extra_tokens}
    return dataclasses.replace(
        cfg,
        abbreviations=abbreviations,
        generic_tokens=frozenset(cfg.generic_tokens | {t for t in tokens if t}),
    )


def _estimation(raw: Mapping[str, Any]) -> EstimationConfig:
    changes: dict[str, Any] = dict(raw)
    for key in ("stated_headcount", "locations", "licensed_technicians"):
        if key in changes:
            rule = _mapping(changes[key], f"estimation.{key}")
            changes[key] = _override(getattr(EstimationConfig(), key), rule, f"estimation.{key}")
    return _override(EstimationConfig(), changes, "estimation")


def _ranking(raw: Mapping[str, Any]) -> RankConfig:
    weights = _mapping(raw.get("weights"), "ranking.weights")
    priority = _mapping(raw.get("priority"), "ranking.priority")
    changes: dict[str, Any] = {f"weight_{k}": float(v) for k, v in weights.items()}
    if "max_rank" in priority:
        changes["priority_max_rank"] = int(priority["max_rank"])
    if "min_p_in_band" in priority:
        changes["priority_min_p_in_band"] = float(priority["min_p_in_band"])
    return _override(RankConfig(), changes, "ranking")


def _classify(raw: Mapping[str, Any]) -> ClassifyConfig:
    hook = _mapping(raw.get("llm_hook"), "classify.llm_hook")
    changes = {
        "llm_hook_enabled": bool(hook.get("enabled", False)),
        "llm_hook": hook.get("callable"),
    }
    return _override(ClassifyConfig(), changes, "classify.llm_hook")


def _band(size: Mapping[str, Any]) -> tuple[float, float]:
    ebitda_min = float(_required(size, "ebitda_min", "size"))
    ebitda_max = float(_required(size, "ebitda_max", "size"))
    if not 0 < ebitda_min < ebitda_max:
        raise ThesisError("size: need 0 < ebitda_min < ebitda_max")
    return ebitda_min, ebitda_max


def _states(geography: Mapping[str, Any]) -> tuple[str, ...]:
    states = tuple(
        s.upper() for s in _strings(_required(geography, "states", "geography"), "states")
    )
    if any(len(s) != _STATE_CODE_LENGTH or not s.isalpha() for s in states):
        raise ThesisError("geography.states must be two-letter state codes")
    return states


def _top_n(output: Mapping[str, Any]) -> int:
    top_n = int(output.get("brief_top_n", 10))
    if top_n < 1:
        raise ThesisError("output.brief_top_n must be a positive integer")
    return top_n


def thesis_from_mapping(raw: Any) -> Thesis:
    """Build and validate a thesis from parsed YAML.

    Args:
        raw: The mapping produced by ``yaml.safe_load``.

    Returns:
        A validated, immutable :class:`Thesis`.

    Raises:
        ThesisError: If a required field is missing or a value is malformed or out of range.
    """
    try:
        return _build_thesis(raw)
    except ThesisToTargetError:
        raise
    except (ValueError, TypeError) as exc:  # e.g. text where the file needs a number
        raise ThesisError(f"invalid value in thesis file: {exc}") from exc


def _build_thesis(raw: Any) -> Thesis:
    root = _mapping(raw, "thesis file")
    meta = _mapping(_required(root, "thesis", ""), "thesis")
    industry = _mapping(_required(root, "industry", ""), "industry")
    mix = _mapping(_required(industry, "service_mix", "industry"), "industry.service_mix")
    ebitda_min, ebitda_max = _band(_mapping(_required(root, "size", ""), "size"))
    presence_specs, presence_cfg = _presence(_mapping(root.get("presence"), "presence"))
    return Thesis(
        name=str(_required(meta, "name", "thesis")).strip(),
        description=" ".join(str(meta.get("description", "")).split()),
        naics=tuple(str(n) for n in (industry.get("naics") or [])),
        include_keywords=_strings(
            _required(industry, "include_keywords", "industry"), "include_keywords"
        ),
        adjacent_keywords=_strings(industry.get("adjacent_keywords"), "adjacent_keywords"),
        residential_only_keywords=_strings(
            industry.get("residential_only_keywords"), "residential_only_keywords"
        ),
        segments=_segments(industry),
        recurring_keywords=_strings(mix.get("recurring_keywords"), "recurring_keywords"),
        install_keywords=_strings(mix.get("install_keywords"), "install_keywords"),
        margins=_margins(mix),
        ebitda_min=ebitda_min,
        ebitda_max=ebitda_max,
        states=_states(_mapping(_required(root, "geography", ""), "geography")),
        sources=_sources(_required(root, "sources", "")),
        presence_databases=presence_specs,
        synthetic=_override(
            SyntheticSettings(), _mapping(root.get("synthetic"), "synthetic"), "synthetic"
        ),
        resolve=_resolve(_mapping(root.get("resolve"), "resolve")),
        estimation=_estimation(_mapping(root.get("estimation"), "estimation")),
        presence=presence_cfg,
        ranking=_ranking(_mapping(root.get("ranking"), "ranking")),
        classify=_classify(_mapping(root.get("classify"), "classify")),
        brief_top_n=_top_n(_mapping(root.get("output"), "output")),
    )


def thesis_from_yaml(text: str) -> Thesis:
    """Parse and validate thesis YAML text.

    Args:
        text: YAML document.

    Returns:
        A validated, immutable :class:`Thesis`.

    Raises:
        ThesisError: If the text is not valid YAML or fails validation.
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ThesisError(f"thesis file is not valid YAML: {exc}") from exc
    return thesis_from_mapping(raw)


def load_thesis(path: str | Path) -> Thesis:
    """Read and validate a thesis YAML file.

    Args:
        path: Path to the YAML file.

    Returns:
        A validated, immutable :class:`Thesis`.

    Raises:
        ThesisError: If the file is missing, is not valid YAML, or fails validation.
    """
    path = Path(path)
    if not path.is_file():
        raise ThesisError(f"thesis file not found: {path}")
    return thesis_from_yaml(path.read_text(encoding="utf-8"))


def demo_thesis_text() -> str:
    """Return the packaged demo thesis exactly as shipped (LF line endings)."""
    return files("thesis_to_target").joinpath(DEMO_THESIS_RESOURCE).read_text(encoding="utf-8")


def load_demo_thesis() -> Thesis:
    """Load the demo thesis that ships inside the package, from any working directory."""
    return thesis_from_yaml(demo_thesis_text())

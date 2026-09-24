"""Source adapter and presence checker that serve the synthetic world to the pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar

from ..errors import ConfigError
from ..models import RawRecord
from ..presence import ListingIndexChecker
from ..qa import EntityTruth
from ..sources import SourceAdapter
from .vocabulary import FEEDS
from .world import SyntheticWorld, build_world

if TYPE_CHECKING:
    from ..thesis import PresenceSpec, Thesis


class SyntheticFeedAdapter(SourceAdapter):
    """Serves one feed of the seeded synthetic world, with its ground truth."""

    synthetic: ClassVar[bool] = True

    def __init__(
        self, feed: str, trust: float = 0.5, options: Mapping[str, Any] | None = None
    ) -> None:
        """Configure the adapter.

        Args:
            feed: One of the synthetic feeds (license roll, registry, web listing, association).
            trust: Weight of this feed when records disagree.
            options: Unused; accepted for interface compatibility.

        Raises:
            ConfigError: If ``feed`` is not a synthetic feed.
        """
        if feed not in FEEDS:
            raise ConfigError(f"synthetic feed must be one of {FEEDS}, got '{feed}'")
        super().__init__(feed, trust, options)
        self._world: SyntheticWorld | None = None

    def fetch(self, thesis: Thesis) -> list[RawRecord]:
        """Return this feed's records from the world seeded by ``thesis.synthetic``."""
        self._world = build_world(thesis.synthetic)
        return list(self._world.records[self.feed])

    def ground_truth(self) -> dict[str, str] | None:
        """Record id -> firm id for this feed, once fetched."""
        if self._world is None:
            return None
        return {r.record_id: self._world.truth[r.record_id] for r in self._world.records[self.feed]}

    def entity_truth(self) -> dict[str, EntityTruth] | None:
        """Firm id -> true EBITDA and database listings, once fetched."""
        if self._world is None:
            return None
        return {
            f.firm_id: EntityTruth(ebitda=f.true_ebitda, listed_in=dict(f.in_db))
            for f in self._world.firms
        }


def synthetic_presence_checker(thesis: Thesis, spec: PresenceSpec) -> ListingIndexChecker:
    """Build a presence checker over one synthetic database index.

    Args:
        thesis: Supplies the synthetic seed and matching configuration.
        spec: Database name and weight.

    Returns:
        A checker over that database's synthetic listings.

    Raises:
        ConfigError: If the database is not one the generator creates.
    """
    world = build_world(thesis.synthetic)
    if spec.database not in world.listings:
        raise ConfigError(
            f"synthetic database must be one of {sorted(world.listings)}, got '{spec.database}'"
        )
    return ListingIndexChecker(
        spec.database,
        spec.weight,
        world.listings[spec.database],
        threshold=thesis.presence.match_threshold,
        resolve_cfg=thesis.resolve,
    )

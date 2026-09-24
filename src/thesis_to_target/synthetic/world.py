"""Building the complete synthetic world for a seed: firms, feeds, listings and truth."""

from __future__ import annotations

import functools
from dataclasses import dataclass

import numpy as np

from ..config import SyntheticSettings
from ..models import RawRecord
from ..presence import Listing
from .draws import Draws
from .feeds import FeedRenderer, render_listings
from .firms import FirmFactory, SyntheticFirm, WorldConfig, check_capacity


@dataclass(frozen=True)
class SyntheticWorld:
    """Everything the generator produced for one seed.

    Attributes:
        seed: Seed used.
        firms: Ground-truth firms.
        records: Feed name -> records.
        truth: Record id -> firm id.
        listings: Database name -> listings.
    """

    seed: int
    firms: tuple[SyntheticFirm, ...]
    records: dict[str, list[RawRecord]]
    truth: dict[str, str]
    listings: dict[str, list[Listing]]

    def firm(self, firm_id: str) -> SyntheticFirm:
        """Return the firm with the given id.

        Raises:
            KeyError: If no firm has that id.
        """
        for f in self.firms:
            if f.firm_id == firm_id:
                return f
        raise KeyError(firm_id)


@functools.cache
def build_world(settings: SyntheticSettings, config: WorldConfig | None = None) -> SyntheticWorld:
    """Generate the synthetic world for a seed. Same inputs always give the same world.

    Args:
        settings: Seed and number of base firms.
        config: Generator knobs; defaults to :class:`WorldConfig`.

    Returns:
        Firms, feeds, ground truth and database listings.

    Raises:
        CapacityError: If ``settings.n_firms`` exceeds what the fixed pools can supply.
    """
    cfg = config or WorldConfig()
    check_capacity(settings, cfg)
    draws = Draws(np.random.default_rng(settings.seed))
    factory = FirmFactory(draws, cfg)
    factory.add_base_firms(settings.n_firms)
    factory.add_look_alikes(settings.n_firms)
    renderer = FeedRenderer(draws, cfg)
    renderer.render(factory.firms)
    records, truth = renderer.finalize()
    listings = render_listings(factory.firms, draws, cfg, factory.cores)
    return SyntheticWorld(settings.seed, tuple(factory.firms), records, truth, listings)

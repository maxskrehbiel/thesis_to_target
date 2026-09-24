"""Seeded synthetic world of fictional firms, messy source feeds and database listings.

Only the composition root (``registry.py``) imports this package; the core pipeline
receives its sources and presence checkers by injection.
"""

from .adapter import SyntheticFeedAdapter, synthetic_presence_checker
from .firms import SyntheticFirm, WorldConfig, max_firms
from .vocabulary import FEEDS
from .world import SyntheticWorld, build_world

__all__ = [
    "FEEDS",
    "SyntheticFeedAdapter",
    "SyntheticFirm",
    "SyntheticWorld",
    "WorldConfig",
    "build_world",
    "max_firms",
    "synthetic_presence_checker",
]

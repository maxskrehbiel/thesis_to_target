"""Source-adapter interface: how any feed becomes a list of RawRecord rows."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar

from .models import RawRecord

if TYPE_CHECKING:
    from .qa import EntityTruth
    from .thesis import Thesis


class SourceAdapter(ABC):
    """One feed of raw company records.

    An adapter maps a feed's columns onto :class:`RawRecord` and does nothing
    else: no cleaning, no matching. Facts go into ``RawRecord.attributes`` under
    this standard vocabulary (all optional):

    - ``naics``: NAICS code string, e.g. ``"238220"``.
    - ``license_type`` / ``license_status``: a sector license and its status.
    - ``licensed_technicians``: count of licensed individuals tied to the entity.
    - ``employee_band``: headcount band such as ``"20-49"`` or ``"500+"``.
    - ``stated_headcount``: a headcount the company states about itself.
    - ``locations``: number of operating locations.
    - ``services``: list of service phrases; ``listing_category``: directory category.
    - ``formation_year``: year the entity was registered.
    - ``parent_entity``: name of a parent or controlling owner, if any.

    Attributes:
        synthetic: True when the adapter serves generated rather than real data;
            outputs are labeled accordingly.
    """

    synthetic: ClassVar[bool] = False

    def __init__(
        self, feed: str, trust: float = 0.5, options: Mapping[str, Any] | None = None
    ) -> None:
        """Configure the adapter.

        Args:
            feed: Feed name; becomes ``RawRecord.source``.
            trust: Weight of this feed when records disagree (0-1).
            options: Adapter-specific options from the thesis file.
        """
        self.feed = feed
        self.trust = trust
        self.options: Mapping[str, Any] = options or {}

    @abstractmethod
    def fetch(self, thesis: Thesis) -> list[RawRecord]:
        """Return the feed's records for a thesis.

        Args:
            thesis: The thesis being sourced.

        Returns:
            Records whose ``record_id`` values are unique across all feeds.
        """

    def ground_truth(self) -> dict[str, str] | None:
        """Return record id -> true entity id for records already fetched, if known.

        Only labeled data (such as the synthetic world) can answer this; the default
        is ``None``. When every adapter answers, the run is graded in ``qa.py``.
        """
        return None

    def entity_truth(self) -> dict[str, EntityTruth] | None:
        """Return true entity id -> known facts (EBITDA, database listings), if known."""
        return None

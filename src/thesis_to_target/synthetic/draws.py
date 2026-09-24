"""Seeded random draws built only on ``Generator.random()`` so the stream never shifts."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TypeVar

import numpy as np

_T = TypeVar("_T")


class Draws:
    """Random draws for the generator, derived from one explicitly passed numpy Generator.

    Every draw is computed from ``Generator.random()``, whose values are fixed by the
    bit generator (PCG64). NumPy does not promise that higher-level methods such as
    ``integers``, ``choice`` or ``normal`` keep the same stream across releases, so
    they are not used; the same seed therefore gives the same world on every
    supported NumPy version and platform.
    """

    def __init__(self, rng: np.random.Generator) -> None:
        """Wrap a seeded generator, e.g. ``np.random.default_rng(42)``."""
        self._rng = rng

    def uniform(self, low: float = 0.0, high: float = 1.0) -> float:
        """A float in ``[low, high)``."""
        return low + (high - low) * float(self._rng.random())

    def chance(self, p: float) -> bool:
        """True with probability ``p``."""
        return self.uniform() < p

    def integer(self, low: int, high: int) -> int:
        """An integer in ``[low, high]``, both ends included."""
        span = high - low + 1
        return low + min(int(self.uniform() * span), span - 1)

    def normal(self, mean: float = 0.0, sd: float = 1.0) -> float:
        """A normal draw via the Box-Muller transform."""
        u1 = 1.0 - self.uniform()  # in (0, 1], so the logarithm is finite
        u2 = self.uniform()
        return mean + sd * math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)

    def choice(self, items: Sequence[_T]) -> _T:
        """One item, uniformly at random."""
        return items[self.integer(0, len(items) - 1)]

    def weighted(self, items: Sequence[_T], weights: Sequence[float]) -> _T:
        """One item with probability proportional to its weight."""
        target = self.uniform(0.0, sum(weights))
        for item, weight in zip(items, weights, strict=True):
            target -= weight
            if target < 0:
                return item
        return items[-1]

    def shuffled(self, items: Sequence[_T]) -> list[_T]:
        """A shuffled copy (Fisher-Yates)."""
        out = list(items)
        for i in range(len(out) - 1, 0, -1):
            j = self.integer(0, i)
            out[i], out[j] = out[j], out[i]
        return out

    def sample(self, items: Sequence[_T], k: int) -> list[_T]:
        """Up to ``k`` distinct items in random order."""
        return self.shuffled(items)[: min(k, len(items))]

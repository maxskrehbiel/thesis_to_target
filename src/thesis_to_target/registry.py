"""Composition root: maps thesis names to source adapters and presence checkers."""

from __future__ import annotations

from collections.abc import Callable

from .errors import UnknownComponentError
from .presence import PresenceChecker
from .sources import SourceAdapter
from .synthetic import SyntheticFeedAdapter, synthetic_presence_checker
from .thesis import PresenceSpec, Thesis

#: Builds a presence checker for one database named in the thesis.
PresenceFactory = Callable[[Thesis, PresenceSpec], PresenceChecker]

_ADAPTERS: dict[str, type[SourceAdapter]] = {"synthetic": SyntheticFeedAdapter}
_PRESENCE: dict[str, PresenceFactory] = {"synthetic": synthetic_presence_checker}


def register_adapter(name: str, adapter: type[SourceAdapter]) -> None:
    """Make a source adapter available to thesis files under ``name``.

    Args:
        name: Value used in the thesis ``sources[].adapter`` field.
        adapter: The adapter class.
    """
    _ADAPTERS[name] = adapter


def register_presence(name: str, factory: PresenceFactory) -> None:
    """Make a presence checker available to thesis files under ``name``.

    Args:
        name: Value used in the thesis ``presence.databases[].checker`` field.
        factory: Function building the checker from the thesis and its spec.
    """
    _PRESENCE[name] = factory


def build_adapters(thesis: Thesis) -> list[SourceAdapter]:
    """Instantiate every source adapter the thesis lists.

    Raises:
        UnknownComponentError: If an adapter name is not registered.
    """
    adapters = []
    for spec in thesis.sources:
        if spec.adapter not in _ADAPTERS:
            raise UnknownComponentError(
                f"unknown source adapter '{spec.adapter}' (registered: {sorted(_ADAPTERS)})"
            )
        adapters.append(_ADAPTERS[spec.adapter](spec.feed, spec.trust, spec.options))
    return adapters


def build_presence_checkers(thesis: Thesis) -> list[PresenceChecker]:
    """Instantiate every presence checker the thesis lists.

    Raises:
        UnknownComponentError: If a checker name is not registered.
    """
    checkers = []
    for spec in thesis.presence_databases:
        if spec.checker not in _PRESENCE:
            raise UnknownComponentError(
                f"unknown presence checker '{spec.checker}' (registered: {sorted(_PRESENCE)})"
            )
        checkers.append(_PRESENCE[spec.checker](thesis, spec))
    return checkers

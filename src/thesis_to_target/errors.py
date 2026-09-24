"""Package exception hierarchy; the command line maps these onto exit codes."""

from __future__ import annotations


class ThesisToTargetError(Exception):
    """Base class of every error this package raises on purpose."""


class ConfigError(ThesisToTargetError, ValueError):
    """A thesis, configuration value, component name or input is invalid (exit code 2)."""


class ThesisError(ConfigError):
    """A thesis file is missing fields or contradicts itself."""


class HookError(ConfigError):
    """The configured model-classification hook cannot be loaded or returned bad output."""


class UnknownComponentError(ConfigError):
    """A thesis names a source adapter or presence checker that is not registered."""


class CapacityError(ConfigError):
    """A generator was asked for more items than its fixed pools can supply."""


class LedgerError(ThesisToTargetError, ValueError):
    """A claim breaks a ledger rule, or the finished ledger fails verification (exit code 1)."""

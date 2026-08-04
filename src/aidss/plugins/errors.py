"""Exceptions raised by the plugin layer."""

from __future__ import annotations


class PluginError(Exception):
    """Base class for every plugin error."""


class PluginRegistrationError(PluginError):
    """An adapter failed the contract check at registration time."""


class PluginNotFoundError(PluginError, LookupError):
    """Configuration names an adapter that is not registered."""


class ProviderUnavailableError(PluginError):
    """An external provider failed, transiently or permanently.

    Core Logic reads ``retryable`` to decide between a retry and a fallback
    (Section 12.8).
    """

    def __init__(self, provider: str, message: str, *, retryable: bool = True) -> None:
        super().__init__(f"[{provider}] {message}")
        self.provider = provider
        self.retryable = retryable

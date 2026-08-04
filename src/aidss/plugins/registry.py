"""Plugin Manager (Section 9) - adapter registration, validation, resolution.

Adapters register through the ``@register`` decorator. Instances are built by
a factory that takes ``Settings``, so credentials are read at exactly one
point rather than scattered across the codebase (Section 13).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import TypeVar

from aidss.config import Settings, get_settings
from aidss.plugins.errors import PluginNotFoundError, PluginRegistrationError
from aidss.plugins.interfaces import (
    AIProvider,
    MarketDataProvider,
    NewsProvider,
    ProviderPlugin,
    StorageProvider,
)

P = TypeVar("P", bound=ProviderPlugin)

#: kind -> {name -> adapter class}
_REGISTRY: dict[str, dict[str, type[ProviderPlugin]]] = {}

_INTERFACE_BY_KIND: dict[str, type[ProviderPlugin]] = {
    "market_data": MarketDataProvider,
    "news": NewsProvider,
    "ai": AIProvider,
    "storage": StorageProvider,
}


def register(cls: type[P]) -> type[P]:
    """Register an adapter. This is also the gate where the contract is checked."""
    name = getattr(cls, "name", None)
    if not isinstance(name, str) or not name:
        raise PluginRegistrationError(
            f"{cls.__name__} must define a non-empty string class attribute `name`"
        )

    kind = getattr(cls, "kind", None)
    if kind not in _INTERFACE_BY_KIND:
        raise PluginRegistrationError(
            f"{cls.__name__} declares unknown kind={kind!r}; "
            f"valid values are {sorted(_INTERFACE_BY_KIND)}"
        )

    interface = _INTERFACE_BY_KIND[kind]
    if not issubclass(cls, interface):
        raise PluginRegistrationError(
            f"{cls.__name__} declares kind={kind!r} but is not a subclass of {interface.__name__}"
        )

    if inspect.isabstract(cls):
        missing = sorted(cls.__abstractmethods__)
        raise PluginRegistrationError(
            f"{cls.__name__} is still abstract; unimplemented methods: {missing}"
        )

    bucket = _REGISTRY.setdefault(kind, {})
    existing = bucket.get(name)
    if existing is not None and existing is not cls:
        raise PluginRegistrationError(
            f"Plugin name {name!r} for kind={kind!r} is already taken by {existing.__name__}"
        )
    bucket[name] = cls
    return cls


def available(kind: str) -> list[str]:
    """Adapters registered for one kind (used by the /providers endpoint)."""
    return sorted(_REGISTRY.get(kind, {}))


def registry_snapshot() -> dict[str, list[str]]:
    """Every registered adapter, for the admin dashboard and diagnostics."""
    return {kind: sorted(names) for kind, names in sorted(_REGISTRY.items())}


def get_plugin_class(kind: str, name: str) -> type[ProviderPlugin]:
    try:
        return _REGISTRY[kind][name]
    except KeyError as exc:
        raise PluginNotFoundError(
            f"Provider {name!r} for kind={kind!r} is not registered. "
            f"Available: {available(kind)}"
        ) from exc


def _build(kind: str, name: str, settings: Settings) -> ProviderPlugin:
    cls = get_plugin_class(kind, name)
    factory: Callable[[Settings], ProviderPlugin] | None = getattr(cls, "from_settings", None)
    if factory is None:
        return cls()  # type: ignore[call-arg]
    return factory(settings)


def get_market_data_provider(settings: Settings | None = None) -> MarketDataProvider:
    settings = settings or get_settings()
    provider = _build("market_data", settings.market_data_provider, settings)
    assert isinstance(provider, MarketDataProvider)
    return provider


def get_news_provider(settings: Settings | None = None) -> NewsProvider:
    settings = settings or get_settings()
    provider = _build("news", settings.news_provider, settings)
    assert isinstance(provider, NewsProvider)
    return provider


def get_ai_provider(settings: Settings | None = None) -> AIProvider:
    settings = settings or get_settings()
    provider = _build("ai", settings.ai_provider, settings)
    assert isinstance(provider, AIProvider)
    return provider


def get_storage_provider(settings: Settings | None = None) -> StorageProvider:
    settings = settings or get_settings()
    provider = _build("storage", settings.storage_provider, settings)
    assert isinstance(provider, StorageProvider)
    return provider

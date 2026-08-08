"""Plugin layer (Section 5).

Importing this package loads every bundled adapter into the registry.
"""

from aidss.plugins import adapters  # noqa: F401  (side effect: adapter registration)
from aidss.plugins.errors import (
    PluginError,
    PluginNotFoundError,
    PluginRegistrationError,
    ProviderUnavailableError,
)
from aidss.plugins.interfaces import (
    AIProvider,
    MarketDataProvider,
    NewsProvider,
    ProviderPlugin,
    StorageProvider,
)
from aidss.plugins.registry import (
    available,
    get_ai_provider,
    get_market_data_provider,
    get_news_provider,
    get_storage_provider,
    register,
    registry_snapshot,
)

__all__ = [
    "AIProvider",
    "MarketDataProvider",
    "NewsProvider",
    "PluginError",
    "PluginNotFoundError",
    "PluginRegistrationError",
    "ProviderPlugin",
    "ProviderUnavailableError",
    "StorageProvider",
    "available",
    "get_ai_provider",
    "get_market_data_provider",
    "get_news_provider",
    "get_storage_provider",
    "register",
    "registry_snapshot",
]

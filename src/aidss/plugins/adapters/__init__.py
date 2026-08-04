"""Import every adapter so the ``@register`` decorators run.

Adding a provider means adding one module here plus one import line. Core
Logic does not change at all (Section 7).

Import order carries no meaning: ``market_composite`` resolves the adapters it
delegates to by name inside ``from_settings``, which runs long after every
module here has been imported.
"""

from aidss.plugins.adapters import (  # noqa: F401
    ai_fixture,
    ai_openai_compatible,
    market_alphavantage,
    market_composite,
    market_finnhub,
    market_fixture,
    market_yahoo,
    news_fixture,
    storage_local,
)

__all__ = [
    "ai_fixture",
    "ai_openai_compatible",
    "market_alphavantage",
    "market_composite",
    "market_finnhub",
    "market_fixture",
    "market_yahoo",
    "news_fixture",
    "storage_local",
]

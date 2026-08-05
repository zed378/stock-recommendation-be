"""Provider plugin contracts (Section 7).

Four abstraction points: AIProvider, MarketDataProvider, NewsProvider, and
StorageProvider. Core Logic talks *only* to these interfaces, so adding a
provider means writing one adapter rather than editing the core.

Hard constraint (Sections 4, 8, 10): there is no interface here for a broker,
an order, or a trade execution - and none may be added. Every interface is
read-only with respect to external systems; the sole exception is
StorageProvider, which writes to the platform's own storage.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, ClassVar

from aidss.domain.types import (
    Candle,
    ChatCompletion,
    ChatMessage,
    FundamentalPoint,
    NewsArticle,
    Quote,
    Timeframe,
)


class ProviderPlugin(ABC):
    """Base for every plugin. ``name`` is the key used in configuration."""

    #: Unique adapter key, referenced from settings (e.g. AIDSS_MARKET_DATA_PROVIDER).
    #: Presence is validated by the PluginManager at registration time.
    name: ClassVar[str]
    #: Which interface family this implements; set by the interface class, not by adapters.
    kind: ClassVar[str]

    def health_check(self) -> bool:
        """Used by the Plugin Manager and the /health endpoint."""
        return True

    def bind_session(self, session: Any) -> ProviderPlugin:
        """Offer this adapter the platform's own database session.

        Almost no adapter wants it - an external API needs a key, not a
        session - so the default ignores it and returns self. The RSS news
        adapter is the exception: the feeds it reads are configured by
        administrators at runtime, not baked into settings, and that list lives
        in the database like every other thing an administrator manages.

        On the base class rather than special-cased at the call site, so
        callers can offer it unconditionally and adapters decide.
        """
        return self


class MarketDataProvider(ProviderPlugin, ABC):
    """A source of price and market data (Section 6.1)."""

    kind: ClassVar[str] = "market_data"

    @abstractmethod
    def get_quote(self, ticker: str) -> Quote:
        """Latest price for one instrument."""

    @abstractmethod
    def get_historical_candles(
        self,
        ticker: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """Historical candles over [start, end], in ascending time order."""

    def supports_realtime(self) -> bool:
        """Not every provider offers a realtime channel (Section 6.1)."""
        return False

    def get_fundamentals(self, ticker: str) -> list[FundamentalPoint]:
        """Reported financial metrics, if the provider publishes any.

        Optional rather than abstract: many price feeds carry no fundamental
        data at all, and forcing every adapter to implement a method it cannot
        satisfy produces a wall of `raise NotImplementedError`. An empty list
        means "this provider has none", which the collector reports rather than
        treating as a failure.
        """
        return []

    def fundamentals_source_name(self) -> str:
        """Which adapter a stored fundamental figure should be attributed to.

        Almost always this provider itself. It is overridable because an
        adapter may delegate - drawing prices from one source and fundamentals
        from another - and recording the wrapper's name would leave a stored
        metric untraceable. "Which source said this?" is the first question
        asked of a figure that looks wrong.

        Concrete default rather than abstract, for the same reason
        ``get_fundamentals`` is: an adapter that does not delegate should not
        have to say so.
        """
        return self.name


class NewsProvider(ProviderPlugin, ABC):
    """A source of per-ticker news (Section 6.3)."""

    kind: ClassVar[str] = "news"

    @abstractmethod
    def get_news(self, ticker: str, start: datetime, end: datetime) -> list[NewsArticle]:
        """Articles for one ticker over a time range."""

    def get_native_sentiment(self, ticker: str) -> float | None:
        """The provider's own sentiment score, if it publishes one."""
        return None


class AIProvider(ProviderPlugin, ABC):
    """The OpenAI-compatible abstraction (Section 12.1)."""

    kind: ClassVar[str] = "ai"

    @abstractmethod
    def chat_completion(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> ChatCompletion:
        """Section 12.2. ``response_format`` drives structured output (12.5)."""

    @abstractmethod
    def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        """Section 12.3. The embedding model is configured separately from chat."""

    def supports_tool_calling(self) -> bool:
        """Section 12.4 - support is uneven across providers."""
        return False

    def supports_structured_output(self) -> bool:
        """Section 12.5 - when False, Core falls back to prompt-enforced JSON."""
        return False


class StorageProvider(ProviderPlugin, ABC):
    """Storage for knowledge base documents, reports, and backups (Section 7)."""

    kind: ClassVar[str] = "storage"

    @abstractmethod
    def store(
        self, key: str, data: bytes, *, content_type: str = "application/octet-stream"
    ) -> str:
        """Store an object and return its internal URI."""

    @abstractmethod
    def retrieve(self, key: str) -> bytes:
        """Fetch an object. Raises ``KeyError`` when absent."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove an object. Idempotent."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Whether the object is present."""

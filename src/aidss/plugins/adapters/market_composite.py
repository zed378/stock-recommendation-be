"""Prices from one provider, fundamentals from another.

This exists because the free sources have complementary holes rather than
overlapping coverage. Yahoo's chart endpoint serves IDX prices without a key
and without a practical request ceiling, but its fundamentals endpoint answers
401. Alpha Vantage serves fundamentals under a documented free key, but 25
requests a day cannot feed a price collector. Neither is sufficient; together
they are.

Before this adapter, using both meant either editing the core to call two
providers - defeating the point of the plugin layer - or picking one and
accepting the hole. Section 5 says provider choice is configuration, so the
combination is configuration too:

    AIDSS_MARKET_DATA_PROVIDER=composite
    AIDSS_COMPOSITE_PRICE_PROVIDER=yahoo
    AIDSS_COMPOSITE_FUNDAMENTALS_PROVIDER=alphavantage

The delegation is total. This class holds no parsing, no HTTP, and no
normalisation of its own, so it cannot develop opinions that differ from the
adapter it is standing in front of.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from aidss.config import Settings
from aidss.domain.types import Candle, FundamentalPoint, Quote, Timeframe
from aidss.plugins.errors import PluginRegistrationError
from aidss.plugins.interfaces import MarketDataProvider
from aidss.plugins.registry import register


@register
class CompositeMarketDataProvider(MarketDataProvider):
    name: ClassVar[str] = "composite"

    def __init__(
        self,
        *,
        prices: MarketDataProvider,
        fundamentals: MarketDataProvider,
    ) -> None:
        if prices.name == self.name or fundamentals.name == self.name:
            # A composite delegating to a composite would recurse until the
            # stack ran out, and the traceback would name this file a hundred
            # times without ever saying why.
            raise ValueError(
                "A composite provider cannot delegate to another composite; "
                "name a concrete adapter for each half"
            )
        self._prices = prices
        self._fundamentals = fundamentals

    @classmethod
    def from_settings(cls, settings: Settings) -> CompositeMarketDataProvider:
        # Imported here rather than at module scope: the registry imports this
        # module during adapter registration, and importing it back would be a
        # cycle.
        from aidss.plugins.registry import get_plugin_class

        def build(role: str, provider_name: str) -> MarketDataProvider:
            if provider_name == cls.name:
                raise PluginRegistrationError(
                    f"AIDSS_COMPOSITE_{role.upper()}_PROVIDER cannot be "
                    f"{cls.name!r}; name a concrete adapter"
                )
            plugin = get_plugin_class("market_data", provider_name)
            factory = getattr(plugin, "from_settings", None)
            instance = factory(settings) if factory else plugin()
            assert isinstance(instance, MarketDataProvider)
            return instance

        return cls(
            prices=build("price", settings.composite_price_provider),
            fundamentals=build("fundamentals", settings.composite_fundamentals_provider),
        )

    # --- introspection ---------------------------------------------------

    @property
    def price_provider(self) -> MarketDataProvider:
        return self._prices

    @property
    def fundamentals_provider(self) -> MarketDataProvider:
        return self._fundamentals

    def describe(self) -> dict[str, str]:
        """Which half came from where, for /providers and the audit trail.

        Recording `composite` alone would leave a stored metric unattributable,
        and "which source said this?" is the first question asked of a figure
        that looks wrong.
        """
        return {"prices": self._prices.name, "fundamentals": self._fundamentals.name}

    # --- MarketDataProvider contract -------------------------------------

    def get_quote(self, ticker: str) -> Quote:
        return self._prices.get_quote(ticker)

    def get_historical_candles(
        self,
        ticker: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        return self._prices.get_historical_candles(ticker, timeframe, start, end)

    def get_fundamentals(self, ticker: str) -> list[FundamentalPoint]:
        return self._fundamentals.get_fundamentals(ticker)

    def fundamentals_source_name(self) -> str:
        # The reason the interface makes this overridable: a metric collected
        # through a composite belongs to whichever half answered, and `composite`
        # would name a wrapper rather than a source.
        return self._fundamentals.fundamentals_source_name()

    def supports_realtime(self) -> bool:
        # Only the price half can offer one, so only the price half is asked.
        return self._prices.supports_realtime()

    def health_check(self) -> bool:
        """Healthy only when both halves are.

        Reporting healthy while fundamentals are down would hide the exact
        failure this adapter was built to make visible.
        """
        return self._prices.health_check() and self._fundamentals.health_check()


__all__ = ["CompositeMarketDataProvider"]

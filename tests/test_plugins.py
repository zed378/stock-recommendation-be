"""Plugin layer contract tests (Section 5).

FR-07 says a provider must be swappable through configuration alone. These
tests hold the registry to that promise: the contract is enforced at
registration time, and resolution is driven purely by settings.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aidss.config import Settings
from aidss.domain.types import Candle, Timeframe
from aidss.plugins import errors, registry
from aidss.plugins.interfaces import (
    AIProvider,
    MarketDataProvider,
    NewsProvider,
    StorageProvider,
)


def test_all_four_interfaces_have_at_least_one_adapter() -> None:
    snapshot = registry.registry_snapshot()
    for kind in ("market_data", "news", "ai", "storage"):
        assert snapshot.get(kind), f"no adapter registered for {kind}"


def test_provider_selection_follows_settings() -> None:
    settings = Settings(market_data_provider="fixture", storage_provider="local")
    assert isinstance(registry.get_market_data_provider(settings), MarketDataProvider)
    assert isinstance(registry.get_storage_provider(settings), StorageProvider)


def test_unknown_provider_name_is_reported_with_the_available_options() -> None:
    settings = Settings(market_data_provider="does-not-exist")
    with pytest.raises(errors.PluginNotFoundError) as excinfo:
        registry.get_market_data_provider(settings)
    assert "fixture" in str(excinfo.value)


def test_adapter_without_a_name_is_rejected() -> None:
    class Nameless(NewsProvider):
        def get_news(self, ticker, start, end):
            return []

    with pytest.raises(errors.PluginRegistrationError, match="name"):
        registry.register(Nameless)


def test_adapter_declaring_the_wrong_kind_is_rejected() -> None:
    class Mismatched(NewsProvider):
        name = "mismatched"
        kind = "market_data"  # claims to be market data, but is a NewsProvider

        def get_news(self, ticker, start, end):
            return []

    with pytest.raises(errors.PluginRegistrationError, match="subclass"):
        registry.register(Mismatched)


def test_adapter_with_unimplemented_methods_is_rejected() -> None:
    class Incomplete(AIProvider):
        name = "incomplete"

        def chat_completion(self, messages, **kwargs):  # embed() is missing
            raise NotImplementedError

    with pytest.raises(errors.PluginRegistrationError, match="abstrak|abstract"):
        registry.register(Incomplete)


def test_registering_a_duplicate_name_is_rejected() -> None:
    class First(StorageProvider):
        name = "duplicate-probe"

        def store(self, key, data, *, content_type="application/octet-stream"):
            return key

        def retrieve(self, key):
            return b""

        def delete(self, key):
            return None

        def exists(self, key):
            return False

    class Second(First):
        pass

    registry.register(First)
    try:
        with pytest.raises(errors.PluginRegistrationError, match="already|sudah"):
            registry.register(Second)
    finally:
        registry._REGISTRY["storage"].pop("duplicate-probe", None)


def test_fixture_market_data_is_reproducible() -> None:
    provider = registry.get_market_data_provider(Settings(market_data_provider="fixture"))
    end = datetime(2025, 1, 1, tzinfo=UTC)
    start = end - timedelta(days=30)

    first = provider.get_historical_candles("BBCA", Timeframe.D1, start, end)
    second = provider.get_historical_candles("BBCA", Timeframe.D1, start, end)
    assert first == second, "the fixture provider must be deterministic"
    assert all(isinstance(c, Candle) for c in first)


def test_fixture_candles_are_ordered_and_structurally_sound() -> None:
    provider = registry.get_market_data_provider(Settings(market_data_provider="fixture"))
    end = datetime(2025, 1, 1, tzinfo=UTC)
    candles = provider.get_historical_candles("TLKM", Timeframe.D1, end - timedelta(days=60), end)

    assert candles
    timestamps = [c.timestamp for c in candles]
    assert timestamps == sorted(timestamps)
    for candle in candles:
        assert candle.high >= max(candle.open, candle.close)
        assert candle.low <= min(candle.open, candle.close)
        assert candle.volume >= 0


def test_overlapping_ranges_return_identical_bars() -> None:
    """Idempotent re-fetch depends on this: the same slot must not drift."""
    provider = registry.get_market_data_provider(Settings(market_data_provider="fixture"))
    end = datetime(2025, 1, 1, tzinfo=UTC)

    wide = provider.get_historical_candles("ASII", Timeframe.D1, end - timedelta(days=40), end)
    narrow = provider.get_historical_candles("ASII", Timeframe.D1, end - timedelta(days=10), end)

    by_timestamp = {c.timestamp: c for c in wide}
    for candle in narrow:
        assert by_timestamp[candle.timestamp] == candle


def test_naive_datetimes_are_rejected() -> None:
    provider = registry.get_market_data_provider(Settings(market_data_provider="fixture"))
    with pytest.raises(ValueError, match="aware"):
        provider.get_historical_candles(
            "BBCA", Timeframe.D1, datetime(2025, 1, 1), datetime(2025, 2, 1)
        )


def test_local_storage_round_trip(tmp_path) -> None:
    provider = registry.get_storage_provider(
        Settings(storage_provider="local", local_storage_root=str(tmp_path))
    )
    provider.store("docs/note.txt", b"hello")
    assert provider.exists("docs/note.txt")
    assert provider.retrieve("docs/note.txt") == b"hello"
    provider.delete("docs/note.txt")
    assert not provider.exists("docs/note.txt")
    with pytest.raises(KeyError):
        provider.retrieve("docs/note.txt")


def test_local_storage_blocks_path_traversal(tmp_path) -> None:
    provider = registry.get_storage_provider(
        Settings(storage_provider="local", local_storage_root=str(tmp_path))
    )
    with pytest.raises(ValueError, match="root"):
        provider.store("../escaped.txt", b"nope")


def test_finnhub_adapter_requires_a_key() -> None:
    settings = Settings(market_data_provider="finnhub", finnhub_api_key=None)
    with pytest.raises(ValueError, match="FINNHUB"):
        registry.get_market_data_provider(settings)


def test_the_ai_adapter_uses_the_configured_timeout() -> None:
    """The constructor took a timeout and `from_settings` did not pass it, so
    every deployment ran on the 60-second default whatever it configured.

    The symptom was three analyzers failing at once with "the read operation
    timed out" against a self-hosted gateway that needs minutes for an analyzer
    prompt - which reads as a broken gateway rather than as this side hanging
    up early. A setting that exists and is ignored is worse than none: it looks
    like the knob was turned.
    """
    from aidss.config import Settings
    from aidss.plugins.adapters.ai_openai_compatible import OpenAICompatibleProvider

    settings = Settings(
        jwt_secret="test-secret-not-for-production-0123456789abcdef",
        ai_timeout_seconds=123.0,
    )
    provider = OpenAICompatibleProvider.from_settings(settings)

    assert provider._client.timeout.read == 123.0  # noqa: SLF001


def test_the_model_timeout_is_separate_from_the_http_one() -> None:
    """A feed that has not answered in fifteen seconds is broken; a gateway
    generating structured JSON has barely started. One setting for both would
    have to be wrong for one of them."""
    from aidss.config import Settings

    settings = Settings(jwt_secret="test-secret-not-for-production-0123456789abcdef")
    assert settings.ai_timeout_seconds > settings.http_timeout_seconds

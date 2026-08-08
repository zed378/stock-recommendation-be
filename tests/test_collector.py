"""Market Data Collector tests (Phase 2, Section 10).

Covers the three things that decide whether downstream analysis can be
trusted: bad bars never reach storage, provider quirks are normalised away,
and re-running the same fetch changes nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from aidss.collectors.market_data import MarketDataCollector, load_candles
from aidss.collectors.normalization import normalize_candles, normalize_ticker
from aidss.collectors.validation import validate_candles
from aidss.config import Settings
from aidss.db.models import HistoricalPrice, JobStatus, ProviderIngestionRun
from aidss.domain.types import Candle, Timeframe
from aidss.plugins.errors import ProviderUnavailableError
from aidss.plugins.interfaces import MarketDataProvider
from aidss.plugins.registry import get_market_data_provider

BASE = datetime(2025, 1, 1, tzinfo=UTC)


def candle(
    minute: int = 0,
    *,
    open_: str = "100",
    high: str = "105",
    low: str = "95",
    close: str = "102",
    volume: str = "1000",
    timestamp: datetime | None = None,
) -> Candle:
    return Candle(
        timestamp=timestamp or BASE + timedelta(minutes=minute),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal(volume),
    )


# --- Validation ------------------------------------------------------------


def test_valid_candles_pass_through_untouched() -> None:
    result = validate_candles([candle(0), candle(1)])
    assert len(result.accepted) == 2
    assert result.rejected_count == 0


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"high": "90"}, "high"),  # high below open/close
        ({"low": "110"}, "low"),  # low above open/close
        ({"close": "0"}, "non-positive"),
        ({"volume": "-5"}, "volume"),
    ],
)
def test_structurally_broken_candles_are_rejected(kwargs: dict, expected: str) -> None:
    result = validate_candles([candle(0, **kwargs)])
    assert result.accepted == []
    assert expected in result.rejected[0].reason


def test_absurd_price_jumps_are_rejected_not_silently_kept() -> None:
    good = candle(0, open_="100", high="105", low="95", close="100")
    # A tenfold move between consecutive bars is a data error, not a market move.
    spike = candle(1, open_="1000", high="1100", low="900", close="1000")
    result = validate_candles([good, spike])
    assert result.accepted == [good]
    assert "jump" in result.rejected[0].reason


def test_one_bad_bar_does_not_reject_the_bars_after_it() -> None:
    """Outliers are measured against the last *valid* close."""
    a = candle(0, close="100")
    spike = candle(1, open_="1000", high="1100", low="900", close="1000")
    b = candle(2, close="101")
    result = validate_candles([a, spike, b])
    assert result.accepted == [a, b]
    assert result.rejected_count == 1


# --- Normalisation ---------------------------------------------------------


def test_candles_are_sorted_by_time() -> None:
    out = normalize_candles([candle(5), candle(1), candle(3)], Timeframe.M1)
    assert [c.timestamp for c in out] == sorted(c.timestamp for c in out)


def test_duplicate_timestamps_keep_the_latest_revision() -> None:
    original = candle(0, close="100")
    revised = candle(0, close="103")
    out = normalize_candles([original, revised], Timeframe.M1)
    assert len(out) == 1
    assert out[0].close == Decimal("103")


def test_timestamps_are_snapped_to_the_timeframe_grid() -> None:
    off_grid = candle(timestamp=BASE + timedelta(minutes=1, seconds=37))
    out = normalize_candles([off_grid], Timeframe.M1)
    assert out[0].timestamp == BASE + timedelta(minutes=1)


def test_non_utc_timestamps_are_converted() -> None:
    jakarta = timezone(timedelta(hours=7))
    out = normalize_candles([candle(timestamp=BASE.astimezone(jakarta))], Timeframe.M1)
    assert out[0].timestamp.utcoffset() == timedelta(0)
    assert out[0].timestamp == BASE


@pytest.mark.parametrize("raw", ["bbca", " BBCA ", "BBCA"])
def test_ticker_normalisation(raw: str) -> None:
    assert normalize_ticker(raw) == "BBCA"


@pytest.mark.parametrize("raw", ["", "  ", "BB CA", "!!"])
def test_malformed_tickers_are_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_ticker(raw)


# --- Collector -------------------------------------------------------------


@pytest.fixture
def collector() -> MarketDataCollector:
    return MarketDataCollector(get_market_data_provider(Settings(market_data_provider="fixture")))


def test_collect_persists_candles(session, collector: MarketDataCollector) -> None:
    asset = collector.get_or_create_asset(session, "BBCA")
    end = datetime.now(UTC)
    report = collector.collect(session, asset, Timeframe.D1, end - timedelta(days=90), end)

    assert report.fetched > 0
    assert report.inserted == report.fetched - report.rejected
    stored = session.scalar(
        select(func.count())
        .select_from(HistoricalPrice)
        .where(HistoricalPrice.asset_id == asset.id)
    )
    assert stored == report.inserted


def test_re_running_the_same_fetch_inserts_nothing_new(
    session, collector: MarketDataCollector
) -> None:
    """Idempotency: a retried job must not duplicate rows."""
    asset = collector.get_or_create_asset(session, "TLKM")
    end = datetime(2025, 6, 1, tzinfo=UTC)
    start = end - timedelta(days=60)

    first = collector.collect(session, asset, Timeframe.D1, start, end)
    second = collector.collect(session, asset, Timeframe.D1, start, end)

    assert first.inserted > 0
    assert second.inserted == 0
    assert second.updated == 0

    total = session.scalar(
        select(func.count())
        .select_from(HistoricalPrice)
        .where(HistoricalPrice.asset_id == asset.id)
    )
    assert total == first.inserted


def test_overlapping_ranges_do_not_duplicate_rows(
    session, collector: MarketDataCollector
) -> None:
    asset = collector.get_or_create_asset(session, "ASII")
    end = datetime(2025, 6, 1, tzinfo=UTC)

    collector.collect(session, asset, Timeframe.D1, end - timedelta(days=60), end)
    collector.collect(session, asset, Timeframe.D1, end - timedelta(days=30), end)

    rows = session.scalars(
        select(HistoricalPrice.timestamp).where(HistoricalPrice.asset_id == asset.id)
    ).all()
    assert len(rows) == len(set(rows))


def test_each_run_is_recorded_for_observability(session, collector: MarketDataCollector) -> None:
    asset = collector.get_or_create_asset(session, "BBRI")
    end = datetime.now(UTC)
    collector.collect(session, asset, Timeframe.D1, end - timedelta(days=30), end)

    run = session.scalar(
        select(ProviderIngestionRun).where(ProviderIngestionRun.asset_id == asset.id)
    )
    assert run is not None
    assert run.status == JobStatus.SUCCEEDED
    assert run.provider_name == "fixture"
    assert run.finished_at is not None


def test_provider_failure_is_recorded_and_propagated(session) -> None:
    class BrokenProvider(MarketDataProvider):
        name = "broken-for-test"

        def get_quote(self, ticker):
            raise ProviderUnavailableError(self.name, "down")

        def get_historical_candles(self, ticker, timeframe, start, end):
            raise ProviderUnavailableError(self.name, "upstream timeout", retryable=True)

    collector = MarketDataCollector(BrokenProvider())
    asset = collector.get_or_create_asset(session, "GOTO")
    end = datetime.now(UTC)

    # The collector must not swallow the failure: the caller decides whether to
    # retry or fall back to another provider.
    with pytest.raises(ProviderUnavailableError):
        collector.collect(session, asset, Timeframe.D1, end - timedelta(days=5), end)

    run = session.scalar(
        select(ProviderIngestionRun).where(ProviderIngestionRun.asset_id == asset.id)
    )
    assert run is not None
    assert run.status == JobStatus.FAILED
    assert "timeout" in (run.error or "")


def test_get_or_create_asset_is_stable(session, collector: MarketDataCollector) -> None:
    first = collector.get_or_create_asset(session, "bbca")
    second = collector.get_or_create_asset(session, "BBCA")
    assert first.id == second.id


def test_load_candles_returns_chronological_order(session, collector: MarketDataCollector) -> None:
    asset = collector.get_or_create_asset(session, "BBCA")
    end = datetime.now(UTC)
    collector.collect(session, asset, Timeframe.D1, end - timedelta(days=90), end)

    candles = load_candles(session, asset.id, Timeframe.D1, limit=20)
    assert len(candles) == 20
    timestamps = [c.timestamp for c in candles]
    assert timestamps == sorted(timestamps), "indicators require an ascending series"


def test_load_candles_limit_returns_the_most_recent_bars(
    session, collector: MarketDataCollector
) -> None:
    asset = collector.get_or_create_asset(session, "BBCA")
    end = datetime.now(UTC)
    collector.collect(session, asset, Timeframe.D1, end - timedelta(days=90), end)

    everything = load_candles(session, asset.id, Timeframe.D1)
    limited = load_candles(session, asset.id, Timeframe.D1, limit=10)
    assert limited == everything[-10:]

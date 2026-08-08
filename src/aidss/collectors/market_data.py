"""Market Data Collector (Phase 2, Section 7).

The flow: fetch from a MarketDataProvider -> Cleaning & Validation ->
Normalization -> upsert into ``historical_prices``. Upsert rather than insert
is what makes re-fetching the same range idempotent, which in turn is what
makes retrying a job that died halfway through safe.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.collectors.normalization import normalize_candles, normalize_ticker
from aidss.collectors.validation import ValidationResult, validate_candles
from aidss.db.base import utcnow
from aidss.db.models import (
    Asset,
    FundamentalMetric,
    HistoricalPrice,
    JobStatus,
    ProviderIngestionRun,
)
from aidss.domain.types import Candle, Timeframe
from aidss.plugins.errors import ProviderUnavailableError
from aidss.plugins.interfaces import MarketDataProvider


@dataclass(slots=True)
class IngestionReport:
    """Summary of one collector run; also persisted to ``provider_ingestion_runs``."""

    asset_id: uuid.UUID
    ticker: str
    timeframe: Timeframe
    provider: str
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    rejected: int = 0
    rejection_reasons: list[str] | None = None

    @property
    def persisted(self) -> int:
        return self.inserted + self.updated


class MarketDataCollector:
    def __init__(self, provider: MarketDataProvider) -> None:
        self._provider = provider

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def get_or_create_asset(
        self, session: Session, ticker: str, *, exchange: str = "IDX", **fields: object
    ) -> Asset:
        ticker = normalize_ticker(ticker)
        asset = session.scalar(
            select(Asset).where(Asset.ticker == ticker, Asset.exchange == exchange)
        )
        if asset is None:
            asset = Asset(ticker=ticker, exchange=exchange, **fields)  # type: ignore[arg-type]
            session.add(asset)
            session.flush()
        return asset

    def collect(
        self,
        session: Session,
        asset: Asset,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> IngestionReport:
        """Fetch, validate, normalise, and store candles for one asset."""
        report = IngestionReport(
            asset_id=asset.id,
            ticker=asset.ticker,
            timeframe=timeframe,
            provider=self._provider.name,
            rejection_reasons=[],
        )
        run = ProviderIngestionRun(
            provider_name=self._provider.name,
            asset_id=asset.id,
            timeframe=timeframe.value,
            range_start=start,
            range_end=end,
            status=JobStatus.RUNNING,
        )
        session.add(run)
        session.flush()

        try:
            raw = self._provider.get_historical_candles(asset.ticker, timeframe, start, end)
        except ProviderUnavailableError as exc:
            run.status = JobStatus.FAILED
            run.error = str(exc)
            run.finished_at = utcnow()
            # Deliberately not swallowed: the caller (worker or endpoint) is the
            # one that decides between a retry and a provider fallback.
            raise

        report.fetched = len(raw)
        validation: ValidationResult = validate_candles(raw)
        report.rejected = validation.rejected_count
        report.rejection_reasons = sorted({r.reason for r in validation.rejected})

        candles = normalize_candles(validation.accepted, timeframe)
        inserted, updated = self._upsert(session, asset, timeframe, candles)
        report.inserted, report.updated = inserted, updated

        run.fetched_count = report.fetched
        run.inserted_count = inserted
        run.updated_count = updated
        run.rejected_count = report.rejected
        run.status = JobStatus.SUCCEEDED
        run.finished_at = utcnow()
        session.flush()
        return report

    def _upsert(
        self,
        session: Session,
        asset: Asset,
        timeframe: Timeframe,
        candles: list[Candle],
    ) -> tuple[int, int]:
        if not candles:
            return 0, 0

        timestamps = [c.timestamp for c in candles]
        existing_rows = session.scalars(
            select(HistoricalPrice).where(
                HistoricalPrice.asset_id == asset.id,
                HistoricalPrice.timeframe == timeframe.value,
                HistoricalPrice.timestamp.in_(timestamps),
            )
        ).all()
        existing = {row.timestamp: row for row in existing_rows}

        inserted = updated = 0
        for candle in candles:
            row = existing.get(candle.timestamp)
            if row is None:
                session.add(
                    HistoricalPrice(
                        asset_id=asset.id,
                        timeframe=timeframe.value,
                        timestamp=candle.timestamp,
                        open=candle.open,
                        high=candle.high,
                        low=candle.low,
                        close=candle.close,
                        volume=candle.volume,
                        source=self._provider.name,
                    )
                )
                inserted += 1
                continue

            changed = (
                row.open != candle.open
                or row.high != candle.high
                or row.low != candle.low
                or row.close != candle.close
                or row.volume != candle.volume
            )
            if changed:
                row.open, row.high = candle.open, candle.high
                row.low, row.close = candle.low, candle.close
                row.volume = candle.volume
                row.source = self._provider.name
                row.ingested_at = utcnow()
                updated += 1

        session.flush()
        return inserted, updated


@dataclass(slots=True)
class FundamentalReport:
    """Summary of one fundamental fetch."""

    ticker: str
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    #: Set when the provider simply has no fundamental coverage - a fact worth
    #: distinguishing from a failure, because it is not one.
    unsupported: bool = False


class FundamentalCollector:
    """Fetches reported financial metrics into ``fundamental_metrics``.

    Separate from the candle collector because the two have nothing in common
    operationally: prices arrive continuously and are appended, fundamentals
    arrive quarterly and are revised. Upserting on
    (asset, period, period_type, metric) means a restated figure replaces the
    old one rather than sitting beside it.
    """

    def __init__(self, provider: MarketDataProvider) -> None:
        self._provider = provider
        # Attributed to whichever adapter actually answered. Under a composite
        # provider that is not `provider.name`, and recording the wrapper
        # instead would make a stored figure untraceable to its source.
        self._source = provider.fundamentals_source_name()

    def collect(self, session: Session, asset: Asset) -> FundamentalReport:
        report = FundamentalReport(ticker=asset.ticker)

        points = self._provider.get_fundamentals(asset.ticker)
        if not points:
            # An empty result from a provider with no fundamental coverage is
            # not an error; the Fundamental Analyzer will skip and say why.
            report.unsupported = True
            return report

        report.fetched = len(points)
        existing_rows = session.scalars(
            select(FundamentalMetric).where(FundamentalMetric.asset_id == asset.id)
        ).all()
        existing = {
            (row.period, row.period_type, row.metric_name): row for row in existing_rows
        }

        for point in points:
            key = (point.period, point.period_type, point.metric)
            row = existing.get(key)
            if row is None:
                session.add(
                    FundamentalMetric(
                        asset_id=asset.id,
                        period=point.period,
                        period_type=point.period_type,
                        metric_name=point.metric,
                        value=point.value,
                        source=self._source,
                    )
                )
                report.inserted += 1
            elif row.value != point.value:
                row.value = point.value
                row.source = self._source
                row.ingested_at = utcnow()
                report.updated += 1

        session.flush()
        return report


def load_candles(
    session: Session,
    asset_id: uuid.UUID,
    timeframe: Timeframe,
    *,
    limit: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[Candle]:
    """Read stored candles back as domain types - the Indicator Engine's input."""
    stmt = select(HistoricalPrice).where(
        HistoricalPrice.asset_id == asset_id,
        HistoricalPrice.timeframe == timeframe.value,
    )
    if start is not None:
        stmt = stmt.where(HistoricalPrice.timestamp >= start)
    if end is not None:
        stmt = stmt.where(HistoricalPrice.timestamp <= end)

    if limit is not None:
        # Take the newest N, then reverse: indicators require an ascending
        # chronological series, but "most recent" is what a limit should mean.
        rows = list(
            session.scalars(stmt.order_by(HistoricalPrice.timestamp.desc()).limit(limit)).all()
        )
        rows.reverse()
    else:
        rows = list(session.scalars(stmt.order_by(HistoricalPrice.timestamp.asc())).all())

    return [
        Candle(
            timestamp=row.timestamp,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
        )
        for row in rows
    ]

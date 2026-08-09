"""Turning an issuer the platform merely knows about into one it can analyse.

The whole-exchange scan made every listed issuer reachable: the market scan and
the screener both link straight to `/assets/{ticker}`, and there are about
eight hundred of those against the dozen anybody had registered. Everything
else on the issuer page then answers "Asset 'EMDE' on exchange 'IDX' is not
registered", which is true and useless - the reader is looking at a row the
platform itself put in front of them.

**Registering is a separate outcome from collecting, and conflating them made
the button unfixable.** The ingest route created the `Asset` row and then asked
the price provider for history; when the provider had nothing for that symbol
it raised, the response became a 502, and the transaction rolled back - taking
the row with it. Pressing the button again repeated exactly that. An issuer the
provider does not carry could never be registered, no matter how many times
somebody tried.

**The prices were already here.** One request per session gives OHLCV for all
963 issuers, and the scan has been storing them for months. Asking an external
provider for a symbol it may not carry, while the exchange's own record for
that issuer sits in the next table, is the wrong source to reach for first.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.collectors.normalization import normalize_ticker
from aidss.collectors.trading_summary import candles_from_summaries, summaries_for
from aidss.db.models import Asset, HistoricalPrice, Issuer
from aidss.domain.types import Timeframe

logger = logging.getLogger("aidss.collectors")

#: Where the seeded bars say they came from. Named for the exchange rather than
#: for a provider, so a row's origin stays honest in a column several adapters
#: write to.
SOURCE = "idx_trading_summary"


@dataclass(frozen=True, slots=True)
class Registration:
    asset: Asset
    created: bool
    #: Bars copied from the stored exchange sessions.
    seeded: int

    def as_payload(self) -> dict[str, Any]:
        return {
            "ticker": self.asset.ticker,
            "created": self.created,
            "seeded_bars": self.seeded,
        }


def directory_entry(session: Session, ticker: str) -> Issuer | None:
    return session.scalar(select(Issuer).where(Issuer.ticker == normalize_ticker(ticker)))


def seed_prices(session: Session, asset: Asset) -> int:
    """Copy stored exchange sessions into this asset's price history.

    Only the sessions not already present. Re-running is therefore free and
    cannot duplicate a bar, which matters because this is called from a route
    somebody may press twice.
    """
    bars = candles_from_summaries(summaries_for(session, asset.ticker))
    if not bars:
        return 0

    existing = set(
        session.scalars(
            select(HistoricalPrice.timestamp).where(
                HistoricalPrice.asset_id == asset.id,
                HistoricalPrice.timeframe == Timeframe.D1,
            )
        ).all()
    )

    added = 0
    for bar in bars:
        if bar.timestamp in existing:
            continue
        session.add(
            HistoricalPrice(
                asset_id=asset.id,
                timeframe=Timeframe.D1,
                timestamp=bar.timestamp,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                source=SOURCE,
            )
        )
        added += 1

    session.flush()
    return added


def register(session: Session, ticker: str, *, exchange: str = "IDX") -> Registration | None:
    """Register a listed issuer so the rest of the platform can work with it.

    Returns None for a ticker that is not in the issuer directory. That
    restriction is the whole safety of this: the directory is the exchange's
    own list of listed companies, so anything in it is real, and anything else
    - a typo, a crawler walking the URL space - creates nothing. Without it,
    `GET /assets/NOPE` would mint an asset row advertising an instrument that
    does not exist.

    Name and sector come from the directory rather than being left blank: they
    are already known, and an issuer page headed by a bare four-letter code
    tells the reader less than the exchange already published.
    """
    issuer = directory_entry(session, ticker)
    if issuer is None:
        return None

    code = normalize_ticker(ticker)
    asset = session.scalar(
        select(Asset).where(Asset.ticker == code, Asset.exchange == exchange)
    )
    created = asset is None
    if asset is None:
        asset = Asset(
            ticker=code,
            exchange=exchange,
            name=issuer.name,
            sector=issuer.sector,
            industry=issuer.industry,
        )
        session.add(asset)
        session.flush()

    seeded = seed_prices(session, asset)
    # `created` is a reserved attribute on `LogRecord` - passing it in `extra`
    # raises rather than logging - so the field is named for what it says.
    logger.info(
        "issuer registered from directory",
        extra={"ticker": code, "asset_created": created, "seeded_bars": seeded},
    )
    return Registration(asset=asset, created=created, seeded=seeded)

"""Adding a listed issuer the platform already has prices for.

The whole-exchange scan made every listed issuer reachable - the scan and the
screener both link to `/assets/{ticker}` - while `Asset` rows existed only for
the handful anybody had registered. Opening one of those links answered "not
registered", and pressing the fetch button could not fix it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from aidss.collectors.registration import SOURCE, register, seed_prices
from aidss.collectors.trading_summary import sync_summaries
from aidss.db.models import Asset, HistoricalPrice, Issuer
from aidss.domain.types import Timeframe


def listed(session, ticker="EMDE", name="Megapolitan Developments") -> Issuer:
    issuer = Issuer(ticker=ticker, name=name, sector="Properties", industry="Real Estate")
    session.add(issuer)
    session.flush()
    return issuer


def sessions(session, ticker="EMDE", count=40) -> None:
    start = date(2026, 6, 1)
    rows = []
    for index in range(count):
        on_date = start + timedelta(days=index)
        if on_date.weekday() >= 5:
            continue
        close = 100.0 + index
        rows.append(
            {
                "StockCode": ticker,
                "Date": datetime.combine(on_date, datetime.min.time()).isoformat(),
                "OpenPrice": close,
                "High": close * 1.01,
                "Low": close * 0.99,
                "Close": close,
                "Previous": close,
                "Volume": 500_000,
                "Value": 500_000 * close,
                "Frequency": 100,
                "ForeignBuy": 0,
                "ForeignSell": 0,
            }
        )
    sync_summaries(session, rows)
    session.flush()


def test_a_listed_issuer_can_be_added(session) -> None:
    listed(session)
    sessions(session)

    result = register(session, "EMDE")

    assert result is not None
    assert result.created is True
    assert result.seeded > 0


def test_the_name_comes_from_the_directory(session) -> None:
    """It is already known. An issuer page headed by a bare four-letter code
    tells the reader less than the exchange itself published."""
    listed(session)

    result = register(session, "EMDE")

    assert result.asset.name == "Megapolitan Developments"
    assert result.asset.sector == "Properties"


def test_a_ticker_not_in_the_directory_creates_nothing(session) -> None:
    """The restriction that makes this safe. Without it, walking the URL space
    would mint an asset row for every four-letter string somebody tried, each
    advertising an instrument that does not exist."""
    assert register(session, "NOPE") is None
    assert session.scalars(select(Asset)).all() == []


def test_prices_come_from_the_exchange_records_already_stored(session) -> None:
    """The point of the fix. One request per session gives OHLCV for all 963
    issuers and the scan has been storing them, so asking an external provider
    for a symbol it may not carry is the wrong source to reach for first."""
    listed(session)
    sessions(session, count=40)

    register(session, "EMDE")

    bars = session.scalars(
        select(HistoricalPrice).where(HistoricalPrice.timeframe == Timeframe.D1)
    ).all()
    assert bars
    assert {bar.source for bar in bars} == {SOURCE}


def test_adding_twice_does_not_duplicate_a_bar(session) -> None:
    """Called from a route somebody may press twice."""
    listed(session)
    sessions(session)

    first = register(session, "EMDE")
    second = register(session, "EMDE")

    assert second.created is False
    assert second.seeded == 0
    assert len(session.scalars(select(HistoricalPrice)).all()) == first.seeded


def test_an_issuer_with_no_stored_sessions_is_still_added(session) -> None:
    """Registering and collecting are separate outcomes. An issuer with no
    stored history is a page saying "no prices yet", which is a different and
    better thing than a page saying the issuer does not exist."""
    listed(session, ticker="AAAA", name="Nothing Traded Yet")

    result = register(session, "AAAA")

    assert result.created is True
    assert result.seeded == 0


def test_seeding_is_case_insensitive_about_the_code(session) -> None:
    listed(session)
    sessions(session)

    result = register(session, "emde")

    assert result.asset.ticker == "EMDE"
    assert result.seeded > 0


# --- the endpoint -----------------------------------------------------------


def test_the_404_tells_a_reader_what_to_do(client, auth_headers, session) -> None:
    """"Not registered" was true and useless: the scan put that row in front of
    the reader, and the message said nothing about the button that fixes it."""
    from aidss.db.base import get_sessionmaker

    db = get_sessionmaker()()
    try:
        db.add(Issuer(ticker="EMDE", name="Megapolitan Developments"))
        db.commit()
    finally:
        db.close()

    response = client.get("/assets/EMDE/candles", headers=auth_headers)

    assert response.status_code == 404
    assert "not yet" in response.json()["detail"]


def test_an_unlisted_code_keeps_the_plain_message(client, auth_headers) -> None:
    """A typo must not be offered an Add button."""
    response = client.get("/assets/ZZZZ/candles", headers=auth_headers)

    assert response.status_code == 404
    assert "not registered" in response.json()["detail"]


def test_registering_an_unlisted_code_is_refused(client, auth_headers) -> None:
    response = client.post("/assets/ZZZZ/register", headers=auth_headers)

    assert response.status_code == 404
    assert "directory" in response.json()["detail"]


def test_the_register_endpoint_adds_and_seeds(client, auth_headers) -> None:
    from aidss.db.base import get_sessionmaker

    db = get_sessionmaker()()
    try:
        listed(db)
        sessions(db)
        db.commit()
    finally:
        db.close()

    response = client.post("/assets/EMDE/register", headers=auth_headers)

    assert response.status_code == 201
    body = response.json()
    assert body["ticker"] == "EMDE"
    assert body["created"] is True
    assert body["seeded_bars"] > 0

    # The page that was answering 404 a moment ago now answers.
    assert client.get("/assets/EMDE/candles", headers=auth_headers).status_code == 200


def test_a_failed_fetch_no_longer_discards_the_registration(client, auth_headers) -> None:
    """The bug behind the report. `ingest` created the Asset row and then asked
    the provider for history; when the provider had nothing for that symbol it
    raised, the 502 rolled the transaction back, and the row went with it.
    Pressing the button again repeated exactly that, forever.
    """
    from aidss.db.base import get_sessionmaker
    from aidss.plugins.errors import ProviderUnavailableError
    from aidss.plugins.registry import get_market_data_provider

    db = get_sessionmaker()()
    try:
        listed(db)
        sessions(db)
        db.commit()
    finally:
        db.close()

    provider = get_market_data_provider()

    def refuse(*args, **kwargs):
        raise ProviderUnavailableError("yahoo", "no data for this symbol", retryable=False)

    original = type(provider).get_historical_candles
    type(provider).get_historical_candles = refuse
    try:
        response = client.post(
            "/assets/EMDE/ingest", headers=auth_headers, json={"timeframe": "1d", "days": 400}
        )
    finally:
        type(provider).get_historical_candles = original

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["inserted"] > 0
    assert body["provider"] == SOURCE
    assert any("provider unavailable" in reason for reason in body["rejection_reasons"])


def test_a_provider_failure_with_nothing_stored_still_reports_it(
    client, auth_headers
) -> None:
    """The fallback must not turn a genuine outage into a silent success."""
    from aidss.db.base import get_sessionmaker
    from aidss.plugins.errors import ProviderUnavailableError
    from aidss.plugins.registry import get_market_data_provider

    db = get_sessionmaker()()
    try:
        listed(db, ticker="BBBB", name="No Sessions Held")
        db.commit()
    finally:
        db.close()

    provider = get_market_data_provider()

    def refuse(*args, **kwargs):
        raise ProviderUnavailableError("yahoo", "upstream is down", retryable=True)

    original = type(provider).get_historical_candles
    type(provider).get_historical_candles = refuse
    try:
        response = client.post(
            "/assets/BBBB/ingest", headers=auth_headers, json={"timeframe": "1d", "days": 400}
        )
    finally:
        type(provider).get_historical_candles = original

    assert response.status_code == 502
    assert "nothing to fall back on" in response.json()["detail"]["message"]

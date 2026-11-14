"""Tests for TradingAgents multi-agent debate, vendors, and decision memory."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from aidss.agents.trading_agents import load_past_lessons, settle_pending_decisions
from aidss.collectors.vendors import (
    fetch_fred_series,
    fetch_reddit_posts,
    fetch_sec_company_facts,
    fetch_stocktwits_messages,
)
from aidss.db.models import Asset, HistoricalPrice, TradingDecisionLog
from aidss.domain.types import RecommendationLabel, Timeframe


@pytest.fixture(autouse=True)
def fixture_ai_provider(monkeypatch):
    monkeypatch.setenv("AIDSS_AI_PROVIDER", "fixture")
    from aidss.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def ingested(client: TestClient, auth_headers) -> None:
    resp = client.post(
        "/assets/BBCA/ingest", json={"timeframe": "1d", "days": 400}, headers=auth_headers
    )
    assert resp.status_code == 200


def test_stocktwits_vendor_parses_messages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "messages": [
                    {
                        "body": "Bullish on &amp;AAPL breakout",
                        "created_at": "2026-10-01T12:00:00Z",
                        "user": {"username": "trader1"},
                        "entities": {"sentiment": {"basic": "Bullish"}},
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        msgs = fetch_stocktwits_messages("AAPL", client=client)

    assert len(msgs) == 1
    assert msgs[0]["body"] == "Bullish on &AAPL breakout"
    assert msgs[0]["sentiment"] == "Bullish"
    assert msgs[0]["user"] == "trader1"


def test_reddit_vendor_parses_posts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "children": [
                        {
                            "data": {
                                "title": "AAPL earnings discussion",
                                "subreddit": "stocks",
                                "score": 42,
                                "num_comments": 10,
                                "created_utc": 1760000000,
                                "selftext": "Solid margins.",
                                "url": "https://reddit.com/r/stocks/1",
                            }
                        }
                    ]
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        posts = fetch_reddit_posts("AAPL", client=client)

    assert len(posts) == 1
    assert posts[0]["title"] == "AAPL earnings discussion"
    assert posts[0]["subreddit"] == "stocks"


def test_fred_vendor_parses_csv_fallback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="DATE,FEDFUNDS\n2026-09-01,4.50\n2026-10-01,4.25\n")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        obs = fetch_fred_series("fed_funds_rate", api_key="", client=client)

    assert len(obs) == 2
    assert obs[-1] == {"date": "2026-10-01", "value": "4.25"}


def test_sec_edgar_vendor_parses_facts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "company_tickers.json" in str(request.url):
            return httpx.Response(200, json={"0": {"cik_str": 320193, "ticker": "AAPL"}})
        return httpx.Response(
            200,
            json={
                "entityName": "Apple Inc.",
                "facts": {
                    "us-gaap": {
                        "Revenues": {
                            "units": {
                                "USD": [
                                    {
                                        "val": 391000000000,
                                        "end": "2025-09-30",
                                        "filed": "2025-11-01",
                                        "form": "10-K",
                                    }
                                ]
                            }
                        }
                    }
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        facts = fetch_sec_company_facts("AAPL", client=client)

    assert facts["entity_name"] == "Apple Inc."
    assert facts["facts"]["Revenues"]["val"] == 391000000000


def test_trading_agents_mode_runs_full_debate_and_logs_decision(
    client: TestClient, auth_headers, ingested, monkeypatch
) -> None:
    # Avoid live network calls during vendor enrichment
    monkeypatch.setattr("aidss.collectors.vendors.fetch_stocktwits_messages", lambda *a, **kw: [])
    monkeypatch.setattr("aidss.collectors.vendors.fetch_reddit_posts", lambda *a, **kw: [])
    monkeypatch.setattr("aidss.collectors.vendors.fetch_fred_macro_snapshot", lambda *a, **kw: {})
    monkeypatch.setattr("aidss.collectors.vendors.fetch_sec_company_facts", lambda *a, **kw: {})

    resp = client.post(
        "/assets/BBCA/analysis",
        json={
            "timeframe": "1d",
            "mode": "trading_agents",
            "max_debate_rounds": 1,
            "max_risk_rounds": 1,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "trading_agents"
    ta = body["trading_agents"]
    assert ta is not None
    assert len(ta["research_debate"]) == 2
    assert ta["research_manager"]["consensus_bias"] == "neutral"
    assert ta["trader_proposal"]["proposed_stance"] == "watchlist"
    assert len(ta["risk_debate"]) == 3
    assert ta["portfolio_manager"]["final_rating"] == "watchlist"
    assert ta["decision_log_id"] is not None

    # Decision log endpoint returns the persisted decision
    decisions_resp = client.get("/assets/BBCA/decisions", headers=auth_headers)
    assert decisions_resp.status_code == 200
    decisions = decisions_resp.json()
    assert len(decisions) >= 1
    assert decisions[0]["ticker"] == "BBCA"
    assert decisions[0]["final_rating"] == "watchlist"


def test_decision_settlement_is_lookahead_safe(session) -> None:
    asset = Asset(ticker="TEST", exchange="IDX", name="Test Corp")
    session.add(asset)
    session.flush()

    t0 = datetime.now(UTC) - timedelta(days=5)
    t1 = t0 + timedelta(days=2)

    session.add(
        HistoricalPrice(
            asset_id=asset.id,
            timeframe=Timeframe.D1.value,
            timestamp=t1,
            open=Decimal("105"),
            high=Decimal("112"),
            low=Decimal("104"),
            close=Decimal("110"),
            volume=1000,
            source="test",
        )
    )
    log = TradingDecisionLog(
        asset_id=asset.id,
        ticker="TEST",
        exchange="IDX",
        trade_date=t0,
        final_rating=RecommendationLabel.BUY,
        confidence=70.0,
        entry_price=Decimal("100"),
        investment_plan="Constructive plan",
        trader_proposal="Buy stance",
        portfolio_decision="Approved buy stance",
        debate_trace={},
    )
    session.add(log)
    session.flush()

    settled = settle_pending_decisions(session, asset)
    assert len(settled) == 1
    assert settled[0].settled_price == Decimal("110")
    assert settled[0].realized_return_pct == pytest.approx(10.0)
    assert settled[0].outcome_label == "aligned"
    assert settled[0].reflection_lesson

    lessons = load_past_lessons(session, asset.id, "TEST")
    assert len(lessons) == 1
    assert lessons[0]["scope"] == "same_ticker"

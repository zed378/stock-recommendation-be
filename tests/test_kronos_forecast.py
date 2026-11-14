"""Tests for NeoQuasar/Kronos-base OHLCV forecasting integration."""

from __future__ import annotations

import builtins

import pytest
from fastapi.testclient import TestClient

from aidss.config import get_settings


@pytest.fixture
def ingested(client: TestClient, auth_headers) -> None:
    resp = client.post(
        "/assets/BBCA/ingest", json={"timeframe": "1d", "days": 120}, headers=auth_headers
    )
    assert resp.status_code == 200


def test_kronos_forecast_fixture_mode(
    client: TestClient, auth_headers, ingested, monkeypatch
) -> None:
    monkeypatch.setenv("AIDSS_KRONOS_PROVIDER", "fixture")
    get_settings.cache_clear()
    try:
        resp = client.post(
            "/assets/BBCA/forecast",
            json={"timeframe": "1d", "exchange": "IDX", "pred_len": 5},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ticker"] == "BBCA"
        assert body["model_id"] == "NeoQuasar/Kronos-base"
        assert body["tokenizer_id"] == "NeoQuasar/Kronos-Tokenizer-base"
        assert body["provider"] == "fixture"
        assert body["pred_len"] == 5
        assert len(body["bars"]) == 5
        assert body["direction_bias"] in {"bullish", "neutral", "bearish"}
    finally:
        get_settings.cache_clear()


def test_kronos_forecast_requires_minimum_candles(
    client: TestClient, auth_headers, monkeypatch
) -> None:
    monkeypatch.setenv("AIDSS_KRONOS_PROVIDER", "fixture")
    get_settings.cache_clear()
    try:
        # Ingest only 5 days (< 20 required)
        client.post(
            "/assets/BBCA/ingest", json={"timeframe": "1d", "days": 5}, headers=auth_headers
        )
        resp = client.post(
            "/assets/BBCA/forecast",
            json={"timeframe": "1d", "exchange": "IDX", "pred_len": 5},
            headers=auth_headers,
        )
        assert resp.status_code == 409
    finally:
        get_settings.cache_clear()


def test_kronos_forecast_missing_torch_returns_503(
    client: TestClient, auth_headers, ingested, monkeypatch
) -> None:
    monkeypatch.setenv("AIDSS_KRONOS_PROVIDER", "huggingface")
    get_settings.cache_clear()

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "torch" or name.startswith("aidss.forecasting.kronos_model"):
            raise ImportError("No module named 'torch'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    try:
        resp = client.post(
            "/assets/BBCA/forecast",
            json={"timeframe": "1d", "exchange": "IDX", "pred_len": 5},
            headers=auth_headers,
        )
        assert resp.status_code == 503
        assert "kronos" in resp.json()["detail"].lower()
    finally:
        get_settings.cache_clear()


def test_analysis_context_carries_cpu_kronos_forecast(
    client: TestClient, auth_headers, ingested
) -> None:
    from sqlalchemy import select

    from aidss.agents.analyzers import TechnicalAnalyzer
    from aidss.agents.context import ContextBuilder
    from aidss.db import get_sessionmaker
    from aidss.db.models import Asset
    from aidss.domain.types import Timeframe

    assert get_settings().kronos_device == "cpu"
    with get_sessionmaker()() as session:
        asset = session.scalar(select(Asset).where(Asset.ticker == "BBCA"))
        context = ContextBuilder(session).build(asset, Timeframe.D1)
        assert context.forecast["pred_len"] == 5
        assert context.snapshot()["kronos_forecast"] is not None
        prompt = TechnicalAnalyzer().prompt_context(context)
        assert prompt["kronos_forecast"]["direction_bias"] in {"bullish", "neutral", "bearish"}

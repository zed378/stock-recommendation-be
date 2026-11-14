"""FRED (Federal Reserve Economic Data) macroeconomic vendor."""

from __future__ import annotations

import csv
import io
import logging
import os
from datetime import UTC, datetime, timedelta

import httpx

logger = logging.getLogger("aidss.vendors.fred")

_FRED_API_OBS = "https://api.stlouisfed.org/fred/series/observations"
_FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

MACRO_SERIES: dict[str, str] = {
    "fed_funds_rate": "FEDFUNDS",
    "2y_treasury": "DGS2",
    "10y_treasury": "DGS10",
    "yield_curve": "T10Y2Y",
    "cpi": "CPIAUCSL",
    "unemployment_rate": "UNRATE",
    "vix": "VIXCLS",
    "dollar_index": "DTWEXBGS",
    "consumer_sentiment": "UMCSENT",
}


def fetch_fred_series(
    series_id_or_alias: str,
    *,
    api_key: str | None = None,
    lookback_days: int = 365,
    max_rows: int = 20,
    timeout: float = 15.0,
    client: httpx.Client | None = None,
) -> list[dict[str, str]]:
    """Fetch recent observations for a FRED series.

    Uses ``FRED_API_KEY`` when available and falls back to FRED's public CSV
    endpoint otherwise. Returns ``[{"date": ..., "value": ...}]``.
    """
    series_id = MACRO_SERIES.get(series_id_or_alias.lower(), series_id_or_alias.upper())
    key = api_key or os.environ.get("FRED_API_KEY", "").strip()
    start_date = (datetime.now(UTC) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    try:
        if key:
            params = {
                "series_id": series_id,
                "api_key": key,
                "file_type": "json",
                "observation_start": start_date,
                "sort_order": "desc",
                "limit": str(max_rows),
            }
            if client is not None:
                resp = client.get(_FRED_API_OBS, params=params, timeout=timeout)
            else:
                with httpx.Client(timeout=timeout) as c:
                    resp = c.get(_FRED_API_OBS, params=params)
            if resp.status_code != 200:
                return []
            obs = resp.json().get("observations") or []
            return [
                {"date": o["date"], "value": o["value"]}
                for o in reversed(obs)
                if o.get("value") not in (None, ".")
            ]

        params = {"id": series_id, "cosd": start_date}
        if client is not None:
            resp = client.get(_FRED_CSV_URL, params=params, timeout=timeout)
        else:
            with httpx.Client(timeout=timeout) as c:
                resp = c.get(_FRED_CSV_URL, params=params)
        if resp.status_code != 200:
            return []
        reader = csv.reader(io.StringIO(resp.text))
        rows = list(reader)
        if len(rows) <= 1:
            return []
        parsed = [
            {"date": r[0], "value": r[1]}
            for r in rows[1:]
            if len(r) >= 2 and r[1] not in ("", ".")
        ]
        return parsed[-max_rows:]
    except Exception as exc:  # noqa: BLE001
        logger.debug("FRED fetch failed for %s: %s", series_id, exc)
        return []


def fetch_fred_macro_snapshot(
    *,
    series: tuple[str, ...] = ("fed_funds_rate", "10y_treasury", "yield_curve", "vix", "cpi"),
    api_key: str | None = None,
    client: httpx.Client | None = None,
) -> dict[str, dict[str, str]]:
    """Fetch the latest value for a standard set of macro indicators."""
    snapshot: dict[str, dict[str, str]] = {}
    for name in series:
        obs = fetch_fred_series(name, api_key=api_key, max_rows=5, client=client)
        if obs:
            snapshot[name] = obs[-1]
    return snapshot

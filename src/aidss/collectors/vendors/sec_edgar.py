"""SEC EDGAR company facts fetcher for US equities."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("aidss.vendors.sec_edgar")

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
_DEFAULT_UA = "AIDSSResearch/0.1 (contact@example.com)"

_KEY_TAGS = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "NetIncomeLoss",
    "EarningsPerShareDiluted",
    "Assets",
    "Liabilities",
    "StockholdersEquity",
    "CashAndCashEquivalentsAtCarryingValue",
)


def _sec_headers() -> dict[str, str]:
    ua = os.environ.get("SEC_EDGAR_USER_AGENT", "").strip() or _DEFAULT_UA
    return {"User-Agent": ua, "Accept": "application/json"}


def fetch_sec_company_facts(
    ticker: str,
    *,
    timeout: float = 15.0,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Fetch latest US-GAAP XBRL facts for ``ticker`` from SEC EDGAR.

    Returns a compact dict of key financial tags with their most recent filed
    values, or ``{}`` when the ticker is not an SEC filer or the request fails.
    """
    symbol = ticker.strip().upper()
    if not symbol or "." in symbol:
        return {}

    headers = _sec_headers()
    try:
        if client is not None:
            cik = _lookup_cik(symbol, headers, timeout, client)
            if not cik:
                return {}
            resp = client.get(_FACTS_URL.format(cik=cik), headers=headers, timeout=timeout)
        else:
            with httpx.Client(timeout=timeout) as c:
                cik = _lookup_cik(symbol, headers, timeout, c)
                if not cik:
                    return {}
                resp = c.get(_FACTS_URL.format(cik=cik), headers=headers)
        if resp.status_code != 200:
            return {}
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.debug("SEC EDGAR fetch failed for %s: %s", symbol, exc)
        return {}

    us_gaap = (data.get("facts") or {}).get("us-gaap") or {}
    summary: dict[str, Any] = {"entity_name": data.get("entityName", ""), "facts": {}}
    for tag in _KEY_TAGS:
        tag_data = us_gaap.get(tag)
        if not tag_data:
            continue
        units = tag_data.get("units") or {}
        entries = units.get("USD") or units.get("USD/shares") or []
        if not entries:
            continue
        latest = sorted(entries, key=lambda e: (e.get("filed") or "", e.get("end") or ""))[-1]
        summary["facts"][tag] = {
            "val": latest.get("val"),
            "end": latest.get("end"),
            "filed": latest.get("filed"),
            "form": latest.get("form"),
        }
    return summary if summary["facts"] else {}


def _lookup_cik(
    symbol: str, headers: dict[str, str], timeout: float, client: httpx.Client
) -> str | None:
    resp = client.get(_TICKERS_URL, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        return None
    mapping = resp.json()
    for entry in mapping.values():
        if str(entry.get("ticker", "")).upper() == symbol:
            return str(entry["cik_str"]).zfill(10)
    return None

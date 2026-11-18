"""Live check of the EODHD adapter. Skipped unless `AIDSS_EODHD_API_KEY` is set and the `network`
marker is selected (`pytest -m network tests/test_eodhd_live.py`). One fundamentals request costs
10 of the plan's daily API calls. This is what turns the documented shapes into observed ones."""

from __future__ import annotations

import os

import pytest

from aidss.plugins.adapters.market_eodhd import EODHDMarketDataProvider

pytestmark = pytest.mark.network

KEY = os.environ.get("AIDSS_EODHD_API_KEY", "").strip()


@pytest.mark.skipif(not KEY, reason="AIDSS_EODHD_API_KEY is not set")
def test_an_idx_ticker_returns_fundamentals() -> None:
    points = EODHDMarketDataProvider(KEY).get_fundamentals("BBCA")
    assert points, "no coverage for BBCA.JK on this plan, or the response shape differs"
    assert {p.metric for p in points} & {"pe_ratio", "return_on_equity", "market_cap"}

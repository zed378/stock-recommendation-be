"""External data vendors ported from TradingAgents for social, macro, and filings.

Each vendor uses ``httpx`` with short timeouts and graceful degradation:
network errors, rate limits, or missing configuration return empty results
rather than crashing an analysis run.
"""

from aidss.collectors.vendors.fred import MACRO_SERIES, fetch_fred_macro_snapshot, fetch_fred_series
from aidss.collectors.vendors.reddit import fetch_reddit_posts
from aidss.collectors.vendors.sec_edgar import fetch_sec_company_facts
from aidss.collectors.vendors.stocktwits import fetch_stocktwits_messages

__all__ = [
    "MACRO_SERIES",
    "fetch_fred_macro_snapshot",
    "fetch_fred_series",
    "fetch_reddit_posts",
    "fetch_sec_company_facts",
    "fetch_stocktwits_messages",
]

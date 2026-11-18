"""Which markets "ALL" means right now.

ALL is not "every market": the exchange lists hundreds, and the strategy needs fresh candles for
each active pair while the public API is rate limited. So ALL is the markets that pass the owner's
liquidity filter, best 24 hour quote volume first, at most the owner's N of them. The liquidity
numbers come from the exchange's one summary call, so choosing costs one request, not one per pair.

A pure function: no I/O, so it is tested without an exchange and cannot trade anything.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal

from aidss_trader.connector.types import MarketSummary, PairInfo
from aidss_trader.runtime.settings_store import LiquidityFilter

QUOTE = "IDR"


def spread_pct(summary: MarketSummary) -> Decimal | None:
    if summary.bid is None or summary.ask is None or summary.bid <= 0 or summary.ask < summary.bid:
        return None
    return (summary.ask - summary.bid) / summary.bid * 100


def resolve_all(
    pairs: Iterable[PairInfo],
    summaries: Mapping[str, MarketSummary],
    liquidity: LiquidityFilter,
    max_pairs: int,
) -> tuple[str, ...]:
    """The pairs ALL covers: IDR markets that trade (not in maintenance, not suspended), with a
    known 24 hour volume at or above the floor and a known spread at or below the cap, ordered by
    volume (ties by name) and cut at `max_pairs`. Unknown means excluded, never included."""
    if (
        not liquidity.configured
        or max_pairs <= 0
        or liquidity.min_quote_volume_24h_idr is None
        or liquidity.max_spread_pct is None
    ):
        return ()
    floor, cap = liquidity.min_quote_volume_24h_idr, liquidity.max_spread_pct
    eligible: list[tuple[Decimal, str]] = []
    for info in pairs:
        if not info.pair.endswith(QUOTE):
            continue
        if info.maintenance or info.suspended:
            continue
        summary = summaries.get(info.pair)
        if summary is None or summary.quote_volume_24h is None:
            continue
        spread = spread_pct(summary)
        if spread is None or spread > cap or summary.quote_volume_24h < floor:
            continue
        eligible.append((summary.quote_volume_24h, info.pair))
    eligible.sort(key=lambda item: (-item[0], item[1]))
    return tuple(pair for _, pair in eligible[:max_pairs])

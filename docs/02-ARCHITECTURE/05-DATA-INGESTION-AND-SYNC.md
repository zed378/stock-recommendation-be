# 05 — Data Ingestion and Sync

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-011, ADR-012, ADR-022 |
| **Open items** | OQ-4, OQ-6 (resolved, ADR-041 and ADR-043), OQ-15 (resolved, ADR-041) |

All sync is **polling** (ADR-011). Intervals that limit loss are the owner's settings and are not defaulted
here.

## Streams

| Stream | Trigger | Idempotency | Freshness check |
|---|---|---|---|
| Candles 4H and 1D | After each candle period closes, plus a startup backfill | Unique on (pair, timeframe, open time); upsert | Latest closed candle must be the expected one |
| Pair metadata | Startup and on a refresh interval; also before sizing an order | Replace by pair, version-stamped | Age against the refresh interval |
| Prices (last, best bid/ask) | Every **10 seconds** (ADR-041) | Latest value; history optional | Fetch time against `<freshness_limit>` |
| Account balances | Start, each reconciliation, before sizing | Snapshot rows | Age |
| Open orders and order detail | While any order is open, every `<order_poll_interval>` | State transitions keyed by order | Time since last confirmation |
| Trades | After a fill is expected, and each reconciliation | Unique on `tradeId`; append-only | n/a |

## Candle Handling

- The OHLC response uses fields `Time`, `Open`, `High`, `Low`, `Close`, `Volume`; numeric values appear both
  as numbers and as strings in the examples, so the parser accepts both and converts to `Decimal`.
- Timeframes used: `240` and `1D`. The 4H and daily **boundary and time zone are unverified** (OQ-4). The
  strategy must not run until a live comparison fixes them.
- The **current, unfinished candle is never used** for a decision. A decision at candle close uses only
  closed candles. This is also what prevents look-ahead in the backtest (FR-T29).
- A gap in candles is recorded and blocks decisions for that pair until backfilled.

## Backfill

A new pair or a long outage triggers a backfill for the strategy's lookback window. The endpoint takes
`from` and `to` Unix timestamps; the maximum range per request is not stated in the docs, so the fetcher
pages by a conservative window and verifies continuity.

## History Windows

`order/histories` and `myTrades` cap each query at **7 days**. Reconciliation queries in windows no larger
than that, and an outage longer than 7 days cannot be fully reconciled from those endpoints alone; the
runbook covers it.

## Stale Data Policy

A stale price or candle blocks **entries** for the affected pair and raises a warning. It does not stop
the Exit Monitor from using the best available price, but it does raise a critical alert, because a
position being monitored on stale data is effectively unprotected (ADR-007).

## Time

Each signed request carries a millisecond `timestamp` and optional `recvWindow`. The connector checks local
time against `/api/server_time` at start and periodically and halts beyond tolerance (FR-T18).

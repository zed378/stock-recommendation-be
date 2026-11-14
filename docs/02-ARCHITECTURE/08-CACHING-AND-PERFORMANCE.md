# 08 — Caching and Performance

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Open items** | OQ-6 (resolved, ADR-041 and ADR-043) |

Performance here means staying inside Indodax's rate limits and keeping stops responsive. It does not mean
throughput.

## Rate Limits to Respect (from the official docs)

| Scope | Limit |
|---|---|
| Trade API 2.0 public endpoints | 300 requests per minute |
| Legacy public REST (candles, pairs, server time) | 180 requests per minute |
| Create, cancel, open orders, get order, account, order history, trade history | 300 requests per minute per IP |
| Create order | 20 requests per second per user per pair |
| Cancel order | 30 requests per second per user |

Whether public and signed limits are counted together per IP is not stated; the design assumes they might
be and keeps total traffic far below the lowest limit.

## Request Budget (formula, not a setting)

Let `P` be the number of allowlisted pairs.

| Source | Requests per minute |
|---|---|
| Last price and best bid/ask | `2 x 60 / price_poll_interval_s` total, **independent of `P`** (multi-symbol calls) |
| Candles | `P x 2` per candle close; negligible per minute |
| Open-order polling | `ceil(open_orders / 1)` per `order_poll_interval`, only while orders are open |
| Reconciliation | A handful per run |

For a small allowlist and a swing horizon the budget is a small fraction of any limit. The numbers that
set it (`price_poll_interval`, `order_poll_interval`, `reconcile_interval`) are the owner's: price poll 10 s and reconcile 60 s (ADR-041); the order poll interval is 10 s (ADR-043).
A throttle below the limits is still required (FR-T17).

## Caching

| Item | Cache | Invalidate |
|---|---|---|
| Pair metadata (increments, minimums, maintenance) | In memory and DB | On refresh interval, and **before sizing any order** |
| Candles | Database | Append on close |
| Prices | In memory, with timestamp | Replaced on each poll |
| **Balances** | **Not cached for order decisions** | Read fresh before sizing and at reconciliation |
| Credential | Decrypted in memory only while in use | On rotation |

A cached balance used to size an order could permit an order the account cannot fund or exceed a limit, so
balances are always read fresh at decision time.

## Latency That Matters

Only stop reaction: stop crossing to `MARKET` exit. It is bounded by the price polling interval plus
processing, not by Kronos, the analysis platform, or the notifier (NFR-T05). Anything slow runs outside the
exit path.

## CPU Budget

Kronos-base on CPU takes on the order of seconds per sample (measured at about 4 seconds for one sample and
12 seconds for five on the development machine). That is acceptable for a candle-close veto and is why it is
never in the order path or the stop path (ADR-004, ADR-012).

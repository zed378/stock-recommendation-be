# 00 — Canonical Domain Model

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-021, ADR-022, ADR-025 |

All tables live in PostgreSQL schema `trading` (ADR-021). Column-level detail for orders, fills, and the
ledger is in `04-ORDER-POSITION-LEDGER-SCHEMA.md`; risk and audit in `05-RISK-AND-AUDIT-SCHEMA.md`.

## Entities

| Entity | Purpose | Append-only |
|---|---|---|
| `pair` | Exchange metadata for an allowlisted pair: increments, minimums, state | No (versioned) |
| `candle` | Closed OHLCV candles per pair and timeframe | Yes |
| `price_snapshot` | Last, bid, ask with fetch time | Yes |
| `strategy` | A strategy definition and its current mode | No |
| `strategy_version` | Immutable parameter set; a change creates a new version | Yes |
| `signal` | A strategy's output at a candle close | Yes |
| `order_intent` | A sized, priced, risk-checked proposal | State only |
| `risk_check_result` | Per-limit result for an intent | Yes |
| `order` | An instruction sent to Indodax, or simulated | State columns only |
| `order_event` | Every state transition of an order | Yes |
| `fill` | An execution, with fee, tax, clearing | Yes |
| `ledger_entry` | Double-entry style movement from a fill, fee, or adjustment | Yes |
| `balance_snapshot` | Exchange balances at a time | Yes |
| `risk_limit` | Configured limits | Versioned |
| `breaker_event` | A circuit breaker tripping and resuming | Yes |
| `kill_switch_event` | `HALT`, `CANCEL`, `FLATTEN` and each step's result | Yes |
| `approval_request` | An intent awaiting the owner | State only |
| `mode_change` | Mode promotion or demotion with evidence | Yes |
| `reconciliation_run` | One comparison with the exchange | Yes |
| `reconciliation_difference` | A single mismatch | Yes |
| `backtest_run` | Parameters, cost model, results | Yes |
| `credential` | Encrypted Indodax key and secret | No (rotated) |
| `trading_event` | Notification source events | Yes |
| `audit_log` | Every mutation | Yes |
| `lease` | Single-instance lease | No |

## Relationships

```
strategy 1---* strategy_version
strategy 1---* signal 1---0..1 order_intent 1---* risk_check_result
order_intent 1---0..* order 1---* order_event
order 1---* fill 1---* ledger_entry
pair 1---* candle ; pair 1---* price_snapshot ; pair 1---* order
reconciliation_run 1---* reconciliation_difference
```

## Cross-Cutting Fields

Every domain row carries:

| Field | Meaning |
|---|---|
| `id` | UUID primary key |
| `created_at` | UTC, set by the database |
| `origin` | `LIVE`, `PAPER`, or `BACKTEST`. **Rows of different origin never aggregate together** |
| `strategy_version_id` | Where the row came from, when applicable |
| `source` | `exchange`, `local`, or `simulated`. What the data is, not where it was stored |

## Numeric Types (ADR-025)

All money, price, and quantity columns are `NUMERIC(38,18)`. Application code uses `Decimal`. A column of a
float type in `trading` is a defect. Exchange values arrive as strings and are parsed to `Decimal` at the
connector edge.

## Time

All timestamps are `timestamptz` in UTC. Indodax mixes units: most fields are milliseconds, while the OHLC
`Time` example is a Unix timestamp in seconds. The connector normalizes at the edge
(`03-TIME-SERIES-AND-MARKET-DATA.md`).

## Identity of an Order

An order is identified internally by its UUID and externally by two ids that must both be stored: the
numeric `orderId` and the `fullOrderId` such as `btcidr-limit-6423` (different endpoints use different
ones), plus our `clientOrderId`.

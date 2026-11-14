# 04 — Order, Position, and Ledger Schema

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-022, ADR-024, ADR-025, ADR-026 |
| **Open items** | OQ-5 |

Logical schema; exact DDL is written in task T1-03. All money columns are `NUMERIC(38,18)`.

## `order_intent`

| Column | Notes |
|---|---|
| `id`, `strategy_version_id`, `signal_id`, `pair_id`, `origin` | |
| `side` | `BUY` or `SELL` |
| `entry_price`, `quantity`, `stop_price`, `target_price` | `stop_price` is required for an entry (ADR-008) |
| `risk_amount_idr` | `equity x risk_percent`, the amount the stop exposes |
| `rule_snapshot` | JSON of the rule inputs and outputs (FR-T08) |
| `analysis_context` | JSON of what the analysis platform returned, or null |
| `veto` | Boolean and reason, or null |
| `state` | See `02` |
| `expires_at` | For `AWAITING_APPROVAL` |

## `order`

| Column | Notes |
|---|---|
| `id`, `intent_id`, `pair_id`, `origin` | |
| `client_order_id` | Unique. `[A-Za-z0-9_-]{1,36}`, derived from the intent (ADR-024) |
| `exchange_order_id` | Numeric `orderId`; null until accepted |
| `exchange_full_order_id` | `fullOrderId`, for `myTrades` |
| `side`, `type` | `type` in `LIMIT`, `MARKET` |
| `time_in_force` | `GTC` or `MOC`; null for `MARKET` |
| `price`, `quantity`, `quote_order_qty` | `quote_order_qty` only for `BUY MARKET` |
| `executed_qty` | From the exchange |
| `state`, `exchange_status`, `cancel_reason` | |
| `purpose` | `ENTRY`, `EXIT_TARGET`, `EXIT_STOP`, `KILL_CANCEL`, `KILL_FLATTEN` |
| `submitted_at`, `updated_at` | |

**Column-level privilege:** the Trader's role may `UPDATE` only `exchange_order_id`,
`exchange_full_order_id`, `executed_qty`, `state`, `exchange_status`, `cancel_reason`, and `updated_at`.
Everything else is fixed at insert, so an order's intent, price, and size cannot be rewritten afterwards.

## `order_event` (append-only)

`order_id`, `from_state`, `to_state`, `at`, `raw_response` (redacted JSON), `reason`, `actor`
(`system`, `owner`, `killswitch`, `reconciler`).

## `fill` (append-only)

| Column | Notes |
|---|---|
| `id`, `order_id`, `origin` | |
| `exchange_trade_id` | Unique per origin; the idempotency key for ingestion |
| `price`, `quantity`, `quote_quantity` | |
| `is_maker` | Boolean |
| `commission`, `commission_asset` | As returned by `myTrades`; combines fee and tax |
| `fee`, `tax`, `clearing` | Filled **only** when the source provides the split (OQ-5); otherwise null, never estimated |
| `executed_at` | |

Paper fills use the same table with `origin = PAPER` and `exchange_trade_id` null.

## `ledger_entry` (append-only)

| Column | Notes |
|---|---|
| `id`, `origin`, `fill_id` (nullable) | |
| `entry_type` | `FILL_BASE`, `FILL_QUOTE`, `FEE`, `TAX`, `CLEARING`, `ADJUSTMENT` |
| `asset` | e.g. `BTC`, `IDR` |
| `amount` | Signed |
| `reason` | Required for `ADJUSTMENT` |
| `at` | |

`ADJUSTMENT` is the only way to correct the ledger. It needs a reason and writes an audit row.

## Positions (derived)

A position is **computed** from the ledger per (`pair`, `origin`): quantity and weighted average cost.
A materialized cache may exist for speed but is rebuilt from the ledger and never edited. This removes a
whole class of drift between positions and fills.

## PnL

- **Realized:** on a reducing fill, `(sell price - average cost) x quantity` less costs, by weighted average
  cost (ADR-022).
- **Unrealized:** `(last price - average cost) x quantity` at a stated price time.
- Fee, tax, and clearing are **separate lines**, never folded into the price.
- Paper, live, and backtest PnL are separate figures.

## Idempotency

| Operation | Key |
|---|---|
| Insert an order | `client_order_id` unique |
| Ingest a fill | (`origin`, `exchange_trade_id`) unique |
| Insert a candle | (`pair`, `timeframe`, `open_time`) unique |
| Reconciliation difference | (`run_id`, `kind`, `reference`) unique |

# 01 — Source of Truth Matrix

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-022 |

Which system is authoritative for each fact, and what the Trader stores.

| Fact | Authoritative source | Local copy | Refresh and rule |
|---|---|---|---|
| Balances (free, locked) | **Indodax** `GET /api/v2/account` | `balance_snapshot` | Read fresh before sizing and at each reconciliation. Never trusted from cache for a decision |
| API key permissions (`canTrade`, `canWithdraw`, `canWithdrawFiat`) | **Indodax** | Last seen value, for display | Checked at start and every reconciliation |
| Order existence and status | **Indodax** | `order`, `order_event` | Polled; a local state that disagrees with Indodax is a reconciliation difference |
| Executed quantity of an order | **Indodax** | `order.executed_qty` | From order detail or fills; never computed from our own assumption |
| Fills, fee, tax, clearing | **Indodax** (`myTrades`, and `commission` field) | `fill`, `ledger_entry` | Appended once per `tradeId`; the `commission` field combines fees and taxes, so the split is only known from other sources (`06-INTEGRATIONS/10`) |
| Pair rules (increments, minimums, maintenance) | **Indodax** public | `pair` | Refreshed, and before each order |
| Candles | **Indodax** public OHLC | `candle` | Append closed candles only |
| Prices | **Indodax** public | `price_snapshot` | Timestamped; staleness is a property, not a hidden default |
| Server time | **Indodax** | none | Used for skew check |
| Strategy parameters | **Trader** (owner-configured) | `strategy_version` | Immutable versions |
| Risk limits | **Trader** (owner-configured) | `risk_limit` | Versioned; missing means disabled |
| Mode of a strategy | **Trader** | `strategy`, `mode_change` | Changed only through the audited flow |
| Approval decisions | **Trader** | `approval_request` | Bound to the exact intent |
| Ledger | **Derived** from exchange fills | `ledger_entry` | Append-only; a correction is a new entry with a reason |
| Realized and unrealized PnL | **Derived** | Computed from ledger and prices | Recomputable at any time |
| AI and Kronos context | **Analysis platform** | Stored on the intent as read | The Trader stores what it saw, not the analysis platform's tables |
| Credential | **Owner** (generated at Indodax) | `credential` ciphertext | Stored encrypted; the plaintext is not recoverable by any API |

## Rules

1. **When the exchange and the ledger disagree, the exchange wins and trading halts.** The ledger is
   corrected only by a new compensating entry that states the reason.
2. A derived figure (PnL, equity, exposure) is never stored as the only copy; it can be recomputed.
3. `origin` separates live, paper, and backtest rows; a figure that mixes them is a defect.
4. Anything the Trader decided for itself (strategy parameters, limits, modes) is authoritative in the
   Trader and audited.

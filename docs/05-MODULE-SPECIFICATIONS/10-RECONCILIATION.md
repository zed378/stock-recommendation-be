# 10 — Reconciliation

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-022 |
| **Open items** | OQ-15 (resolved, ADR-041) |

Keeps the Trader's records honest by comparing them with the exchange (FR-T27).

## When

At start, then every **60 seconds** (ADR-041), and on demand. Also after any `UNKNOWN` order resolves
and after a kill-switch run.

## What Is Compared

| Check | Local | Exchange |
|---|---|---|
| Open orders | `order` in non-terminal states | `GET /api/v2/openOrders` |
| Recent orders | `order` created in the window | `GET /api/v2/order/histories` per symbol |
| Fills | `fill` in the window | `GET /api/v2/myTrades` per symbol |
| Balances | Ledger-implied holdings | `GET /api/v2/account` |
| Permissions | Credential state | `canTrade`, `canWithdraw`, `canWithdrawFiat` |

History queries are limited to **7 days per request** (`order/histories` and `myTrades`) and require a
`symbol`, so reconciliation iterates over allowlisted pairs and windows. The outage window beyond 7 days
cannot be recovered from these endpoints alone (`02-ARCHITECTURE/05`).

## Difference Kinds

`ORDER_MISSING_LOCALLY`, `ORDER_MISSING_AT_EXCHANGE`, `STATE_MISMATCH`, `QTY_MISMATCH`, `FILL_MISSING_LOCALLY`,
`FILL_MISSING_AT_EXCHANGE`, `BALANCE_MISMATCH`, `PERMISSION_CHANGED`, `UNKNOWN_STATUS`.

A difference is recorded as a `reconciliation_difference` with both values. Rounding tolerances are explicit
and per asset (the pair's quantity increment), not a global fudge.

## Response

1. A difference **halts trading** (`HALT`) and raises `CRITICAL` (ADR-022).
2. **The ledger is not auto-corrected.** Nothing is overwritten.
3. The Owner investigates. Some causes are outside the Trader (an order placed manually on the Indodax app,
   a deposit, a fee change).
4. Resolution is recorded: a cause, and, where the ledger is wrong, an `ADJUSTMENT` entry with a reason and
   an audit row.
5. Resume is an explicit owner action, blocked while an unresolved difference exists.

## Special Cases

- **An order placed outside the Trader** appears as `ORDER_MISSING_LOCALLY`. The Trader does not adopt it
  silently; the owner decides.
- **A permission change** (`canWithdraw` true) halts immediately; it means the key changed at Indodax.
- **Balance mismatch** may be a deposit, withdrawal, or fee the Trader did not make; the Trader cannot
  distinguish them and says so.

## Cost

Each run uses a bounded number of requests (a few per pair), within the rate budget
(`02-ARCHITECTURE/08`). Its interval trades detection speed for request budget (60 seconds, ADR-041).

## Output

A `reconciliation_run` row with counts per check, the differences, duration, and result, shown on the
dashboard with its age (`04-UX-UI/01`).

## Tests (planned)

Each difference kind injected on the mock exchange halts and is not auto-corrected; a permission change
halts; a clean run records and does not halt; a window larger than 7 days is split.

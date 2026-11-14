# 04 — Order Manager

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-006, ADR-024, ADR-026 |
| **Open items** | OQ-22 (resolved, ADR-035 and ADR-042) |

Owns the order state machine (`03-DATA-MODEL/02`). Only this module and the kill switch call
order-mutating connector methods.

## Create Flow

1. Receive a risk-approved intent (or an emergency exit).
2. Derive `clientOrderId` from the intent identity (ADR-024): characters `[A-Za-z0-9_-]`, at most 36.
3. **Persist the order row as `SUBMITTING` and commit (ADR-026).** If this fails, send nothing.
4. Send `POST /api/v2/order` with `symbol`, `side`, `type`, `price` and `quantity` (or `quoteOrderQty` for
   `BUY MARKET`), `newClientOrderId`, `timeInForce`, and `selfTradePreventionMode`.
5. On success record `exchange_order_id` and `fullOrderId`; state `OPEN`.
6. On an error code, record it; state `REJECTED` (`-2010` is a legitimate refusal such as insufficient
   balance or duplicate `clientOrderId`).
7. On timeout or 5xx: state `UNKNOWN`, then resolve (below). **Never send the create again.**

`PAPER` replaces step 4 with the paper executor (`06-PAPER-TRADING-AND-BACKTEST.md`); steps 1 to 3 and 5
to 6 are identical, so the same state machine is exercised.

## Resolving `UNKNOWN` (FR-T14)

Query by `clientOrderId` (`GET /api/v2/order` with `origClientOrderId`, then `openOrders` and
`order/histories` for the symbol). Indodax notes an accepted order "may not be immediately available", so
a single not-found is not proof of absence. The manager retries the query **5 times over 30 seconds** (ADR-042), then raises `CRITICAL` and holds that pair. Only the owner confirms "not found" after
checking the exchange; it is never inferred silently.

## Lifecycle Tracking

Polling, not WebSocket (ADR-011). While an order is open the manager polls `GET /api/v2/order` or
`openOrders` at `<order_poll_interval>`, updates `executed_qty`, appends an `order_event` on every change,
and ingests fills from `myTrades` by `tradeId`. A fill is appended exactly once.

Fills and order status are confirmed against each other: an order reporting `FILLED` whose fills sum to
less than `origQty` is a reconciliation difference.

## Cancel and Reprice

A `LIMIT` order that has not filled within the configured wait is cancelled and, if the signal is still
valid and the Risk Engine agrees again, replaced by a new order with a **new** `clientOrderId`. The wait is **5 minutes** and the maximum is **3 reprices**, after which the signal is abandoned (ADR-042); the
price follows the best bid or ask (ADR-035). After a cancel request the
manager confirms the outcome by reading the order, because the order may have filled first
(`CANCEL_REQUESTED` -> `FILLED` is a valid transition).

Cancels use `DELETE /api/v2/order` with `symbol` and `orderId` or `origClientOrderId`. The documentation
marks both as mandatory in its table but states either is enough; the connector sends `orderId` when known
(`06-INTEGRATIONS/11`).

## Order Types and Parameters

| Purpose | Type | Notes |
|---|---|---|
| Entry | `LIMIT` with `MOC` (ADR-035) | Rejected by the exchange if the price would match immediately; the entry is then handled by the reprice rule |
| Normal exit | `LIMIT`, `GTC` | Placed at the best ask |
| Stop exit, `FLATTEN` | `MARKET` | `SELL` with `quantity`. A `BUY MARKET` is never needed |
| Any | `selfTradePreventionMode` | Sent explicitly as `EXPIRE_TAKER` (ADR-035): the new order expires and the existing state is kept. The exchange default is `EXPIRE_MAKER` |

A test asserts that no entry or normal-exit path can emit `MARKET` (FR-T16).

## Partial Fills

The remaining quantity is tracked. For an exit, a partial fill leaves a smaller position that the Exit
Monitor continues to protect. For an entry, the stop and size follow the executed quantity.

## Throttle

All requests go through the connector's throttle (FR-T17). The manager never loops tighter than the
throttle allows.

## Failure Handling

| Condition | Action |
|---|---|
| `-1021` timestamp | Re-sync time, retry once; repeated means halt |
| `-1003` / HTTP 429 | Back off; investigate the throttle |
| `-2015` access denied | `DISABLED`; credential or permission change |
| `-1016` market suspended | `REJECTED`; the pair is suspended |
| `-2010` rejected | Record and, if it is insufficient balance, raise a reconciliation check |

## Audit

Every create, cancel, reprice, and state change writes an `order_event` and an audit row with the
correlation id of its intent.

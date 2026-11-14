# 06 — Indodax Orders (Trade API 2.0)

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Integration Engineer |
| **Decided by** | ADR-006, ADR-024 |
| **Open items** | OQ-18 (decided, ADR-038), OQ-22 (resolved, ADR-035 and ADR-042) |

Source: `INDODAX-TradeAPI-2-Private.md`, `tapi-v2/enums.md`. **Documented, not yet observed.** All requests
are signed (`04`).

## Create Order: `POST /api/v2/order`

| Parameter | Required | Notes |
|---|---|---|
| `symbol` | Yes | e.g. `BTCIDR` |
| `side` | Yes | `BUY` or `SELL` |
| `type` | Yes | `LIMIT` or `MARKET` |
| `price` | For `LIMIT` | Decimal, must follow the pair's price rules |
| `quantity` | For all orders **except** `BUY MARKET` | Base asset quantity |
| `quoteOrderQty` | For `BUY MARKET` only | IDR amount (int64); not with `quantity` |
| `newClientOrderId` | No | Letters, digits, `_`, `-`; at most 36 characters. Auto-generated if omitted. The Trader **always** sets it (ADR-024) |
| `timeInForce` | No | `GTC` (default) or `MOC` for `LIMIT`. See `11` regarding `FOK` |
| `selfTradePreventionMode` | No | `EXPIRE_TAKER`, `EXPIRE_MAKER` (default), `EXPIRE_BOTH` |

**Rate limit:** 20 requests per second per authenticated user per trading pair (applies even to whitelisted
IPs). The general table also lists 300 per minute per IP for this endpoint; the stricter limit binds
(`11`).

**Unsupported:** `STOP_LIMIT` returns `-1130` with `stop_limit_not_available`. There is no exchange-side
stop (ADR-007).

**Response** (success): `symbol`, `orderId` (numeric), `clientOrderId`, `side`, `type`, `price` (LIMIT
only), `origQty`, `executedQty`, `fullOrderId` such as `btcidr-limit-6423`.

**Important:** "A successful order response confirms that the order has been **accepted**. The order may not
be immediately available through `GET /api/v2/order`." For later status use polling (ADR-011).

**Validation errors seen in the docs:** `-1121` invalid symbol; `-1130` invalid side, type, missing price for
LIMIT, `stop_limit_not_available`, or "[quantity] amount has more precision than allowed". `-2010` is an
order rejection (insufficient balance, duplicate client order ID, other). The Trader rounds quantity down to
the pair increment before sending, so precision errors indicate a bug.

## Cancel Order: `DELETE /api/v2/order`

Parameters in the query string: `symbol` (required), and `orderId` **or** `origClientOrderId` (the table
marks both required; the notes say either, and `orderId` wins if both are sent). Rate limit: 30 requests
per second per user.

Response: `symbol`, `orderId`, `origClientOrderId`, `side`, `type`, `price`, `stopPrice` (if applicable),
`origQty`, `executedQty`, `fullOrderId`. A successful response "confirms that the cancellation has been
processed"; the latest status is confirmed by reading the order.

Errors: `-2013` order not found (examples: "order 30325 is not exists"), `-1121`.

## Get Order: `GET /api/v2/order`

`symbol` plus `orderId` or `origClientOrderId`. Returns the order with `status` (`NEW`, `PARTIALLY_FILLED`,
`FILLED`, `CANCELLED`, `REJECTED`), `executedQty`, `time`, `fullOrderId`. Not-found is `-2013` ("Order not
found or not yet available").

## Open Orders: `GET /api/v2/openOrders`

Optional `symbol`. Returns an array of orders (empty `[]` when none) with `status` and `time`.

## Enums

| Enum | Values |
|---|---|
| `side` | `BUY`, `SELL` |
| `type` | `MARKET`, `LIMIT` |
| `status` | `NEW`, `CANCELLED`, `REJECTED`, `PARTIALLY_FILLED`, `FILLED` |
| `timeInForce` | `GTC` (LIMIT), `MOC` (LIMIT, maker or cancel), `FOK` (listed for MARKET) |
| `selfTradePreventionMode` | `EXPIRE_TAKER`, `EXPIRE_MAKER`, `EXPIRE_BOTH` |

## How the Trader Uses Orders

| Purpose | Request |
|---|---|
| Entry | `LIMIT` with `MOC`, explicit `newClientOrderId` |
| Normal exit | `LIMIT` with `GTC`, explicit `newClientOrderId` |
| Stop exit, `FLATTEN` | `MARKET` `SELL` with `quantity` |
| Never | `BUY MARKET` (not needed), `FOK`, `STOP_LIMIT` |

Placement rules: price at the best bid or ask, `MOC` on entries, `EXPIRE_TAKER` (ADR-035); wait 5 minutes and up to 3 reprices (ADR-042).

## Idempotency and Unknown Outcome

`-2010` can mean a duplicate `newClientOrderId`, which makes the ID usable as an idempotency key. After a
timeout, query by `origClientOrderId`; do not re-send (ADR-024, `05-MODULE-SPECIFICATIONS/04`).

## To Verify Live (OQ-18)

Whether `Accept` is enforced on writes; behavior of `MOC` that would match; what `GET order` returns for a
just-accepted order; what happens on a duplicate `clientOrderId`. Do this against a Read plus Trade key only
with the owner's explicit instruction and a trivially small amount.

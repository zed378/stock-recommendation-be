# 07 — Indodax Account and History (Trade API 2.0)

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Integration Engineer |
| **Decided by** | ADR-013, ADR-022 |
| **Open items** | OQ-5, OQ-18 (decided, ADR-038) |

Source: `INDODAX-TradeAPI-2-Private.md`. **Documented, not yet observed.** All signed.

## Account: `GET /api/v2/account`

Optional `omitZeroBalances` (boolean, default false).

```json
{ "canTrade": true, "canWithdraw": false, "canWithdrawFiat": true,
  "accountType": "individual",
  "balances": [{ "asset": "BTC", "free": "...", "locked": "..." }],
  "uid": 0 }
```

| Field | Use |
|---|---|
| `canTrade` | Must be true |
| `canWithdraw`, `canWithdrawFiat` | **Must be false.** If either is true the Trader refuses to trade (ADR-013) |
| `balances[].free` | Available balance, used for sizing and the funded-buy check |
| `balances[].locked` | In open orders |
| `uid` | Account id. **Never logged, shown, or sent in notifications** |

Note the example shows `canWithdrawFiat: true` next to `canWithdraw: false`; the Trader treats either flag
as a refusal.

## Order History: `GET /api/v2/order/histories`

| Parameter | Notes |
|---|---|
| `symbol` | **Required** |
| `startTime`, `endTime` | Milliseconds UTC. Default: last 24 hours |
| `limit` | 10 to 1000, default 100 |
| `sort` | `asc` or `desc`, default `desc` |

**Maximum interval between `startTime` and `endTime` is 7 days.** Response: `{"data": [...]}` with
`orderId` (a full id such as `aaveidr-limit-3568`), `clientOrderId`, `symbol`, `side`, `type`, `status`
(`FILLED`, `CANCELLED`, `REJECTED`), `price`, `oriQty`, `executedQty`, `submitTime`, `finishTime`, and an
optional `cancelReason` (`SELF_TRADE_PREVENTION`).

Note the quantity field is spelled `oriQty` here and `origQty` elsewhere (`11`). Sorting is newest first by
default.

## Trade History: `GET /api/v2/myTrades`

| Parameter | Notes |
|---|---|
| `symbol` | **Required** |
| `orderId` | A full order id (e.g. `aaveidr-limit-3568`), not the numeric one |
| `clientOrderId` | Filter by client id |
| `startTime`, `endTime` | Milliseconds UTC. Default: last 24 hours. **Maximum interval 7 days** |
| `limit` | 10 to 1000, default 500 |
| `sort` | `asc` or `desc` |

The old `from_id` and `end_id` parameters were removed. Response `{"data": [...]}` with `tradeId`, `orderId`,
`clientOrderId`, `symbol`, `price`, `qty`, `quoteQty`, `commission`, `commissionAsset`, `isBuyer`, `isMaker`,
`time`.

**`commission` is the total of trading fees and applicable taxes in one number** (and, per the
Private WebSocket, a separate clearing fee exists). The split is not in `myTrades` (OQ-5,
`05-MODULE-SPECIFICATIONS/05`).

## How These Are Used

| Need | Call |
|---|---|
| Start check, sizing, equity | `account` |
| Reconciliation | `account`, `openOrders`, `order/histories`, `myTrades` |
| Fill ingestion | `myTrades`, keyed by `tradeId` |
| Resolving `UNKNOWN` | `order`, `openOrders`, `order/histories` |

## Windowing

Both history endpoints need a `symbol` and cap a request at 7 days. The reconciler iterates over the
allowlisted pairs and windows (`05-MODULE-SPECIFICATIONS/10`). Pagination beyond `limit` is by narrowing
the time window; no cursor is documented.

## Explicitly Not Implemented

`capital/config/getall`, `capital/withdraw/history`, `capital/deposit/hisrec`, `fiat/orders`,
`capital/withdraw/apply`, `capital/deposit/address/list`, `fiat/withdraw`, `fiat/deposit`. The Trader has no
need for them, and the withdrawal ones must not exist (ADR-013).

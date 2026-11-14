# 02 — Glossary

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Technical Lead |

## Trading Domain

| Term | Definition |
|---|---|
| **Pair / symbol** | A market such as BTC/IDR. Indodax spells it differently by endpoint: `BTCIDR` (Trade API 2.0 parameters), `btcidr` (pairs `id`, order history `symbol`), `btc_idr` (`ticker_id`, legacy). The Trader stores one canonical form and converts at the connector edge |
| **Base / quote** | In BTC/IDR, BTC is the base (traded) asset and IDR the quote |
| **Allowlist** | The owner-maintained set of pairs the Trader may trade (ADR-005) |
| **Strategy** | A deterministic rule set that turns candles into entry and exit *signals* |
| **Signal** | A strategy's statement that conditions are met. Carries no size and no price authority |
| **Order intent** | A signal, sized and priced by the Trader, awaiting risk checks. Not yet an order |
| **Order** | An instruction sent to Indodax (or simulated in `PAPER`) |
| **Fill** | An execution of all or part of an order, with fee, tax, and clearing |
| **Position** | Net base-asset quantity held per pair, with weighted-average cost |
| **Equity** | Account value in IDR, from exchange balances valued at last prices |
| **Drawdown** | Fall of equity from its peak |
| **Slippage** | Difference between expected and executed price |
| **WAC** | Weighted average cost, the PnL method (ADR-022) |

## Modes and Controls

| Term | Definition |
|---|---|
| **PAPER** | Simulated fills. Never contacts the order endpoint |
| **APPROVAL** | An order is created only after the owner approves the specific intent |
| **AUTO** | Orders are created from valid intents without approval, within all limits |
| **Promotion** | Moving a strategy to the next mode after meeting the gates (ADR-020) |
| **Risk Engine** | The component that checks every intent against limits before any order exists |
| **Circuit breaker** | A limit that, when crossed, stops trading automatically |
| **Kill switch** | The tiered emergency control |
| **HALT** | Stop creating new orders |
| **CANCEL** | `HALT` plus cancel all open orders |
| **FLATTEN** | `CANCEL` plus close all positions with `MARKET` |
| **Veto** | An AI or Kronos signal that blocks an entry. It can never cause one |
| **Exit Monitor** | The bot-side component that enforces stops and targets (ADR-007) |
| **Reconciliation** | Comparing local ledger with Indodax orders, trades, and balances |
| **Stale data** | Market data older than the configured freshness limit |
| **UNKNOWN** | An order whose outcome is not yet known after a timeout or 5xx |

## Indodax API Terms

| Term | Definition |
|---|---|
| **TAPI v2 / Trade API 2.0** | `https://api.indodax.com/api/v2/...`, HMAC-SHA256, `X-APIKEY` and `Sign` headers, dedicated key |
| **Legacy API** | `https://indodax.com/tapi`, `method=...` calls, HMAC-SHA512, `Key` header. Not used (ADR-002) |
| **`orderId`** | Numeric id used by `GET` and `DELETE /api/v2/order` |
| **`fullOrderId`** | Reference such as `btcidr-limit-6423`. Used by `myTrades` to filter by order |
| **`clientOrderId`** | Our idempotency key, set through `newClientOrderId`, at most 36 characters of letters, digits, `_`, `-` |
| **`recvWindow`** | Milliseconds a signed request stays valid after its `timestamp`; default 5000 |
| **`quoteOrderQty`** | IDR amount for a `BUY MARKET` order, mutually exclusive with `quantity` |
| **GTC** | Good till cancelled |
| **MOC** | Maker or cancel: rejected if it would match immediately |
| **STP** | Self-trade prevention; modes `EXPIRE_TAKER`, `EXPIRE_MAKER` (default), `EXPIRE_BOTH` |
| **Deadman Switch** | `/countdownCancelAll`, cancels open orders if not refreshed. Legacy-auth only; unused (ADR-007) |

## Platform Terms

| Term | Definition |
|---|---|
| **AIDSS** | The existing analysis platform (`src/aidss`) |
| **Kronos-base** | `NeoQuasar/Kronos-base`, an OHLCV forecasting model run on CPU by the analysis platform |
| **Execution language** | Wording that reads as an instruction to trade. The analysis platform rejects it in model output |
| **Open question (OQ)** | An undecided item in `TASKS/BACKLOG.md` |

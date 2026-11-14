# 09 — Indodax WebSockets and Deadman Switch (Deferred)

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Integration Engineer |
| **Decided by** | ADR-002, ADR-007, ADR-011 |
| **Open items** | OQ-3 |

Documented for completeness and for the day they are reconsidered. **Neither is implemented, and neither is
part of the MVP.**

## Market-Data WebSocket

`wss://ws3.indodax.com/ws/`. After connecting, the client sends an authentication message containing a
**static token published in Indodax's own documentation**, then subscribes by `method: 1` and a `channel`.

| Channel | Purpose |
|---|---|
| `chart:tick-<pair>` | Tick stream: `[epoch seconds, sequence, price, volume]` |
| `market:summary-24h` | Market summary |
| Trade activity, orderbook | Per the document |

A ping uses `method: 7`. The docs describe recoverable subscriptions with `epoch` and `offset`.

**Why deferred (ADR-011):** a swing strategy does not need ticks; REST polling is simpler to test; a
connection needs reconnect and gap handling. **If the Exit Monitor's polling interval proves too slow for
stops, this is the first thing to revisit**, because a stream shortens stop reaction time.

## Private WebSocket

1. `POST https://indodax.com/api/private_ws/v1/generate_token` with body `client=tapi` and `tapi_key`, signed
   in the `Sign` header with **HMAC-SHA512 using the tapi secret**. Returns `connToken` and a private
   `channel`.
2. Connect to `wss://pws.indodax.com/ws/?cf_ws_frame_ping_pong=true`, send `connect` with the token, then
   `subscribe` to the channel.
3. Receive `order_update` events: `orderId` (full id), `tradeId`, `symbol`, `side`, `origQty`, `unfilledQty`,
   `executedQty`, `price`, `status`, `transactionTime`, `clientOrderId`, and, for fills, a `fillInformation`
   block with `participant` (`MAKER` or `TAKER`), `filledQty`, `qty`, and **fee, tax, and clearing** each
   with asset, rate, and amount.

**Why deferred (ADR-002, ADR-011):** token generation uses the legacy scheme. Whether a TAPIv2 key works
here is unknown (OQ-3).

**What the deferral costs:** under REST-only polling the fee, tax, and clearing split is not available
(`07`, `05-MODULE-SPECIFICATIONS/05`), and order status has polling latency. If the owner needs the
split for reporting, this stream is the documented source (OQ-5).

## Deadman Switch

`POST https://indodax.com/tapi/countdownCancelAll` (legacy host and auth: `Key` header, HMAC-SHA512,
`Content-Type: text/plain`). Parameters: `pair` (comma list, `btc_idr,eth_idr`), `countdownTime` in ms
(default 5000; `0` cancels the timer), and `timestamp`/`recvWindow` or `nonce`. If not refreshed within the
countdown, **all open orders on those pairs are cancelled**. Rate limit 10 per 10 seconds per IP. Success is
`{"success": 1}`; errors come back with HTTP 200 and `success: 0` plus an `error_code`.

**What it would and would not do for the Trader:** it cancels **open orders** if the Trader stops
refreshing it. It does not close positions and does not place a stop. So it would protect against a
runaway or orphaned resting order, not against the main residual risk in ADR-007 (a position with no stop
while the Trader is down).

**Why unavailable (ADR-002, ADR-007):** legacy auth only. Whether a TAPIv2 key can call it is unknown.

## Conditions to Revisit

1. Stops prove too slow under polling.
2. The owner wants the fee, tax, and clearing split in the ledger.
3. A live test shows a TAPIv2 key authenticates these features (OQ-3).
4. Indodax documents TAPIv2 equivalents.

Any of these needs a new ADR and updates to `02-ARCHITECTURE/05` and `07`.

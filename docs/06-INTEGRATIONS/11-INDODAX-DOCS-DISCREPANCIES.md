# 11 — Indodax Documentation Discrepancies

| | |
|---|---|
| **Status** | Draft, 2026-11-14; Resolved section started 2026-11-18 |
| **Owner** | Integration Engineer |
| **Open items** | OQ-3, OQ-18 (decided, ADR-038) |

Where Indodax's own documentation disagrees with itself or leaves a gap. Found by reading commit `8d1b409`
(2026-11-10). **Items are resolved against a live response one at a time; see Resolved below** (first run
2026-11-18: T2-07 phase A and B). The table that follows is the original finding and is left as written. The
connector tolerates both forms until a real response settles a question, and this document is then corrected
through the deviation protocol.

| # | Topic | What the docs say | Treatment |
|---|---|---|---|
| D1 | Trade API 2.0 base URL | The Private API page: `https://api.indodax.com/`. The STP page: `https://tapi.indodax.com` and `https://tapi.btcapi.net` | Base URL is configuration; verify which answers |
| D2 | Cancel Order parameters | Table marks `orderId` **and** `origClientOrderId` mandatory "yes"; the note says **either** is enough and `orderId` wins | Send `orderId` when known; verify either-only works |
| D3 | Get Order parameters | Same as D2; `orderId` typed `string` in Get Order but `int64` in Cancel Order | Send as a string of digits; verify |
| D4 | `timeInForce` | Create Order lists `GTC`, `MOC`. The enums page also lists `FOK` for `MARKET` | Use only `GTC` and `MOC` |
| D5 | Order status values | REST enums: `NEW`, `CANCELLED`, `REJECTED`, `PARTIALLY_FILLED`, `FILLED`. Private WebSocket examples use `NEW` and `FILL`; its field table lists `FILLED`, `CANCELLED`, `REJECTED` | WebSocket is deferred; an unknown status is `MALFORMED` and halts |
| D6 | `stopPrice` | Appears in Cancel Order, Open Orders, and Get Order responses, yet `STOP_LIMIT` is not supported | Ignore `stopPrice`; do not rely on it |
| D7 | Rate limit for Create Order | Table: 300 per minute per IP. Section: 20 per second per user per pair. | Both apply; the stricter binds (`08`) |
| D8 | Order id forms | Numeric `orderId` on create, cancel, get; full id like `aaveidr-limit-3568` in history, `myTrades`, and WebSocket | Store both and use the right one per endpoint |
| D9 | Quantity field name | `origQty` on create, cancel, get, open orders; `oriQty` in order history | Parser accepts both |
| D10 | Symbol spelling | `BTCIDR`, `btcidr`, and `btc_idr` across endpoints | One canonical form, converted at the edge |
| D11 | Time units | Milliseconds almost everywhere; the OHLC example `Time` is Unix seconds; the market-data WebSocket tick epoch is seconds | Normalize at the edge |
| D12 | Numeric typing | Some examples show numbers (`Open`, `price` in `ticker`) and others strings (`Volume`, `price` in Trade API 2.0) | Parse via string to `Decimal`; accept both |
| D13 | `recvWindow` examples | Legacy and Deadman examples use `recvWindow` values like `1578303937000`, which is an absolute timestamp, not a duration; Trade API 2.0 says default `5000` | Use milliseconds as a duration; verify |
| D14 | Sample values | Create Order sample shows `origQty` of `4988.0` for `BTCIDR` and a limit price `421004000`; other samples show prices like `1236777000` | Treat all sample numbers as illustrative only |
| D15 | Legacy-key coupling | TAPIv2 says an existing TAPI key cannot be reused, while the Private WebSocket and Deadman Switch are documented only with the legacy key and HMAC-SHA512 | Treated as unavailable until a live test (OQ-3) |
| D16 | Cross-document link | The STP page links `./INDODAX-TradeAPI-2.md`, which does not exist in the repository (the file is `INDODAX-TradeAPI-2-Private.md`) | Documentation hygiene; no impact |
| D17 | Error code forms | Some codes appear with and without a minus sign (`1109`, `1112` versus `-1130`, `-2013`) | Accept both |
| D18 | OHLC details | The maximum range, candle boundary, time zone, and whether an unfinished candle is returned are not stated | OQ-4 |
| D19 | Public REST limit | Legacy public 180 per minute; Trade API 2.0 public 300 per minute | Use the lower for the legacy host |
| D20 | Fee fields | `trade_fee_percent*` appear on only some entries in the `/api/pairs` sample | Optional; do not rely on them for the cost model |

## How This Table Is Used

- Contract tests include both forms where two are accepted (D9, D12, D17).
- Each item that blocks trading when unresolved (D2, D3, D5, D13) has a **live verification step** in
  `TASKS/PHASE-T2-EXCHANGE-CONNECTOR.md` task T2-07, done read-only first and on the owner's instruction.
- When an item is resolved, add a dated row to `Resolved` below with the evidence, and amend the relevant
  document through the deviation protocol.

## Resolved

Evidence: `MEMORY/records/2026-11-18-T2-07-phase-A-and-first-backtest.md` (public, no key, from the owner's
workstation) and `MEMORY/records/2026-11-18-T2-07-phase-B-readonly.md` (signed GETs, a Read-only key made for
the check and revoked afterwards). Only what a response showed is written here; nothing is inferred beyond it.

| # | Date | Observed | What it settles | What stays open |
|---|---|---|---|---|
| D1 | 2026-11-18 | The public v2 call answered 200 with the same shape on `api.indodax.com` and `tapi.indodax.com`. An unsigned `GET /api/v2/account` answered `-2014` (key not found in header) on `api`, `tapi` and `tapi.btcapi.net`. A **signed** private call (B1, B2, B4, B7) answered 200 on `api.indodax.com`. | `api.indodax.com` serves Trade API 2.0, private and public. Configuration stays as set (`https://api.indodax.com`). | A signed call on `tapi.*` was not made. |
| D2 | 2026-11-18 | Not tested: cancel needs a live order. | Nothing. | Phase C (needs a Trade key, T5-06). |
| D3 | 2026-11-18 | `GET /api/v2/order` for an order that does not exist, once by `orderId` and once by `origClientOrderId`, answered HTTP 404, code `-2013` both times, not a missing-parameter error. | On the **read** side, either parameter alone is understood. | The type of `orderId` (string or integer) with a real id; D2 (cancel). |
| D10 | 2026-11-18 | `ticker/price` answered 200 for `BTCIDR`, `btcidr` and `btc_idr`. | All three spellings are accepted on the v2 public ticker. The Trader still converts to one canonical form. | Other endpoints. |
| D11 | 2026-11-18 | `server_time` is 13 digits (milliseconds). The OHLC `Time` is 10 digits (seconds). | The units differ exactly as the table says; normalisation at the edge stays. | The WebSocket tick epoch (not used). |
| D12 | 2026-11-18 | `price_precision` in `/api/pairs` is an integer. OHLC `Time`, `Open`, `High`, `Low`, `Close` are integers and `Volume` is a string. | Both typings occur in real responses. Parse through string to `Decimal`, as the connector does. | |
| D13 | 2026-11-18 | A signed call with a deliberately stale timestamp and a tiny `recvWindow` answered HTTP 400, code `-1021`. A call with both `timestamp` and `nonce` answered 200. | The rejection behaves as a duration in milliseconds. | Which of the two is used when both are present (the call succeeded either way). |
| D17 | 2026-11-18 | Observed error codes, all with a **negative** sign: `-1121` (invalid symbol), `-1130` (invalid limit), `-1102` (missing parameter), `-2013` (order not found, HTTP 404), `-1002` (wrong signature, HTTP 401), `-1021` (stale timestamp, HTTP 400), `-2014` (key missing, HTTP 400). | Negative codes are what the exchange sends for these. | The positive forms (`1109`, `1112`) were not seen; the connector keeps accepting both. |
| D18 | 2026-11-18 | Over 4H and 1D requests, the newest candle returned was still open when fetched, and its time was an exact multiple of 14,400 s (4H) and 86,400 s (1D) from the Unix epoch, so candles are aligned to UTC (00, 04, 08, 12, 16, 20 UTC for 4H; 00:00 UTC for 1D). 85 candles came back for the 4H range asked, 15 for 1D. | Time zone and boundary: UTC. An unfinished candle **is** returned, so closed-candle-only storage in the Trader is required (it does that). | The maximum range per request and long-term availability of `/tradingview/history_v2` (OQ-4 stays open for these); a comparison with Indodax's own chart was not made. |
| D20 | 2026-11-18 | `trade_fee_percent`, `_maker` and `_taker` are present on all 450 entries of `/api/pairs`. | The fee fields are not sparse as the sample suggested. | Whether they include tax and clearing (OQ-5). |
| D21 (new) | 2026-11-18 | A signed `GET /api/v2/account` with a deliberately wrong signature answered **HTTP 401, code `-1002`**, not `-1022` as `04` and `08` list for a bad signature. | A bad signature and bad credentials look the same on this endpoint: `-1002`. The connector already classifies `-1002` as `AUTH`. `-1022` has not been seen. | Whether `-1022` appears for a missing signature or a repeated nonce. |
| (D22) | 2026-11-18 | Not an Indodax discrepancy: `/api/price_increments` and `pricescale` agree numerically for every IDR pair. The 22 mismatches first reported by the live-check script compared text (the string `0.000001` against the float `1e-06`) and are 10 IDR pairs spelled differently plus 12 USDT pairs (not traded here). | Nothing to change in the Trader. The script now compares numbers. | |

Not observed and so not resolved: D4, D5, D6, D7, D8, D9 (the history rows were not described field by field),
D14, D15, D16, D19. Phase C items need a Trade key and the owner present (T5-06).

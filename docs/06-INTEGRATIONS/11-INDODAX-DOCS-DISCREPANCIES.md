# 11 — Indodax Documentation Discrepancies

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Integration Engineer |
| **Open items** | OQ-3, OQ-18 (decided, ADR-038) |

Where Indodax's own documentation disagrees with itself or leaves a gap. Found by reading commit `8d1b409`
(2026-11-10). **None has been resolved against a live response.** The connector tolerates both forms until a
real response settles the question, records which it saw, and this table is then corrected through the
deviation protocol.

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

None yet.

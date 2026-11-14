# 02 — Connector Contract Tests

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | QA Engineer, Integration Engineer |
| **Decided by** | ADR-002, ADR-024 |

Every connector method is tested against the mock exchange for each applicable case. A test names the method
and the case. Fixtures are synthetic and shaped from the documentation (`07`).

## Required Cases

| Case | What is asserted |
|---|---|
| Success | The response parses to typed values; `Decimal`, not float |
| Malformed body | `MALFORMED`; no partial acceptance |
| Missing required field | `MALFORMED`, not a default |
| Timeout | `TIMEOUT`; for a write, the outcome is unknown and the caller resolves by query |
| Server error (5xx, `-1001`) | `UNAVAILABLE`; reads retry with backoff; a write is not retried blindly |
| Authentication failure (`-1002`, `-1022`, `-2014`) | `AUTH`; no retry |
| Permission failure (`-2015`) | `PERMISSION`; the Trader goes `DISABLED` |
| Clock skew (`-1021`) | `CLOCK_SKEW`; one re-sync then halt |
| Rate limit (`-1003`, 429) | `RATE_LIMIT`; backoff; the throttle did not allow it, so a defect is logged |
| Validation (`-1102`, `-1130`, `-1111`, `-1121`, `1109`) | `VALIDATION`; no retry |
| Not found (`-2013`, `1112`, `-1099`) | `NOT_FOUND` |
| Rejected (`-2010`) | `REJECTED`; including a duplicate `clientOrderId` |
| Market suspended (`-1016`) | `MARKET_SUSPENDED` |
| Windowing | History requests never exceed 7 days; larger spans are split |
| Duplicate | A repeated fill (`tradeId`) is ingested once |
| Partial result | A partial fill and a partial history page are handled |
| Unknown status or code | `MALFORMED`, raises a difference, does not guess |

## Per-Method Matrix (summary)

| Method | Extra checks |
|---|---|
| `create_order` | `clientOrderId` always set and valid; `LIMIT` requires `price`; `BUY MARKET` uses `quoteOrderQty` and never `quantity`; `STOP_LIMIT` is never sent; quantity is pre-quantized so `-1130` precision error does not occur |
| `cancel_order` | Sends `orderId` when known; tolerates both documented forms; confirms by reading |
| `get_order`, `get_open_orders` | Both order-id forms handled; `NEW` maps to `OPEN`; an unknown status halts |
| `get_account` | Either withdrawal flag true refuses trading |
| `get_order_history`, `get_my_trades` | Requires `symbol`; 7-day windows; `oriQty` and `origQty` both accepted; `commission` kept combined |
| `get_ohlc` | Seconds `Time` normalized; numbers and strings both accepted; the unfinished candle excluded |
| `get_pairs`, `get_price_increments` | Disagreement blocks the pair; a missing field blocks the pair |
| `get_server_time` | Used for skew |
| Ticker endpoints | Multi-symbol parsing; symbol-format conversion |

## Both Documented Forms

For each item in `06-INTEGRATIONS/11` marked "accepts both" (D9, D12, D17), the suite has a fixture for each
form, so a later live observation that settles the question does not break the connector.

## Signing

The mock verifies the signature scheme using **test-only keys defined in the test**. Cases: correct
signature; wrong secret; altered parameter after signing; reordered parameters; missing `X-APIKEY`; missing
`Sign`; timestamp outside `recvWindow`; both `timestamp` and `nonce`. A test asserts that no key, secret, or
signature appears in any log.

## Allowlist Test

A test enumerates the connector's public methods and compares them with the allowlist in `06/01`. Adding a
method that is not listed fails the build. No withdrawal, deposit, or fiat method may exist.

## Provenance

Each fixture states it is synthetic and from which documentation page. After the owner-led read-only
verification (T2-07) a fixture recorded from a real response is added, with credentials and identifiers
redacted, and is labelled as recorded.

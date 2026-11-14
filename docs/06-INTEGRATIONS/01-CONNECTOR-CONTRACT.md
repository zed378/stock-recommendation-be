# 01 — Connector Contract

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Integration Engineer |
| **Decided by** | ADR-002, ADR-013, ADR-024 |

The shape every call to an external system follows. For the Indodax connector it is the only way the
Trader talks to the exchange (`02-ARCHITECTURE/03` rule 8).

## Allowed Operations (an allowlist, not a deny-list)

| Group | Methods |
|---|---|
| Public read | `get_server_time`, `get_pairs`, `get_price_increments`, `get_ohlc`, `get_last_price`, `get_book_ticker`, `get_depth` |
| Private read | `get_account`, `get_open_orders`, `get_order`, `get_order_history`, `get_my_trades` |
| Private write | `create_order`, `cancel_order` |

**Nothing else exists.** No withdrawal, deposit, fiat, address, or legacy method is defined, even disabled
(ADR-013). A test enumerates the connector's public methods and fails if one is added that is not on this
list.

`create_order` and `cancel_order` are importable only by the Order Manager and the kill switch
(`02-ARCHITECTURE/03` rule 2).

## Result Shape

Every call returns either a result or a normalized error, each carrying:

| Field | Meaning |
|---|---|
| `source` | `indodax_public` or `indodax_tapi_v2` |
| `operation` | Method name |
| `requested_at`, `responded_at` | UTC, with the request's own timestamp parameter recorded |
| `correlation_id` | Ties to the intent or job |
| `http_status`, `exchange_code` | As received |
| `raw` | The response body, **redacted**, kept for diagnosis |

## Normalized Error Classes

| Class | Examples |
|---|---|
| `AUTH` | `-1002`, `-1022`, `-2014`, bad signature |
| `PERMISSION` | `-2015` (access denied, key permission, IP, version) |
| `CLOCK_SKEW` | `-1021` |
| `RATE_LIMIT` | `-1003`, HTTP 429 |
| `VALIDATION` | `-1102`, `-1111`, `-1130`, `1109` |
| `NOT_FOUND` | `-2013`, `1112`, `-1099` |
| `REJECTED` | `-2010` |
| `MARKET_SUSPENDED` | `-1016` |
| `UNAVAILABLE` | 5xx, `-1001`, connection refused |
| `TIMEOUT` | No response within the limit |
| `MALFORMED` | A response that does not parse or lacks a required field |

The mapping table with the Trader's response to each is in `08-INDODAX-ERRORS-AND-RATE-LIMITS.md`.
**`UNAVAILABLE` and `TIMEOUT` on a write mean "outcome unknown"**, not "failed" (ADR-024).

## Retry Classes

| Class | Methods | Rule |
|---|---|---|
| Safe | All reads | Bounded retries, backoff, jitter |
| Verify-then-act | `cancel_order` | Confirm by reading the order before repeating |
| **Never blind** | `create_order` | Resolve by `clientOrderId`; never re-send |

## Timeouts and Throttle

Each method has its own connect and read timeout. A shared throttle (token bucket) keeps total requests
below the lowest applicable Indodax limit with headroom, with separate buckets for public traffic, general
private traffic, and the per-pair create limit (FR-T17).

## Parsing Rules

- Numeric strings become `Decimal` at the edge; floats never appear (ADR-025).
- A missing required field is `MALFORMED`, not a default.
- An unknown enum value (for example an order status) is `MALFORMED` and raises a reconciliation difference.
- Both documented forms of a quirky field are accepted (`11-INDODAX-DOCS-DISCREPANCIES.md`).

## Required Contract Tests (every method)

Success; malformed body; timeout; authentication failure; permission failure; clock skew; rate limit;
and, where relevant, pagination or windowing, a duplicate (`-2010` on a repeated `clientOrderId`), and a
partial result. Defined in `../11-TESTING-QUALITY/02-CONNECTOR-CONTRACT-TESTS.md`.

## No Fabrication

A fixture or mock response is labelled as such and is shaped from the documentation. It is never presented as
a real exchange response, and a connector verified only against fixtures is described as "not yet verified
against the live exchange".

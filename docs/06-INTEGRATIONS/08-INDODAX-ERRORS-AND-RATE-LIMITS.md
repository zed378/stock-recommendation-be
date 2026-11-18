# 08 — Indodax Errors and Rate Limits

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Integration Engineer |
| **Decided by** | ADR-024 |
| **Open items** | OQ-18 (decided, ADR-038) |

Source: `INDODAX-TradeAPI-2-Private.md` and the public docs. **Documented, not yet observed.**

## Error Format (Trade API 2.0)

```json
{ "code": -1121, "msg": "Invalid Symbol" }
```

## Error Codes, Normalized Class, and the Trader's Response

| HTTP | Code | Meaning (docs) | Class | Trader response |
|---|---|---|---|---|
| 500 | -1001 | Internal error; retry | `UNAVAILABLE` | Retry reads; on a write, outcome unknown |
| 401 | -1002 | Invalid credentials. **Observed 2026-11-18 also for a wrong signature** (`11`, D21) | `AUTH` | `DISABLED`, alert |
| 400 | -1021 | Timestamp outside `recvWindow` | `CLOCK_SKEW` | Re-sync, retry once, then halt |
| 400 | -1022 | Invalid nonce or signature (documented; **not observed**: a wrong signature returned -1002) | `AUTH` | `DISABLED`; check signing |
| 431, 405, 400 | -1000 | Unknown error (header too large, method not allowed, or duplicate request) | `MALFORMED` | Log and investigate; no retry |
| 400 | -1102 | Mandatory parameter missing or malformed | `VALIDATION` | A bug; no retry |
| 400 | 1109 | Invalid parameter value | `VALIDATION` | A bug |
| 400 | 1112 | Order not found or not yet available | `NOT_FOUND` | During `UNKNOWN` resolution, query again |
| 400 | -1121 | Invalid symbol | `VALIDATION` | Pair mapping bug |
| 400 | -1130 | Parameter fails trading rules | `VALIDATION` | Usually precision or `stop_limit_not_available` |
| 400 | -1111 | Quantity validation failed | `VALIDATION` | Increments or minimums |
| 400 | -2014 | API key not in header | `AUTH` | Bug |
| 403 | -2015 | Access denied: Trade API disabled, account locked, no permission, unauthorized IP, or invalid TAPI version key | `PERMISSION` | `DISABLED`, alert |
| 404 | -1099 | Resource does not exist | `NOT_FOUND` | A bug (wrong path) |
| 404 | -2013 | Order not found or not yet available | `NOT_FOUND` | Query again during resolution |
| 429 | -1003 | Too many requests | `RATE_LIMIT` | Back off; investigate the throttle |
| 400 | -1016 | Market is suspended | `MARKET_SUSPENDED` | Suspend the pair; `FLATTEN` reports it |
| 400 | -2010 | Order rejected: insufficient balance, duplicate client order ID, other | `REJECTED` | Record; check balance; never retry the same id |
| 400 | -4033 to -4060 | Withdrawal and capital errors | n/a | Not applicable: no withdrawal code exists |

An unknown code is `MALFORMED` and is logged with its raw (redacted) body; it is never silently treated as
success or as retryable.

Two codes appear both as `1109`/`1112` (no minus sign) and as `-2013`/`-1130` for similar situations; the
connector accepts both forms (`11`).

## Rate Limits

| Scope | Limit |
|---|---|
| Trade API 2.0 public endpoints | 300 per minute |
| Legacy public REST (candles, pairs, server time) | 180 per minute |
| Create, cancel, pending, get order, account, order history, trade history | 300 per minute **per IP** |
| `capital/*` and `fiat/*` | 50 per minute (not used) |
| **Create order, additionally** | **20 per second per authenticated user per trading pair** |
| **Cancel order, additionally** | **30 per second per authenticated user** |
| Deadman Switch | 10 per 10 seconds per IP (not used) |

"If the rate limit is exceeded, the API may reject subsequent requests until the applicable rate-limit window
resets." The per-second order limits apply even to whitelisted IPs.

### Which Limit Binds

300 per minute is 5 per second sustained, which is **stricter** than 20 per second for creates. At swing
frequency this never matters in practice, but the throttle is built from the strictest figure with
headroom, not from the larger one. Whether public and private traffic from the same IP share a counter is not
stated; the design assumes they might.

## Throttle Design

A token bucket per scope (public, private-general, create-per-pair, cancel), configured **below** these
limits. A `-1003` is treated as evidence the throttle is wrong and is logged as a defect, not just retried.

## To Verify Live (OQ-18)

Response headers that report usage (none are documented); the real behavior at the limit; whether
`-1021` includes a server time hint.

# 00 — API Standards

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-001, ADR-013, ADR-015 |
| **Open items** | OQ-14 (resolved, ADR-028) |

Standards for the **Trader's own operator API**. The analysis platform's API is unchanged.

## Basics

- JSON over HTTPS. Base path `/trader/v1` (the prefix keeps it separable if both are served behind one
  proxy; see ADR-028).
- An OpenAPI document is generated from the code, and the frontend types come from it
  (`openapi-typescript`, as the existing front end does). The diff in the generated types is the record of an
  API change.
- Timestamps are ISO 8601 UTC. Money and quantities are **strings** of decimal numbers, never JSON floats.

## Authentication and Authorization

- Bearer JWT from the platform's existing login, carrying the user and role.
- Every route declares the permission it needs (`01-PRODUCT-REQUIREMENTS/06`). A route with no declared
  permission is a defect, and a test enumerates the OpenAPI document to prove none exists.
- Authorization is checked in the Trader. The front end is never the control.

## Response Envelope With Freshness

Read responses carry:

```json
{ "data": { ... }, "meta": { "source": "exchange|local|simulated", "origin": "LIVE|PAPER|BACKTEST",
  "as_of": "2026-11-14T10:00:00Z", "stale": false } }
```

`origin` is on every figure-bearing response so paper and live are never confused (FR-T28, FR-T34).

## Error Model

```json
{ "error": { "class": "VALIDATION", "code": "limit_unset", "message": "...",
  "correlation_id": "...", "retryable": false } }
```

Classes are those of `06-INTEGRATIONS/01`, plus `FORBIDDEN`, `CONFLICT` (for example approving an expired
intent), and `HALTED` (an action that needs the Trader to be running). Messages never contain a key,
signature, balance total, or an exchange payload. Status codes distinguish unauthorized, forbidden, not
found, conflict, and unavailable.

## Mutations

- Every mutating route requires an `Idempotency-Key` header so a double click or retry cannot repeat an
  action (an approval, a kill, a promotion).
- Every mutation writes an audit row naming actor, action, and before and after (FR-T33).
- Destructive routes (`CANCEL`, `FLATTEN`) require a confirmation field in the body that restates the effect;
  the API rejects a request without it, so the confirmation is not only a UI courtesy.

## Hard Rules

1. **No route creates an order directly.** Orders come only from strategies and the approval flow. There is no
   manual order entry. A test fails if a route accepts `side`, `price`, and `quantity` to place an order.
2. **No route accepts, returns, or logs a credential value.** The credential route is write-only.
3. **No route performs a withdrawal, deposit, or fiat action**, because no such function exists.
4. **No route lets a caller bypass the Risk Engine or set a limit as a side effect of another call.**
5. **Resume is its own route** with a required note; it is never implied.

## Pagination and Filtering

Cursor pagination for ledger, orders, audit, and events, newest first, with a documented maximum page size.
Filters by pair, strategy, origin, and time range. History calls to the exchange are internal and are not
exposed as pass-through.

## Versioning

`/trader/v1`. A breaking change adds `/v2` and keeps `/v1` for a deprecation period stated in the ADR.

## Rate Limiting

Per-client limits on the operator API, with the kill-switch route exempt from throttling so it can always be
used.

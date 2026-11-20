# 01 — Trader API

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-003, ADR-010, ADR-013 |
| **Open items** | OQ-14 (resolved, ADR-028) |

Routes under `/trader/v1`. Permissions are from `01-PRODUCT-REQUIREMENTS/06`. Paths are proposals for the
build; the contract is these behaviors.

## Read

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/status` | `trade:view` | Trading state and halt reason, lease holder, modes, key permission check result, unset required settings |
| GET | `/health` | `trade:view` | Connector breaker, clock skew, last successful calls, watchdog, data freshness per feed |
| GET | `/dashboard` | `trade:view` | Positions, open orders, risk usage, PnL by origin, approvals pending |
| GET | `/strategies` | `trade:view` | Strategies, versions, modes, disabled reasons |
| GET | `/strategies/{id}/promotion` | `trade:view` | Each promotion gate, measured value, threshold, result |
| GET | `/intents`, `/intents/{id}` | `trade:view` | Intents with rule snapshot, context, veto, risk checks |
| GET | `/orders`, `/orders/{id}` | `trade:view` | Orders with state history |
| GET | `/ledger` | `trade:view` | Ledger entries |
| GET | `/pnl` | `trade:view` | Realized and unrealized, by origin |
| GET | `/reconciliation` | `trade:view` | Runs and differences |
| GET | `/limits`, `/allowlist` | `trade:view` | Current limits (unset shown as null) and allowlist |
| GET | `/audit` | `trade:read_audit` | Audit log |
| GET | `/events` | `trade:view` | Trading events |
| GET | `/export` | `trade:view` | CSV of ledger or audit for a range |
| GET | `/credentials` | `trade:view` | Masked hint, last test time and result. **Never the key or secret** |

## Write

| Method | Path | Permission | Purpose |
|---|---|---|---|
| POST | `/intents/{id}/approve` | `trade:approve` | Approve the exact intent (body carries the intent hash) |
| POST | `/intents/{id}/deny` | `trade:approve` | Deny with optional reason |
| POST | `/strategies/{id}/promote` | `trade:promote` | Promote to the next mode; fails if any gate fails or is unset |
| POST | `/strategies/{id}/demote` | `trade:promote` | Demote to a lower mode |
| PUT | `/strategies/{id}/parameters` | `trade:configure_strategy` | Creates a new version, returns the strategy to `PAPER` |
| PUT | `/limits` | `trade:configure_risk` | Creates a new limits version |
| PUT | `/allowlist` | `trade:configure_risk` | Replaces the allowlist (audited) |
| POST | `/kill` | `trade:halt` for `HALT`; `trade:kill` for `CANCEL`, `FLATTEN` | Body: tier and confirmation |
| POST | `/resume` | `trade:resume` | Leave `HALTED`; requires a note; refused while a difference or `UNKNOWN` order is unresolved |
| PUT | `/credentials` | `trade:manage_credentials` | Store and test a new key (write-only fields) |
| POST | `/credentials/test` | `trade:manage_credentials` | Read-only test of the stored key |
| DELETE | `/credentials` | `trade:manage_credentials` | Remove the credential |
| POST | `/events/{id}/ack` | `trade:view` | Acknowledge a `CRITICAL` event |

## What Does Not Exist

| Absent | Why |
|---|---|
| `POST /orders` or any order-entry route | Orders come only from strategies and approvals (`00`) |
| Anything under withdrawal, deposit, or fiat | ADR-013 |
| A route returning a credential, signature, or full account id | NFR-T10 |
| A route to edit or delete a ledger, fill, or audit row | Append-only; corrections are `ADJUSTMENT` entries through a dedicated, audited reconciliation action |
| A route that sets a limit as a side effect | `00` hard rule 4 |

The reconciliation resolution action (`POST /reconciliation/{id}/resolve`) records a cause and, if needed, an
`ADJUSTMENT` entry with a mandatory reason; it needs `trade:configure_risk`.

## Guard Tests (planned)

1. Enumerate the OpenAPI document: no route without a permission; no route name contains `withdraw`,
   `deposit`, or `fiat`; no route accepts order-entry parameters.
2. No response schema contains a field named like a secret.
3. The `kill` route works with the Strategy Engine stopped.

## Ownership of Idempotency

Mutating routes require `Idempotency-Key`. `approve` additionally requires the intent hash so a stale card
cannot approve a changed order (`05/07`).

## Indodax builder review API (ADR-068)

| Method | Path under `/trader/v1` | Permission | Behavior |
|---|---|---|---|
| GET | `/signal-builder/schema` | VIEW | Strict declarative definition schema |
| GET | `/signal-builder/work` | VIEW | Pending exact-candle public Indodax work for enabled definitions and named IDR pairs |
| GET | `/signal-builder/reviews` | VIEW | Latest 50 SHADOW reviews, including whether each is still current |
| POST | `/signal-builder/reviews` | CONFIGURE_STRATEGY | Idempotency-Key required; strict typed evidence; server derives PASS/BLOCKED, rechecks work identity, appends evidence and audit in one transaction |

Configuration is persisted through existing POST/PUT `/strategy-defs` routes as kind
`signal_builder`, with the sole parameter `definition` (JSON). Those routes retain
their existing permission, idempotency, audit, version reset and delete guards.
No additional order-entry or model-inference route is exposed. The model worker is
external to the Trader. A review cannot be replaced; changed evidence for an existing
identity is a conflict. Model text and projected prices never become order fields.

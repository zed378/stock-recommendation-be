# 02 — C4 Containers

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-021 |
| **Open items** | OQ-14 (resolved, ADR-028) |

## Containers in the Compose Project

| Container | Exists today | Role |
|---|---|---|
| `postgres` | Yes | Shared server; now also holds schema `trading` |
| `api` | Yes | Analysis platform API. No access to `trading` writes |
| `worker` | Yes | Analysis jobs and scheduler. Unchanged |
| `frontend` | Yes | Existing React UI. Hosts the Trader screens (ADR-028) |
| **`trader`** | **No (planned)** | The Trader process: scheduler loop plus operator API |

## The `trader` Container

| Aspect | Decision |
|---|---|
| Image | Its own Dockerfile. It does not include torch, Hugging Face, or the analysis test suite |
| Process | One process. A loop for strategies, exits, reconciliation, and a small FastAPI app for the operator API |
| Instances | Exactly one active (ADR-027). A second instance idles |
| Database | Same PostgreSQL server and database, schema `trading`, role `trader_rw` |
| Migrations | Own Alembic environment and version table inside `trading` |
| Configuration | Environment for infrastructure (database URL, master key). Everything else, including limits and the credential, is stored in the database and edited through the operator surface |
| Network | Outbound HTTPS only. No published port other than what the operator surface needs (ADR-028) |
| Restart policy | `always`, with state recovered at start (NFR-T03) |

## Data Stores

| Store | Content | Who writes |
|---|---|---|
| Schema `trading` | Strategies, intents, orders, fills, ledger, positions, limits, audit, credential ciphertext, reconciliation runs | `trader_rw` only |
| Analysis tables (`public`) | Candles for equities, analysis results, recommendations | Analysis platform |

The Trader's role has no privilege on `public` writes; the analysis role has no privilege on `trading`
writes (NFR-T13). The Trader stores its own candle history for crypto pairs in `trading`; it does not use
`historical_prices`.

## Operator Surface (ADR-028)

New pages in the existing front end, calling the Trader's own API. The Trader verifies each bearer token by
calling the analysis API's `GET /auth/me` and reading the user and role; it does not hold the JWT signing
secret. The Trader's API enforces every permission in
`../01-PRODUCT-REQUIREMENTS/06-ROLE-PERMISSION-MATRIX.md`, so the front end is never the control.

**Consequence:** if the analysis API is down, the operator screens cannot authorize requests. The command-line
kill tool (`../05-MODULE-SPECIFICATIONS/08-KILL-SWITCH.md`) is therefore the path that does not depend on it. A
short-lived verification cache is a possible optimization and is not decided.

## Why Not Reuse `worker`

The existing worker runs analysis and news jobs from a database queue with retries. Retrying is exactly
what an order path must not do blindly (ADR-024), and a hung analysis job must never delay a stop. The
Trader has its own loop.

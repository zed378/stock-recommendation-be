# 01 — System Context

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Technical Lead |
| **Decided by** | ADR-001, ADR-002, ADR-021 |

## Business Context

One owner wants to trade a small set of Indodax IDR pairs on a swing horizon without watching the market
continuously, while keeping real-money risk bounded and inspectable. The owner already runs the AIDSS
analysis platform for Indonesian equities, which has a multi-agent analysis pipeline and a CPU Kronos-base
forecaster. The Trader reuses that analysis as context, not as authority.

## System Boundary

Inside the boundary (the Trader): Strategy Engine, Risk Engine, Order Manager, Exit Monitor, kill switch,
ledger, reconciler, mode controller, approval queue, credential administration, notifier, and the
operator API and screens.

Outside the boundary and **not changed by this project**: the AIDSS analysis platform, its database
tables, its migrations, and its architecture test.

## Actors

| Actor | Relationship |
|---|---|
| **Owner** | Sole operator. Approves orders, sets risk numbers, promotes modes, holds the Indodax key, presses the kill switch |
| **Indodax** | The exchange. Source of truth for balances, orders, trades. Trade API 2.0 plus public market data |
| **AIDSS analysis platform** | Read-only provider of analysis and Kronos context (`06-INTEGRATIONS/13`) |
| **Notification channel** | Telegram, to the owner's phone (ADR-031) |
| **PostgreSQL** | Shared server; the Trader owns schema `trading` with its own role (ADR-021) |
| **Hugging Face Hub** | Source of the Kronos-base weights, downloaded once by the analysis platform |

## Upstream and Downstream Systems

```
              +-------------------------+
 Owner  <---> |  Trader UI / operator API|
              +-----------+-------------+
                          |
 AIDSS analysis  --read-->|  AIDSS Trader (service)  --signed REST--> Indodax TAPI 2.0
 (context, veto)          |                          --public REST--> Indodax public
                          +-----------+--------------+
                                      |
                          PostgreSQL schema "trading"      --push--> Telegram
```

## Deployment Context

The platform runs as a Docker Compose stack (`postgres`, `api`, `worker`, `frontend`) on one host. The
Trader adds a `trader` container to the same project and uses the same PostgreSQL server (ADR-021). It
has no inbound public exposure; the owner reaches it through the existing front end or its own operator
API (`07-API-CONTRACTS/01-TRADER-API.md`, ADR-028).

## What the Trader Does Not Know

It has no view of the owner's other exchange accounts, bank balances, or tax position. Tax and
regulatory treatment of automated crypto trading in Indonesia is **not analysed here**; the owner states it has been considered (ADR-037).

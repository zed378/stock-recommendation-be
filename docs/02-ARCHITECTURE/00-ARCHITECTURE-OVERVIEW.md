# 00 — Architecture Overview

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-001, ADR-004, ADR-009, ADR-021, ADR-026, ADR-027 |

## Shape

A single new service, **`aidss-trader`** (Python package `aidss_trader`), beside the existing analysis
platform. It owns a PostgreSQL schema `trading`, talks to Indodax over HTTPS, and reads analysis context from
the analysis platform through a read-only interface. The two code bases share a server, a Compose project,
and nothing else (ADR-001, ADR-021).

## Design Principles

1. **Every order passes the Risk Engine.** The only route to the exchange is through it.
2. **Fail closed.** Doubt halts trading.
3. **The exchange is the source of truth.** The ledger is a record of what happened, reconciled to it.
4. **Write ahead.** An order row is persisted *before* the request is sent, so a crash cannot lose the
   knowledge that a request may have reached the exchange (ADR-026).
5. **One active Trader.** A database lease allows exactly one instance to trade (ADR-027).
6. **Deterministic core.** Strategy, sizing, and risk are pure functions of their inputs and configuration.
7. **AI is outside the order path.** It informs and may veto; it never decides.
8. **The kill switch is independent.** It has its own entry point and does not depend on the Strategy Engine.

## Major Components

| Component | One-line responsibility |
|---|---|
| Exchange Connector | Signed and public HTTP to Indodax; the only component that speaks its API |
| Market Data Service | Candles, prices, pair metadata, with freshness |
| Strategy Engine | Candles to signals, deterministic |
| Intent Builder | Signal to sized, priced order intent |
| Analysis Bridge | Fetch AI and Kronos context; produce a veto or none |
| Risk Engine | Pre-trade checks and circuit breakers |
| Order Manager | Order state machine, idempotency, polling, cancel and reprice |
| Exit Monitor | Bot-side stops and targets; watchdog |
| Kill Switch | `HALT`, `CANCEL`, `FLATTEN` |
| Ledger | Append-only fills, positions, PnL |
| Reconciler | Compare with Indodax; halt on difference |
| Mode Controller | `PAPER`, `APPROVAL`, `AUTO`; promotion gates |
| Approval Queue | Owner approve, deny, expire |
| Credential Store | Encrypted key storage |
| Notifier | In-app and mobile messages |
| Operator API and UI | The owner's surface |

Detail: `03-COMPONENT-ARCHITECTURE.md`.

## Main Flow (one entry, `AUTO` mode)

```
candle closes -> Strategy -> signal -> Intent Builder (size, quantize, minimums)
   -> Analysis Bridge (context, optional veto) -> Risk Engine (all checks)
   -> Order Manager: persist order row -> send LIMIT -> poll -> fills -> Ledger
   -> Exit Monitor watches the position -> stop or target -> exit through the Risk Engine's emergency path
   -> Reconciler compares everything with Indodax on schedule
```

In `PAPER` the Order Manager's send step is replaced by the paper executor. In `APPROVAL` the flow pauses
after the Risk Engine until the owner approves.

## Technology (follows the existing platform; no new runtime)

Python 3.11+, SQLAlchemy 2, Alembic, psycopg, httpx, `Decimal`, PostgreSQL. A small FastAPI operator API.
The Trader has its own Alembic history and image. No new database, queue, or framework is introduced; a
change to that needs an ADR (`09-ARCHITECTURE-DECISIONS.md`).

## Why a Separate Service

See ADR-001: it preserves the analysis platform's tested guarantee that no order path exists there, and
confines a trading bug to one process with its own credentials and database role.

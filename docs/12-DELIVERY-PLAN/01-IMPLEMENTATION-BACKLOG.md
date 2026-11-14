# 01 — Implementation Backlog

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Technical Lead |

Index of the task cards. The cards themselves, with Definition of Done and abuse cases, are in
`../../TASKS/PHASE-T*.md`. Status is only ever kept in `../../TASKS/PROGRESS.md`.

## T0 — Specification

| ID | Task |
|---|---|
| T0-06 | **Owner-led:** the owner fills the numbers worksheet |

## T1 — Foundation

| ID | Task |
|---|---|
| T1-01 | Scaffold `aidss_trader`, `Dockerfile.trader`, the Compose service definition |
| T1-02 | Guard tests: import boundary, analysis architecture test unmodified, no-withdrawal allowlist scaffold |
| T1-03 | Schema `trading`, roles, column-level privileges, Alembic environment, drift test |
| T1-04 | Credential store with a dedicated master key |
| T1-05 | Audit log (append-only, hash chain design) |
| T1-06 | Configuration loading; "unset means disabled" |
| T1-07 | Lease and single-instance control |
| T1-08 | Token verification and the `trader` role (touches the analysis platform) |

## T2 — Exchange Connector

| ID | Task |
|---|---|
| T2-01 | Mock exchange server |
| T2-02 | Connector core: signing, HTTP client, normalized errors, allowlist |
| T2-03 | Public market data: pairs, increments, OHLC, tickers, server time |
| T2-04 | Account read and permission check |
| T2-05 | Throttle and clock-skew handling |
| T2-06 | Order endpoints against the mock |
| T2-07 | **Owner-led** read-only live verification and discrepancy resolution |

## T3 — Strategy, Backtest, Paper

| ID | Task |
|---|---|
| T3-01 | Strategy interface and determinism tests |
| T3-02 | Reference EMA plus ADX strategy |
| T3-03 | Signal to intent, sizing, quantization |
| T3-04 | Order state machine (shared), paper executor, backtest engine, ledger and PnL |
| T3-05 | Analysis context bridge, record-only (post-MVP, ADR-032) |
| T3-06 | Candle-in forecast endpoint in the analysis platform (post-MVP, ADR-032) |

## T4 — Execution Core

| ID | Task |
|---|---|
| T4-01 | Risk Engine and checks |
| T4-02 | Circuit breakers |
| T4-03 | Order Manager: create, write-ahead, idempotency, `UNKNOWN` |
| T4-04 | Lifecycle polling, partial fills, cancel and reprice |
| T4-05 | Exit Monitor and watchdog |
| T4-06 | Kill switch and the command-line tool |
| T4-07 | Reconciler |

## T5 — Operator Surface and `APPROVAL`

| ID | Task |
|---|---|
| T5-01 | Approval workflow and step-up authentication |
| T5-02 | Notifier and the chosen channel |
| T5-03 | Mode promotion |
| T5-04 | Operator dashboard and controls |
| T5-05 | Export |
| T5-06 | **Owner-led** `APPROVAL` with small real capital |

## T6 — Hardening

| ID | Task |
|---|---|
| T6-01 | Security tests and independent review |
| T6-02 | Resilience and soak tests |
| T6-03 | Runbook drills and restore rehearsal |
| T6-04 | Out-of-process liveness check |
| T6-05 | Release checklist and the `AUTO` readiness review |

## Rule for Adding a Task

A task with no `Spec refs`, or one that needs a decision that is not in `../../MEMORY/DECISIONS.md`, is not a
task. It is an open question in `../../TASKS/BACKLOG.md`.

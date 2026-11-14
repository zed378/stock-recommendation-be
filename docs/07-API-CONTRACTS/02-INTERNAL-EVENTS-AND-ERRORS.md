# 02 — Internal Events and Errors

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-016, ADR-024 |

## Trading Events

Stored in `trading_event` before any notification is sent (`02-ARCHITECTURE/06`). One shape:

```json
{ "id": "...", "type": "breaker_tripped", "severity": "CRITICAL", "at": "...",
  "origin": "LIVE", "subject": { "type": "strategy", "id": "..." },
  "facts": { "...": "..." }, "correlation_id": "...", "acknowledged_at": null }
```

`facts` holds machine-readable values; the human message is composed from them at send time, so the same
event can be rendered for the app and the phone with different levels of detail.

Types are listed in `05-MODULE-SPECIFICATIONS/12-NOTIFICATIONS.md`.

## Component Events (inside the process)

| Event | Producer | Consumers |
|---|---|---|
| `signal_created` | Strategy Engine | Intent Builder |
| `intent_created`, `intent_vetoed`, `intent_rejected` | Intent Builder, Risk Engine | Audit, Notifier |
| `order_state_changed` | Order Manager | Ledger, Audit, Notifier |
| `fill_ingested` | Order Manager | Ledger |
| `breaker_tripped` | Risk Engine | Kill Switch, Notifier |
| `reconciliation_difference` | Reconciler | Kill Switch, Notifier |
| `watchdog_stalled` | Watchdog | Kill Switch, Notifier |
| `kill_requested`, `kill_step_done` | Kill Switch | Audit, Notifier |

In-process events are delivered synchronously or by a simple in-process queue. No external broker is added
(ADR-001 principle; `02-ARCHITECTURE/09`). Persistent facts go to the database in the same transaction as
the action they describe.

## Normalized Errors

| Class | Raised by | Meaning |
|---|---|---|
| `AUTH`, `PERMISSION`, `CLOCK_SKEW`, `RATE_LIMIT`, `VALIDATION`, `NOT_FOUND`, `REJECTED`, `MARKET_SUSPENDED`, `UNAVAILABLE`, `TIMEOUT`, `MALFORMED` | Connector | See `06-INTEGRATIONS/01` |
| `LIMIT_UNSET` | Risk Engine | A required limit has no value; trading disabled |
| `LIMIT_EXCEEDED` | Risk Engine | Names the check, observed, limit |
| `HALTED` | Mode and state | Action refused because trading is halted |
| `UNKNOWN_ORDER` | Order Manager | An order's outcome is not yet known |
| `RECONCILIATION_DIFFERENCE` | Reconciler | Local and exchange disagree |
| `CONFLICT` | API | Stale approval, already-decided intent |
| `INTEGRITY` | Ledger | An impossible state (for example a sell larger than the position) |

Each error carries `class`, `code`, `message` (no secrets), `correlation_id`, and `retryable`. `retryable`
is **false** for any write whose outcome is unknown, because resolving it is a query, not a retry
(ADR-024).

## Correlation

A `correlation_id` is created with the signal and carried on the intent, order, fill, ledger entries,
events, audit rows, and log lines, so one trade can be followed end to end.

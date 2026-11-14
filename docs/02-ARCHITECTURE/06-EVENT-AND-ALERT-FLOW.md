# 06 — Event and Alert Flow

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-016 |
| **Open items** | OQ-2 (resolved, ADR-031) |

## Principle

The Trader emits **trading events** with a vocabulary of its own. They are not added to the analysis
platform's closed `NotificationEvent` set, which deliberately cannot express an instruction. A trading
event states a fact (an order filled, a limit was crossed); it is not a recommendation.

## Flow

```
component -> TradingEvent(type, severity, payload) -> event table (audit-grade)
          -> Notifier: redact -> in-app (notification centre)
                              -> mobile channel (severity >= configured)
```

An event is stored before it is sent, so a failed send never loses it.

## Severity

| Level | Meaning | Channel |
|---|---|---|
| `INFO` | Routine fact (order filled, intent created) | In-app |
| `WARN` | Needs attention, not urgent (stale price on a pair, near a limit) | In-app, and mobile if configured |
| `CRITICAL` | Money is exposed or trading is stopped (breaker tripped, reconciliation difference, bot or feed down, `UNKNOWN` order unresolved, kill switch used) | In-app and mobile, repeated until acknowledged |

## Event Types

Defined in `05-MODULE-SPECIFICATIONS/12-NOTIFICATIONS.md`. Examples: `intent_awaiting_approval`,
`order_filled`, `order_unknown`, `breaker_tripped`, `kill_switch_used`, `reconciliation_difference`,
`watchdog_stalled`, `credential_changed`, `mode_changed`.

## Delivery Guarantees

At-least-once for `CRITICAL`: retried with backoff and shown as unacknowledged in the UI until the owner
acknowledges. Best effort for `INFO`. If the mobile channel itself is down, the in-app alert still exists
and the failure is recorded.

## What an Alert Must Not Contain

No key, secret, signature, full balance, or account identifier. Positions are shown in the minimum detail
the message needs (`09-SECURITY-PRIVACY/05-SENSITIVE-DATA-REDACTION.md`).

## Alert Fatigue

An `INFO` event never pages the phone. A repeated identical `WARN` is collapsed. A `CRITICAL` is never
collapsed. The owner can change the mobile threshold but cannot silence `CRITICAL`.

# 12 — Notifications

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-016 |
| **Open items** | OQ-2 (resolved, ADR-031) |

Delivery: in-app and a mobile messaging channel (Telegram, ADR-031). Events are separate from the
analysis platform's `NotificationEvent` set (`02-ARCHITECTURE/06`).

## Events

| Event | Severity | Mobile | Content (facts only) |
|---|---|---|---|
| `intent_awaiting_approval` | `WARN` | Yes | Pair, side, expiry; link to the queue |
| `order_filled` | `INFO` | No | Pair, side, quantity, price |
| `order_partially_filled` | `INFO` | No | Pair, executed of total |
| `order_rejected` | `WARN` | If configured | Pair, error class |
| `order_unknown` | `CRITICAL` | Yes | Pair, time unresolved |
| `stop_executed` | `WARN` | Yes | Pair, stop price, achieved price |
| `exit_unprotected` | `CRITICAL` | Yes | Pair, reason (stale price or feed down) |
| `breaker_tripped` | `CRITICAL` | Yes | Which breaker, observed versus limit, tier |
| `kill_switch_used` | `CRITICAL` | Yes | Tier, trigger, step results |
| `reconciliation_difference` | `CRITICAL` | Yes | Kind and pair |
| `watchdog_stalled` | `CRITICAL` | Yes | Which component |
| `trader_started`, `trader_stopped` | `WARN` | Yes | Time, reason |
| `credential_changed` | `WARN` | Yes | That it changed and who; never the value |
| `permission_changed` | `CRITICAL` | Yes | `canWithdraw` or `canTrade` changed |
| `mode_changed` | `WARN` | Yes | Strategy, from, to |
| `limit_changed` | `WARN` | Yes | Which limit, who |
| `clock_skew` | `WARN` | If configured | Measured offset |
| `connector_degraded` | `WARN` | If configured | Cause and duration |

## Content Rules (`09-SECURITY-PRIVACY/05`)

- No key, secret, signature, or account identifier.
- No full balance or total equity. Positions appear only at the detail the message needs.
- An event states a fact, not a recommendation. It never says "you should buy".
- Links go to the authenticated UI, never a deep link that performs an action.

## Delivery

An event is stored before sending. `CRITICAL` is retried with backoff and stays unacknowledged in the UI
until the owner acknowledges it. `INFO` is best effort. A failed mobile delivery is itself recorded.

## Throttling

Identical `WARN` events collapse within a window. `CRITICAL` never collapses. The owner can change which
severities go to the phone but **cannot disable `CRITICAL`**.

## Channel (ADR-031)

Telegram, outbound only: a bot sending to the owner's chat. The notifier is still written behind a small
interface (`06-INTEGRATIONS/12`), so another channel can be added later. The channel is never a control surface.

## Tests (planned, FR-T32)

Each event produces the expected severity and routing; no payload contains a key, signature, or balance;
a failed mobile send leaves the in-app event intact; `CRITICAL` cannot be silenced.

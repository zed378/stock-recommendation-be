# 07 — Resilience and Degradation

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-007, ADR-024, ADR-026, ADR-027 |
| **Open items** | OQ-6 (resolved, ADR-041 and ADR-043) |

Two things are both called "circuit breaker" in this system. To avoid confusion:

- **Risk circuit breaker**: a trading limit (loss, drawdown, exposure). Halts trading. `05/03`.
- **Connector breaker**: protects the Trader from a failing remote API by stopping calls for a time. This file.

## Retry Policy by Request Type

| Request | Safe to retry? | Rule |
|---|---|---|
| Any public or signed `GET` | Yes | Bounded retries with backoff and jitter |
| `POST /api/v2/order` | **No, not blindly** | On timeout or 5xx, query by `clientOrderId` first (ADR-024) |
| `DELETE /api/v2/order` | Yes, after checking | A cancel is idempotent in effect; confirm by reading the order |
| `HTTP 429` / `-1003` | Yes | Honor backoff; the throttle should have prevented it, so it is also a bug signal |
| `-1021` (timestamp outside window) | Once | Re-sync time, then retry once; repeated means clock problem, halt |
| `-2015` (access denied, key or IP) | No | Halt; credential or permission change |
| `-2010` (order rejected) | No | A valid refusal (balance, duplicate id); record it |

## Failure Modes and Responses

| Failure | Response |
|---|---|
| Indodax unreachable or 5xx for longer than a limit | Connector breaker opens; no new entries; Exit Monitor keeps trying; `CRITICAL` |
| Price feed stale | No new entries for the pair; critical alert if a position exists on it |
| Exit Monitor or loop stalled | Watchdog `CRITICAL`; if the Trader is alive it enters `HALT` |
| Database unavailable | **No order is sent without a persisted row** (ADR-026), so trading halts; alerts via the last working channel |
| Notification channel down | In-app continues; failure recorded; retry |
| Analysis platform unavailable | Context unavailable; rules proceed unless a strategy requires it (ADR-004) |
| Clock skew beyond tolerance | `HALT` before any signed request |
| Reconciliation difference | `HALT` and alert; no auto-correction |
| `UNKNOWN` order unresolved | Hold the pair, alert; resolve by query |
| Credential unreadable | Do not trade; alert |
| Two Trader instances | Only the lease holder trades (ADR-027); the other idles |

## Write-Ahead Orders (ADR-026, proposed)

Before a create is sent, the Order Manager writes the order row (state `SUBMITTING`, with its
`clientOrderId`) and commits. After the response it updates the row. If the process dies in between, the
row says a request **may** have reached the exchange, and the next start resolves it by querying
`clientOrderId`. Without this, a crash after sending could leave an order the Trader does not know it has.

## Single Active Instance (ADR-027, proposed)

The Trader acquires a database lease before trading, using the same self-healing pattern as the analysis
platform's scheduler lease (`aidss.jobs.leader`), renewed on a heartbeat. A holder that stops renewing
loses the lease. Two instances can therefore never both send orders.

## What Stays Up

Under every failure above the **kill switch** and the read-only views remain reachable. The kill switch
does not depend on the Strategy Engine, the Analysis Bridge, or the approval queue.

## Degradation Is Visible

Every degraded state shows on the dashboard with its cause and age. A degraded Trader never looks healthy.

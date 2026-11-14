# 07 — Approval Workflow

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-003, ADR-015 |
| **Open items** | OQ-22 (resolved, ADR-035 and ADR-042) |

For strategies in `APPROVAL` mode (FR-T22).

## Flow

```
intent passes Risk Engine -> AWAITING_APPROVAL (expires_at) -> notify owner
   -> owner Approve -> APPROVED -> Order Manager -> ORDERED
   -> owner Deny    -> DENIED (reason)
   -> expiry        -> EXPIRED
```

## Rules

1. **Approval is bound to the exact intent.** It stores the intent's hash of price, quantity, side, pair,
   and stop. If any of these would change (for example because the order must be repriced), the approval is
   void and a new one is required.
2. **The Risk Engine runs before the card is shown and again at send time.** An intent approved ten minutes
   ago is re-checked against the limits and market data **now**; if it no longer passes, it is not sent and
   the owner is told why.
3. **Expiry is real.** An intent that expires is never sent. The expiry is **1 hour** (ADR-042).
4. **Only `trade:approve` may approve.** No automated actor can (`01/06`).
5. **One decision per intent.** An approved, denied, or expired intent cannot be decided again.
6. **Stops and kill-switch exits are never queued.** They do not wait for approval; they are protective
   (ADR-007, ADR-010).
7. **A denial is information.** The reason is stored and shown, and does not penalize the strategy.

## Scope of Approval

Approval authorizes **one order for one intent**. It does not approve a strategy, a pair, a mode, or future
orders. The owner approves entries; the protective exits that follow need no further approval.

## Concurrency

Two approvals of the same intent resolve to one: the second returns the already-decided state. The decision
and its audit row are one transaction.

## Auditing

Each decision records actor, time, the exact intent hash, the limits headroom shown, and the context shown
(`audit_log`, FR-T33).

## Failure

If the owner approves and the send fails (for example the exchange rejects it), the intent shows the
outcome and does not retry on its own, because a retry would create a second order from one approval.

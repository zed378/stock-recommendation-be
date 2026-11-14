# T0 — Owner answers, batch 5 (timing)

**Date:** 2026-11-14
**Task:** T0-01 (follow-up)
**Author:** Claude (AI agent), working with the project owner
**Spec refs:** `MEMORY/DECISIONS.md` ADR-041

---

## Hook

The four timing numbers that set how fast the Trader notices trouble were chosen: **price poll 10 s, watchdog 3
missed cycles (30 s), reconcile every 60 s, clock-skew halt at 250 ms**. The skew limit follows from an Indodax
rule: a request whose timestamp is 1 s or more ahead of its clock is rejected.

---

## What Changed

| Setting | Value | Open question |
|---|---|---|
| Price poll interval | 10 seconds | OQ-6 (part) |
| Watchdog | 3 missed poll cycles (30 s) | OQ-6 (part) |
| Reconciliation | every 60 seconds | OQ-15 resolved |
| Clock-skew halt | 250 ms | OQ-19 resolved |

OQ-6 is only **partly** decided: the **order poll interval** and the **lease TTL and heartbeat** remain open (the
lease TTL sets the unprotected window after a crash). 41 ADRs; 12 open questions.

---

## Why

Owner's choice from a multiple-choice round. The author deliberately gave **no recommendation** on the price
poll and watchdog numbers, because they are safety numbers.

---

## Alternatives Considered

Price poll 30 s, 60 s, or 5 min; watchdog 2, 5, or 10 cycles; reconcile every 5, 15, or 60 minutes; skew 500 or
750 ms.

---

## What Surprised Me

- Reconciling every 60 s costs about `2P + 2` private requests per minute for `P` pairs, because history and trade
  endpoints require a symbol. It fits the 300-per-minute limit for a small allowlist, but it is **the largest
  consumer of the private request budget** and must be re-budgeted if the allowlist grows.
- A 250 ms skew limit makes any time-endpoint latency visible. The measurement has to account for round-trip
  time or the Trader will halt spuriously. This is carried into T2-05.
- The unprotected window after a crash is now **lease TTL + 30 s**, and the lease TTL is not decided.

---

## Tests

Not applicable: documentation only.

---

## Definition of Done

- [x] Decisions recorded and synced into the worksheet, registry, module specs, and task cards
- [x] Record written and indexed
- [ ] The owner has reviewed

**Waived:** none.

---

## Security and Compliance

No security-relevant change beyond the safety timing itself.

---

## What to Watch

- The private request budget at 60 s reconciliation as pairs are added.
- Spurious halts from the 250 ms skew limit if the host's NTP is poor.

---

## What Was Not Determined

Open (12): OQ-3, 4, 5 (need the live check); OQ-6 (order poll, lease TTL); OQ-22 numbers (reprice wait, max
reprices, approval expiry, `UNKNOWN` attempts); OQ-7, 8, 9, 11, 12, 16, 25 (owner numbers: the worksheet).

---

## Follow-Ups

`TASKS/BACKLOG.md`.

---

## Links

- ADR: ADR-041
- Previous record: `2026-11-14-owner-answers-batch-4.md`

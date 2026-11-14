# T0 — Owner answers, batch 7

**Date:** 2026-11-14
**Task:** T0-01 (follow-up)
**Author:** Claude (AI agent), working with the project owner
**Spec refs:** `MEMORY/DECISIONS.md` ADR-043 to ADR-045

---

## Hook

Every question that a multiple-choice round can sensibly answer is now answered. What remains are **owner numbers
that limit loss** (risk limits, strategy parameters, promotion thresholds, capital, liquidity filter) and three
items that need the **live exchange check**. The owner also chose two pairs where the author recommended one.

---

## What Changed

| Question | Answer | ADR |
|---|---|---|
| OQ-6: order poll | 10 seconds | 043 |
| OQ-6: lease | TTL 15 s, heartbeat 5 s | 043 |
| OQ-7: initial allowlist | BTCIDR and ETHIDR (inactive until the liquidity filter passes) | 044 |
| OQ-25: AI veto | Decided later, with evidence | 045 |

45 ADRs; **8 open questions remain**: OQ-3, 4, 5 (live check), OQ-8, 9, 11, 12, 16 (owner numbers).

---

## Why

Owner's choice. The author recommended 10 s for order polling, a single pair, and deferring the veto; the owner
followed the first and third and chose two pairs. No recommendation was given on the lease.

---

## Alternatives Considered

Order polling 5 s or 30 s; lease TTL 30 s or 60 s; `BTCIDR` only; never enabling a veto; setting veto
thresholds now.

---

## What Surprised Me

- A **15 s lease TTL with a 5 s heartbeat** means three missed heartbeats stop a healthy Trader. Short database
  stalls will produce halts. This is the safe direction, but the owner should expect some.
- Two pairs double the per-pair reconciliation requests. With a 60 s reconciliation interval that is about
  `2P + 2 = 6` private requests per minute, still small against the 300 per minute limit.
- The "no threshold chosen after seeing evidence" rule for the veto is now an explicit step of the post-MVP
  review, because the owner deferred both the decision and the numbers.

---

## Tests

Not applicable: documentation only.

---

## Definition of Done

- [x] Decisions recorded and synced into the worksheet, registry, and task cards
- [x] Record written and indexed
- [ ] The owner has reviewed

**Waived:** none.

---

## Security and Compliance

No security-relevant change.

---

## What to Watch

Spurious halts from the short lease TTL; the liquidity filter must be set before either pair can trade.

---

## What Was Not Determined

Open (8):

- **Need the live check (T2-07):** OQ-3 (does a TAPIv2 key work with the Deadman Switch and the Private WebSocket
  token), OQ-4 (candle boundaries and limits), OQ-5 (real fee, tax, clearing).
- **Owner numbers (the worksheet):** OQ-8 (liquidity filter), OQ-9 (risk limits), OQ-11 (strategy parameters),
  OQ-12 (promotion thresholds), OQ-16 (initial capital).

---

## Follow-Ups

`TASKS/BACKLOG.md`; `docs/01-PRODUCT-REQUIREMENTS/08-OWNER-NUMBERS-WORKSHEET.md` for the five owner numbers.

---

## Links

- ADR: ADR-043, ADR-044, ADR-045
- Previous record: `2026-11-14-owner-answers-batch-6.md`

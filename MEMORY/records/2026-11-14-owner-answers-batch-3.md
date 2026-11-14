# T0 — Owner answers, batch 3

**Date:** 2026-11-14
**Task:** T0-01 (follow-up)
**Author:** Claude (AI agent), working with the project owner
**Spec refs:** `MEMORY/DECISIONS.md` ADR-035, ADR-036

---

## Hook

Order placement rules were decided (maker-first at the touch, `MOC` on entries, `EXPIRE_TAKER`), and the owner
chose **no automatic `FLATTEN`**: a stop-out in a thin market stays a human decision.

---

## What Changed

| Question | Answer | ADR |
|---|---|---|
| OQ-22: entry price rule | Best bid (buy) and best ask (sell), maker-first | 035 |
| OQ-22: self-trade prevention | `EXPIRE_TAKER` | 035 |
| OQ-22: `MOC` on entries | Yes | 035 |
| OQ-10: automatic `FLATTEN` | None; automatic triggers are `HALT` or `CANCEL` only | 036 |

OQ-22 is **partly** decided: the rules are set, but its numbers (reprice wait, maximum reprices, approval
expiry, `UNKNOWN` query attempts and window) remain open and live in the worksheet. 36 ADRs; 18 open questions.

---

## Why

Owner's choice from a multiple-choice round, following the author's recommendation on all four.

---

## Alternatives Considered

Quoting one tick inside the spread or crossing it; `EXPIRE_MAKER` or `EXPIRE_BOTH`; plain `GTC` entries;
automatic `FLATTEN` on a drawdown breaker or a security event.

---

## What Surprised Me

- With no automatic `FLATTEN`, the **only** automatic protections are `HALT`, `CANCEL`, and the bot-side stops.
  If the owner cannot be reached during a fast fall, open positions are bounded only by the exposure limits and
  the stops. That is a conscious trade-off, now in ADR-036.
- Quoting at the touch with `MOC` will produce **cancelled entries** in a fast market (an order that would
  cross is cancelled). They must be counted as a normal outcome, not as failures, or the dashboard will look
  worse than the system is behaving.
- ADR-010 (written earlier) says automatic `FLATTEN` is limited to owner-listed conditions. ADR-036 refines it
  to "none". ADR-010 is left as written, per the rule that ADRs are never edited.

---

## Tests

Not applicable: documentation only. Reference check re-run after the changes (results in the final message).

---

## Definition of Done

- [x] Answers recorded as ADRs and synced across documents and task cards
- [x] Record written and indexed
- [ ] The owner has reviewed

**Waived:** none.

---

## Security and Compliance

No security-relevant change beyond ADR-036's effect on what happens when the owner is unreachable.

---

## What to Watch

- A fast market with MOC entries: many cancelled entries, few fills. The reprice cap (OQ-22 numbers) controls
  how persistent the Trader is.
- The unprotected gap when the owner cannot be reached (ADR-007 and ADR-036 together).

---

## What Was Not Determined

OQ-22 numbers; OQ-1, 3, 4, 5, 6, 7, 8, 9, 11, 12, 15, 16, 18, 19, 20, 25, 26.

---

## Follow-Ups

`TASKS/BACKLOG.md`.

---

## Links

- ADR: ADR-035, ADR-036 (refines ADR-010)
- Previous record: `2026-11-14-owner-answers-batch-2.md`

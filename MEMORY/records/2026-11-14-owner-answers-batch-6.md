# T0 — Owner answers, batch 6 (order placement numbers)

**Date:** 2026-11-14
**Task:** T0-01 (follow-up)
**Author:** Claude (AI agent), working with the project owner
**Spec refs:** `MEMORY/DECISIONS.md` ADR-042

---

## Hook

OQ-22 is fully answered. The one choice with a safety edge is the **`UNKNOWN` window**: 5 queries over 30
seconds is short against an exchange that says a freshly accepted order "may not be immediately available", and
the lag is not quantified anywhere. The failure mode is safe (a held pair and a `CRITICAL` alert, never a
duplicate order), but it may trip often.

---

## What Changed

| Setting | Value |
|---|---|
| Wait before cancel and reprice | 5 minutes |
| Maximum reprices per signal | 3 |
| Approval expiry (`APPROVAL` mode) | 1 hour |
| `UNKNOWN` order queries | 5 attempts over 30 seconds, then hold the pair and alert |

41 to 42 ADRs; 11 open questions remain.

---

## Why

Owner's choice. The author recommended the first three and abstained on the fourth (safety number). All three
recommended values were chosen.

---

## Alternatives Considered

Reprice waits of 1 min, 15 min, 1 h; 0 or 10 reprices; approval expiry of 15 min, 2 h, 3 h; `UNKNOWN` queried 10
times in 2 min or 20 times in 10 min.

---

## What Surprised Me

- With a 5-minute wait and 3 reprices, a chased entry lasts at most about **20 minutes**.
- A short `UNKNOWN` window likely produces `CRITICAL` alerts on ordinary visibility lag. If it does, the owner
  will see repeated false alarms and the setting should be revisited once the real lag is observed at T5-06.
- The mock exchange must reproduce visibility lag longer than the 30 s window, otherwise the hold-and-alert path
  would never be exercised in tests (`11/07` already lists a configurable lag; this makes it a required case).

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

No security-relevant change.

---

## What to Watch

False `CRITICAL` alerts from the 30 s `UNKNOWN` window; the pair is held until the owner confirms.

---

## What Was Not Determined

Open (11): OQ-3, 4, 5 (need the live check); OQ-6 (order poll interval, lease TTL); OQ-7, 8, 9, 11, 12, 16, 25.

---

## Follow-Ups

`TASKS/BACKLOG.md`. The mock exchange must include a visibility lag longer than the `UNKNOWN` window (T2-01).

---

## Links

- ADR: ADR-042
- Previous record: `2026-11-14-owner-answers-batch-5.md`

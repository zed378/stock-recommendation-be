# T0 — Owner answers, batch 2

**Date:** 2026-11-14
**Task:** T0-01 (follow-up)
**Author:** Claude (AI agent), working with the project owner
**Spec refs:** `MEMORY/DECISIONS.md` ADR-031 to ADR-034

---

## Hook

Four open questions answered. The one with real scope consequences: **AI and Kronos context for crypto is out of
the MVP** (ADR-032), which removes two tasks (T3-05, T3-06) from the first release.

---

## What Changed

| Question | Answer | ADR |
|---|---|---|
| OQ-2 Notification channel | Telegram, outbound only | 031 |
| OQ-13 AI context for crypto | MVP without it; then option B (candle-in endpoint), record-only first | 032 |
| OQ-21 May `admin` `HALT`? | Yes (`CANCEL`, `FLATTEN`, resume stay with `trader`) | 033 |
| OQ-23 What is "a day"? | Local midnight WIB (UTC+7) | 034 |

About 40 documents and task cards that referred to these questions were updated; headers now read "resolved" or
"decided". Counts: 34 ADRs, 19 open questions. The owner numbers worksheet, settings registry, roadmap,
progress board, and backlog were adjusted.

---

## Why

The owner chose these in a multiple-choice round. The author's recommendation was followed for OQ-13 and
OQ-21; for OQ-2 and OQ-23 the owner chose between options the author did not recommend either way.

---

## Alternatives Considered

For OQ-13: building option B inside the MVP, option A (full crypto asset support), or never using AI context for
crypto. For OQ-23: UTC midnight or a rolling 24 hours.

---

## What Surprised Me

- Deferring AI context moves **FR-T09 (veto) and tasks T3-05, T3-06 out of the MVP**, so the MVP's behavior is
  purely rules plus limits. That is simpler, but it also means there is **no AI evidence** for crypto pairs
  until some time after the MVP.
- The WIB day boundary means the loss allowance resets at 00:00 WIB, which can hand the strategy a fresh budget
  in the middle of a market move. The owner accepted this knowingly; the cumulative drawdown limit is
  unaffected.
- `admin` being able to `HALT` is an **availability** exposure (a compromised admin can halt trading), not a
  loss exposure. It is audited and notified.

---

## Tests

Not applicable: documentation only. The reference consistency check was re-run: 131 files, no missing
references, OQ-1 to OQ-26 and ADR-001 to ADR-034 all defined, 19 open questions remaining.

---

## Definition of Done

- [x] Answers recorded as ADRs and synced
- [x] Record written and indexed
- [ ] The owner has reviewed

**Waived:** none.

---

## Security and Compliance

ADR-031 adds a Telegram bot token (a credential: encrypted, never logged, rotatable). Telegram's Bot API
behavior and what the provider can read were **not researched** and are verified in T5-02.

---

## What to Watch

- Telegram messages leave your infrastructure. Redaction rules (`09/05`) apply; positions appear only at the
  detail a message needs.
- Post-MVP work (T3-05, T3-06) is easy to forget. It is on the roadmap under "Post-MVP (decided)".

---

## What Was Not Determined

Still open (19): OQ-1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 16, 18, 19, 20, 22, 25, 26. Most are **owner
numbers** that belong in the worksheet (`docs/01-PRODUCT-REQUIREMENTS/08-OWNER-NUMBERS-WORKSHEET.md`).

---

## Follow-Ups

`TASKS/BACKLOG.md`.

---

## Links

- ADR: ADR-031, ADR-032, ADR-033, ADR-034
- Previous record: `2026-11-14-owner-answers-batch-1.md`

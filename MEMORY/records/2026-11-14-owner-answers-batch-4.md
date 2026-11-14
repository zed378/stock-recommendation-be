# T0 — Owner answers, batch 4

**Date:** 2026-11-14
**Task:** T0-01 (follow-up)
**Author:** Claude (AI agent), working with the project owner
**Spec refs:** `MEMORY/DECISIONS.md` ADR-037 to ADR-040

---

## Hook

Two of the four answers **accept a known gap**: nothing alerts if the whole host is down (ADR-039), and
off-host backups are manual so the audit-trail RPO is unbounded (ADR-040). Both are now written down as accepted
risks, not left implicit.

---

## What Changed

| Question | Answer | ADR |
|---|---|---|
| OQ-1 Legal and tax | Considered by the owner; no checklist gate | 037 |
| OQ-18 When is the live read-only check? | After the connector and mock exist (T2-07) | 038 |
| OQ-26 Out-of-process liveness monitor | A host script, read-only role, straight to Telegram | 039 |
| OQ-20 Off-host backups | Manual, to an external disk or the owner's PC | 040 |

Sync: the release checklist lost its legal item and gained ADR references; T5-06 and T6 task cards updated; a
third database role (`trader_monitor`) and a second host secret (the liveness script's Telegram token) were
added to the data-model and secrets documents. 40 ADRs; 14 open questions.

---

## Why

Owner's choice. For OQ-18 and OQ-26 the owner took the author's recommendation. For OQ-1 and OQ-20 the owner
chose against it (no checklist gate; manual instead of automatic or SSH-based backup copies).

---

## Alternatives Considered

OQ-1: a checklist statement, or a task recording professional advice. OQ-18: an earlier public-only phase, or
deferring all live contact to T5-06. OQ-26: an external uptime service, or both. OQ-20: another host over SSH, or
encrypted cloud storage.

---

## What Surprised Me

- **Removing the legal gate does not remove the issue.** The exchange's own STP page treats self-trades from
  automated systems as a concern, and every fill carries a tax amount. The author left a recommendation in the
  ADR and in the documents; the system will not prompt for it.
- **Manual backups interact badly with a mandatory pre-release backup**: the backup is taken on the host, then
  has to be copied off by the owner. A release is therefore not complete until that copy exists; the procedure
  already requires a restorable backup, and the owner is the one who makes it off-host.
- **The new liveness script adds an attack surface**: a database role, a token on the host, and a scheduled job.
  Each is small and read-only, but they are new.

---

## Tests

Not applicable: documentation only. Reference check re-run (results in the final message).

---

## Definition of Done

- [x] Answers recorded as ADRs and synced across documents and task cards
- [x] Record written and indexed
- [ ] The owner has reviewed

**Waived:** none. (The legal checklist item was **removed on the owner's instruction**, not waived: ADR-037.)

---

## Security and Compliance

- ADR-039: the host script's Telegram token must be a root-only file; the `trader_monitor` role has `SELECT` on
  the heartbeat only.
- ADR-040: a backup contains the encrypted credential but not the master key; the owner must keep the key and
  the copied dump apart (ADR-029).

---

## What to Watch

- A host outage is silent. Consider (later, with approval) an external heartbeat service.
- Copies made manually go stale. A reminder would help; it was not added without approval.

---

## What Was Not Determined

Open (14): OQ-3, 4, 5 (need the live check); OQ-6, 15, 19 and the OQ-22 numbers (timing); OQ-7, 8, 9, 11, 12, 16,
25 (owner numbers: the worksheet).

---

## Follow-Ups

`TASKS/BACKLOG.md`.

---

## Links

- ADR: ADR-037, ADR-038, ADR-039, ADR-040
- Previous record: `2026-11-14-owner-answers-batch-3.md`

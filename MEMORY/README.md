# MEMORY/ — Change Record and Decision Log

`TASKS/` is what will be done. `MEMORY/` is what **was** done, and why it ended up that way.

This folder exists because `docs/` describes the intended system and the code describes the current system,
but neither explains how one became the other. `MEMORY/` is the continuity across agent sessions, which is
why writing to it is part of a task and not a summary appended afterwards.

Convention adopted from the Central Dashboard repository's `MEMORY/` at the project owner's request, scaled
to this project: the Trader is documented but not built, so this folder starts with the decisions from the
design interview and grows one record per completed task.

Scope: the **AIDSS Trader** (Indodax crypto auto-trading). The analysis platform's own history lives in git
and in `docs/archive/Dokumen_Perencanaan_AI_Investment_Decision_Support.md`.

---

## Structure

| Path | Purpose |
|---|---|
| [`MEMORY-INDEX.md`](./MEMORY-INDEX.md) | One line per record, newest first. The entry point |
| [`CHANGELOG.md`](./CHANGELOG.md) | Chronological summary, coarser than the records |
| [`DECISIONS.md`](./DECISIONS.md) | ADRs: every choice `docs/` leaves open and every deviation from it |
| [`records/`](./records/) | One file per completed task: what changed, why, and what to watch |
| `specs/` | Feature specs for tasks marked `Spec required`, written **before** implementation. Created with the first spec |
| [`templates/`](./templates/) | The change-record, phase-summary, and feature-spec templates |

**Where the current status lives:** [`../TASKS/PROGRESS.md`](../TASKS/PROGRESS.md), not here. This folder is
history; the board is state. A snapshot kept in two places drifts, and then neither can be trusted.

## What Gets a Record

**Every task that reaches `DONE`.** See the Definition of Done in
[`../TASKS/00-TASK-CONVENTIONS.md`](../TASKS/00-TASK-CONVENTIONS.md): a task without a record is not done,
however finished the code looks.

Also recorded:

- **Any deviation from `docs/`**, as an ADR, per the deviation protocol.
- **Any decision `docs/` deliberately left open.**
- **Phase completions**: what shipped, what deviated, what was deferred, what to watch.
- **Security-relevant outcomes**: a key rotation, a credential test, a penetration review.
- **Operational events with lasting consequence**: an incident, a kill-switch use, a rollback, a drill, a
  restore rehearsal, a promotion decision.
- **Live observations of the exchange** that confirm or contradict the documentation.

## What Does Not Get a Record

- Work in progress. Records describe completed changes.
- Anything git already tells you accurately. A record explains **why**, not what changed on which line.
- Restating a `docs/` document. Link to it instead.

## Writing a Record

1. Copy [`templates/CHANGE-RECORD-TEMPLATE.md`](./templates/CHANGE-RECORD-TEMPLATE.md).
2. Name it `records/YYYY-MM-DD-<task-id>-<slug>.md`.
3. Fill in **every** section. "Not applicable" is valid; a blank section is not.
4. Add a one-line pointer to [`MEMORY-INDEX.md`](./MEMORY-INDEX.md) at the top of the list.
5. Add a [`CHANGELOG.md`](./CHANGELOG.md) entry if the change is user-visible or operationally significant.
6. Add an ADR to [`DECISIONS.md`](./DECISIONS.md) if a decision was made or a document deviated from.
7. Commit all of it **with the code**, not afterwards.

## Honesty Rules

- **Record what happened, not what was supposed to happen.** If a test was skipped, say so.
- **Record failures.** A drill that failed, an endpoint that behaved unexpectedly, a limit that did not
  trigger: these are the highest-value records.
- **Never claim a test passed without naming it.**
- **Do not retroactively edit a record to look better.** Add a follow-up record.
- **Record open questions found during the work** and add them to
  [`../TASKS/BACKLOG.md`](../TASKS/BACKLOG.md) so they have a consequence.
- **Distinguish "passes on the mock" from "works on the exchange".** A connector that parses a fixture is not
  a connector verified against Indodax. Both distinctions belong in a record, never rounded up.
- **Distinguish paper from live** every time a result is reported.
- **Never record a secret**, including Indodax's sample keys.

## Relationship to Other Folders

| Folder | Direction | Nature |
|---|---|---|
| `docs/` | Reference | What the system **is**. Amended only through the deviation protocol |
| `TASKS/` | Forward | What will be built, in what order, and how it will be judged done |
| `MEMORY/` | Backward | What was built, what it cost, and what to watch |

# 06 — Documentation Maintenance

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Documentation Writer |
| **Decided by** | ADR-017, ADR-023 |

## Principle

`docs/` describes the system **as intended**, the code describes it **as built**, and `MEMORY/` explains how
one became the other. A document that no longer matches reality is a defect, and a confidently wrong
document is worse than a missing one.

## Rules

1. **Amend through the deviation protocol.** If implementation shows a document is wrong, stop, write an
   ADR, amend the document referencing it, and note both in the record
   (`TASKS/00-TASK-CONVENTIONS.md`).
2. **Docs change in the same commit as the reality they describe.**
3. **Never invent.** Where nothing is decided, a document says so and points to its open question. A number is
   never filled in to make a document look complete.
4. **Status markers stay honest.** "Documented, not yet observed" is removed from an Indodax detail only when a
   live observation is recorded, with its date.
5. **Cite sources.** Indodax details cite the documentation commit; analysis-platform details cite the code
   path; measurements cite the date and conditions.
6. **Open questions have consequences.** An open question lives in `TASKS/BACKLOG.md` and is referenced by the
   documents that depend on it; resolving it updates all of them.
7. **Supersede, do not rewrite.** ADRs and records are never edited to look better; a new one supersedes.

## Ownership

Per `00-PROJECT-CONTEXT/00-README.md`. The owner of a document keeps it current; anyone may propose a change
through the deviation protocol.

## Review Cadence

| Trigger | Review |
|---|---|
| Every release | The threat model, runbooks, and release checklist |
| After the live read-only verification (T2-07) | `06-INTEGRATIONS/03` to `11` |
| After any incident | The relevant runbook and the threat model |
| Each phase completion | The roadmap, `TASKS/PROGRESS.md`, and `CLAUDE.md` "What Is Currently Failing" |
| When Indodax changes its documentation | `06-INTEGRATIONS/` against the new commit |

## Drift Checks

- `CLAUDE.md` commands are run before being claimed.
- The traceability table (`01-PRODUCT-REQUIREMENTS/07`) is compared with real tests once they exist, and
  "planned" becomes a real name only when the test passes.
- `docs/` links are checked.

## Relationship to the Analysis Platform's Documents

The archived planning document stays as the analysis platform's specification and is not maintained as part of
the Trader. Code comments that say "Section N" refer to it.

## Catalog

`../../trader-document-catalog.md` indexes every document and states its purpose. Add an entry when a
document is added.

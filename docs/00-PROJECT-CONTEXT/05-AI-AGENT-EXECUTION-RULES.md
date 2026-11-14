# 05 — AI Agent Execution Rules

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Technical Lead |
| **Decided by** | ADR-001, ADR-004, ADR-013 |

Instructions for coding agents working on the Trader. `../../CLAUDE.md` is the short version; this is the
detail.

## Order of Work

1. Read `../../TASKS/PROGRESS.md`, then the active phase file, then the task's `Spec refs`.
2. Check `../../TASKS/BACKLOG.md` for open questions that block the task.
3. Write the feature spec first if the task says `Spec required`.
4. Implement, test, write the record, update `PROGRESS.md`, in one commit.

## What an Agent May Do

- Read all documents and code.
- Write code in `src/aidss_trader/`, `tests/trader/`, and the Trader's migrations once the phase is active.
- Run the hermetic test suite, lint, and the mock exchange server.
- Record a safe, reversible default as a `proposed` ADR and continue.

## What an Agent May Not Do

| Prohibited | Why |
|---|---|
| Send a signed request to the production Indodax API | A real key can move money. Needs the owner's explicit per-action instruction |
| Write, run, or stub a withdrawal, deposit-address, or fiat endpoint call | ADR-013 |
| Choose a risk limit, threshold, polling interval, or capital amount | The owner sets every number that limits loss (OQ-9, OQ-12, OQ-16) |
| Edit `tests/test_architecture_constraints.py` or add trading code under `src/aidss` | ADR-001 |
| Pass model output into an order field | ADR-004 |
| Disable, skip, or weaken a risk check or the kill switch to make something pass | The control is the product |
| Commit a key, secret, token, signature, or any sample credential copied from Indodax's pages | Secrets are never literal |
| Present paper or backtest output as real trading | No fabricated data |
| Reset or drop a database to resolve a migration problem | Additive migrations only; the ledger is append-only |
| Promote a strategy's mode | Only the owner, through the audited promotion flow |

## Recording Assumptions

A choice made without the owner goes into `MEMORY/DECISIONS.md` as `proposed`, with the alternatives and the
bad implications, and the task record links to it. If the choice affects money, it is a backlog question
instead, and the work stops at that point.

## Testing Requirements

Every connector interaction, every risk limit, and every kill-switch tier has a named test. An assertion
that something was tested is not evidence; the record names the tests
(`../11-TESTING-QUALITY/00-TEST-STRATEGY.md`).

## When Documents Disagree With the Exchange

Real Indodax behavior wins over this documentation and over Indodax's own pages. Do not quietly adapt:
record the observation, correct the document through the deviation protocol, and note it in
`../06-INTEGRATIONS/11-INDODAX-DOCS-DISCREPANCIES.md`.

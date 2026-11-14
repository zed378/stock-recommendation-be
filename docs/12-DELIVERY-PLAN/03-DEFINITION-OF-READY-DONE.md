# 03 — Definition of Ready and Done

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Technical Lead |
| **Decided by** | ADR-013, ADR-024 |

The authoritative global DoD is in `../../TASKS/00-TASK-CONVENTIONS.md`; this file states Ready and
summarizes Done for convenience.

## Definition of Ready

A task is ready when:

- its dependencies are `DONE` and its phase is active;
- every document in `Spec refs` exists;
- no open question it depends on is unresolved (otherwise it is `BLOCKED`);
- a feature spec exists if the card says `Spec required`;
- the tests it will add are named;
- anything needing a credential, a live exchange call, or an owner-set number has the owner's input, or is an
  owner-led task.

## Definition of Done (summary)

### Code

- Implements the spec in `docs/`.
- Money is `Decimal`; no float.
- No fabricated or demo data presented as live without a label; `origin` correct.
- Errors normalized, with source, operation, time, and correlation id.

### Trading-specific (unwaivable)

- No path to the exchange that skips the Risk Engine.
- No withdrawal, deposit, or fiat code.
- No model text reaches an order field.
- A control that limits loss has a test that fails when the control is removed.
- Uncertain state halts; nothing continues "with a warning".

### Integrations

- Read-only by default; the only writes are `create_order` and `cancel_order`.
- A failure does not erase or corrupt records and distinguishes unavailable, stale, empty, unauthorized.
- No endpoint or field invented: validated against the official documentation, with the commit cited, and
  noted as "not yet verified against the live exchange" until T2-07 or a later observation.
- No secret committed; credentials are references.

### Testing

- Unit tests including error branches; connector contract tests (`11/02`); integration scenarios where
  relevant.
- No test contacts the production exchange.
- The named tests are in the record.

### Build

- Lint, typecheck, build. The analysis platform's architecture test passes unmodified.

### Documentation

- `docs/` amended if and only if reality changed. An ADR if a decision was made or a document deviated from.

### Record

- `MEMORY/records/YYYY-MM-DD-<task-id>-<slug>.md`, an index line, a changelog entry if operationally
  significant, and `TASKS/PROGRESS.md` updated **in the same commit**.

## What May Be Waived

Most items, with a recorded decision naming who agreed. **Never waivable:** a fabricated-data finding, a
bypass of the Risk Engine, a withdrawal path, and a secret in the repository.

## Evidence

An assertion that a test passed is not evidence. Name the test.

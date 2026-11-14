# 04 — Audit Logging

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Security Engineer |
| **Decided by** | ADR-021, ADR-022 |

Schema: `../03-DATA-MODEL/05-RISK-AND-AUDIT-SCHEMA.md`.

## What Is Audited

| Domain | Actions |
|---|---|
| Orders | Create, cancel, reprice, every state change, with the correlation id |
| Intents | Created, vetoed, rejected (with the failing check), approved, denied, expired |
| Modes | Promotion, demotion, with gate evidence |
| Limits and allowlist | Every new version, who, before and after |
| Strategy parameters | New versions |
| Kill switch | Each tier, trigger, and step result |
| Breakers | Trip and resume, with values and resume note |
| Credentials | Store, test, rotate, remove: actor and time, **never the value** |
| Reconciliation | Runs, differences, resolutions, adjustments |
| Authentication | Sensitive-action authentication and failures on the operator API |
| Access | Read of the audit log and exports |
| Lifecycle | Trader start, stop, lease acquired and lost |

## Properties

- **Append-only.** `trader_rw` has `INSERT` and `SELECT` only on `audit_log`.
- **Actor is always named**: a user id, or `system:<component>`.
- **Before and after** for every change, redacted.
- **Correlation.** One id links a signal, intent, order, fills, and events.
- **Mode recorded.** The strategy's mode at the time, so a `PAPER` row cannot pass for a live one.
- **Time** comes from the Trader process, not the database (the hash needs it before the row exists, and an
  UPDATE to add it later is exactly what the role cannot do). Appends assume a single writer, which the lease
  guarantees (ADR-027).

## Tamper Evidence (proposed)

Each audit row stores a hash of its content and the previous row's hash, forming a chain. A periodic job
verifies the chain and raises `CRITICAL` on a break. A database owner can still rewrite the whole chain, so
the chain's head is also recorded outside the database (for example in the notification channel or a
separate log) on a schedule. The design and the schedule are decided in task T1-05 and recorded as an ADR.

## What Is Never Written

Keys, secrets, signatures, the master key, and full request headers.

## Access

Readable with `trade:read_audit` (the owner and `admin`). Exports are themselves audited.

## Retention

Kept indefinitely by default (`03-DATA-MODEL/06`).

## Tests (planned, FR-T33)

Every mutating route and every state change writes a row; no row contains a secret; an `UPDATE` or `DELETE`
as `trader_rw` fails; the chain detects a modified row.

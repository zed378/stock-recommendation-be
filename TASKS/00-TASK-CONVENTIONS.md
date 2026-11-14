# 00 — Task Conventions

How to work in this repository on the Trader. Read before starting any task. Adapted from the Central
Dashboard repository's convention to a trading domain.

---

## Task IDs

```
T<phase>-<sequence>          T1-03, T4-06
```

Phases: T0 (specification), T1 (foundation), T2 (exchange connector), T3 (strategy, backtest, paper), T4
(execution core), T5 (operator surface and approval), T6 (hardening and release). See
[`README.md`](./README.md). The `T` prefix distinguishes these from other projects' `P<phase>` scheme.

## Statuses

| Status | Meaning |
|---|---|
| `TODO` | not started; dependencies may or may not be met |
| `BLOCKED` | dependencies not met, or waiting on an owner number or decision (see `BACKLOG.md`) |
| `WIP` | in progress, on a branch |
| `REVIEW` | PR open, or documentation awaiting the owner's review |
| `DONE` | merged **and** its `MEMORY/records/` entry exists |

**`DONE` requires the record.** A task without one is not done.

## Anatomy of a Task Card

```markdown
### T4-03 — Order Manager: create, write-ahead, idempotency, UNKNOWN

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T2-06, T4-01 |
| **Spec refs** | docs/05-MODULE-SPECIFICATIONS/04-ORDER-MANAGER.md · docs/03-DATA-MODEL/02-STATUS-AND-STATE-MACHINES.md |
| **Spec required** | yes |
| **Open numbers** | none (ADR-042) |
| **Owner-led** | no |

**Why:** ...

**Definition of Done**
- [ ] ...

**Abuse cases**
- ...
```

**Spec refs are mandatory.** **Open numbers** lists every owner-set value the task needs; if one is unset the
task implements the mechanism only and reads the value from configuration, or is `BLOCKED`. **Abuse cases**
state how the task could be satisfied dishonestly; write at least one per task that touches money.

## Branches

```
{type}/{task-id}-{kebab-description}

feat/T4-03-order-manager-create
fix/T2-05-clock-skew-halt
docs/T0-02-risk-engine-spec
```

Types: `feat`, `fix`, `refactor`, `docs`, `chore`, `test`. One task, one branch, one PR. `main` stays
deployable.

## Commits

```
T4-03: Add the Order Manager create path with write-ahead

- Persist the SUBMITTING row before sending (ADR-026)
- Deterministic clientOrderId; timeout resolves by query, never by retry (ADR-024)
- Tests: test_timeout_is_resolved_by_query_not_retry, test_persist_failure_sends_nothing
```

Subject carries the task ID. Body explains **why**.

## The Global Definition of Done

Every task inherits this. A task's own DoD **adds** to it.

### Code

- [ ] Implements the spec in `docs/`
- [ ] Money and quantities are `Decimal`; no float
- [ ] No fabricated, demo, paper, or backtest data presented as live; `origin` correct
- [ ] Errors normalized, retaining source, operation, time, and correlation id

### Trading safety: unwaivable where touched

- [ ] No path to the exchange skips the Risk Engine
- [ ] No withdrawal, deposit, or fiat code
- [ ] No model text reaches an order field
- [ ] Uncertain state halts; nothing continues "with a warning"
- [ ] A control that limits loss has a test that fails when the control is removed
- [ ] A write whose outcome is unknown is resolved by query, never blindly retried

### Integrations

- [ ] Read-only by default; the only writes are `create_order` and `cancel_order`
- [ ] A failure does not erase or corrupt records, and distinguishes unavailable, stale, empty, unauthorized
- [ ] No endpoint or field invented: validated against the official Indodax documentation (commit cited) and
      marked "not yet verified against the live exchange" until observed
- [ ] No secret committed; credentials are references, never literal. No Indodax sample keys

### Testing

- [ ] Unit tests including error branches
- [ ] Connector contract tests: success, malformed, timeout, auth failure, clock skew, rate limit,
      rejection, windowing, duplicate, partial result
- [ ] No test contacts the production exchange
- [ ] The analysis platform's `tests/test_architecture_constraints.py` passes **unmodified**
- [ ] Tests pass at the configured gate

### Build

- [ ] `ruff check`
- [ ] Type checks, where configured
- [ ] Build succeeds; the Trader image has no torch and no test suite

### Documentation

- [ ] `docs/` amended if and only if reality changed
- [ ] An ADR if a decision was made or a `docs/` document deviated from

### Record

- [ ] `MEMORY/records/YYYY-MM-DD-<task-id>-<slug>.md` written
- [ ] A line added to `MEMORY/MEMORY-INDEX.md`
- [ ] A `MEMORY/CHANGELOG.md` entry if user-visible or operationally significant
- [ ] `TASKS/PROGRESS.md` updated **in the same commit**

## What May Be Waived, and What May Not

**Never waivable:** a fabricated-data finding; a bypass of the Risk Engine; any withdrawal path; a secret in
the repository. Everything else is negotiable with a recorded decision **naming who agreed**, written into
the change record.

## The Deviation Protocol

When implementation reveals `docs/` is wrong, incomplete, or contradictory:

1. **Stop.** Do not quietly implement something different.
2. Write an **ADR** in `MEMORY/DECISIONS.md`: decision, rationale, alternatives, implications including the
   bad ones.
3. Amend the `docs/` document, referencing the ADR.
4. Note both in the change record.

If the deviation needs a decision the owner has not made, it is an Open Question in
[`BACKLOG.md`](./BACKLOG.md), not a judgement call. If a safe, reversible default exists and **nothing
touching money or credentials is being built**, record it as a `proposed` ADR and continue. A number that
limits loss is never defaulted.

## Evidence

> **An assertion that a test passed is not evidence. Name the test.**

"Connector tested, all good" with no test named is **worse than saying nothing**, because it stops anyone
looking again. "Passes on the mock" must not be reported as "works on Indodax".

## Before Opening a PR

Run lint and the test suite per `../CLAUDE.md` § Commands. Do not invent commands not defined there.

## PR

**Title:** `T4-03: Add the Order Manager create path with write-ahead`

**Body:** spec refs, what changed and why, named tests (and what they do **not** cover), the DoD checklist,
anything waived and who agreed, anything not determined, and the open numbers the task depends on.

# TASKS/ — Execution Plan

`../trader-document-catalog.md` describes **what** documents exist and **what** the Trader is. This folder
describes **what to do next, in what order, and how to know it is finished**.

Nothing here invents architecture. Every task points back to `docs/`. **If a task would need a decision
`docs/` does not contain, it is not a task**: it is an entry in [`BACKLOG.md`](./BACKLOG.md) under Open
Questions.

---

## Read This First

**The Trader is specified but not built.** Phase T0 (documentation) is awaiting the owner's review. No
`aidss_trader` code exists. The analysis platform it sits beside is built and is unchanged by this plan.
See `PROGRESS.md` § What Exists Today.

## Files

| File | Purpose |
|---|---|
| [`00-TASK-CONVENTIONS.md`](./00-TASK-CONVENTIONS.md) | Task IDs, statuses, card anatomy, the Definition of Done every task inherits |
| [`PROGRESS.md`](./PROGRESS.md) | **The single status board.** What is shipped, what is not |
| [`PHASE-T0-SPECIFICATION.md`](./PHASE-T0-SPECIFICATION.md) | Documentation. In review |
| [`PHASE-T1-FOUNDATION.md`](./PHASE-T1-FOUNDATION.md) | Package, image, schema, roles, guards, credential store, audit, lease. No exchange calls |
| [`PHASE-T2-EXCHANGE-CONNECTOR.md`](./PHASE-T2-EXCHANGE-CONNECTOR.md) | Mock exchange, connector, public data, account, throttle, orders against the mock, **owner-led read-only live verification** |
| [`PHASE-T3-STRATEGY-BACKTEST-PAPER.md`](./PHASE-T3-STRATEGY-BACKTEST-PAPER.md) | Strategy, sizing, order state machine, paper, backtest, ledger, analysis bridge (record-only) |
| [`PHASE-T4-EXECUTION-CORE.md`](./PHASE-T4-EXECUTION-CORE.md) | Risk Engine, breakers, Order Manager, Exit Monitor, kill switch, reconciliation, all on the mock |
| [`PHASE-T5-OPERATOR-SURFACE-AND-APPROVAL.md`](./PHASE-T5-OPERATOR-SURFACE-AND-APPROVAL.md) | Approval, notifications, promotion, dashboard, export, **owner-led `APPROVAL` with small real capital** |
| [`PHASE-T6-HARDENING-AND-RELEASE.md`](./PHASE-T6-HARDENING-AND-RELEASE.md) | Security review, resilience, drills, liveness, release, the `AUTO` readiness review |
| [`BACKLOG.md`](./BACKLOG.md) | Open questions, specification gaps, deliberate deferrals |

## How to Use This Folder

1. **Open [`PROGRESS.md`](./PROGRESS.md)** and find the lowest-numbered `TODO` task in the active phase whose
   dependencies are all `DONE`.
2. **Read every document in the task's `Spec refs`.**
3. **If the task is marked `Spec required`**, write the feature spec from
   [`../MEMORY/templates/FEATURE-SPEC-TEMPLATE.md`](../MEMORY/templates/FEATURE-SPEC-TEMPLATE.md) **before**
   code.
4. **Check the task's "Open numbers"**: any owner-set value it needs must exist, or the task is `BLOCKED`.
5. **Implement**, satisfying the task's DoD plus the global DoD.
6. **Record the change** in [`../MEMORY/`](../MEMORY/README.md).
7. **Update `PROGRESS.md`** and tick the task, in the same commit as the work.

## The Phase Rule

> **Never build a Phase N+1 feature while Phase N is incomplete.**

Concretely: no order code before the connector, mock, and state machine exist; no live money before the Risk
Engine, kill switch, reconciliation, and restore rehearsal are done; no `AUTO` before the `APPROVAL` period and
the owner-set gates.

## Owner-Led Tasks

`T2-07` (live read-only verification) and `T5-06` (`APPROVAL` with real capital) cannot be completed by an
agent. They need the owner's key, instruction, and judgement. An agent prepares them and stops.

## The One Rule About Evidence

> **An assertion that a test passed is not evidence. Name the test.**

And: **"passes on the mock" is not "works on the exchange".**

## Relationship to `docs/` and `MEMORY/`

| Folder | Direction | Nature |
|---|---|---|
| `docs/` | Reference | What the system **is**. Amended only through the deviation protocol |
| `TASKS/` | Forward | What will be built, in what order, and how it will be judged done |
| `MEMORY/` | Backward | What was built, what it cost, and what to watch |

`TASKS/` is forward-looking; `MEMORY/` is backward-looking. **They are updated in the same commit: a task is
not `DONE` until its `MEMORY` record exists.**

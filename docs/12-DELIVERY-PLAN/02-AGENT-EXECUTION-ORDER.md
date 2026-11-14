# 02 — Agent Execution Order

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Technical Lead |

The order in which a coding agent takes tasks, and where it must stop for the owner.

## Order

1. Take the lowest-numbered `TODO` task in the **active** phase whose dependencies are `DONE`
   (`../../TASKS/PROGRESS.md`).
2. Do not start a task whose `Spec refs` name an open question that blocks it; record it as `BLOCKED`.
3. Within a phase, the default order is the ID order, except where a card states a dependency.

## Recommended Sequencing Within Phases

| Phase | Notes |
|---|---|
| T1 | `T1-02` (guards) early, so the boundary is enforced before code accumulates. `T1-03` before `T1-04` and `T1-05` |
| T2 | `T2-01` (mock) before `T2-06`; `T2-02` before the rest. `T2-07` last and only with the owner |
| T3 | The order state machine in `T3-04` is shared with T4; implement it once, with the full transition table |
| T4 | `T4-01` before `T4-03`; `T4-06` (kill switch) is built early in T4 and **never depends** on `T4-03`'s strategy-facing parts |
| T5 | `T5-06` last |

## Stop Points: the Agent Must Ask the Owner

| Trigger | Why |
|---|---|
| A task needs a credential, a live exchange call, or funded action | Money and keys are the owner's |
| A task needs a number that limits loss (a limit, threshold, interval, capital amount) | Never defaulted |
| A decision that would add a withdrawal path or widen the analysis platform's reach into execution | Needs an ADR and approval |
| The owner-led tasks `T2-07` and `T5-06` | Cannot be done by an agent alone |
| A documentation contradiction with a live observation | Deviation protocol, ADR, then continue |
| A promotion of a strategy's mode | Owner only |

## What an Agent Produces per Task

Code and tests; the `MEMORY/records/` entry that names its tests; an index line; a `PROGRESS.md` update; any
ADR or backlog entry the task surfaced; and an honest "What Was Not Determined" section.

## Parallelism

Tasks with no dependency on each other may be worked on in parallel, each on its own branch. Two tasks never
edit the same document at once without coordinating; the documentation writer role merges.

## Never

Skip a phase, reorder around a missing record, mark a task `DONE` without its record, or fill a blocking open
question with a guess.

# Progress — Single Status Board

What is shipped, what is not. Updated in the same commit as the work it reflects.

---

## Phase Status

| Phase | Name | Status | Notes |
|---|---|---|---|
| T0 | Specification | 🔎 in review (2026-11-14) | Documents written; **awaiting the owner's review**. See `MEMORY/records/2026-11-14-trader-docs-scaffolding.md`. 108 files in `docs/`, 45 ADRs, 8 open questions |
| T1 | Foundation | ⏳ TODO | Waiting only for T0 to be accepted; OQ-14, OQ-17, OQ-24 are decided (ADR-028 to ADR-030) |
| T2 | Exchange connector | ⏳ TODO | T2-07 is owner-led (needs a Read-only key) |
| T3 | Strategy, backtest, paper | ⏳ TODO | Needs OQ-5, OQ-11 (AI context deferred to post-MVP, ADR-032) |
| T4 | Execution core | ⏳ TODO | Needs OQ-9 (mechanism can be built before values are set) |
| T5 | Operator surface and `APPROVAL` | ⏳ TODO | T5-06 is owner-led; needs OQ-12, OQ-16 |
| T6 | Hardening and release | ⏳ TODO | No open question blocks T6 (ADR-037, ADR-039, ADR-040) |

## What Exists Today

### The analysis platform (built; not changed by this plan)

Python 3.11+, FastAPI, PostgreSQL 16 with pgvector, React and Vite. Market data, indicators, a multi-agent
analysis pipeline with a calibrated recommendation, TradingAgents-style debate, Kronos-base CPU forecasting,
portfolio analytics, news and RAG, reporting, and a dashboard. Decision support only: no order, broker, or
execution path, enforced by `tests/test_architecture_constraints.py`.

Last full test run (2026-11-14): **1,754 passed, 1 failed**
(`tests/test_output_language.py::test_translation_covers_every_prose_field`, pre-existing, unrelated).

Deployed on the project's host as images `zed378/aidss-api` and `zed378/aidss-frontend`, published to a
**public** Docker Hub repository at the owner's choice.

### The Trader

| Item | State |
|---|---|
| `aidss_trader` package | does not exist |
| `trading` schema, roles, migrations | do not exist |
| Indodax connector, mock exchange | do not exist |
| Any trading table, route, or order code | does not exist |
| Documentation | exists (T0) |
| Indodax API key | none; none has been seen |
| Live response from Indodax | none captured |

Every Indodax detail in `docs/06-INTEGRATIONS/` is **documented, not yet observed**.

## Task Board

### T0 — Specification

| Task | Status | Notes |
|---|---|---|
| T0-01 Design interview and ADRs | REVIEW | ADR-001 to ADR-027 |
| T0-02 `docs/` tree (13 categories) | REVIEW | 108 files (four added after the owner approved them) |
| T0-03 `MEMORY/` and `TASKS/` | REVIEW | |
| T0-04 `CLAUDE.md`, `AGENTS.md`, catalog | REVIEW | |
| T0-05 Archive the planning document; README note | REVIEW | `git mv`; one README line |
| T0-06 Owner fills the numbers worksheet | TODO | Owner-led; every value is the owner's |

### T1 to T6

All `TODO`. See each phase file.

## Open Risks (named, not fixed)

- Position has **no stop while the Trader is down** (ADR-007).
- The trade key **cannot be IP-restricted** (ADR-013).
- No exchange sandbox exists; mock-only verification until T2-07.
- The analysis platform cannot supply AI context for crypto pairs; deferred to post-MVP (ADR-032).
- The deployment host keeps database backups on the same machine; off-host copies are manual (ADR-040).
- The host's Compose file builds from source and can revert a deployed image.
- A production server password was shared in chat on 2026-11-14 and should be rotated.

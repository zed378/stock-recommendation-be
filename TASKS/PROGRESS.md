# Progress — Single Status Board

What is shipped, what is not. Updated in the same commit as the work it reflects.

---

## Phase Status

| Phase | Name | Status | Notes |
|---|---|---|---|
| T0 | Specification | 🔎 in review (2026-11-14) | Documents written; **awaiting the owner's review**. See `MEMORY/records/2026-11-14-trader-docs-scaffolding.md`. 108 files in `docs/`, 45 ADRs, 8 open questions |
| T1 | Foundation | 🚧 built, in review (2026-11-14) | Code and 40 tests exist. **Not verified:** PostgreSQL privileges (`-m postgres`, no PostgreSQL was available), the Docker image build, and the Compose override. See `MEMORY/records/2026-11-14-t1-foundation.md` |
| T2 | Exchange connector | 🚧 built, in review (2026-11-14) | Mock-verified only. **T2-07 (live Read-only check) is owner-led and not done**; every Indodax shape is documented, not observed |
| T3 | Strategy, backtest, paper | 🚧 built, in review (2026-11-15) | Mechanism only; OQ-5 and OQ-11 values unset, tests use their own numbers. Backtest runs persist to `trading.backtest_run` (`0007_backtest_runs`) and feed the promotion `backtest` gate (`MEMORY/records/2026-11-15-j4-missing-features.md`). Per-pair parameter override schema proposed in ADR-049. AI context deferred (ADR-032) |
| T4 | Execution core | 🚧 built, in review (2026-11-14) | Risk, order manager, exits, kill switch, reconciliation exist and are tested; now wired into the run loop (mock-tested only); a fresh install starts `HALTED`. OQ-9 values unset |
| T5 | Operator surface and `APPROVAL` | 🚧 built, component-tested, live browser check pending (2026-11-15) | T5-01, 02, 03, 05, the T5-04 API and front end exist with 33 Trader Vitest + Testing Library tests (51 total frontend tests), WCAG AA contrast (`text-muted` ≥ 6.08:1 across all 7 screens), localized ID/EN ledger headers, OpenAPI response models (`trader-schema.d.ts`), OQ-12 promotion thresholds editor, origin-separated `LIVE`/`PAPER`/`BACKTEST` portfolio panels, and CSV exports (`MEMORY/records/2026-11-15-t5-04-frontend-tests-and-ui-audit.md`, `MEMORY/records/2026-11-15-j4-missing-features.md`, `MEMORY/records/2026-11-15-c-trader-ui-contrast-and-i18n-fixes.md`). T5-06 is owner-led and not started; needs OQ-12, OQ-16 |
| T6 | Hardening and release | 🚧 partial, mock-verified, owner-led steps pending (2026-11-15) | T6-01 tests + review packet, T6-02 resilience/soak tests, T6-03 restore rehearsal script (`deploy/trader/rehearse_restore.sh`), T6-04 host liveness monitor (`deploy/trader/check_liveness.py`, Acceptance A13), and T6-05 evidence-populated release checklist exist (`MEMORY/records/2026-11-15-t6-security-and-resilience-tests.md`, `MEMORY/records/2026-11-15-t6-03-04-05-liveness-and-release-prep.md`). **Owner-led:** independent review, VM restore & kill-switch drills, host cron installation, and `AUTO` readiness |

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
| `aidss_trader` package | exists: T1 foundation plus connector, market data, strategy, intents, paper, backtest, risk, orders, exits, killswitch, reconcile |
| `trading` schema, roles, migrations | three migrations; privileges unverified on PostgreSQL |
| Indodax connector, mock exchange | exist; mock is synthetic, the connector has never touched the real API |
| Order code | exists and is wired into the run loop (mock-tested only); starts `HALTED`, every owner number unset, no exchange URL configured, so it trades nothing |
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

### T1 — Foundation

| Task | Status | Notes |
|---|---|---|
| T1-01 Scaffold, `Dockerfile.trader`, Compose override | REVIEW | Image **not built** (Docker unavailable); the package runs under pytest only |
| T1-02 Guard tests | REVIEW | Import boundary, no-withdrawal, no-float, tree-not-empty. The "architecture test unmodified" check is manual (the file is untouched); no CI step yet |
| T1-03 Schema, roles, privileges, Alembic | REVIEW | Migration builds the models on SQLite. **Privileges unverified** (`tests/trader/test_privileges_postgres.py` never run) |
| T1-04 Credential store | REVIEW | Fernet, key from a file; not derived from the JWT secret (tested) |
| T1-05 Audit log | REVIEW | Hash chain detects an altered or removed row (tested). Recording the head hash outside the database is **not built** |
| T1-06 Configuration, unset means disabled | REVIEW | Risk-limit mechanism and tests. Loading operational settings from the database is **not built** |
| T1-07 Lease | REVIEW | Tested on SQLite; the real PostgreSQL behaviour is untested |
| T1-08 Token verification, `trader` role | WIP | Role added with viewer-level rights (tested). The Trader's `GET /auth/me` verification client is **not built** |

### T2 to T4

Built and in review; see `MEMORY/records/2026-11-14-t2-t4-connector-strategy-execution.md` for what is and is not verified.

### T5

Backend and a first front end built, unwired and unrendered; see `MEMORY/records/2026-11-14-t5-operator-surface-backend.md`. T5-06 (real money) is owner-led and untouched.

### T6

All `TODO`. See the phase file.

## Open Risks (named, not fixed)

- Position has **no stop while the Trader is down** (ADR-007).
- The trade key **cannot be IP-restricted** (ADR-013).
- No exchange sandbox exists; mock-only verification until T2-07.
- The analysis platform cannot supply AI context for crypto pairs; deferred to post-MVP (ADR-032).
- The deployment host keeps database backups on the same machine (`~/aidss-pre-trader-*.sql.gz`); off-host copies are manual (ADR-040).
- Host PostgreSQL port 5432 exposure, superuser password rotation, and moving the analysis API to limited role `aidss_app` (ADR-021) are scripted in `deploy/trader/isolate_analysis_role.sql` + `rollback_analysis_role.sql` and awaiting the owner's approval to execute on `10.1.200.13` (`MEMORY/records/2026-11-15-host-hardening-plan.md`).
- The host's Compose file builds from source and can revert a deployed image.
- A production server password was shared in chat on 2026-11-14 and should be rotated.

# Progress — Single Status Board

What is shipped, what is not. Updated in the same commit as the work it reflects.

---

## Phase Status

| Phase | Name | Status | Notes |
|---|---|---|---|
| T0 | Specification | 🔎 in review (2026-11-14) | Documents written; **awaiting the owner's review**. See `MEMORY/records/2026-11-14-trader-docs-scaffolding.md`. 108 files in `docs/`, 45 ADRs, 8 open questions |
| T1 | Foundation | 🚧 built, deployed HALTED on VM, in review (2026-11-15) | Code and tests exist (`515` Trader+arch+routing tests pass, no xfail; S13 is closed by a 28-package hash lock of the Trader's own dependencies, ADR-050 and ADR-053; the lock is not yet in a deployed image). Trader image built and deployed on VM (`zed378/aidss-trader:e410ab7`, `zed378/aidss-frontend:db57068`, `zed378/aidss-api:e7b3da3`), migrations `0001..0008` applied (`30` tables), lease held, authenticated `GET /auth/me` verified on VM (`MEMORY/records/2026-11-15-first-deploy.md`). `7/7` `-m postgres` privilege & index tests pass on local PostgreSQL 18; PG 16 VM clone rehearsal passed (`6/6` privilege tests, isolate `1.1s`, rollback `1.2s`, `MEMORY/records/2026-11-15-pg16-host-hardening-rehearsal.md`); VM production hardening (`aidss_app` role, port 5432 closure) awaits owner gate |
| T2 | Exchange connector | 🚧 built, in review (2026-11-14) | Mock-verified only. **T2-07 (live Read-only check) is owner-led and not done**; every Indodax shape is documented, not observed |
| T3 | Strategy, backtest, paper | 🚧 built, in review (2026-11-15) | Mechanism only; OQ-5 and OQ-11 values unset, tests use their own numbers. Backtest runs persist to `trading.backtest_run` (`0007_backtest_runs`) and feed the promotion `backtest` gate (`MEMORY/records/2026-11-15-j4-missing-features.md`). Per-pair parameter override schema proposed in ADR-049. AI context deferred (ADR-032) |
| T4 | Execution core | 🚧 built, in review (2026-11-14) | Risk, order manager, exits, kill switch, reconciliation exist and are tested; now wired into the run loop (mock-tested only); a fresh install starts `HALTED`. OQ-9 values unset |
| T5 | Operator surface and `APPROVAL` | 🚧 built, component-tested, live browser verified (`2026-11-15`) | T5-01, 02, 03, 05, the T5-04 API and front end exist with Vitest + Testing Library tests (`82` passing with `--pool=vmThreads`; `tsc` + `oxlint` 0 warnings), WCAG AA contrast (`text-muted` ≥ 6.08:1 across all 7 screens), localized ID/EN ledger headers, OpenAPI response models (`trader-schema.d.ts`), OQ-12 promotion thresholds editor, origin-separated `LIVE`/`PAPER`/`BACKTEST` portfolio panels, and CSV exports. Frontend deployed as `zed378/aidss-frontend:2fc6c0b` (`index-HvlgnJp2.js`; `flex-wrap` on `/assets/:ticker` Analysis action row, `grid-cols-1` on `/picks`, `44px` minimum tap height below `sm` on shared primitives, timeframe/horizon selectors, and Monitoring `TabStrip`). Live Playwright verification on `https://aidss.zedth.my.id` (`MEMORY/records/2026-11-15-q-production-layout-remeasure.md`) confirmed `0` overflow across all 8 routes and all 6 `/assets/BBCA` tabs (`en`/`id`) at `375px` and `320px` (including `Analisis` `id` at `320px` and `/picks` at `375px`), `Monitoring` `TabStrip` fitting `309/309px` (`46px` tabs, click + `Tab`+`Enter`), desktop `1280px` heights unchanged (`33×24`, `138×38`, `38px` tabs), and `<main>` `<44px` controls at `375px` reduced to TradingView attribution (`35×19`), native checkboxes (`13×13`), and inline ticker links (`31×20`/`35×24` on `/picks`); non-shared `<44px` controls in `Admin.tsx`, `Layout.tsx`, `Notifications.tsx`, `TranslateToggle.tsx`, and `Users.tsx` recorded as findings. T5-06 is owner-led and not started; needs OQ-12, OQ-16 | Then `zed378/aidss-frontend:db57068` (`index-BR0mddld.js`; 44px phone height on the header controls, the notification bell, the Trader bar's `All controls` link, and ticker links in lists via `tickerLinkHitArea`; the brand text hides under 368px; classes confirmed in the production chunks, sizes measured only locally at 375, 360 and 320px on a mocked API).
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
| `trading` schema, roles, migrations | eight migrations (`0001..0008`, `30` tables) applied on VM PostgreSQL; `3` `trader_rw` privilege tests passed on VM scratch DB, `7/7` `-m postgres` tests passed on local PostgreSQL 18; `aidss_app` isolation on VM awaits owner gate |
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
| T1-01 Scaffold, `Dockerfile.trader`, Compose override | REVIEW | Image built from `git archive HEAD` and deployed on VM (`zed378/aidss-trader:813d9cd`, then `e410ab7`) with Compose stdin override; starts `HALTED` (`2026-11-15-first-deploy.md`) |
| T1-02 Guard tests | REVIEW | Import boundary, no-withdrawal, no-float, tree-not-empty. The "architecture test unmodified" check is manual (the file is untouched); no CI step yet |
| T1-03 Schema, roles, privileges, Alembic | REVIEW | Migrations `0001..0008` applied on VM PostgreSQL as `trader_owner` (`30` tables); `3/3` `trader_rw` privilege tests passed on VM scratch DB (`2026-11-15-first-deploy.md`) and `7/7` `-m postgres` tests passed on local PostgreSQL 18 (`2026-11-15-d2-d3-d4-postgres-rehearsal-and-checklist.md`). `aidss_app` isolation on VM awaits owner gate |
| T1-04 Credential store | REVIEW | Fernet, key from a file (`~/.aidss-trader-master.key`, `0600`); not derived from the JWT secret (tested) |
| T1-05 Audit log | REVIEW | Hash chain detects an altered or removed row (tested). Recording the head hash outside the database is **not built** |
| T1-06 Configuration, unset means disabled | REVIEW | Risk-limit mechanism and tests. Loading operational settings from the database is built (`runtime/settings_store.py`) and tested on SQLite |
| T1-07 Lease | REVIEW | Tested on SQLite and observed held in VM PostgreSQL (`trading.lease`, `healthcheck` exit 0 in `2026-11-15-first-deploy.md`) |
| T1-08 Token verification, `trader` role | REVIEW | `trader` role added (`viewer`-level platform rights) and `admin` holds all trader permissions (ADR-048); `TokenVerifier` (`GET /auth/me`) built and proved by one authenticated 200 call in VM Trader logs (`2026-11-15-first-deploy.md`) |

### T2 to T4

Built and in review; see `MEMORY/records/2026-11-14-t2-t4-connector-strategy-execution.md` for what is and is not verified.

### T5

API and front end built, deployed on VM (`zed378/aidss-frontend:e410ab7`), and covered by 33 Trader Vitest tests (`51` total frontend tests, WCAG AA contrast + ID/EN ledger headers fixed in `1a07d95`). Live browser click-through on `https://aidss.zedth.my.id` was blocked locally (`DevToolsActivePort` missing). T5-06 (real money) is owner-led and untouched.

### T6

Partial: T6-01/T6-02 mock tests, T6-03 restore script (`3s` local PostgreSQL 18 rehearsal), T6-04 liveness script (`check_liveness.py`, awaiting VM cron approval), T6-05 release checklist (`05-RELEASE-CHECKLIST.md`), `P5` PostgreSQL 18 `EXPLAIN (ANALYZE, BUFFERS)` index verification, and the host-hardening rehearsal on the VM's PostgreSQL 16 (clone of `aidss`: isolate 1.1 s, rollback 1.2 s database side, 6/6 privilege tests; production steps not run) are done; `R5` (ADR-052), VM host hardening, and owner-led drills remain open. See `TASKS/PHASE-T6-HARDENING-AND-RELEASE.md`.

## Open Risks (named, not fixed)

- Position has **no stop while the Trader is down** (ADR-007).
- The trade key **cannot be IP-restricted** (ADR-013).
- No exchange sandbox exists; mock-only verification until T2-07.
- The analysis platform cannot supply AI context for crypto pairs; deferred to post-MVP (ADR-032).
- The deployment host keeps database backups on the same machine (`~/aidss-pre-trader-*.sql.gz`); off-host copies are manual (ADR-040).
- Host PostgreSQL port 5432 exposure, superuser password rotation, and moving the analysis API to limited role `aidss_app` (ADR-021) are scripted in `deploy/trader/isolate_analysis_role.sql` + `rollback_analysis_role.sql` and awaiting the owner's approval to execute on `10.1.200.13` (`MEMORY/records/2026-11-15-host-hardening-plan.md`).
- The host's Compose file builds from source and can revert a deployed image.
- A production server password was shared in chat on 2026-11-14 and should be rotated.

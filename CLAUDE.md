# CLAUDE.md — Operating Instructions for AI Agents

Operating instructions for this repository. Role definitions are in [`AGENTS.md`](AGENTS.md); read that
before claiming a role. Language of all project documents: English (ADR-017).

---

## Read This First

This repository holds **two systems at two different maturity levels**:

| System | State | Where |
|---|---|---|
| **AIDSS analysis platform** | Built and running. FastAPI + PostgreSQL + React. Decision support only: no order, no broker, no execution, enforced by tests. | `src/aidss/`, `frontend/`, `alembic/`, `tests/` |
| **AIDSS Trader** (Indodax crypto auto-trading) | **Phases T1 to T5 built, T6 partial; deployed `HALTED` on the VM (`zed378/aidss-trader:9b52dfa`, migrations `0001..0008`).** `aidss_trader` has the foundation, Indodax connector, strategy, paper/backtest, Risk Engine, order manager, exit monitor, kill switch, reconciler, and `/trader/v1` + `frontend/src/trader/` operator surface, verified against a synthetic mock and SQLite (plus local PostgreSQL 18 privilege/index/restore rehearsals). **Never run against a real exchange; the VM instance starts `HALTED` with no exchange URL, no keys, and every owner number unset, so it trades nothing until the owner acts.** | `src/aidss_trader/`, `frontend/src/trader/`, `docs/`, `MEMORY/`, `TASKS/` |

If this file and `TASKS/PROGRESS.md` disagree about what exists, trust `PROGRESS.md` and fix this file. A
stale instruction document produces confidently wrong work.

**Do not describe the Trader as able to trade.** It has a connector and an order path, but it has never touched
a real exchange, starts `HALTED`, and has no owner-set number, so nothing has traded and nothing may be claimed
about live behaviour. Work follows the active phase in `TASKS/PROGRESS.md`.

## What the Trader Is

An autonomous spot-trading service for **IDR pairs on Indodax**, using **Trade API 2.0 only**
(ADR-002). Swing horizon, 4H and 1D candles (ADR-012). Deterministic strategies decide; AI and Kronos-base
(CPU) are context and veto only (ADR-004). It runs in three modes per strategy: `PAPER`, `APPROVAL`,
`AUTO` (ADR-003). It lives in a **separate service, package, container, schema, and PostgreSQL role** from the
analysis platform (ADR-001, ADR-021).

Everything decided so far is in `MEMORY/DECISIONS.md`. Everything undecided is in `TASKS/BACKLOG.md`.

## Before You Start

1. Read `trader-document-catalog.md` (the index of what documents exist and why).
2. Read `TASKS/PROGRESS.md`: which phase is active, what is done.
3. Read `TASKS/00-TASK-CONVENTIONS.md`: task IDs, statuses, the Definition of Done.
4. Read `MEMORY/DECISIONS.md` before assuming any architecture choice is open.
5. Read `TASKS/BACKLOG.md`: your question may already be an open one, and some numbers (limits,
   thresholds, intervals) are deliberately **not set**.
6. For Indodax behavior, read `docs/06-INTEGRATIONS/03` to `11`. Do not trust memory or other exchanges'
   conventions.

## The Non-Negotiables

### No withdrawal code, ever (ADR-013)

The Trader's key is Read plus Trade. No withdrawal, deposit-address, or fiat client is written, not even
disabled. The Trader refuses to start if the account reports `canWithdraw` or `canWithdrawFiat` as true.

### Deterministic rules decide; AI never touches an order (ADR-004)

AI and Kronos output may be attached to an intent and may veto an entry. It never creates, sizes, prices,
or modifies an order. Model text never reaches the order path.

### Every order passes the Risk Engine (ADR-009)

There is no code path from a strategy, the approval queue, or the UI to the exchange that skips the Risk
Engine. A new path is a bug, not a feature.

### Fail closed

Uncertainty means `HALT`, not trade: stale data, a reconciliation difference, an `UNKNOWN` order, a clock
skew beyond `recvWindow`, an unreadable credential. Never "continue and log a warning".

### The exchange is the source of truth (ADR-022)

Balances, orders, and fills come from Indodax. A difference is an alert and a halt, never a silent
correction.

### Orders are idempotent; never blind-retry (ADR-024)

After a timeout, query by `clientOrderId` first. Do not re-send a create.

### Money is `Decimal` (ADR-025)

No `float` in prices, quantities, balances, fees, or PnL.

### No fabricated data

Paper fills and backtest results are labelled as such everywhere they appear and are never shown as real
trades. A widget that looks live but is not from the exchange is the most damaging bug this system can
ship.

### No live exchange calls from agents or tests

Tests use the recorded fixtures and the mock server (`docs/11-TESTING-QUALITY/07-FIXTURES-AND-MOCK-SERVERS.md`).
An agent never sends a signed request to the production Indodax API without the owner's explicit,
per-action instruction, and never with a key that has Trade permission unless that instruction says so.

### Secrets are never literal

No API key, secret, token, or signature in source, docs, logs, fixtures, or commit messages. Indodax's own
documentation contains sample keys and secrets; do not copy them into this repository, even as
placeholders.

### The analysis platform's guarantee stays intact (ADR-001)

`tests/test_architecture_constraints.py` is not edited to make room for trading. Trading code lives
outside `src/aidss`.

## The Traps

| Trap | Consequence |
|---|---|
| Deriving the Trader's encryption key from `AIDSS_JWT_SECRET` the way `aidss.security.secrets` does | A DB dump plus the analysis API's JWT secret recovers the exchange key (ADR-014 requires a separate master key) |
| Assuming a stop-loss exists on the exchange | `STOP_LIMIT` is rejected (`stop_limit_not_available`). Stops are bot-side (ADR-007); with the bot down there is no stop |
| Treating an accepted create-order response as a fill or even as visible | Accepted only means accepted; the order "may not be immediately available" via `GET /api/v2/order` |
| Reading order status from WebSocket examples | The Private WebSocket example uses `FILL`; REST uses `FILLED` and `PARTIALLY_FILLED`. See `11-INDODAX-DOCS-DISCREPANCIES.md` |
| Mixing the two Indodax APIs | TAPI 2.0 uses `X-APIKEY` and HMAC-SHA256; legacy uses `Key` and HMAC-SHA512. The Deadman Switch and Private WebSocket token are legacy-only |
| Using `orderId` interchangeably | `GET/DELETE /api/v2/order` use the numeric id; `myTrades` filters by the full id such as `btcidr-limit-123` |
| Querying history beyond 7 days | `order/histories` and `myTrades` cap the range at 7 days |
| Assuming 24/7 means "no gaps" | The market is continuous, but a pair can be suspended (`-1016`) or in maintenance; the daily candle boundary and time zone are unverified (OQ-4) |
| Sizing a position without the pair's minimums | `trade_min_base_currency` and `trade_min_traded_currency` differ per pair; below them the order is rejected |
| Editing `tests/test_architecture_constraints.py` to allow an order table | Violates ADR-001. Put trading code in its own package and schema |
| Resetting or dropping the database to fix a schema problem | Never. Additive Alembic migrations only; the ledger is append-only |
| Presenting a promotion as done without the gates | ADR-020: no strategy leaves `PAPER` until the owner has set the thresholds (OQ-12) and the evidence exists |
| Deploying one service with `docker compose ... up -d --no-build <service>` on the VM without `--no-deps` | Compose also recreates its dependencies when their image tag moved locally: on 2026-11-17 `up frontend` recreated PostgreSQL (the `pgvector/pgvector:pg16` tag pointed at a newer image than the running container) and about 2 minutes of database outage followed. Always add `--no-deps`, run `docker ps` first, and never put `pull` and `up` in one SSH command that both read the override from stdin |

## Workflow

1. Pick the lowest-numbered `TODO` task in the active phase whose dependencies are `DONE`.
2. Read every document in the task's `Spec refs`.
3. If `Spec required: yes`, write the feature spec from `MEMORY/templates/FEATURE-SPEC-TEMPLATE.md` first.
4. Implement, satisfying the task's DoD plus the global DoD in `TASKS/00-TASK-CONVENTIONS.md`.
5. Write the `MEMORY/records/` entry, index it, update `TASKS/PROGRESS.md`, all in the same commit as the
   code.

Documentation-only work follows the same record rule.

## Commands

All verified against `README.md` and `pyproject.toml`. Run from the repository root.
Windows paths shown (`.venv/Scripts/python`); on Linux and macOS use `.venv/bin/python`.

### Analysis platform

| Command | Description |
|---|---|
| `python -m venv .venv` then `.venv/Scripts/python -m pip install -e ".[dev]"` | Install with test and lint tools |
| `.venv/Scripts/python -m pip install -e ".[kronos]"` | Optional: Kronos-base dependencies. Install a CPU build of torch first (`pip install torch --index-url https://download.pytorch.org/whl/cpu`) |
| `docker compose up -d postgres` | PostgreSQL 16 with pgvector |
| `python -m alembic upgrade head` | Apply migrations (needs `AIDSS_DATABASE_URL`) |
| `python -m uvicorn aidss.main:app --reload` | API at `http://127.0.0.1:8000/docs` |
| `python -m aidss.jobs` | Worker and scheduler, a separate process on purpose |
| `docker compose up --build` | The whole stack |
| `python -m pytest` | Hermetic suite on SQLite. Excludes `network` and `postgres` markers by default |
| `python -m pytest -m postgres` | Dialect behaviour that needs a real PostgreSQL |
| `python -m pytest -m network` | Live-endpoint checks; deselected by default |
| `ruff check src tests` | Lint (line length 100; rules E, F, I, UP, B) |

### Frontend (`frontend/`)

| Command | Description |
|---|---|
| `npm run dev` | Vite dev server |
| `npm run build` | `tsc -b && vite build` |
| `npm run lint` | oxlint |
| `npm run typecheck` | `tsc -b --noEmit` |
| `npm run api:types` | Regenerate `src/api/schema.d.ts` from the running API on port 7153 |
| `python -m aidss_trader.api.openapi frontend/.trader-openapi.json`, then `npx openapi-typescript .trader-openapi.json -o src/api/trader-schema.d.ts` (in `frontend/`) | Regenerate the Trader API types; delete the JSON afterwards |

### Trader

Historical PostgreSQL verification: `7 passed` on local PostgreSQL 18 and `6 passed` on a VM PostgreSQL 16 clone (2026-11-15). Current image references in the 2026-11-17 handoff are Trader `9b52dfa`, frontend `latest` (= `603e606`) and API `latest` (= `93a1151`); Trader remains `HALTED`. These are recorded deployment facts, not a fresh host check. Local verification is recorded below and in the stage-11 handoff.

| Command | Description |
|---|---|
| `python -m pytest tests/trader tests/test_architecture_constraints.py` | Trader + architecture tests (`-m postgres` opt-in; 7/7 passed on local PostgreSQL 18, and 3/3 `trader_rw` tests passed on a VM scratch DB on 2026-11-15) |
| `python -m aidss_trader generate-master-key --out <path>` | Write a new random master key file; refuses to overwrite |
| `python -m aidss_trader run` | Run loop + `/trader/v1` API; starts `HALTED` on fresh install (ADR-047). Needs `AIDSS_TRADER_DATABASE_URL` |
| `python -m aidss_trader healthcheck` | Exit 0 if a recent heartbeat exists |
| `alembic -c alembic_trader.ini upgrade head` | Migrations as `trader_owner` (`AIDSS_TRADER_MIGRATION_DATABASE_URL`); applied through `0008_indexes_idempotency` on VM PostgreSQL (2026-11-15) |

The connector, strategy, paper, backtest, risk, order manager, exit monitor, kill switch, and reconciler (T2 to T4), plus the T5 backend (approvals, step-up, notifier, promotion, export, `/trader/v1` API) and operator UI (`frontend/src/trader/`, `frontend/src/pages/Trader*.tsx`), are wired into `aidss_trader run` and deployed `HALTED` on the VM (`zed378/aidss-trader:9b52dfa`, `zed378/aidss-frontend:latest` (= `603e606`), `zed378/aidss-api:latest` (= `93a1151`)). Every owner number is unset and the Compose file passes no exchange URL, so the deployed image trades nothing. The PAPER lifecycle is built (mock-tested) and does nothing until the owner sets the paper cost model. The `admin` role holds every trader permission (ADR-048). No real Indodax call has been made (`T2-07` is owner-led; `python -m aidss_trader live-check` is prepared). Live Playwright browser inspection on `https://aidss.zedth.my.id` (`75bc905`) passed direct `goto`/`reload` on all 7 `/trader` routes, collapsible sidebar persistence, landing page (`/`), security headers, and simulated `502` outage.

## Code Style

Python: ruff (`pyproject.toml`), line length 100, type hints, `from __future__ import annotations`.
Comments explain **why**, not what. The existing code sets the tone: a docstring that states a trade-off
plainly is the house style. Money is `Decimal`. For UI, copy, and comment work the user's global
`antislop` skills apply.

## What Is Currently Failing

The stage-11 prompt reports a pre-change baseline of **525 Trader + architecture + routing tests**, plus **100 frontend Vitest tests**. These replace the stale 515/93 counts but are handoff claims until independently rerun; see the stage-11 record for actual local results. Historical PostgreSQL results remain **7 passed** on local PostgreSQL 18 and **6 passed** on the VM PostgreSQL 16 clone. Frontend tests use `--pool=vmThreads` on this machine's Node 26. S13 is closed by the Trader's own 28-package hash lock (ADR-050/053), included in the Trader image since `7d03693` (now `9b52dfa`).

No known failing test as of 2026-11-18: `test_translation_covers_every_prose_field` was fixed by classifying the 24 agent prose fields (`notable_posts` is deliberately not translated, being verbatim quotes).

Host hardening was applied on 2026-11-16/17 (`MEMORY/records/2026-11-16-host-backup-pg-dumpall.md`, steps 1 to 7): api and worker use `aidss_app`, the superuser password was rotated, 5432/7153 are unpublished, and frontend 5173 is loopback-only for host cloudflared. The host Compose file uses images instead of source builds and refuses missing application database/JWT variables. The JWT secret remains in `~/stocks/.env` (`infra:infra 600`); changing it makes stored provider keys unreadable.

The migration kit in `deploy/production/` and `docs/10-OPERATIONS/09-MIGRATION-RUNBOOK.md` is prepared. Its production Compose configuration was compared on the host with the running five-service stack with zero differences (record `2026-11-17-migration-kit.md`). This is preparation, not a completed move.

ADR-054's hourly audit anchor wrapper (`deploy/trader/aidss-anchor.sh`) was installed on the host on 2026-11-17. Two manual runs and verify-only passed; cron's first scheduled invocation and failure alerting were not observed in the installation record. Preserve the append-only anchor file on migration. Starter profiles and `deploy/trader/import_owner_profile.py` exist under ADR-055 (`proposed`): dry run by default, owner-accepted profile required for apply, no resume or promotion. They are proposals, never runtime defaults. `.gitattributes` keeps shell/cron files LF; preserve this when editing on Windows.

Remaining deployment risks: the inventory reports no host firewall, and no real off-host backup is recorded. Stage 11 supplies a local encrypted-copy tool and an unapplied firewall plan (`docs/10-OPERATIONS/08-HOST-FIREWALL-PLAN.md`); neither means a host action has occurred. Liveness/failure notifications and owner-led live gates remain pending.

## If You Are Unsure

Check `TASKS/BACKLOG.md` first. If it is genuinely new and touches money, credentials, or an irreversible
action, **stop and ask the owner**. If a safe, reversible default exists and nothing irreversible is being
built, record it as a `proposed` ADR in `MEMORY/DECISIONS.md` and continue. A number that would limit
losses (a risk limit, a threshold, an interval) is never defaulted silently: record it as an open
question.

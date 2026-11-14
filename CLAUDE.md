# CLAUDE.md — Operating Instructions for AI Agents

Operating instructions for this repository. Role definitions are in [`AGENTS.md`](AGENTS.md); read that
before claiming a role. Language of all project documents: English (ADR-017).

---

## Read This First

This repository holds **two systems at two different maturity levels**:

| System | State | Where |
|---|---|---|
| **AIDSS analysis platform** | Built and running. FastAPI + PostgreSQL + React. Decision support only: no order, no broker, no execution, enforced by tests. | `src/aidss/`, `frontend/`, `alembic/`, `tests/` |
| **AIDSS Trader** (Indodax crypto auto-trading) | **Phases T1 to T4 built, in review.** `aidss_trader` has the foundation plus an Indodax connector, strategy, paper and backtest, Risk Engine, order manager, exit monitor, kill switch, and reconciler, all verified against a synthetic mock only and not wired into the run loop. **It cannot trade yet.** | `src/aidss_trader/`, `docs/`, `MEMORY/`, `TASKS/` |

If this file and `TASKS/PROGRESS.md` disagree about what exists, trust `PROGRESS.md` and fix this file. A
stale instruction document produces confidently wrong work.

**Do not describe the Trader as able to trade.** It cannot: it has no connector and no order path. Work follows
the active phase in `TASKS/PROGRESS.md`.

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

Verified on 2026-11-14 (hermetic, SQLite; no exchange and no PostgreSQL needed):

| Command | Description |
|---|---|
| `python -m pytest tests/trader` | Trader tests (PostgreSQL privilege tests are `-m postgres`, opt-in, **not yet run**) |
| `python -m aidss_trader generate-master-key --out <path>` | Write a new random master key file; refuses to overwrite |
| `python -m aidss_trader run` | The T1 loop: lease and heartbeat only, always `DISABLED`. Needs `AIDSS_TRADER_DATABASE_URL` |
| `python -m aidss_trader healthcheck` | Exit 0 if a recent heartbeat exists |
| `alembic -c alembic_trader.ini upgrade head` | Migrations as `trader_owner` (`AIDSS_TRADER_MIGRATION_DATABASE_URL`); **not yet run against PostgreSQL** |

The connector, strategy, paper, backtest, risk, order manager, exit monitor, kill switch, and reconciler exist (T2 to T4, mock-verified only), plus the T5 backend (approvals, step-up, notifier, promotion, export, `/trader/v1` API) and a first front end under `frontend/src/trader` (never rendered in a browser), but are **not wired into the run loop**; `aidss_trader run` still never trades. No real Indodax call has been made (T2-07 is owner-led).

## Code Style

Python: ruff (`pyproject.toml`), line length 100, type hints, `from __future__ import annotations`.
Comments explain **why**, not what. The existing code sets the tone: a docstring that states a trade-off
plainly is the house style. Money is `Decimal`. For UI, copy, and comment work the user's global
`antislop` skills apply.

## What Is Currently Failing

Last full run on 2026-11-14 (after T4, with the known failure below deselected): 1,979 passed.

- `tests/test_output_language.py::test_translation_covers_every_prose_field`: the TradingAgents agents' prose
  fields (`thesis`, `key_arguments`, and others) are neither translated nor excluded. Pre-existing, not
  related to the Trader.

Open risks of the deployment (not code): `docker-compose.yml` on the server builds from source, so an
`up --build` there reverts a deployed image; PostgreSQL backups and the server are the same host.

## If You Are Unsure

Check `TASKS/BACKLOG.md` first. If it is genuinely new and touches money, credentials, or an irreversible
action, **stop and ask the owner**. If a safe, reversible default exists and nothing irreversible is being
built, record it as a `proposed` ADR in `MEMORY/DECISIONS.md` and continue. A number that would limit
losses (a risk limit, a threshold, an interval) is never defaulted silently: record it as an open
question.

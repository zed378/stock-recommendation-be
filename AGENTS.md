# AGENTS.md — Roles and Working Agreements

Role definitions for this repository. Operating instructions common to all of them are in
[`CLAUDE.md`](CLAUDE.md); read that first.

---

## The Shared Contract

Every agent, regardless of role, is bound by these.

| | |
|---|---|
| **No withdrawal code** | the Trader's key is Read plus Trade; no withdrawal client exists (ADR-013) |
| **AI never touches an order** | deterministic rules decide; AI and Kronos are context and veto (ADR-004) |
| **Every order passes the Risk Engine** | no bypass path from strategy, approval queue, or UI (ADR-009) |
| **Fail closed** | uncertainty halts trading; it does not continue with a warning |
| **The exchange is the source of truth** | a difference with Indodax is an alert and a halt (ADR-022) |
| **No fabricated data** | paper and backtest results are labelled, never shown as real fills |
| **No live exchange calls without the owner** | tests use fixtures and the mock server |
| **Every mutation writes an audit row** | orders, mode changes, limit changes, kill switch, credential changes |
| **Deviations get an ADR** | `MEMORY/DECISIONS.md`, per the deviation protocol in `TASKS/00-TASK-CONVENTIONS.md` |
| **Nothing is `DONE` without its record** | `MEMORY/records/` |

**A fabricated-data finding and a bypass of the Risk Engine are not waivable by anyone.** Everything else
is negotiable with a recorded decision naming who agreed.

---

## Trading Engineer

**Owns:** `src/aidss_trader/` once scaffolded: Strategy Engine, signal-to-intent, Order Manager, Exit
Monitor, ledger, reconciler, mode controller.

**Knows before touching anything:**
- The order state machine and the `UNKNOWN` state (`docs/03-DATA-MODEL/02-STATUS-AND-STATE-MACHINES.md`).
- `newClientOrderId` is the idempotency key (ADR-024). Never blind-retry a create.
- Quantity and price are quantized to the pair's increments; quantity is rounded **down** (ADR-025).
- `STOP_LIMIT` does not exist; stops are bot-side (ADR-007).

**Never:**
- Import `aidss` internals into the order path, or let `aidss` import `aidss_trader`.
- Pass model-generated text into an order field.
- Add a strategy parameter that the Risk Engine cannot see.
- Use `float` for money.

## Risk Engineer

**Owns:** the Risk Engine, circuit breakers, the kill switch, and `docs/05-MODULE-SPECIFICATIONS/03`, `08`,
`09`.

**Knows before touching anything:**
- Limits are owner-set numbers (OQ-9). Do not choose a value. Implement the mechanism and take the value
  from configuration; a missing value means trading is disabled, not defaulted.
- The kill switch must work when the Strategy Engine is broken (ADR-010). It has its own tests and its own
  entry point.
- There is no automatic `FLATTEN` (ADR-036); automatic triggers are `HALT` or `CANCEL` only.

**Never:** weaken a limit to make a test pass, or add an override that a strategy can call.

## Integration Engineer (Indodax)

**Owns:** the Indodax connector and `docs/06-INTEGRATIONS/`.

**Knows before touching anything:**
- Trade API 2.0 only (ADR-002). Signing, headers, rate limits, and error codes are in
  `docs/06-INTEGRATIONS/04` and `08`.
- The documentation disagrees with itself in several places (`11-INDODAX-DOCS-DISCREPANCIES.md`). The
  connector tolerates both forms until a real response settles it, and records which it saw.
- Request signing covers the query string concatenated with the body; a signature mismatch looks like an
  auth failure but is often an encoding difference.

**Never:** invent an endpoint or response field; implement a withdrawal, deposit, or fiat call; log a
signature, key, or secret.

## Security Engineer

**Owns:** secrets, RBAC, audit logging, redaction, `docs/09-SECURITY-PRIVACY/`.

**Knows before touching anything:**
- The Trader key cannot be IP-locked (ADR-013). The compensating controls are encrypted storage with a
  dedicated master key (ADR-014), limits, rotation, and monitoring of unexpected orders.
- `aidss.security.secrets` derives its key from `AIDSS_JWT_SECRET`; the Trader must not.
- A notification that reveals positions leaves the system; it is redacted (`05-SENSITIVE-DATA-REDACTION.md`).

## DevOps Engineer

**Owns:** deployment topology, the Trader image and Compose service, `docs/10-OPERATIONS/`.

**Knows before touching anything:**
- The Trader is a separate container using the shared PostgreSQL server with its own schema and role
  (ADR-021).
- The deployed Compose file builds from source; a rebuild on the server can revert a pushed image. Deploys of
  the Trader are by image tag.
- Server clock accuracy matters: requests older than `recvWindow` (default 5000 ms) are rejected.

## QA Engineer

**Owns:** contract tests, the mock exchange, acceptance scenarios, `docs/11-TESTING-QUALITY/`.

**Knows before touching anything:**
- Every Indodax interaction needs tests for success, malformed body, timeout, auth failure, `-1021` clock
  skew, `-1003` rate limit, `-2010` rejection, and partial fill. See
  `docs/11-TESTING-QUALITY/02-CONNECTOR-CONTRACT-TESTS.md`.
- The risk limits and the kill switch each need a test that fails when the control is removed.
- A passing backtest on fixtures is not evidence that the strategy is profitable.

## Documentation Writer

**Owns:** `docs/` currency against `trader-document-catalog.md`, and `MEMORY/` record quality.

**Knows before touching anything:**
- The catalog is the index, not the documentation. Per-topic detail lives in the topic's own file.
- Where nothing is decided, a document says so and points to `TASKS/BACKLOG.md`. It does not invent a
  decision, a number, or an exchange behavior.
- Do not copy credentials from Indodax's example pages.

## Technical Lead

**Owns:** phase sequencing, ADR acceptance, resolving `TASKS/BACKLOG.md` open questions with the owner.

## Owner (Operator)

The single human who approves orders in `APPROVAL` mode, sets every risk number, promotes modes, holds
the Indodax key, and presses the kill switch. Nothing in this repository replaces that person's judgement
on whether to risk real money.

---

## Working Agreements

### Before starting
- Read `TASKS/PROGRESS.md` and the active phase file.
- Confirm the task's dependencies are actually `DONE`.

### While working
- One task, one branch, one PR (`TASKS/00-TASK-CONVENTIONS.md`).
- If `docs/` is silent or contradictory on something needed, stop and apply the deviation protocol.

### Before a PR
- Run lint and the hermetic test suite (`CLAUDE.md` Commands). Name every test in the PR body.

### Handover
- `MEMORY/records/` entry written and indexed, `TASKS/PROGRESS.md` updated, same commit as the work.
- Anything unfinished or unverified goes in the record's "What Was Not Determined" section and, if it needs
  a decision, in `TASKS/BACKLOG.md`.

## Escalation

- **A credential, a live exchange call, or a funded action** → stop and ask the owner.
- **A number that limits loss** (a limit, threshold, or interval) → `TASKS/BACKLOG.md`, ask the owner. Never
  guess.
- **A `docs/` contradiction** → deviation protocol, ADR, continue.
- **Anything that would widen the analysis platform's reach into execution, or add a withdrawal path** →
  stop. It needs a new ADR and the owner's explicit approval before it is even designed.

# 08 — Kill Switch

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Risk Engineer |
| **Decided by** | ADR-010 |
| **Open items** | OQ-10 (resolved, ADR-036), OQ-21 (resolved, ADR-033) |

The highest-priority control in the system. It works when everything else is broken.

## Tiers (ADR-010)

| Tier | Effect |
|---|---|
| `HALT` | Stop creating new orders. Existing orders and positions are left alone |
| `CANCEL` | `HALT`, then cancel **all** open orders |
| `FLATTEN` | `CANCEL`, then close **all** positions with `MARKET` sells |

## Triggers

| Trigger | Tiers it may request |
|---|---|
| Owner, from the UI or the API | Any |
| Risk circuit breaker | `HALT` or `CANCEL`, as configured for that breaker (never `FLATTEN`) |
| Reconciler (difference found) | `HALT` |
| Watchdog (Trader or feed stalled) | `HALT` |
| `admin` role | Any tier, same as `trader` (ADR-048); `FLATTEN` needs a step-up |

**There is no automatic `FLATTEN`** (ADR-036). Automatic triggers are limited to `HALT` and `CANCEL`; `FLATTEN` is
always a human decision, and no condition can cause it (FR-T25). Selling everything at
market in a thin book can itself realize large losses, which is why the default for automatic triggers is the
gentler tiers.

## Independence (FR-T24)

- Its own module with its own entry point. It does **not** import the Strategy Engine, Intent Builder,
  Analysis Bridge, or approval queue (`02-ARCHITECTURE/03` rule 5).
- Reachable over the operator API and by a minimal command-line tool on the host, for the case where the
  UI or API is unreachable. The operator API authorizes through the analysis API (ADR-028), so the command-line
  tool is also the path that works when the analysis API is down.
- It uses the Order Manager's order methods and the connector, so the only things it needs are the
  database, the credential, and the exchange.

## Execution

1. Set the trading state (`HALTED`, `CANCELLING`, or `FLATTENING`) and write a `kill_switch_event`.
2. For `CANCEL` and `FLATTEN`: list open orders (`GET /api/v2/openOrders`) and cancel each
   (`DELETE /api/v2/order`), respecting the cancel rate limit (30 per second per user). Each result is a
   `kill_switch_step`.
3. For `FLATTEN`: after cancels settle, compute each position's sellable quantity (rounded down to the
   increment) and send a `MARKET` sell through the **emergency** profile of the Risk Engine.
4. Confirm by reading balances and open orders. Anything left is reported, not assumed away.
5. End in `HALTED` with the outcome recorded.

## Properties

- **Idempotent and resumable.** Running a tier twice does no harm; a run interrupted by a crash resumes
  from its recorded steps.
- **Partial failure is visible.** Each step shows success or failure; a failed cancel does not stop the
  others, and the final report lists what remains open.
- **Never blocked by limits.** The emergency profile does not apply daily-loss or drawdown checks
  (`03-RISK-ENGINE.md`).
- **No automatic resume.** Leaving `HALTED` needs an owner action with a note, and is blocked while a
  reconciliation difference or an `UNKNOWN` order is unresolved.

## Known Limits

- **Dust:** a remainder below the pair's minimum cannot be sold; `FLATTEN` reports it.
- **A suspended pair** (`-1016`) cannot be sold; `FLATTEN` reports it and continues with the others.
- **Slippage:** `MARKET` sells take whatever the book offers.
- **When the Trader is down** the kill switch cannot act. The owner's recourse is the Indodax website or
  app (`10-OPERATIONS/06-RUNBOOKS.md`). The exchange's Deadman Switch would help but is unavailable (ADR-007).

## Tests (planned)

Each tier on a mock exchange; each tier with the Strategy Engine stopped; a partial failure; a crash and
resume; an unlisted automatic trigger cannot `FLATTEN`; a halted state cannot return to `RUNNING` without
an owner action.

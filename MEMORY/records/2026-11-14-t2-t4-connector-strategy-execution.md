# T2 to T4 — Connector, strategy and paper, execution core (built, in review)

**Date:** 2026-11-14
**Task:** T2-01 to T2-06, T3-01 to T3-04, T4 core (risk, order manager, exits, kill switch, reconciliation)
**Author:** Claude (AI agent), working with the project owner
**Spec refs:** `docs/06-INTEGRATIONS/03` to `11`; `docs/05-MODULE-SPECIFICATIONS/`; ADR-002 to 012, 022 to 027, 035, 036, 041, 042

---

## Hook

Every module exists and is tested, **against a synthetic mock only**. Nothing has touched the real Indodax
API, no key was used, and no PostgreSQL ran. Nothing here can trade: the pieces are not wired into the run
loop, which is still the T1 loop (lease and heartbeat, always `DISABLED`).

---

## What Changed

| Area | Detail |
|---|---|
| Connector | `IndodaxClient` with an allowlist of methods, HMAC-SHA256 signing, clock guard, throttle, error classes, writes never retried. No withdrawal, deposit, or fiat method |
| Market data | Idempotent candle ingest, gap detection, pair rules (minimums, increments, blocked pairs) |
| Strategy | Decimal EMA, ATR, ADX; `EmaAdxStrategy` with **no default parameters** |
| Intents | Pure identity and `clientOrderId`; sizing from the stop, rounded down; an unset limit refuses the intent |
| Paper / backtest | Fills only if price trades strictly through; costs and slippage are required inputs; no look-ahead (spy test); results carry `origin` |
| Risk Engine | ENTRY (all checks) and EMERGENCY (malformed-order checks only) profiles; every check persisted; breakers only HALT or CANCEL |
| Order manager | Risk first, write-ahead commit before send, UNKNOWN resolved by query and never re-sent, MARKET only for stop or flatten |
| Exit monitor | One price call per cycle, one exit per position, stop never widened, stale price means unprotected, watchdog |
| Kill switch | HALT, CANCEL, FLATTEN; FLATTEN owner-only; independent import graph (tested); resume blocked by UNKNOWN orders and open differences |
| Reconciliation | Open orders, trades, permission flags, 7-day windows; any difference or failed read halts, nothing is corrected silently |

## Decisions Made While Building

- A backtest same-candle stop exits at the worse of the open and the stop (gap-aware); the first version
  exited at the stop price after a crash, which was optimistic. Found by a test.
- A paper limit buy fills at its limit price even if the candle gapped below it. That is the conservative
  side for a buyer.
- An UNKNOWN order never found after the configured queries stays UNKNOWN and is a HALT condition.

## Not Done, Not Verified

- **Nothing observed live.** T2-07 (owner-led, Read-only key) is untouched; every Indodax shape is from
  documentation.
- The run loop does not call the strategy, risk, order manager, exit monitor, or reconciler yet.
- Daily-loss and drawdown inputs to `RiskContext` have no producer; ledger persistence from fills is partial
  (`ingest_fills` stores trades, no `LedgerEntry` rows are written yet).
- No approval queue, no UI, no Telegram (T5). AI context is post-MVP (ADR-032).
- All owner numbers (OQ-5, 8, 9, 11, 12, 16) are still unset. Tests use values declared inside the tests.
- PostgreSQL privileges and the Docker image remain unverified (see the T1 record).

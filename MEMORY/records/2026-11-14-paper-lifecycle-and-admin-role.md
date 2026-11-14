# PAPER lifecycle and the admin role (built, mock-tested only)

**Date:** 2026-11-14
**Task:** T3 completion (paper), ADR-048
**Author:** Claude (AI agent), working with the project owner
**Spec refs:** `docs/05-MODULE-SPECIFICATIONS/06`, `11`; ADR-003, 020, 046, 048

---

## Hook

A strategy in `PAPER` mode now has a simulated book: entries fill (or not) on the next candle, stops and exits
run, positions and realised loss are replayed from stored paper fills, and simulated equity is recorded for the
promotion gates. **It is only as real as the owner's cost model, and none is set**, so nothing is simulated
until the owner sets the numbers. Separately, the owner asked that `admin` hold every trader permission.

---

## What Changed

| Area | Detail |
|---|---|
| `runtime/paper_lifecycle.py` | Candle-driven, pessimistic, same rules as the backtest. An entry rests one candle and fills only if price trades strictly through; a stop exits at the worse of the open and the stop plus slippage; an entry and a stop in one candle assume the stop was hit; a signal exit sells at the next open; an intent that misses its candle expires. A cursor per pair stops a restart replaying or skipping |
| Separation | Paper rows are `origin = PAPER` and are replayed only by `replay_origin("PAPER")`; simulated equity is a separate table (`paper_equity_snapshot`, migration 0006), so a paper figure can never become a live drawdown peak. The module imports no connector and cannot send an order (guard test) |
| Owner numbers | `paper_config` (slippage, partial-fill fraction, four cost percentages, start capital) has no defaults; unset means no paper decisions and no records. `GET`/`PUT /paper-config` |
| Promotion | The paper drawdown gate is computed from stored simulated equity and is no longer typed in by the caller; "paper trades" counts paper sells. Backtest, live capital, and slippage evidence are still supplied |
| Halted | A halted Trader makes no new paper decisions but still simulates stops on candles that close |
| `admin` role (ADR-048) | `admin` holds every trader permission; step-up still guards FLATTEN, promotion to AUTO, and loosening a limit. Supersedes ADR-033. Anyone given `admin` can now flatten positions and replace the exchange key |

## Found While Building

- Same-instant fills (a stop on the candle an entry filled) replayed in random order because the tiebreak was a
  UUID; replay now sorts buys first. The live ledger had the same latent defect.
- SQLite returns Numeric as a float, so equality checks on stored decimals need a tolerance in tests;
  PostgreSQL is exact.

## Not Done, Not Verified

- Never run against a real exchange or PostgreSQL. Paper results have not been compared with anything real.
- The simulation fills entries at the limit price even if the candle gapped below it (conservative for a buyer)
  and applies tax and clearing as a percentage of quote value, an assumption to check against real fills (OQ-5).
- Paper fees use the owner's numbers only; nothing validates them. Choosing them after seeing results would
  invalidate the evidence; the audit log records each change.
- No front-end view of paper trades or paper equity; the strategies page shows the gates only.
- Backtest results are still not stored, so the "backtest" gate stays "no evidence".

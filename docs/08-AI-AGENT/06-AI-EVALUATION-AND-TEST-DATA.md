# 06 — AI Evaluation and Test Data

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | QA Engineer, Trading Engineer |
| **Decided by** | ADR-004, ADR-020 |
| **Open items** | OQ-13 (decided, ADR-032), OQ-25 (deferred by decision, ADR-045) |

## The Question

Does a veto rule make a strategy **better**, after costs, on data it was not tuned on? Until the answer is
yes with evidence, the rule stays disabled (`02-VETO-RULES.md`).

## Method: Counterfactual Backtest

1. Run the strategy over a period with no veto: baseline.
2. Run the same period with the rule enabled, using the **stored** context for each candle (so the context
   is what would have been available at the time, not recomputed later).
3. Compare out-of-sample: return after costs, max drawdown, trade count, and the outcome of vetoed trades
   (what would they have done).
4. Report the **vetoed trades' results**: a veto that mostly blocks winners is harmful.

## Requirements for Evidence

| Requirement | Why |
|---|---|
| Out-of-sample period | Avoid choosing thresholds on the test data |
| Context captured **at the time** | Otherwise look-ahead (a later forecast uses later prices) |
| Cost model applied | A veto that removes trades also removes costs; compare net |
| Sample size stated | A handful of vetoes is not evidence |
| Thresholds set before looking at the result | The owner sets them first (ADR-045) |

**A hard limit:** the context for crypto pairs does not exist yet (post-MVP, ADR-032), so there is **no history to
evaluate against**. Evidence can start only after the bridge runs and stores context for a stretch of real
time, which is itself a reason to run it in record-only mode early.

## Record-Only Mode

Context is fetched and stored on each intent but does not veto. After enough history the counterfactual
above can run. This costs nothing in risk (ADR-004) and builds the evidence.

## Test Data

| Fixture | Use |
|---|---|
| Typed context responses (OK, partial, unavailable, stale, wrong candle, malformed) | Bridge tests |
| Context sets that cross and do not cross each threshold | Veto tests |
| A recorded candle series with stored context | Counterfactual test |

Fixtures are generated from the schema in `01`, labelled synthetic, and contain no real analysis outputs from
production.

## Ongoing Monitoring

Veto rate per strategy, the share of vetoed trades that would have been profitable, and the age of context
at decision time are tracked. A change in any of them raises a `WARN`.

# 06 — Paper Trading and Backtest

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer, QA Engineer |
| **Decided by** | ADR-003, ADR-020 |
| **Open items** | OQ-5, OQ-12 |

Both exist to produce **evidence**, not reassurance. Neither can establish that live results will match.

## Shared Rules

- Same strategy code, same Intent Builder, same Risk Engine, same order state machine as live. Only the
  final step differs.
- Output is `origin = PAPER` or `BACKTEST` everywhere, and is never shown as real (FR-T28, FR-T30).
- The **cost model** includes maker and taker fees, tax, and clearing for the owner's account. Its values
  are not known (OQ-5); a backtest cannot run until they are configured, and the values used are stored with
  the run.

## Backtest (FR-T29)

| Rule | Detail |
|---|---|
| No look-ahead | A decision at candle *t* uses only candles up to and including *t*. A test proves it cannot read *t+1* |
| Closed candles only | The unfinished candle is never an input |
| Same sizing and limits | Risk limits from a stated configuration apply; the run records them |
| Fills | By the paper fill rules below |
| Costs | The configured cost model |
| Stored | Parameters, strategy version, candle range, cost model, fill rules, results, and the data fingerprint, so a run is reproducible |
| Metrics | Trade count, win rate, average win and loss, profit factor, max drawdown, exposure time, and total return after costs |
| Honesty | The report states the sample size, the period, and that results are historical |

### Overfitting

Tuning on a period and then promoting on the same period is invalid. The promotion evidence must come from
data not used to choose parameters (ADR-020, `11-MODE-PROMOTION.md`). The report separates in-sample from
out-of-sample results.

## Paper Executor (FR-T21, FR-T30)

Replaces the exchange call. **Conservative** by design, so paper does not look better than live would:

| Order | Fill rule |
|---|---|
| `LIMIT` buy | Fills only if a later price trades **through** (strictly below) the limit, not merely touches it |
| `LIMIT` sell | Fills only if a later price trades strictly above the limit |
| `MARKET` | Fills at the worse of the best bid or ask at decision time plus a configured slippage allowance |
| Partial fills | Not simulated beyond a configured fraction (the setting is open) |
| `MOC` | Rejected if the limit would match immediately |
| Fees | The cost model, with taker applied to market orders and to limits that cross |

The exact slippage allowance and partial-fill behavior are owner settings. A paper fill is a row in `fill`
with `origin = PAPER` and no `exchange_trade_id`.

A test asserts that in `PAPER` mode the connector's signed order methods are never called (FR-T21).

## What Paper Cannot Tell You

Paper trading does not feel latency, queue position, rejected orders, exchange maintenance, or your own
market impact. A good paper record is necessary, not sufficient, which is why `APPROVAL` with small real
capital is a separate stage (ADR-020).

## Labelling

Every screen, export, and notification that includes paper or backtest figures labels them on the figure.

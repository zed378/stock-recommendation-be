# KORO / Math Atlas, the part that applies to spot and to stocks

Source: ten slides the owner placed in `param/` (git-ignored), "KORO / MATH ATLAS 01/09 to 09/09" and a
"COPILOT" portfolio snapshot. They describe a Binance **USDT-perpetual** scalping bot: long and short, margin and
leverage, open interest and funding, averaging in, a random entry draw. The owner asked on 2026-11-23 for the
parts that can be built for crypto and, where possible, for stocks. This document decides slide by slide.

## Decision table

| Slide | Content | Crypto (4H signals, public spot data) | Trader (Indodax spot) | Stocks (IDX daily) |
|---|---|---|---|---|
| 01 | Episode accounting: win rate, payoff ratio, profit factor, expectancy, break-even win rate, raw Kelly, drawdown, recovery factor | **Built** on the simulated outcomes (`signals_stats.episode_stats`, in R) | Already partly there (paper metrics); not changed | **Not possible yet**: no closed-trade ledger for stocks (the journal is free text). The formulas are in the module and apply the day a ledger exists |
| 02 | Character statistics and the cross-universe cascade (ATRP, Amihud, zero-volume rate, lag-1 autocorrelation, variance ratio, efficiency ratio, z4 and z24, percentile gates, top K) | **Built** as `aidss_signals/atlas.py`, used by the new `ATLAS` strategy | Not applicable (one or two pairs, no universe) | **Statistics built** as opt-in indicators (`atrp`, `amihud`, `zero_volume_rate`, `efficiency_ratio`, `return_zscore`, beside the existing `lag1_autocorr`, `variance_ratio`). The cross-universe cascade is not built |
| 03 | OBV regression sign routes trend following or mean reversion; EMA21 and ATR14 pullback timing | **Built** (`atlas.route`), long and short, without the open-interest and funding flow gate | Long-only version already exists as `koro_obv_pullback` | OBV slope and pullback indicators already exist |
| 04 | Rolling Kelly turns trade history into an order unit | **Not built.** Raw Kelly is shown as a diagnostic only | Would change order size: needs a spec and owner numbers | Not applicable |
| 05 | Adaptive ADD (averaging in) and recovery | **Not built**: adding to a loser is martingale-like and needs a futures margin model | Not built | Not applicable |
| 06 | Entry lottery with memory (a random draw accepts or rejects an entry) | **Not built**: randomness in the entry decision conflicts with deterministic, replayable signals | Not built (ADR-004) | Not applicable |
| 07 | Outlier brake and momentum portfolio | **Not built**: acts on open leveraged baskets | Not built | Not applicable |
| 08 | Halving: net leverage, gross return, margin survival | **Not built**: margin and leverage do not exist on spot | Not applicable | Not applicable |
| 09 | Balance reference R, halt at 7 percent, restart rules | Not applicable to signals | **Covered by the existing breaker, differently**: see below | Not applicable |

## What was built

1. `aidss_signals/atlas.py`: the statistics, the percentile cascade (ATRP and 24h volume at or above their 30th
   percentile, Amihud at or below its 70th, autocorrelation above 0, variance ratio above 1, |z4| and |z24| at or below
   their 98th percentile taken over the coins that passed the persistence gates, top K by |z4| with K = min(10, universe)),
   the OBV routing and the pullback and mean-reversion entries, and a transparent 0 to 100 rank (shortlist rank 40,
   persistence 20, timing 20, BTC 4H trend alignment 20). A rank, not a probability.
2. A new `ATLAS` choice among the 4-hour strategies. It runs in the existing pass: candles for the whole universe are
   fetched first, the cascade runs once, then each coin is checked. Levels, ids, tracking and the simulation are the
   existing ones.
3. `signals_stats.episode_stats` and the summary endpoint and tab: win rate, payoff ratio, profit factor, expectancy,
   break-even win rate, win-rate edge, raw Kelly (labelled a diagnostic), maximum drawdown and recovery factor, all in R.
4. Stock indicators: `atrp`, `amihud`, `zero_volume_rate`, `efficiency_ratio`, `return_zscore`. Opt-in; the default
   indicator set and the screener scoring are unchanged.

## Differences from the slides (deliberate)

* Timeframe: the slides run the OBV regression and the entry on 5-minute bars and the character statistics on 4H. Every
  statistic here uses 4H candles, the cadence of the signals. Results are close to, not equal to, the slides.
* Quote volume is approximated as base volume times close (the candle fetch does not carry the venue's quote volume).
  The 24-hour volume in the cascade is the exchange's own 24-hour quote volume from the ticker.
* No open-interest or funding gate, and no previous-rank condition on mean reversion (no such data from public spot).
* **Minimum universe of 20 coins** (`MIN_UNIVERSE`, our own safeguard, not from the slides). A percentile gate over five
  coins is not a threshold. With the default Top N of 5 the ATLAS strategy stays idle and the log says why; the owner
  raises Top N (the maximum is 50) to use it.
* Short signals follow the existing `allow_short` switch. They are simulated signals; an Indodax spot account cannot
  short.

## Slide 09 against what the Trader already has

The Trader's `max_drawdown_pct` breaker measures the fall from the highest stored equity (peak to now) and cancels
open orders when it is reached. Slide 09 measures the fall from a **balance reference R** that is ratcheted at session
changes (`R_new = max(R_old, W)`), uses the wallet without open profit and loss, halts at W at or below 0.93 R, and
has explicit restart and lock rules. The owner's proposed profile already sets 7 percent for the existing breaker. The
two are close for a long-only spot account but not identical: the peak-based one is stricter after a rise and ignores
sessions. No code was written for slide 09; a session-reference variant would be a risk-engine change and needs the
owner's decision.

## Not built, and what would unlock it

Slides 04 to 08 (Kelly unit sizing, adaptive ADD, entry lottery, outlier brake and momentum, halving) were requested
as a block. They are not built because each either needs a futures margin model, injects randomness, or changes order
size or order flow in the Trader, and CLAUDE.md requires a spec and an owner-set number for anything that limits
losses, and that every order passes the Risk Engine unchanged. What would unlock the spot-capable ones, one at a time:

* Kelly unit (04): the owner decides the cohort window, the clip limits and whether it may change paper order size at all.
  A display-only suggestion needs no decision beyond the label.
* Outlier brake (07): needs a decision on whether a spot position may be cut early by anything other than its stop.
* Everything else has no spot meaning.

## Verification

Statistics are tested against an independent numpy calculation; the cascade gate by gate; the routing on constructed
candles; the episode statistics against a hand calculation. Nothing here has been backtested on real 4H data and the
rank has no demonstrated edge. The simulated results table exists to measure that.

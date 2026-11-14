# 08 — Owner Numbers Worksheet

| | |
|---|---|
| **Status** | Draft, 2026-11-14. **Every value is blank on purpose** |
| **Owner** | Technical Lead, with the Owner |
| **Decided by** | ADR-008, ADR-009, ADR-010, ADR-020 |
| **Open items** | OQ-5, OQ-6 (resolved, ADR-041 and ADR-043), OQ-7 (allowlist decided, ADR-044), OQ-8, OQ-9, OQ-10 (resolved, ADR-036), OQ-11, OQ-12, OQ-15 (resolved, ADR-041), OQ-16, OQ-19 (resolved, ADR-041), OQ-22 (resolved, ADR-035 and ADR-042), OQ-23 (resolved, ADR-034), OQ-25 (deferred by decision, ADR-045) |

The Trader has **no default for any number that limits loss**. Each one below is yours. This worksheet lists them
in one place, with what each controls, what goes wrong if it is too low or too high, and the relationships that
must hold between them. It is a thinking aid, **not a recommendation**: nothing here proposes a value.

Fill the "Your value" column (leave a row blank if you are not ready). Copy the filled worksheet into the
settings screen when it exists (`03-DATA-MODEL/08-SETTINGS-REGISTRY.md`). Rows left blank keep the affected
strategy **disabled**.

**Set the promotion thresholds (section H) before any evidence exists.** Choosing them after seeing results
defeats their purpose.

## A. Risk limits (OQ-9)

| ID | Setting | Unit | Controls | Too low | Too high | Your value |
|---|---|---|---|---|---|---|
| A1 | `risk_per_trade_pct` | % of equity | IDR lost if a stop holds | Positions too small to meet pair minimums | One bad trade hurts | |
| A2 | `max_daily_loss_idr` | IDR | Entries stop for the day | Breaker trips on one ordinary stop | A bad day is not contained | |
| A3 | `max_drawdown_pct` | % from peak equity | Entries stop until reset | Trips on normal volatility | A long losing run is not contained | |
| A4 | `max_consecutive_losses` | count | Halt after a streak | Halts on routine variance | A broken strategy keeps trading | |
| A5 | `max_open_positions` | count | Simultaneous positions | Few trades | Risk spreads across too many correlated assets | |
| A6 | `max_exposure_per_pair_pct` | % of equity | Concentration in one pair | Rejects normal entries | A single asset can dominate | |
| A7 | `max_total_exposure_pct` | % of equity | Total at-risk capital | Underused capital | Little cash buffer | |
| A8 | `max_order_idr` | IDR | Absolute cap per order | Orders rejected | A sizing bug can place a large order | |
| A9 | `price_deviation_pct` | % from best bid/ask | Fat-finger guard | Normal orders rejected | A wrong price is accepted | |
| A10 | `freshness_limit_s` | seconds | Age at which data is stale | Everything looks stale | Old prices are trusted | |
| A11 | `cooldown_s` | seconds | Gap between orders on a pair | Rapid repeat entries | Missed re-entries | |
| A12 | `trading_window` | optional | Hours entries are allowed | n/a | n/a | |
| A13 | `order_rate_limit` | orders per period | Internal throttle | Legitimate orders delayed | Closer to exchange limits | |

## B. Day boundary (decided, ADR-034)

A "day" for `max_daily_loss_idr` is **local midnight WIB (UTC+7)**. Nothing to fill. The allowance resets at
00:00 WIB, which can give a fresh loss budget in the middle of a market move; the cumulative drawdown limit is
unaffected.

## C. Timing (all decided: ADR-041, ADR-043)

| ID | Setting | Unit | Controls | Too long | Too short | Your value |
|---|---|---|---|---|---|---|
| C1 | `price_poll_interval_s` | seconds | Stop reaction time | A stop can be crossed long before it is seen | More requests, closer to rate limits | **Decided: 10** (ADR-041) |
| C2 | `order_poll_interval_s` | seconds | Order status latency | Slow to see fills | More requests | **Decided: 10** (ADR-043) |
| C3 | `reconcile_interval_s` | seconds | How fast a difference is found | A mismatch lingers | More requests | **Decided: 60** (ADR-041) |
| C4 | `watchdog_timeout_s` | seconds | When a stalled loop alerts | The unprotected window grows | False alarms | **Decided: 3 missed poll cycles** (30 s at 10 s, ADR-041) |
| C5 | `lease_ttl_s` and heartbeat | seconds | The gap after a crash before another instance may trade | Longer unmonitored gap | Two instances could briefly overlap if clocks drift | **Decided: TTL 15, heartbeat 5** (ADR-043) |
| C6 | `clock_skew_tolerance_ms` | ms | Skew before halting | Requests rejected by `recvWindow` | Trades on a wrong clock | **Decided: 250** (ADR-041) |

## D. Order placement (OQ-22 resolved: ADR-035, ADR-042)

| ID | Setting | Options or unit | Your value |
|---|---|---|---|
| D1 | Entry price rule | **Decided:** best bid (buy), best ask (sell), maker-first (ADR-035) | decided |
| D2 | Wait before cancel and reprice | seconds | **Decided: 300** (ADR-042) |
| D3 | Maximum reprices | count | **Decided: 3** (ADR-042) |
| D4 | `selfTradePreventionMode` | **Decided:** `EXPIRE_TAKER` (ADR-035) | decided |
| D5 | Approval expiry | seconds | **Decided: 3600** (ADR-042) |
| D6 | `UNKNOWN` order: query attempts and total time | count, seconds | **Decided: 5 attempts in 30 s** (ADR-042) |
| D7 | Use `MOC` (maker or cancel) on entries | **Decided:** yes (ADR-035) | decided |

## E. Reference strategy (OQ-11)

| ID | Setting | Your value |
|---|---|---|
| E1 | `ema_fast`, `ema_slow` (periods) | |
| E2 | `adx_period`, `adx_threshold` | |
| E3 | `atr_period`, `atr_stop_multiple` | |
| E4 | Timeframe (`4H` or `1D`) | |
| E5 | Held-out data policy (which period is never used to choose parameters) | |

## F. Costs (OQ-5)

Observe these on your real account (`06-INTEGRATIONS/14`); do not copy from a sample.

| ID | Setting | Your value |
|---|---|---|
| F1 | Maker fee % | |
| F2 | Taker fee % | |
| F3 | Tax % and basis | |
| F4 | Clearing fee % | |
| F5 | Paper slippage allowance for `MARKET` | |
| F6 | Paper partial-fill fraction | |

## G. Pairs (OQ-7 decided, ADR-044; OQ-8 open)

| ID | Setting | Your value |
|---|---|---|
| G1 | Initial allowlist (IDR pairs) | **Decided: BTCIDR, ETHIDR** (ADR-044); inactive until G2 and G3 are set and pass |
| G2 | Minimum 24-hour quote volume (IDR) | |
| G3 | Maximum spread (%) | |

## H. Promotion thresholds (OQ-12). Set before seeing evidence

| ID | Gate | Your threshold |
|---|---|---|
| H1 | Backtest out-of-sample criteria (return after costs, drawdown, minimum trades) | |
| H2 | Paper: minimum completed trades | |
| H3 | Paper: maximum drawdown | |
| H4 | Live `APPROVAL`: fill quality tolerance versus paper | |
| H5 | Live `APPROVAL`: acceptable fraction of denied intents | |

The minimum durations (four weeks) are already decided (ADR-020).

## I. Capital (OQ-16)

| ID | Setting | Your value |
|---|---|---|
| I1 | Capital allocated to the Trader for the first `APPROVAL` period (IDR) | |
| I2 | Rule for increasing it | |

## J. Kill switch mapping (OQ-10 and OQ-21 decided)

| ID | Setting | Options | Your value |
|---|---|---|---|
| J1 | Tier triggered by each breaker (daily loss, drawdown, consecutive losses) | `HALT` or `CANCEL` (no automatic `FLATTEN`, ADR-036) | |
| J2 | Tier for a reconciliation difference | `HALT` is the documented default behavior | |
| J3 | Conditions that may cause automatic `FLATTEN` | **Decided: none** (ADR-036) | none |
| J4 | May the `admin` role `HALT` | **Decided: yes** (ADR-033) | yes |

## K. AI veto (OQ-25: deferred by decision, ADR-045)

| ID | Setting | Your value |
|---|---|---|
| K1 | Whether any veto is ever enabled | **Decided: later, with evidence** (ADR-045) |
| K2 | `kronos_veto_return` | |
| K3 | `analysis_veto_confidence` and the opposed label set | |

## L. Operations

| ID | Setting | Your value |
|---|---|---|
| L1 | Backup frequency and retention (copies are manual, ADR-040) | |
| L2 | Price-snapshot and event retention windows | |
| L3 | Severities that page the phone | |
| L4 | Key rotation schedule (OQ-17) | |

## Relationships That Must Hold

The settings screen should reject a combination that breaks one of these (the registry encodes them,
`03-DATA-MODEL/08`). They constrain your choices; they do not pick them.

1. **A2 versus A1:** if `max_daily_loss_idr` is smaller than one full stop at your largest permitted position,
   an ordinary stopped trade trips the breaker. You may want that, but choose it knowingly.
2. **A8 versus A6:** `max_order_idr` must not exceed what A6 allows for one pair at your current equity.
3. **A6 versus A7:** per-pair exposure cannot exceed total exposure.
4. **A5 versus A6 and A7:** `max_open_positions x` the per-pair cap should be reconciled with the total cap.
5. **A3 versus A2:** drawdown is cumulative; if the daily loss, as a percentage of equity, exceeds the
   drawdown limit, the drawdown limit will always trip first.
6. **C1 versus C4:** the price poll interval must be shorter than the watchdog timeout, with margin.
7. **C1 versus A10:** the freshness limit must be a comfortable multiple of the price poll interval, or every
   price is "stale".
8. **C5:** the lease TTL must be longer than its heartbeat interval.
9. **C1, C2, C3 versus the rate budget:** total requests per minute must stay well under the strictest
   Indodax limit (`02-ARCHITECTURE/08`).
10. **D5 versus E4:** the approval expiry should be shorter than the candle period, or an approved entry acts
    on a stale decision.
11. **H before evidence:** thresholds are recorded with a date before the evidence period starts.
12. **F from observation:** cost values come from real fills on your account, not from a sample or a guess.

## After You Fill It

Record the filled copy (with the date) in `MEMORY/records/`, answer the matching open questions in
`TASKS/BACKLOG.md`, and note any value you deliberately left blank. A value you change later is a new,
audited version, not an overwrite.

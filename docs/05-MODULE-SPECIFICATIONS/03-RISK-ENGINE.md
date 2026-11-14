# 03 — Risk Engine

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Risk Engineer |
| **Decided by** | ADR-008, ADR-009, ADR-010 |
| **Open items** | OQ-9, OQ-10 (resolved, ADR-036), OQ-23 (resolved, ADR-034) |

The only gate between an intent and the exchange. **There is no code path to an order that skips it.**

## Principles

1. **Deterministic and explainable.** Each check returns pass or fail with the observed value and the
   limit, stored in `risk_check_result`.
2. **Fail closed.** A check that cannot be computed (missing price, unreadable balance) **fails**.
3. **Outside the strategy's control.** A strategy cannot read, set, or override a limit.
4. **No defaults.** A required limit that is unset disables trading for the strategy (FR-T11).

## Profiles

| Profile | Used for | Checks |
|---|---|---|
| **ENTRY** | New positions and normal exits | All checks below |
| **EMERGENCY** | Stop exits, `FLATTEN`, kill-switch cancels | Only: the order **reduces** an existing position; quantity and price respect increments and minimums; the internal rate throttle; the state is not `DISABLED` for credential reasons |

The emergency profile exists so that the daily-loss or drawdown breaker, which should stop new risk, cannot
also block the order that reduces risk. It still logs every check.

## Checks (ENTRY profile)

| # | Check | Source of the limit |
|---|---|---|
| 1 | Trading state is `RUNNING` and the strategy is not disabled | state |
| 2 | Credential readable and permissions correct (`canTrade` true, `canWithdraw` false) | start check |
| 3 | Clock skew within tolerance | connector |
| 4 | Pair on the allowlist, not suspended or in maintenance, liquidity filter passing | `pair` |
| 5 | Market data fresh (price and candle) | `freshness_limit_s` |
| 6 | Daily loss within `max_daily_loss_idr` | `risk_limit` |
| 7 | Drawdown from peak equity within `max_drawdown_pct` | `risk_limit` |
| 8 | Consecutive losses below `max_consecutive_losses` | `risk_limit` |
| 9 | Open positions below `max_open_positions` | `risk_limit` |
| 10 | Exposure for the pair within `max_exposure_per_pair_pct`, and total within `max_total_exposure_pct`, **including this order** | `risk_limit` |
| 11 | Order value at most `max_order_idr` | `risk_limit` |
| 12 | Price within `price_deviation_pct` of the current best bid and ask (fat-finger guard) | `risk_limit` |
| 13 | Cooldown elapsed for the pair | `cooldown_s` |
| 14 | Within the trading window, if configured | `trading_window` |
| 15 | Internal rate throttle has capacity | `order_rate_limit` |
| 16 | Sufficient free balance for a buy | exchange balances |
| 17 | No unresolved `UNKNOWN` order or reconciliation difference | state |

## Circuit Breakers (checks 6, 7, 8 and reconciliation)

When a breaker trips the Risk Engine sets the trading state to `HALTED`, records a `breaker_event` with
the values, notifies `CRITICAL`, and triggers the tier configured for that breaker (ADR-010). **Resume is an
explicit owner action** and is blocked while the cause persists.

### How the Day Is Defined (ADR-034)

"Daily loss" is measured from **local midnight WIB (UTC+7)**. WIB has no daylight saving, so the boundary is a
fixed offset from UTC. The consequence the owner accepted: the allowance resets at 00:00 WIB, which can give a
fresh loss budget in the middle of a market move; the drawdown breaker, which is cumulative, is unaffected. The
boundary is stored as a setting (`daily_loss_day_boundary`) so a change is audited.

### Equity, Drawdown, and Losses

- **Equity** is exchange balances valued at last prices. If any held asset has no valid price, equity is
  unknown and entries are blocked.
- **Peak equity** is the maximum observed equity since the strategy (or the account) was last reset by the
  owner; drawdown is measured from it.
- A **loss** is a closed position with negative realized PnL after all costs.

## Order of Evaluation

Cheap, state-only checks first; then data-dependent; then those that need a balance read. Evaluation does
not short-circuit silently: every check up to the first failure is recorded, and the rejection reports the
first failing check.

## Ownership of Numbers

The engine implements the mechanism. **Every number is the owner's** (OQ-9). Tests use their own values and
assert behavior, never that a particular production value is correct.

## Tests (planned, FR-T10)

One test per check that fails when the check is removed; a test that the emergency profile still allows a
reducing order while a breaker is tripped; a test that an unset limit disables trading; and a test that no
module calls an order-mutating connector method without a prior `risk_check_result`.

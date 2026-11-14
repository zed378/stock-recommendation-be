# 05 — Risk and Audit Schema

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Risk Engineer, Security Engineer |
| **Decided by** | ADR-009, ADR-010 |
| **Open items** | OQ-9, OQ-10 (resolved, ADR-036) |

## `risk_limit` (versioned)

| Column | Notes |
|---|---|
| `id`, `version`, `effective_from`, `set_by` | A change creates a new version; the previous stays |
| `max_daily_loss_idr` | Owner value (OQ-9). Null means **unset** |
| `max_drawdown_pct` | Null means unset |
| `max_consecutive_losses` | Null means unset |
| `max_open_positions` | Null means unset |
| `max_exposure_per_pair_pct` | Null means unset |
| `max_total_exposure_pct` | Null means unset |
| `risk_per_trade_pct` | Null means unset |
| `max_order_idr` | Absolute cap |
| `price_deviation_pct` | Fat-finger guard |
| `freshness_limit_s` | Stale-data guard |
| `cooldown_s` | Per-pair |
| `trading_window` | Optional |
| `order_rate_limit` | Internal throttle |

**A null in any required column disables trading for the strategy** (FR-T11). There are no defaults in the
schema. The columns are the same ones named in ADR-009; none of their values is set anywhere in the
documentation.

## `risk_check_result`

`intent_id`, `check` (name of the limit), `passed`, `observed`, `limit`, `profile` (`ENTRY` or
`EMERGENCY`, see `05/03`), `at`. One row per check per intent, so a rejection names the limit and the
numbers.

## `breaker_event`

`id`, `breaker`, `tripped_at`, `observed`, `limit`, `tier` (`HALT` or `CANCEL`),
`resumed_at`, `resumed_by`, `resume_note`. Resume fields are filled only by an explicit owner action.

## `kill_switch_event`

`id`, `tier`, `trigger` (`MANUAL_UI`, `MANUAL_API`, `BREAKER`, `RECONCILER`, `WATCHDOG`), `requested_by`,
`started_at`, `finished_at`, and child rows `kill_switch_step` (`kind`, `target`, `result`, `error`) so a
partial `FLATTEN` is visible step by step.

## `audit_log` (append-only)

| Column | Notes |
|---|---|
| `id`, `at` | |
| `actor` | User id, or `system:<component>` |
| `action` | e.g. `order.create`, `mode.promote`, `limit.change`, `kill.flatten`, `credential.rotate` |
| `subject_type`, `subject_id` | |
| `before`, `after` | Redacted JSON |
| `mode` | The strategy's mode at the time |
| `correlation_id` | Ties an intent, its orders, and its fills |
| `prev_hash`, `hash` | **Proposed:** a hash chain for tamper evidence |

The Trader's role can `INSERT` and `SELECT` only. A credential change records that it happened and who did
it, never the value.

## `mode_change`

`strategy_id`, `from_mode`, `to_mode`, `at`, `by`, `evidence` (JSON of each gate and its measured value),
`note`. Demotions need no evidence.

## `lease`

`name`, `holder`, `expires_at`, `heartbeat_at`. One row for the Trader (ADR-027).

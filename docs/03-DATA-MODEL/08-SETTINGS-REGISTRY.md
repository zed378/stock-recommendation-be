# 08 — Settings Registry

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-009, ADR-014, ADR-029 |
| **Open items** | The values of every owner setting (see `01-PRODUCT-REQUIREMENTS/08-OWNER-NUMBERS-WORKSHEET.md`) |

The single list of every setting the Trader reads: its type and unit, its validation, **what happens while it
is unset**, where it lives, and who can change it. It is the reference for task T1-06 and for the settings
screen. **No setting that limits loss has a default value.** The few non-loss settings that behave in a fixed way
while unset say exactly how in their *Unset* cell.

## Rules

1. **Unset means disabled.** A required operational setting that is `null` disables the affected strategy
   (FR-T11) and the dashboard names it. There is no fallback in code.
2. **Versioned.** A change to an operational setting creates a new version; the old one stays. Each change
   writes an audit row with before and after (`09/04`).
3. **Validated together.** Settings are validated on their own **and against each other** (the relationships
   at the end). A save that breaks one is rejected with the reason.
4. **Where it lives.** *Infra* settings are in the container environment. *Operational* settings are in the
   `trading` schema. Secrets are never settings; they are credentials (`05/13`).
5. **Who changes it.** `trade:configure_risk` for risk and allowlist, `trade:configure_strategy` for strategy,
   `trade:promote` for thresholds and modes, `trade:manage_credentials` for credentials, `trade:resume` for
   resume. Infra settings are changed by deploying.

## Infrastructure Settings (environment)

| Key | Type | Notes |
|---|---|---|
| `AIDSS_TRADER_DATABASE_URL` | secret-bearing URL | Role `trader_rw`; schema `trading` |
| `AIDSS_TRADER_MASTER_KEY_FILE` | path | The **path** to the master-key file secret (ADR-029), never the key |
| `AIDSS_TRADER_EXCHANGE_BASE_URL` | URL | Trade API 2.0 base; configuration because documentation disagrees (`06/11` D1) |
| `AIDSS_TRADER_PUBLIC_BASE_URL` | URL | Public host for candles and pairs |
| `AIDSS_TRADER_ANALYSIS_API_URL` | URL | For token verification (`GET /auth/me`, ADR-028) and context |
| `AIDSS_TRADER_INSTANCE_NAME` | string | For the lease holder name and logs |
| `AIDSS_TRADER_LOG_LEVEL` | enum | |

## Operational Settings

`Unset` is what the Trader does while the value is `null`.

### Risk (`risk_limit`, `03/05`)

| Key | Type, unit | Validation | Unset |
|---|---|---|---|
| `risk_per_trade_pct` | decimal, % equity | > 0 and below the daily-loss share | Strategy disabled |
| `max_daily_loss_idr` | decimal, IDR | > 0 | Entries disabled |
| `daily_loss_day_boundary` | enum `UTC`, `LOCAL`, `ROLLING_24H` | one of the three | Decided: `LOCAL` = midnight WIB, UTC+7 (ADR-034). Still a stored, audited setting |
| `max_drawdown_pct` | decimal, % | > 0 | Entries disabled |
| `max_consecutive_losses` | int | >= 1 | Entries disabled |
| `max_open_positions` | int | >= 1 | Entries disabled |
| `max_exposure_per_pair_pct` | decimal, % | > 0 and <= total | Entries disabled |
| `max_total_exposure_pct` | decimal, % | > 0 | Entries disabled |
| `max_order_idr` | decimal, IDR | > 0 | Entries disabled |
| `price_deviation_pct` | decimal, % | > 0 | Entries disabled |
| `freshness_limit_s` | int, s | > a multiple of `price_poll_interval_s` | Entries disabled |
| `cooldown_s` | int, s | >= 0 | Entries disabled |
| `trading_window` | optional | valid window or none | No window (always open); this one is optional |
| `order_rate_limit` | int per period | below the connector throttle | Entries disabled |

### Timing

| Key | Type, unit | Validation | Unset |
|---|---|---|---|
| `price_poll_interval_s` | int, s | < `watchdog_timeout_s` | Decided: 10 s (ADR-041) |
| `order_poll_interval_s` | int, s | > 0 | Decided: 10 s (ADR-043) |
| `reconcile_interval_s` | int, s | > 0, within rate budget | Decided: 60 s (ADR-041) |
| `watchdog_timeout_s` | int, s | > `price_poll_interval_s` | Decided: 3 missed poll cycles, 30 s at 10 s polling (ADR-041) |
| `lease_ttl_s`, `lease_heartbeat_s` | int, s | ttl > heartbeat | Decided: TTL 15 s, heartbeat 5 s (ADR-043) |
| `clock_skew_tolerance_ms` | int, ms | < 1000 (Indodax rejects a timestamp 1 s ahead) and < `recvWindow` | Decided: 250 ms (ADR-041) |
| `recv_window_ms` | int, ms | > 0 and above the skew tolerance | The parameter is omitted and the exchange's documented default (5000 ms) applies. It is not a loss limit |

### Order placement

| Key | Type | Validation | Unset |
|---|---|---|---|
| `entry_price_rule` | enum | defined set | Decided: `BEST_BID_ASK_MAKER` (ADR-035) |
| `reprice_wait_s`, `max_reprices` | int | >= 0 | Decided: 300 s and 3 (ADR-042) |
| `stp_mode` | enum `EXPIRE_MAKER`, `EXPIRE_TAKER`, `EXPIRE_BOTH` | one of three | Decided: `EXPIRE_TAKER` (ADR-035) |
| `approval_expiry_s` | int, s | < candle period | Decided: 3600 s (ADR-042) |
| `unknown_query_attempts`, `unknown_query_window_s` | int | >= 1 | Decided: 5 attempts in 30 s (ADR-042) |
| `use_moc_on_entries` | bool | | Decided: `true` (ADR-035) |

### Strategy (`strategy_version`)

| Key | Type | Unset |
|---|---|---|
| `timeframe` | `4H` or `1D` | Strategy disabled |
| `ema_fast`, `ema_slow`, `adx_period`, `adx_threshold`, `atr_period`, `atr_stop_multiple`, `cooldown_s` | numeric | Strategy disabled |

### Costs

| Key | Type | Unset |
|---|---|---|
| `fee_maker_pct`, `fee_taker_pct`, `tax_pct`, `clearing_pct` | decimal | Backtest and paper cannot run |
| `paper_slippage_allowance`, `paper_partial_fill_fraction` | decimal | Paper cannot run |

### Pairs

| Key | Type | Unset |
|---|---|---|
| `allowlist` | list of canonical pairs | Decided: `BTCIDR`, `ETHIDR` (ADR-044). A pair is tradable only after the liquidity filter is set and passes |
| `min_24h_quote_volume_idr`, `max_spread_pct` | decimal | Liquidity filter disabled, so **the pair is not tradable** |

### Promotion thresholds (`mode_gate`)

Each gate in `05/11`: a threshold value. **Unset blocks promotion.** Each is stamped with the date it was set so
"set before the evidence" can be shown.

### Kill switch

| Key | Type | Unset |
|---|---|---|
| `breaker_tier[<breaker>]` | enum `HALT`, `CANCEL` (never `FLATTEN`, ADR-036) | That breaker cannot be enabled |
| `reconciliation_difference_tier` | enum | `HALT` (the documented behavior; it is also the only behavior ADR-022 allows) |
| `auto_flatten_conditions` | does not exist | Decided: there is no automatic `FLATTEN` (ADR-036) |
| `admin_may_halt` | bool | `false` |

### AI veto

| Key | Type | Unset |
|---|---|---|
| `veto_enabled[<strategy>]` | bool | `false` |
| `kronos_veto_return`, `analysis_veto_confidence`, `opposed_labels` | numeric, set | That rule never vetoes |
| `context_max_age_s` | int | Context is ignored |

### Notifications and operations

| Key | Type | Unset |
|---|---|---|
| `mobile_min_severity` | enum | `CRITICAL` only; `CRITICAL` cannot be disabled |
| `retention_price_snapshot_days`, `retention_events_days`, `retention_logs_days` | int | Keep (no deletion) |
| `viewers_can_see_trading` | bool | `false` |

## Cross-Setting Validation (rejected on save)

The relationships in `01-PRODUCT-REQUIREMENTS/08-OWNER-NUMBERS-WORKSHEET.md`: per-pair exposure at most total;
`max_order_idr` within the per-pair allowance; `price_poll_interval_s` below `watchdog_timeout_s`; freshness a
multiple of the poll interval; lease ttl above its heartbeat; request budget under the rate limits; approval
expiry below the candle period; and, on a limit **increase**, a displayed effect and a confirmation.

## Builder worker infrastructure (ADR-068)

`AIDSS_TRADER_BUILDER_WORKER_TOKEN_FILE` names an owner-only secret file mounted
read-only in the Trader container. It contains a random token of at least 32
characters; the value is never in a database setting or process environment.
`AIDSS_BUILDER_TRADER_TOKEN_FILE` points to the same token inside the separate
worker. The worker polls every **300 seconds** per owner selection. Missing or
unreadable token means the worker endpoints refuse requests.

The worker additionally receives the existing read-only analysis DB URL and
`AIDSS_JWT_SECRET` from protected files to read AI-provider configuration. It
does not receive the Trader database URL, exchange key, or order client.

## Tests (planned)

A test that **no loss-limiting operational setting has a default value** in code; a test per "Unset" cell; a test per
cross-setting rule; a test that a change writes a new version and an audit row; a test that an infra setting
cannot be changed through the API.

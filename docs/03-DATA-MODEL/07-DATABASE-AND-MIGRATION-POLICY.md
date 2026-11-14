# 07 — Database and Migration Policy

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer, DevOps Engineer |
| **Decided by** | ADR-001, ADR-021 |
| **Open items** | OQ-20 (decided, ADR-040) |

## Isolation (ADR-021)

| Item | Rule |
|---|---|
| Schema | `trading`. All Trader tables live here |
| Roles | `trader_owner` (runs migrations, owns objects), `trader_rw` (the running Trader), `trader_monitor` (read-only on the heartbeat, for the host liveness script, ADR-039), and the existing analysis role |
| Analysis role | **No write privilege** on `trading`. Whether it may read is not needed and is not granted |
| `trader_rw` | **No write privilege** outside `trading` |
| Public schema | The Trader does not read or write analysis tables. Analysis context, when it exists, arrives over the interface in ADR-032 |

## Privileges That Enforce the Design

| Table kind | `trader_rw` may |
|---|---|
| Append-only (`fill`, `ledger_entry`, `order_event`, `audit_log`, `candle`, `risk_check_result`, `breaker_event`, `kill_switch_event`, `mode_change`, `reconciliation_*`, `backtest_run`) | `INSERT`, `SELECT` only |
| `order` | `INSERT`, `SELECT`, and column-level `UPDATE` on the state columns listed in `04` |
| `order_intent`, `approval_request` | `INSERT`, `SELECT`, `UPDATE` on state columns |
| `strategy`, `risk_limit`, `pair`, `credential`, `lease` | As needed; every change audited |

A test connects as `trader_rw` and asserts that `UPDATE` and `DELETE` on an append-only table fail
(`FR-T26`).

## Migrations

| Rule | Detail |
|---|---|
| Tool | Alembic, a **separate environment** for the Trader (`alembic_trader/`) with its version table inside `trading`, so it never interferes with the analysis platform's history |
| Direction | **Additive by default.** New columns, new tables, new indexes |
| Destructive changes | A drop or type change needs its own reviewed migration, a backup beforehand, and an ADR if it touches ledger or audit tables |
| Down-migrations | May exist for development; are **not** used against a database holding live records |
| Reset | A database reset is never the answer to a schema problem. It is a "stop and ask the owner" |
| Execution | Run by `trader_owner` at deploy time, **not** by the running Trader |
| Autogenerate | Allowed to draft, never trusted blindly; every migration is reviewed |
| Drift check | A test builds an empty database from migrations and compares it with the models; a mismatch fails the build |

## Guard Tests

1. `aidss` code does not import `aidss_trader`, and the reverse is limited to the documented interface.
2. No float column exists in `trading`.
3. No `orders`, `trades`, or similar table exists in `public`.
4. The analysis platform's `tests/test_architecture_constraints.py` still passes unmodified.

## Backups and Restore

The `trading` schema is part of every backup. A restore of only `trading` must be possible, rehearsed, and
documented (`../10-OPERATIONS/04-BACKUP-RESTORE-AND-RECOVERY.md`). The shared PostgreSQL instance remains a
single failure domain (ADR-021).

## Performance

Indexes are required on (`order.pair_id`, `state`), `order.client_order_id` (unique),
(`fill.origin`, `fill.exchange_trade_id`) (unique), (`candle.pair_id`, `timeframe`, `open_time`) (unique),
and `audit_log.at`. Query plans for the operator dashboard are checked before release.

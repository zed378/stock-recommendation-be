# S2: several strategies in the paper loop (2026-11-19)

Implements ADR-062 and `MEMORY/specs/S2-multi-strategy-paper.md`. Not deployed.

Built: migration `0009_intent_strategy_id` (nullable column and index, added only if missing); `runtime/ownership.py` (ownership, claims, per-strategy trades and stats, the paper limit check); `Runtime._decide` split into the live reference path and `_decide_paper_book` (strategies in ascending id, wind-down for disabled strategies that still own a position); `strategy_enabled:<id>` settings and the cap of 8; API `PUT/GET /strategy-defs/{id}/paper`, `paper_only` refusal on promote, duplicate-parameter refusal, delete guard for any owner; the `ema_adx` gate counts and drawdown now come from its own sales; a Paper card on each strategy tab.

Verified locally: 712 Trader, architecture and routing tests passed, 135 frontend tests passed, ruff clean. Two old tests changed because they built impossible ledgers or asserted the old account-curve drawdown. Not run: `-m postgres` (including the privilege test for the new column), a browser check, and any run against real candles.

Deploy order: migration `0009` as `trader_owner`, then Trader, then frontend, with `--no-deps`. Nothing runs in paper until the owner enables a strategy.

## Deployed (2026-11-19)

Images `zed378/aidss-trader:0cca1d1` and `zed378/aidss-frontend:latest` (= `0cca1d1`). Order followed: backup of the `trading` schema (`~/aidss-pre-0009-trading.dump`, 89 tables, restore list read back), migration `0009_intent_strategy_id` as `trader_owner` from a throwaway container of the new image (head confirmed), then trader and frontend with `--no-deps`; postgres, api and worker were not recreated. Trader and frontend healthy; healthcheck rc 0; frontend answers 200.

Read back from the running Trader: 3 intents, all with NULL `strategy_id` (so `ema_adx`); defs `ema_adx` plus the four library strategies, none enabled; the ownership replay of the real PAPER book succeeded (no `OwnershipError`): `ema_adx` owns `USDTIDR` and `PIEVERSEIDR`, one trade so far. Two open paper positions against a stored `max_open_positions` of 1 means no new paper entry is made, by any strategy, until one closes. Rollback: disable strategies and redeploy `eae6bc2` (the column is nullable and older code ignores it).

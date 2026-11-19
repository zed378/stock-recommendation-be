# Strategy library, builder and strategy tabs (2026-11-19)

Owner's requests: more paper strategies than `ema_adx`, backtests of all of them together, one tab per strategy on the Strategies screen, and a builder to add, edit and delete strategies.

Built (ADR-061): `strategy/indicators.py` (SMA, population stdev, Wilder RSI, MACD, channel highs and lows), `strategy/library.py` (four rules), `strategy/catalog.py` (fixed untuned sets), `strategy/kinds.py` (kinds, bounds, `build_strategy`), strategy definitions in `runtime/settings_store.py`, `backtest/runner.py` and `backtest/jobs.py`, eight routes under `/trader/v1` (`strategy-kinds`, `strategy-defs` list/create/update/delete/backtests, `backtests` start/poll), and on the screen a Compare tab, one tab per strategy, a builder dialog and a Backtest button with a progress line. `deploy/trader/compare_strategies.py` runs every strategy over the stored candles, optionally with the owner's real fee numbers for that run only.

Verified locally: ruff clean; 652 backend tests passed (Trader, architecture, routing; 16 new for the library, 5 for the API); 135 frontend tests passed (4 new for the builder); production build succeeds. The API tests use a SQLite database and the mock exchange; the backtest job is checked only for the missing-inputs failure path, and the comparison script has not yet been run against real stored candles.

Not done: running more than one strategy in the paper loop (ADR-061, Not decided); deploying this code.

## Deployed and first comparison (2026-11-19)

Deployed `zed378/aidss-trader:eae6bc2` and `zed378/aidss-frontend:latest` (= `eae6bc2`) with `--no-deps`; PostgreSQL, api and worker untouched; both services healthy. `compare_strategies.py --owner-costs` ran inside the Trader container, once read only and once with `--record` (identical output). Costs: maker 0.10, taker 0.20, tax 0.21 on sales, clearing 0.00555 (for this run only; the stored paper settings are unchanged). 26 pairs, start equity 74,000 IDR, about 50 days of 4H candles.

| strategy | sum of pair returns % | trades | pairs with trades |
|---|---|---|---|
| ema_adx | -1.928 | 20 | 12 |
| macd_trend | -7.618 | 26 | 11 |
| rsi_reversion | -20.208 | 55 | 18 |
| donchian_breakout | -28.898 | 54 | 20 |
| bollinger_reversion | -33.537 | 134 | 20 |

The pairs themselves fell a mean 9.29% over the same bars. Every rule lost; the sample is one falling market. The four new rows are stored under their catalog ids but no definition exists on the VM, so they have no tab until created in the builder with the same numbers (the same numbers give the same version, so the stored results then show).

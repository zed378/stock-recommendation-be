# Strategy library, builder and strategy tabs (2026-11-19)

Owner's requests: more paper strategies than `ema_adx`, backtests of all of them together, one tab per strategy on the Strategies screen, and a builder to add, edit and delete strategies.

Built (ADR-061): `strategy/indicators.py` (SMA, population stdev, Wilder RSI, MACD, channel highs and lows), `strategy/library.py` (four rules), `strategy/catalog.py` (fixed untuned sets), `strategy/kinds.py` (kinds, bounds, `build_strategy`), strategy definitions in `runtime/settings_store.py`, `backtest/runner.py` and `backtest/jobs.py`, eight routes under `/trader/v1` (`strategy-kinds`, `strategy-defs` list/create/update/delete/backtests, `backtests` start/poll), and on the screen a Compare tab, one tab per strategy, a builder dialog and a Backtest button with a progress line. `deploy/trader/compare_strategies.py` runs every strategy over the stored candles, optionally with the owner's real fee numbers for that run only.

Verified locally: ruff clean; 652 backend tests passed (Trader, architecture, routing; 16 new for the library, 5 for the API); 135 frontend tests passed (4 new for the builder); production build succeeds. The API tests use a SQLite database and the mock exchange; the backtest job is checked only for the missing-inputs failure path, and the comparison script has not yet been run against real stored candles.

Not done: running more than one strategy in the paper loop (ADR-061, Not decided); deploying this code.

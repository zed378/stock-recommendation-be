# KORO / Math Atlas, spot part (2026-11-23)

ADR-069, spec `MEMORY/specs/KORO-atlas-spot.md`. Built, not deployed.

- `src/aidss_signals/atlas.py` (statistics, cascade, routing, rank), `ATLAS` in `h4.py` and `h4_pass.py` (candles for the whole universe first, one cascade, then each coin; a coin with no setup reports the cascade's reason, for example `NO_SETUP:UNIVERSE_TOO_SMALL:5<20`), `ATLAS` accepted by the settings validation and the screen.
- `signals_stats.episode_stats`, the summary endpoint fields `episode_stats` and `episode_stats_by_strategy`, and an episode block on the 4-hour tab.
- Stock indicators `atrp`, `amihud`, `zero_volume_rate`, `efficiency_ratio`, `return_zscore` in `aidss/indicators`.
- Tests: 15 for atlas (numpy cross-check, each gate, routing, score), 2 pass-level, 4 episode statistics (hand calculation), 3 stock statistics, frontend 162.

Findings while doing it: the `param` directory holds ten slides of a futures bot, so most of it does not apply; the slides' "drawdown halt 7 percent" is close to the Trader's existing `max_drawdown_pct` breaker, which measures from peak equity instead of a ratcheted session reference.

Not verified: any real 4H data end to end, and the ATLAS rank against outcomes. With the default Top N of 5 the strategy stays idle on purpose; it needs a universe of at least 20 coins (Top N up to 50).

## Deployed (2026-11-23)

Images `zed378/aidss-trader:5b90ab8`, `zed378/aidss-frontend:5b90ab8`, `zed378/aidss-signals:5b90ab8` (no migration, no schema backup needed). Trader and frontend recreated with `--no-build --no-deps` from a copy of the running override (`~/aidss-deploy-5b90ab8.json`); the worker container recreated with the same flags as before. The analysis API and its worker were not rebuilt: the new stock indicators are opt-in and unused, so they reach the API image at its next release. Postgres untouched.

Checked: trader and frontend healthy after 40 seconds; the Trader stayed `RUNNING` (resumed earlier today by the owner's instruction, all strategies PAPER); the new summary route answers 401 without a token; the hourly anchor wrapper run by hand returned `rc=0` (seq 2878). Not checked: the new tab and the Math Atlas option in a browser, and any ATLAS pass, because ATLAS is not selected in the stored settings and Top N is 5 (it needs at least 20 coins). Rollback images: trader `875f56d`, frontend and signals `85f7f45` and `721e40a`.

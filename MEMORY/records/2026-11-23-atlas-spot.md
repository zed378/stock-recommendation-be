# KORO / Math Atlas, spot part (2026-11-23)

ADR-069, spec `MEMORY/specs/KORO-atlas-spot.md`. Built, not deployed.

- `src/aidss_signals/atlas.py` (statistics, cascade, routing, rank), `ATLAS` in `h4.py` and `h4_pass.py` (candles for the whole universe first, one cascade, then each coin; a coin with no setup reports the cascade's reason, for example `NO_SETUP:UNIVERSE_TOO_SMALL:5<20`), `ATLAS` accepted by the settings validation and the screen.
- `signals_stats.episode_stats`, the summary endpoint fields `episode_stats` and `episode_stats_by_strategy`, and an episode block on the 4-hour tab.
- Stock indicators `atrp`, `amihud`, `zero_volume_rate`, `efficiency_ratio`, `return_zscore` in `aidss/indicators`.
- Tests: 15 for atlas (numpy cross-check, each gate, routing, score), 2 pass-level, 4 episode statistics (hand calculation), 3 stock statistics, frontend 162.

Findings while doing it: the `param` directory holds ten slides of a futures bot, so most of it does not apply; the slides' "drawdown halt 7 percent" is close to the Trader's existing `max_drawdown_pct` breaker, which measures from peak equity instead of a ratcheted session reference.

Not verified: any real 4H data end to end, and the ATLAS rank against outcomes. With the default Top N of 5 the strategy stays idle on purpose; it needs a universe of at least 20 coins (Top N up to 50).

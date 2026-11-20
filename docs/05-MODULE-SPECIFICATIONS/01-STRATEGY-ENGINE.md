# 01 — Strategy Engine

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-004, ADR-012, ADR-019 |
| **Open items** | OQ-11 |

## Contract

A strategy is a **pure function**: closed candles, its parameters, and the current position state in; a
signal out. It has no network, database, clock, or random access. It cannot reach the connector or the
order path (`02-ARCHITECTURE/03` rule 1).

```
evaluate(candles, params, position_state) -> Signal
Signal = { kind: ENTRY | EXIT | NONE, reason, stop_hint?, target_hint? }
```

A signal carries **no size, no order type, and no authority**; the Intent Builder and Risk Engine decide
what, if anything, becomes an order.

## Determinism (FR-T05)

The same candles and parameters produce a byte-identical signal. A test runs a strategy twice on a fixed
fixture and compares the serialized output. Strategies use only closed candles; the unfinished candle is
never an input.

## Versioning

Parameters are stored as an immutable `strategy_version`. Any change creates a new version, which starts in
`PAPER` (ADR-003). Every signal, intent, and order records the version that produced it.

## Position State Input

`flat` or `long` with entry price and size, per pair and strategy. The MVP is **long-only spot**: there is
no short selling, so `SELL` always reduces an existing long position.

## Reference Strategy: EMA plus ADX Trend-Following (ADR-019)

Rule shapes only. **No parameter value is specified**; they are owner settings (OQ-11) and must be tuned
only on data that is then held out from the promotion evidence.

| Element | Rule shape |
|---|---|
| Timeframe | 4H or 1D (strategy setting) |
| Trend filter | Fast EMA above slow EMA |
| Trend strength | ADX above `adx_threshold` |
| Entry | Trend filter and strength both hold at the close of a candle, and the pair is flat |
| Stop | Entry minus `atr_stop_multiple` times ATR, computed at entry and recorded |
| Exit (signal) | Trend filter fails at a candle close |
| Exit (protective) | The bot-side stop (`09-EXIT-MONITOR.md`) |
| Re-entry | Not before `cooldown_s` after an exit, and not on the same candle |

Parameters: `ema_fast`, `ema_slow`, `adx_period`, `adx_threshold`, `atr_period`, `atr_stop_multiple`,
`cooldown_s`.

Indicators come from a tested implementation. The analysis platform already ships deterministic EMA, ADX,
and ATR computation; the Trader either reuses an equivalent tested implementation or its own, but it
**must not import `aidss`** (`02-ARCHITECTURE/03` rule 6). Whether to copy or vendor the math is a design
choice for task T3-02.

## Insufficient History

If a pair has fewer candles than the longest indicator needs, the signal is `NONE` with reason
`insufficient_history`. An indicator without enough data yields no value, never zero.

## Adding a Strategy

Implement the interface, add fixtures that cover entry, exit, no-signal, and insufficient history, add a
determinism test, and document the strategy in `docs/05-MODULE-SPECIFICATIONS/`. A new strategy starts in
`PAPER` regardless of how it was tested.

## What a Strategy Must Never Do

Read the clock, fetch data, call the exchange, size a position, choose an order type, or read AI output. AI
context reaches an intent later and can only veto (`08-AI-AGENT/02`).

## Indodax IDR declarative builder (ADR-068)

The owner selected Indodax spot IDR. In Trader Strategies, **New signal builder**
opens entry/exit ALL/ANY groups with named close, EMA, RSI, ADX and volume-ratio
operands, constants, comparisons and crossovers. Definitions use the existing
audited `strategy-defs` API with kind `signal_builder` and a JSON `definition`
parameter. No rule expression or Python code is evaluated. All numeric parameters
are explicit; incomplete or non-Indodax/non-IDR definitions are refused.

The strategy itself is pure and uses Decimal indicators. Entry supplies an ATR
stop hint; existing intent sizing, pair increments and PAPER portfolio risk checks
still decide whether an intent may be recorded. Exit rules run only for an existing
long. No short or reversal is introduced. The existing non-reference PAPER-only
promotion restriction remains: this builder cannot currently be promoted live.

A separate worker runs Kronos and the existing AI gateway on public candles read
from the Trader. The Trader never imports analysis internals or waits for a model.
An entry requires a passing review for its exact strategy version, pair, timeframe,
candle and normalized data fingerprint. Unavailable, expired, mismatched or vetoed
reviews block entry. Exits, protective stops and kill actions do not require reviews.
Review ids are attached to the rule snapshot for traceability; prose never reaches
an order field. Review history is SHADOW evidence, not fills or profit probabilities.

### Local operation

1. Apply additive migration `0013_builder_review` through the existing owner migration
   process before running the new API/runtime. No production migration was performed
   in this implementation session.
2. In Strategies, create a signal builder and fill every rule, ATR stop, cooldown,
   data-age, review-age, forecast horizon/sample and AI/return threshold field. Keep
   its timeframe aligned with the deployed Trader runtime (currently defaults to 4H).
   Set the named IDR allowlist, liquidity/risk limits and PAPER cost model through
   their existing screens. Enable PAPER for the definition when ready to simulate.
3. Provision a **separate** model-worker environment with the existing optional
   Kronos CPU dependencies/weights and configured AIDSS AI gateway. Do not add torch
   to the Trader image. Set `AIDSS_BUILDER_TRADER_URL` and
   `AIDSS_BUILDER_TRADER_TOKEN_FILE`. Mount the random token read-only from an
   owner-only file in both services; it is never an environment value. It grants
   only builder work/review routes. Use HTTPS externally or `http://trader:8001` on
   the isolated Compose network. For AI gateway calls, provide the analysis role's
   read-only database URL and JWT decryption setting from protected files.
4. Run `python -m aidss_signals.indodax_builder once --models`, or run
   `python -m aidss_signals.indodax_builder serve --models --poll-seconds 300`.
   The owner selected 300 seconds; it only discovers review work, not trading.
   The worker uses a dedicated random token mounted from an owner-only file at
   `/run/secrets/builder_worker_token` in both containers. Its separate analysis
   identity has read-only provider access; it has no Trader database URL, exchange
   key or operator bearer token.
5. Read the SHADOW review history. Only matching fresh reviews can release a PAPER
   candidate, and existing risk checks may still refuse it. Disabling the builder
   or changing its definition prevents old evidence from being reused.

Work currently covers **explicitly named allowlisted pairs**, not ALL discovery;
ALL-only pairs have no model review and their builder entries remain blocked.
The review worker calls only the internal Trader API, never an exchange endpoint.
The worker's model budget/fallbacks are the existing AI gateway's. Any worker error
leaves entries blocked; its errors print a type, never credentials or response bodies.

### Backtest interpretation

Backtests run the deterministic rules on the selected timeframe. They do **not**
reconstruct historical Kronos/AI reviews or claim to evaluate the combined strategy.
Stored parameters carry `evaluation_scope=RULES_ONLY_NO_MODEL_REVIEWS`, and the UI
states this limitation. Live promotion remains unavailable for this strategy kind.

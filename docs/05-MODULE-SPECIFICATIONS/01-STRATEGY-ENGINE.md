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

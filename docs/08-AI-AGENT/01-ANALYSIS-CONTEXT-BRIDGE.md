# 01 — Analysis Context Bridge

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-004 |
| **Open items** | OQ-13 (decided, ADR-032) |

The Analysis Bridge fetches typed context for a pair at a candle close. **It cannot work for crypto until
the gap in `06-INTEGRATIONS/13` is closed.** This document specifies the interface so the Trader can be built
now and the source plugged in later.

## Request

### Offline builder foundation (ADR-068, proposed)

`aidss_signals.builder` evaluates declarative entry/exit rules on supplied closed candles
and attaches Kronos and AI reviews to SHADOW candidates. The owner selected Indodax
spot IDR: `aidss_signals.indodax_builder` now obtains exact-candle work through the
Trader API and posts typed model evidence to append-only `trading.builder_review`
(migration 0013). The Trader's pure `signal_builder` strategy uses those reviews as
a required PAPER entry gate, with owner-set freshness and exact version/data identity.
No model is imported into the Trader. Its exits, stops and kill switch do not wait
for reviews. This is separate from the deferred analysis-platform candle-in endpoint;
existing reference strategies retain their optional-context policy. See
`MEMORY/specs/T3-07-signal-decision-builder.md` and `05/01` for operation and limits.

| Field | Notes |
|---|---|
| `pair` | Canonical pair |
| `timeframe` | `4H` or `1D` |
| `as_of` | The closed candle's open time |
| `horizon_bars` | Forecast length requested |

No account data. Under the candle-in option the request also carries the public candles the Trader holds.

## Response (typed, all fields optional except `status` and `as_of`)

| Field | Type | Meaning |
|---|---|---|
| `status` | `OK`, `PARTIAL`, `UNAVAILABLE` | |
| `as_of` | timestamp | Of the data the context was built from |
| `generated_at` | timestamp | When it was computed |
| `kronos.direction_bias` | `bullish`, `neutral`, `bearish` | From the analysis platform's forecast |
| `kronos.projected_return_pct` | decimal | Over `horizon_bars` |
| `kronos.horizon_bars`, `kronos.samples`, `kronos.model_id` | | For provenance |
| `analysis.label` | closed set | The platform's recommendation stance (an analysis label, not an instruction) |
| `analysis.confidence` | 0 to 100 | The platform's **calibrated** confidence |
| `analysis.platform_ids` | | Identifiers of the platform records, for traceability |

The response has **no free-text field the Trader reads.** Any prose from the platform is shown to the owner
but never parsed.

## Freshness

Context older than `<context_max_age>` (owner setting) is ignored and recorded as stale. A context whose
`as_of` is not the candle being decided is ignored.

## Failure Handling

| Failure | Behavior |
|---|---|
| Timeout, error, `UNAVAILABLE` | Recorded as "context unavailable"; rules proceed (ADR-004) unless the strategy requires context, in which case the entry is held and an alert is raised |
| `PARTIAL` | Use the fields present; absent fields cannot veto |
| Malformed | Treated as unavailable and logged |

Timeouts are short and the call is **asynchronous to the order path**: it runs at candle close, before the
Risk Engine, and never in the stop or kill path.

## Storage

The exact response is stored on the intent (`order_intent.analysis_context`) with the time it was received.
The Trader records what it saw, not what the platform later says.

## Provenance

Because the Kronos forecast is a sampled model projection, the context carries its sample count and model id
so a later review can tell a 1-sample result from a 3-sample result (`03-KRONOS-ON-CPU.md`).

## Authentication

A service credential in the Trader's credential store (ADR-032). The
Trader's role never gets write access to the analysis platform's schema.

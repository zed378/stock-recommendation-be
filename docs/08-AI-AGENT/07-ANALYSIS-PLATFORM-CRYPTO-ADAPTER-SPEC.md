# 07 — Analysis Platform Crypto Adapter Spec

| | |
|---|---|
| **Status** | Draft, 2026-11-14. **Option B is chosen to follow the MVP (ADR-032)** |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-001, ADR-004 |
| **Open items** | OQ-13 (decided, ADR-032), OQ-25 (deferred by decision, ADR-045) |

Specifies the small change to the **analysis platform** (`aidss`) that would let the Trader obtain Kronos
context for crypto pairs (`06-INTEGRATIONS/13`, options A and B). Nothing here is built, and nothing here is
required for the first release (option D: ship without AI context). The owner chose D for the MVP and B afterwards (ADR-032), so this is the specification for the later step.

**Any change to `aidss` must keep `tests/test_architecture_constraints.py` passing unmodified** (ADR-001).

## What the Existing Platform Gives

| Piece | Fact |
|---|---|
| Forecast | `POST /assets/{ticker}/forecast` reads **stored candles** for a registered asset, runs Kronos-base on CPU, and returns projected bars and a direction bias |
| Context builder | A 5-bar, 3-sample Kronos projection already feeds the Technical Analyzer |
| Assets | `POST /assets` accepts any `exchange` and `currency` string, so `BTCIDR` on `INDODAX` can be registered |
| Timeframes | `Timeframe` includes `H4` and `D1`; whether an adapter serves 4H was not checked |
| Provider selection | `AIDSS_MARKET_DATA_PROVIDER` appears to be a **single global choice** (with a composite that splits prices from fundamentals, not equities from crypto). **To verify** |

## Option B (recommended first): candle-in forecast endpoint

The smallest change. The Trader sends the candles it already holds; the platform runs Kronos and returns the
projection. It stores nothing and needs no asset registration, provider, or ingestion.

### Route

`POST /forecast/candles`, permission `READ_ANALYSIS`, authenticated with a **service credential** scoped to this
read (ADR-032). The path avoids every fragment the architecture test forbids (`/order`, `/execute`, `/execution`,
`/broker`, `/trade`).

### Request

| Field | Notes |
|---|---|
| `pair` | Display only; echoed back |
| `timeframe` | `4h` or `1d` |
| `candles` | Closed candles, oldest first: `timestamp` (UTC), `open`, `high`, `low`, `close`, `volume`, as **strings** |
| `pred_len` | Bars to project |
| `sample_count` | Samples to average |

Validation: at least 20 candles and no more than `kronos_max_context`; strictly increasing timestamps; positive
prices; high at least low and containing open and close; sizes capped; **no account fields accepted** (`extra`
forbidden, as the platform's schemas do).

### Response

The existing forecast shape: model id, tokenizer id, provider, lookback, `pred_len`, last close, projected
close, projected return percent, direction bias, and bars. Plus `samples` and `generated_at`. The Trader's
context bridge maps it to `kronos.*` (`08/01`). The analysis label is **absent** (this endpoint runs no agents),
so the response is `PARTIAL` there.

### Runtime

CPU, roughly 4 seconds per sample on the development machine (`08/03`), so a request with three samples can
take on the order of ten seconds. The Trader calls it **asynchronously at candle close**, with a timeout that
fails open (ADR-004). Requests are serialized or limited so concurrent calls do not exhaust the CPU.

### Tests

Fixture mode returns deterministic bars; validation cases; no persistence; the architecture test unmodified;
a test that the route name contains no forbidden fragment.

## Option A: full crypto asset support

Registers crypto assets and lets **all** existing endpoints work for them, at a larger cost.

| Piece | Work |
|---|---|
| Market-data adapter | `market_indodax`: a **read-only** `MarketDataProvider` using the public OHLC and ticker endpoints. Registered in the plugin registry without adding a new **kind** (the registry's four kinds stay) |
| Naming | Avoid every identifier and table name the guard forbids: no `trading_api`, no table named `trades` for public trades |
| Timeframes | Map `4h` to `240` and `1d` to `1D`; the endpoint has no 5-minute timeframe |
| Assets | Register `INDODAX` assets via `POST /assets`; extend whatever resolves assets by exchange |
| Provider routing | If the provider setting is global, add per-asset or per-exchange routing so equities (Yahoo, IDX) and crypto run together. **This is the largest piece** |
| 24/7 handling | Audit the scheduler, monitoring poller, scan, and `idx_rules` for exchange-hours assumptions |
| Agents | News, fundamentals, and social analyzers have no crypto data; they **skip with a reason** as designed. The technical analyzer and Kronos work |
| Ingestion | Scheduled ingest for the allowlist at 4H and 1D |
| Rate limits | Share the legacy public limit (180 per minute) with the Trader's own traffic from the same IP |

Option A gives a stance label and confidence for crypto only to the extent the agents have data, which for
crypto is mainly technical. It is justified only if the owner wants the analysis platform to analyse crypto for
its own sake.

## Recommendation (proposed, not decided)

D now, B next. B isolates the model runtime in the analysis platform, adds one stateless route, and leaves the
data pipeline alone. A is a project of its own.

## Interaction With the Veto Rules

Under B the only context is the Kronos projection, so only the Kronos veto rule (`08/02`) can ever fire; the
analysis-stance rule has no input and never vetoes. That is consistent with fail-open behavior.

## Evidence Before Any Veto Is Enabled

The context for crypto pairs does not exist today, so there is no history to evaluate. Running the bridge in
**record-only mode** early builds it (`08/06`).

## Open Items

The veto thresholds (set at the evidence review, ADR-045) and the "to verify" items above (provider selection scope,
4H adapter support, 24/7 assumptions).

# 13 — AIDSS Analysis Platform (Internal Integration)

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-001, ADR-004 |
| **Open items** | OQ-13 (decided, ADR-032) |

The Trader may read AI and Kronos context from the analysis platform. This document records what exists and
a **gap that blocks the idea today**.

## What the Analysis Platform Offers

| Capability | Where | Notes |
|---|---|---|
| Multi-agent analysis (analyzers, TradingAgents debate, recommendation) | `POST /assets/{ticker}/analysis` | Produces structured agent outputs and a calibrated recommendation |
| Kronos-base forecast (CPU) | `POST /assets/{ticker}/forecast` | Projects OHLCV bars from stored candles; deterministic fixture mode exists |
| Indicators | `GET /assets/{ticker}/indicators` | Deterministic, LLM-free |
| Forecast in analysis | `ContextBuilder` | A 5-bar, 3-sample Kronos projection feeds the Technical Analyzer |

All of this runs on **stored candles for an `Asset`**.

## The Gap (post-MVP, ADR-032)

The analysis platform today has:

- **No Indodax market-data provider.** Its providers are `fixture`, `yahoo`, `idx`, `alphavantage`,
  `finnhub`, and a composite. None serves Indodax pairs.
- **Assets must be registered, but registration is not the obstacle.** `_resolve_asset` in
  `src/aidss/api/routes/assets.py` refuses a ticker and exchange that is not registered, and the default
  exchange is `IDX`. However `POST /assets` (`AssetCreate`) accepts any `exchange` string (and `currency`),
  so an asset such as `BTCIDR` on exchange `INDODAX` **can** be created. The missing piece is data, not
  registration.
- **No 24/7 market handling** (the schedule, monitoring, and `idx_rules` code are built around exchange
  hours); whether that breaks anything for a crypto asset has not been tested.
- **4H candle ingestion was not verified.** The `Timeframe` type includes `H4`, but whether any market-data
  adapter returns 4H bars was not checked and is part of option A or B below.

So **AI and Kronos context for a crypto pair does not exist and cannot be requested today.** The Trader's
`FR-T09` (veto) cannot be satisfied by simply calling the existing endpoints.

## Options (decided: D for the MVP, then B; ADR-032)

| Option | Idea | Cost |
|---|---|---|
| A | Add an Indodax read-only market-data adapter to the **analysis platform** and register crypto assets, so existing endpoints work for crypto pairs | Changes `aidss`, though only data ingestion, not execution; needs care to keep its architecture test and equity assumptions intact. Specified in `08-AI-AGENT/07-ANALYSIS-PLATFORM-CRYPTO-ADAPTER-SPEC.md` |
| B | Add a candle-in endpoint to the analysis platform (`POST /forecast` with the candles supplied by the caller) | Smaller change in `aidss`; the Trader sends candles it already holds. Specified in `08-AI-AGENT/07` |
| C | Run Kronos inside the Trader or a small sidecar that shares only the model code | Duplicates inference; adds torch to a trading image, which ADR-001's isolation was meant to avoid |
| D | Ship the MVP **without** AI and Kronos context | Rules decide anyway (ADR-004). A veto is an extra, not a requirement |

**Decision (ADR-032):** D for the first release, then B, because it keeps trading code free of model
runtimes and needs the smallest change to the analysis platform.

## Interface Principles (any option)

1. **Read-only.** Nothing flows from the Trader into the analysis platform.
2. **Failure is non-blocking** by default (ADR-004): context unavailable means rules proceed.
3. **No model text reaches an order.** Only a structured `veto` and its reason cross into the intent
   (`08-AI-AGENT/02`).
4. **The Trader stores what it saw** (`order_intent.analysis_context`), including the timestamp and the
   analysis platform's own identifiers.
5. **Authentication** uses a service credential held in the Trader's credential store (ADR-032: option B is an HTTP endpoint, so a
   credential, not a database view). The Trader's role never gains write access to `public`.
6. **Timeouts are short.** Analysis never sits in the order or stop path.

## Impact on ADR-001's Guard

Any change under option A or B is made in `aidss` and must keep
`tests/test_architecture_constraints.py` passing unmodified. A crypto data adapter is a market-data
provider, not an execution path, but it must be reviewed against the forbidden identifiers and routes the
test lists.

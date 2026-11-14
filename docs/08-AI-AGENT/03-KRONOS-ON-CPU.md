# 03 — Kronos-base on CPU

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-004, ADR-012 |
| **Open items** | OQ-13 (decided, ADR-032), OQ-25 (deferred by decision, ADR-045) |

## What Exists

The analysis platform integrates `NeoQuasar/Kronos-base` and `NeoQuasar/Kronos-Tokenizer-base` for OHLCV
sequence projection (`src/aidss/forecasting/`). It was configured on 2026-11-14 to run on **CPU** only
(`AIDSS_KRONOS_DEVICE=cpu`, not `auto`, so a GPU is never silently used), with a CPU build of PyTorch.

## Measured Behavior (development machine, 2026-11-14, synthetic input)

| Measure | Result |
|---|---|
| Device reported | `cpu`, CUDA not available |
| One forecast, one sample, warm | about 4 seconds |
| Five samples | about 12 seconds |
| First call | about 39 seconds, including loading weights |

These are timings for a development machine and one synthetic series, not a benchmark. They justify only
the claim that CPU inference is fast enough for a **candle-close** context at a 4H or 1D horizon and **not**
for any decision in the order or stop path.

## What Was Observed About the Output

- On a synthetic series that had risen sharply, the model projected a large fall (roughly 20 to 30 percent
  over five daily bars) consistently across samples. This shows the pipeline works. It says nothing about
  quality on real Indodax pairs.
- The raw model bars could be internally inconsistent (a high below the open). The platform now widens high
  and low to contain open and close.
- A single sample is noisy; the platform's analysis context uses three.

## Honest Limitations

- Kronos is a **statistical sequence model**. Its output is a sampled projection from price history alone,
  not a prediction of fact.
- **Its skill on crypto pairs, at 4H or 1D, has not been evaluated here.** No claim of predictive value is
  made.
- It sees prices and volume only: no news, no order book, no macro context.

## Role in the Trader (ADR-004)

Context and optional veto only. Never in the order or stop path, never a source of price, size, or
direction for an order. Whether it vetoes at all depends on evidence from `06-AI-EVALUATION-AND-TEST-DATA.md`.

## Operational Notes

- The weights (about 400 MB) are downloaded by the analysis platform on first use. The Trader never loads
  a model and its image does not include torch.
- A Kronos run is scheduled at candle close and cached for that candle; it is never invoked per tick.
- CPU contention: running Kronos on the same host as the Trader can slow the host. The call is
  asynchronous and its latency never gates a stop.

## Where This Stands Today

The forecast is available only for assets registered in the analysis platform. For crypto pairs it does
**not** exist yet (`06-INTEGRATIONS/13`, post-MVP per ADR-032).

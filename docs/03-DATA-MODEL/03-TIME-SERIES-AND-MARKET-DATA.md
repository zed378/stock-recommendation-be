# 03 — Time Series and Market Data

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-011, ADR-012 |
| **Open items** | OQ-4 |

## Candles

| Column | Type | Notes |
|---|---|---|
| `pair_id` | FK | |
| `timeframe` | text | `4H` or `1D` internally; mapped to `240` and `1D` at the connector |
| `open_time` | `timestamptz` | UTC start of the candle |
| `open`, `high`, `low`, `close` | `NUMERIC(38,18)` | |
| `volume` | `NUMERIC(38,18)` | Base-asset volume as returned |
| `fetched_at` | `timestamptz` | |
| `source` | text | `indodax_ohlc` |

Unique on (`pair_id`, `timeframe`, `open_time`). Only **closed** candles are stored and used.

### Normalization at the Connector

| Source field | Quirk | Handling |
|---|---|---|
| `Time` | Unix seconds in the documented example | Multiply by 1000 where milliseconds are needed; store as `timestamptz` |
| `Open`, `High`, `Low`, `Close` | Numbers in the example | Parse via string to `Decimal` to avoid binary float error |
| `Volume` | String in the example | `Decimal` |

Because the docs show both strings and numbers across endpoints, the parser accepts both and the contract
tests include each form.

### Validation (rejected with a recorded reason, never silently repaired)

- High below low, or open or close outside the high-low range.
- A non-positive price, or a negative volume.
- A timestamp not aligned to the timeframe boundary.
- A duplicate with different values (flag as a difference; do not overwrite).

### Boundaries and Time Zone (open, OQ-4)

The docs do not state where a 4-hour or daily candle starts or in what time zone. This must be established by
comparing a live response with the exchange's own chart before any backtest result is trusted. Until then
the model records the timeframe and the raw `Time` without asserting alignment.

## Price Snapshots

`last`, `bid`, `ask`, `fetched_at`, `source_time` (if given). The bid/ask come from `bookTicker`, the last
from `ticker/price`. A snapshot older than the freshness limit is stale by definition.

## Missing Values and Gaps

- An absent candle is a **gap**, not zero. A gap blocks decisions on that pair until backfilled.
- A zero-volume candle is real data and is kept.
- Indicators with insufficient history return **no value**, never zero (consistent with the analysis
  platform's indicator engine).

## Aggregation Windows

The Trader does not resample. It uses the exchange's `240` and `1D` series directly, so it never invents a
candle.

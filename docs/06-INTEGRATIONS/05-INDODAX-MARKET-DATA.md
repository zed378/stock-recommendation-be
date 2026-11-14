# 05 — Indodax Market Data

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Integration Engineer |
| **Decided by** | ADR-011, ADR-012 |
| **Open items** | OQ-4 |

Sources: `INDODAX-TradeAPI-2-Public.md`, `Public-RestAPI.md`. **Documented, not yet observed.** No API key
is needed for anything in this file.

## Pair Rules: `GET https://indodax.com/api/pairs`

Returns an array. Fields the Trader uses (some appear only on some pairs in the examples, so each is
treated as optional and a missing one **blocks trading that pair** rather than defaulting):

| Field | Use |
|---|---|
| `id`, `symbol`, `ticker_id` | `btcidr`, `BTCIDR`, `btc_idr`: three spellings of one pair |
| `base_currency`, `traded_currency` | `idr` and the traded asset |
| `price_precision`, `price_round`, `pricescale` | Price increment and precision (examples differ in type) |
| `quantity_increment` | Quantity step. Quantities are rounded **down** to it |
| `volume_precision` | Quantity precision |
| `trade_min_base_currency` | Minimum order value in IDR |
| `trade_min_traded_currency` | Minimum quantity of the traded asset |
| `trade_fee_percent`, `trade_fee_percent_taker`, `trade_fee_percent_maker` | Fee percentages, **present on only some entries in the sample** |
| `is_maintenance`, `is_market_suspended` | Pair state; either set means do not trade |
| `disable_deposit` | Irrelevant |

Rate limit for this host: 180 requests per minute.

## `GET https://indodax.com/api/price_increments`

`{"increments": {"btc_idr": "1000", ...}}`: price step per pair, keyed by `ticker_id`. Cross-checked with
`/api/pairs`; a disagreement blocks the pair.

## `GET https://indodax.com/api/server_time`

`{"timezone": "UTC", "server_time": 1571205969552}`. Used for the clock-skew check.

## OHLC: `GET https://indodax.com/tradingview/history_v2`

| Parameter | Meaning |
|---|---|
| `from`, `to` | Unix timestamps. The example uses seconds |
| `symbol` | e.g. `BTCIDR` |
| `tf` | `1`, `15`, `30`, `60`, `240` (minutes), `1D`, `3D`, `1W` |

Response: array of `{"Time", "Open", "High", "Low", "Close", "Volume"}`. The example shows numeric prices and
a string `Volume`. **No 5-minute timeframe exists.** The Trader uses `240` and `1D` (ADR-012).

Unverified (OQ-4): the maximum range per request, the candle boundaries and time zone, whether the latest
candle is returned while unfinished, and long-term availability. The Trader excludes the unfinished candle
by comparing `Time` with the timeframe length.

## Trade API 2.0 Public Endpoints (`https://api.indodax.com`, 300 requests per minute)

| Endpoint | Parameters | Returns |
|---|---|---|
| `GET /api/v2/ticker/price` | `symbol` or `symbols` | `{symbol, price}` (single) or an array |
| `GET /api/v2/ticker/bookTicker` | `symbol` or `symbols` | `{symbol, bidPrice, bidQty, askPrice, askQty}` |
| `GET /api/v2/ticker/24hr` | `symbol`, `symbols`, `type` (`FULL` or `MINI`) | Price change, last, bid, ask, high, low, volume, quote volume, open and close time |
| `GET /api/v2/depth` | `symbol`, `limit` (1 to 5000, default 100) | `bids`, `asks` as `[price, qty]` strings |
| `GET /api/v2/trades` | `symbol`, `limit` (1 to 500, default 500) | `id, price, qty, quoteQty, time, isBestMatch` |

`symbols` accepts a comma list or a JSON array; a **multi-symbol call costs one request**, which is why the
Exit Monitor uses it (`02-ARCHITECTURE/08`). With no symbol, `bookTicker` and `ticker/price` return every
pair.

## Use in the Trader

| Need | Source |
|---|---|
| Strategy input | OHLC `240`, `1D` |
| Last price for stops | `ticker/price` |
| Fat-finger guard and entry pricing | `bookTicker` |
| Liquidity filter (spread, 24h volume) | `bookTicker`, `ticker/24hr` |
| Pair rules | `/api/pairs`, `/api/price_increments` |

## Symbol Formats

Trade API 2.0 parameters use `BTCIDR` (examples also show lowercase `btcidr` in history). Public legacy uses
`btc_idr` as `ticker_id` and `btcidr` as `id`. The connector holds a single canonical form and converts at
the edge (`00-PROJECT-CONTEXT/02`).

## Errors

`-1121` invalid symbol, `-1130` invalid parameter (for example `limit` out of range), `-1102` mandatory
parameter missing. A malformed or missing field is `MALFORMED` (`01`).

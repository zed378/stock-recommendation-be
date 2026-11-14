# 03 — Indodax Overview

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Integration Engineer |
| **Decided by** | ADR-002 |
| **Open items** | OQ-3, OQ-4, OQ-18 (decided, ADR-038) |

Source: `btcid/indodax-official-api-docs` at commit `8d1b409` (2026-11-10).
**Documented, not yet observed.**

## The Surfaces

| Surface | Base | Auth | Status for the Trader |
|---|---|---|---|
| Trade API 2.0, public | `https://api.indodax.com/api/v2/...` | none | **Used** |
| Trade API 2.0, private | `https://api.indodax.com/api/v2/...` (the STP page names `https://tapi.indodax.com`, see `11`) | `X-APIKEY`, `Sign` (HMAC-SHA256) | **Used** |
| Legacy public REST | `https://indodax.com/api/...` and `/tradingview/history_v2` | none | **Used for candles and pair metadata only** |
| Legacy private REST | `https://indodax.com/tapi` | `Key`, `Sign` (HMAC-SHA512) | **Not used** (to be decommissioned) |
| Market-data WebSocket | `wss://ws3.indodax.com/ws/` | Static public token | Deferred |
| Private WebSocket | `https://indodax.com/api/private_ws/v1/generate_token`, then `wss://pws.indodax.com/ws/` | Legacy HMAC-SHA512 | Deferred |
| Deadman Switch | `https://indodax.com/tapi/countdownCancelAll` | Legacy | Not used |
| Self-Trade Prevention | A parameter on order creation | n/a | Used (`10`) |

## The Index Page's Statements

- Documented streams and endpoints are "official and supported". Anything else is "not supported; use at your
  own risk and with no guarantees".
- Existing integrations on the legacy private endpoint **must migrate** to TAPI v2; legacy `method`
  parameters continue for a "limited transition period" and will be decommissioned on a date to be
  announced.

## Why Candles Come From the "Legacy" Host

Trade API 2.0 public (`/api/v2/depth`, `/trades`, `/ticker/24hr`, `/ticker/price`, `/ticker/bookTicker`) has
**no OHLC endpoint**. The only candle source in the docs is `GET /tradingview/history_v2` on the public REST
host. It is unauthenticated and not part of the private-API decommission, but its long-term status is not
stated (OQ-4). Pair rules (`quantity_increment`, minimums, maintenance flags) are likewise in `GET /api/pairs`
and `GET /api/price_increments`.

## Account Model Facts

- Spot trading only. Pairs are named by base and quote, for example `BTCIDR`.
- Quote currencies seen in the docs: IDR and USDT. The Trader uses **IDR only** (ADR-005).
- Prices are quoted per unit of the base asset. Each pair has its own price and quantity increments and its
  own minimums.
- A **KYC-verified account** is implied; IDR withdrawals need a bank account under the KYC name (irrelevant
  here since withdrawal is not used).

## Self-Trade and Market-Abuse Policy

The STP page states Indodax "strictly prohibits any form of market manipulation or activity intended to
create a false or misleading impression of trading activity". Accidental self-trades from automated systems
are a stated concern. See `10-INDODAX-STP-AND-FEES.md` and OQ-1 (the owner should read Indodax's terms on
automated trading).

## Live Verification Needed Before Trusting This

Every shape here must be compared with a real response before implementation is considered done. The first
live check is **read-only** and uses a key with Read permission only, on the owner's instruction (OQ-18,
`TASKS/PHASE-T2-EXCHANGE-CONNECTOR.md` task T2-07).

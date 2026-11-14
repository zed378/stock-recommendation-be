# 04 — Assumptions and Constraints

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Technical Lead |
| **Open items** | OQ-1 (resolved, ADR-037), OQ-3, OQ-4, OQ-5 |

## Constraints (from sources, not preferences)

| # | Constraint | Source |
|---|---|---|
| C1 | `STOP_LIMIT` orders are rejected: `stop_limit_not_available` | `INDODAX-TradeAPI-2-Private.md`, Create Order |
| C2 | Order types are `LIMIT` and `MARKET` only | Trade API 2.0 enums |
| C3 | A `BUY MARKET` order needs `quoteOrderQty` (IDR), not `quantity` | Create Order parameters |
| C4 | Create order is limited to 20 requests per second per user per pair; cancel to 30 per second per user; the general order endpoints to 300 per minute per IP | Create Order, Cancel Order, rate-limit table |
| C5 | Public Trade API 2.0 endpoints: 300 requests per minute. Legacy public REST: 180 per minute | Public API docs |
| C6 | A request older than `recvWindow` (default 5000 ms) is rejected (`-1021`) | Timing security |
| C7 | `order/histories` and `myTrades`: maximum range 7 days; `limit` 10 to 1000 | History endpoints |
| C8 | A Read plus Trade key cannot be restricted to an IP; IP Permission exists only with Withdrawal | "Generate API Key" notes |
| C9 | A TAPIv2 key must be generated separately; an old key cannot be reused | "Generate API Key" |
| C10 | Available OHLC timeframes: 1, 15, 30, 60, 240, 1D, 3D, 1W (no 5 minute) | Public REST, OHLC History |
| C11 | An accepted order may not be immediately visible via `GET /api/v2/order` | Create Order notes |
| C12 | The analysis platform's architecture test must keep passing unmodified | ADR-001 |

## Assumptions

| # | Assumption | If wrong |
|---|---|---|
| A1 | The owner's Indodax account is KYC-verified and able to create a TAPIv2 key | Nothing can be tested live |
| A2 | The deployment host has accurate time and stable outbound HTTPS to `api.indodax.com` and `indodax.com` | `-1021` rejections; no data |
| A3 | `/tradingview/history_v2` remains available and unauthenticated | No candle source (OQ-4) |
| A4 | The 4H and 1D candle boundaries and time zone match what the strategy expects | Wrong indicator values. Verify before backtest (OQ-4) |
| A5 | Fees for the owner's account are close to the sample values (0.1 percent maker, 0.2 percent taker) plus tax and clearing | Backtest costs wrong (OQ-5) |
| A6 | One host, one owner, one Indodax account | Multi-account is out of scope |
| A7 | The owner decides legality and tax treatment | The owner states it has been considered (ADR-037); not analysed here |

## Dependencies

Indodax availability and its maintenance windows; the analysis platform's API for context (post-MVP, ADR-032); the
shared PostgreSQL server; the notification service (Telegram, ADR-031).

## Known Missing Access

No Indodax key exists in the project. No live response has been captured. Every endpoint shape in
`06-INTEGRATIONS/` comes from the official documentation only and is marked "documented, not yet
observed". `11-INDODAX-DOCS-DISCREPANCIES.md` lists where that documentation disagrees with itself.

## Safe Defaults When Something Is Unspecified

- A missing risk limit: **trading is disabled** for that strategy.
- A missing or unreadable credential: the Trader does not start trading and raises an alert.
- A stale price, an unreadable response, or an unexplained reconciliation difference: `HALT`.
- A missing AI or Kronos result: rules proceed unless the strategy requires it (ADR-004).

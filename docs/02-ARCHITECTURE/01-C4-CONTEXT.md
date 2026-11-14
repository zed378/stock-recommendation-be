# 01 — C4 Context

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |

```
                          +----------------------+
                          |        Owner         |
                          +----------+-----------+
                                     | approve / configure / kill (HTTPS)
                                     v
   +------------------+      +---------------------+      +----------------------+
   | AIDSS analysis   |<-----|     AIDSS Trader    |----->|  Indodax Trade API   |
   | platform         | read |  (spot, IDR pairs)  | sign |  2.0 (api.indodax.   |
   | context + veto   | only |                     | REST |  com/api/v2)         |
   +------------------+      |                     |      +----------------------+
                             |                     |      +----------------------+
                             |                     |----->|  Indodax public REST |
                             |                     | GET  |  (candles, pairs)    |
                             |                     |      +----------------------+
                             |                     |      +----------------------+
                             |                     |----->|  Telegram            |
                             +----------+----------+ push +----------------------+
                                        |
                                        v
                             +---------------------+
                             |  PostgreSQL         |
                             |  schema "trading"   |
                             +---------------------+
```

## Relationships

| From | To | Nature | Auth |
|---|---|---|---|
| Owner | Trader | Operator API and UI | Platform JWT plus `trader` role (ADR-028) |
| Trader | Indodax Trade API 2.0 | Orders, cancels, balances, history. Signed REST | `X-APIKEY` plus HMAC-SHA256 `Sign` |
| Trader | Indodax public | Candles, pairs, tickers. Unauthenticated REST | None |
| Trader | Analysis platform | Read-only context | Service credential, post-MVP (ADR-032) |
| Trader | Notification channel | Outbound message | Channel token (ADR-031) |
| Trader | PostgreSQL | Own schema only | Dedicated role (ADR-021) |

## Boundary Statements

- The Trader makes **outbound** connections only to Indodax, the notification service, and the analysis
  platform. It accepts inbound connections only from the owner's operator surface.
- Nothing flows from the Trader into the analysis platform. Analysis data never includes order or
  position data from the Trader.
- No system in this picture can move funds off the exchange through the Trader (ADR-013).

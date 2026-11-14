# 00 — Integration Catalog

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Integration Engineer |
| **Decided by** | ADR-002, ADR-011, ADR-016 |

**No integration is implemented.** Everything below is from documentation, none of it observed against a
live service.

| # | System | Direction | Used for | Auth | Status | Document |
|---|---|---|---|---|---|---|
| 1 | Indodax public market data | Pull | Candles, pairs, increments, server time | none | Specified | `05` |
| 2 | Indodax Trade API 2.0 public | Pull | Last price, best bid/ask | none | Specified | `05` |
| 3 | Indodax Trade API 2.0 private | Pull and push | Account, orders, cancels, history, trades | `X-APIKEY` + HMAC-SHA256 | Specified | `04`, `06`, `07` |
| 4 | AIDSS analysis platform | Pull | AI and Kronos context | Service credential (ADR-032) | **Post-MVP; gap found** | `13` |
| 5 | Notification channel | Push | Mobile alerts | Channel token | Telegram (ADR-031) | `12` |
| 6 | Indodax WebSockets | Pull | (deferred) | Public static token; private token is legacy-auth | Deferred | `09` |
| 7 | Indodax Deadman Switch | Push | (not used) | Legacy-auth | Unavailable | `09` |

## Explicitly Excluded

| System or endpoint | Why |
|---|---|
| Indodax legacy private API (`https://indodax.com/tapi`, `method=...`) | ADR-002 |
| `capital/*` and `fiat/*` endpoints (withdraw, deposit, history, address list) | No withdrawal or fund-movement code (ADR-013) |
| Any other exchange | One exchange only |
| Hugging Face Hub at runtime | The Trader runs no models; the analysis platform downloads Kronos weights |

## Mapping to the Components

| Integration | Component that owns it |
|---|---|
| 1, 2, 3, 6, 7 | Exchange Connector (the only code that speaks Indodax) |
| 4 | Analysis Bridge |
| 5 | Notifier |

## Documentation Provenance

Indodax details come from the official repository `btcid/indodax-official-api-docs`, read at commit
`8d1b4097933ba793af841d849bf7d9c51f009e9d` (2026-11-10). That repository states its documented streams and
endpoints are "official and supported" and that others are used at one's own risk. The documents disagree
with each other in places (`11-INDODAX-DOCS-DISCREPANCIES.md`). Re-read the source on the day a connector is
built; Indodax edits these pages.

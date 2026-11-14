# 05 — Sensitive Data Redaction

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Security Engineer |
| **Decided by** | ADR-014, ADR-016 |

## What Is Sensitive

| Class | Examples |
|---|---|
| Credentials | API key, secret, master key, tokens, DB passwords |
| Signatures and headers | `Sign`, `X-APIKEY`, `Authorization` |
| Account identity | Indodax `uid`, account type |
| Financial position | Balances, equity, position sizes, total value |
| Strategy | Parameters, limits, allowlist |

## Where Redaction Applies

| Sink | Rule |
|---|---|
| Logs | Never the credentials, signatures, or headers. Account `uid` and balances omitted. Order data limited to pair, side, id, state |
| Stored raw responses (`order_event.raw_response`) | Headers removed; `uid` and balances removed unless the record is a balance snapshot |
| API responses | Credentials never; a masked hint only (last four characters) |
| Error messages | Normalized class and a correlation id; no exchange payload with identifiers |
| Notifications | No credentials, no total balance or equity, no `uid`. Positions only at the detail the message needs (`05/12`) |
| Exports | Contain ledger or audit data the owner asked for; never credentials |
| AI calls | **No account data at all** (`08-AI-AGENT/00`) |
| Fixtures and tests | Synthetic only; no real keys, balances, or Indodax sample credentials |

## Mechanism

A single redaction function used by the logger, the raw-response store, and the notifier, applying an
allowlist of fields to keep (rather than a deny-list of fields to drop), so a new sensitive field added by
the exchange is dropped by default.

## Detection

A test feeds representative responses containing sentinel secrets through each sink and asserts the
sentinels never appear. A CI secret scan covers the repository. A log scanner in staging flags key-shaped
strings.

## Positions Are Sensitive Too

Even without credentials, a leaked position list reveals what the owner holds and how they trade. Mobile
notifications therefore carry the least detail that lets the owner act, and the full picture lives behind
authentication.

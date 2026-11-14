# 06 — Inbound Security

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Security Engineer |
| **Decided by** | ADR-015 |
| **Open items** | OQ-14 (resolved, ADR-028) |

"Inbound" here means anything that reaches the Trader from outside its process: the operator API, and
nothing else. The reference repository's equivalent covers webhooks; **the Indodax documentation read
describes no webhook or callback to the Trader**, so there is no signed inbound exchange message to verify.
(The Trade API 2.0 withdrawal whitelist mentions a "URL Callback" for withdrawals; withdrawals are not used.)

## The Operator API

| Threat | Control |
|---|---|
| Unauthenticated access | Bearer JWT on every route except a minimal liveness probe that reveals no state |
| Missing authorization | Every route declares a permission; an enumeration test fails otherwise |
| CSRF | Bearer tokens carried in a header, not an ambient cookie; if a cookie is ever used, SameSite and a CSRF token |
| Replay of an approval | The approval carries the intent hash and `Idempotency-Key`; a decided or expired intent refuses |
| Double submit | `Idempotency-Key` on every mutation |
| Clickjacking | `frame-ancestors` and `X-Frame-Options` deny on the operator surface |
| Brute force and abuse | Per-client rate limits; the kill-switch route exempt so it cannot be locked out |
| Injection | Parameterized queries only; typed request models that forbid unknown fields; no string-built SQL |
| Overlarge or malformed bodies | Size limits; strict schemas |
| Information leakage | Errors carry a class, a message without internals, and a correlation id |
| Replay with an expired token | Short-lived tokens; suspension checked per request |

## Headers

Security headers on every response (the analysis platform already adds a set; the Trader applies an
equivalent), including `Cache-Control: no-store` on authenticated responses that carry positions.

## The Notification Channel Is Not an Inbound Path

The mobile channel is outbound only. It cannot approve, deny, resume, or kill. Messages contain at most a
link to the authenticated UI, which performs no action on load (`12-NOTIFICATIONS.md`).

## Command-Line Kill Tool

The minimal `kill` command-line tool on the host (`05/08`) is an inbound path too. It runs only on the host
under an operating-system account allowed to run it, uses the same code and audit as the API, and needs no
network access.

## Tests (planned)

Unauthenticated and under-privileged requests are refused for every route; an approval cannot be replayed or
applied to a changed intent; unknown body fields are rejected; no route reflects an exchange payload.

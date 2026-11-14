# 05 — Security Tests

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Security Engineer, QA Engineer |
| **Decided by** | ADR-013, ADR-014 |

Each threat in `09-SECURITY-PRIVACY/00-THREAT-MODEL.md` with a testable control has a test here.

## Tests

| ID | Threat | Test |
|---|---|---|
| S1 | T1, T3 | The credential never appears in any API response, log line, notification, stored raw response, exception message, or export (sentinel test) |
| S2 | T2 | The connector's methods equal the allowlist; no route, identifier, or schema names withdrawal, deposit, or fiat |
| S3 | T2 | A key reporting `canWithdraw` or `canWithdrawFiat` true stops trading at start and at reconciliation |
| S4 | T4 | The Trader's key derivation does not use `AIDSS_JWT_SECRET`: changing the JWT secret leaves the credential readable; changing the master key makes it unreadable and the Trader `DISABLED` |
| S5 | T3 | The credential column holds ciphertext, not the key; a dump contains no plaintext |
| S6 | T5 | Every order path is preceded by a risk result; no module outside the Order Manager and kill switch calls order-mutating methods |
| S7 | T6 | A replayed approval is refused; a duplicate mutation with the same `Idempotency-Key` has one effect |
| S8 | T11 | Every route requires authentication and a declared permission (enumeration); under-privileged requests are refused; security headers present; frames denied |
| S9 | T11 | An approval cannot be applied to a changed intent |
| S10 | T12 | No route or code path acts on a notification channel message |
| S11 | T13 | `UPDATE` and `DELETE` on append-only tables fail as `trader_rw`; the audit hash chain detects a modified row |
| S12 | T10 | Hostile text in analysis context fields cannot reach an order; a context with a prompt-injection string affects only the typed veto |
| S13 | T14 | A floating dependency, a secret in the repository or image, or a high-severity finding fails CI; the Trader image has no torch and no test suite |
| S14 | T19 | Logs and notifications contain no key-shaped strings, `uid`, balances, or totals |
| S15 | A | A suspended user's token is refused; a user cannot change their own role |
| S16 | A | The kill route is not throttled and works when other routes are rate-limited |
| S17 | T20 | An image-layer secret scan passes and the image has no configuration values; before T5-06 the repository is private (ADR-030) |

## Non-Functional Security Checks

- Secret scanning of the repository history for sample keys copied from Indodax's pages.
- A review that the egress allowlist in the deployment matches `09/03`.
- A check that no container port beyond the operator surface is published.

## Penetration and Review

Before the first `APPROVAL` live use, an independent review of the operator API, the credential flow, and
the kill switch is performed, and the findings are recorded. This is the owner's decision on who reviews.
An automated scan does not replace it.

## Reporting

A failed security test is a release blocker. A fabricated-data finding and a Risk Engine bypass are not
waivable (`AGENTS.md`).

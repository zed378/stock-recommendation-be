# 00 — Threat Model

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Security Engineer |
| **Decided by** | ADR-004, ADR-007, ADR-013, ADR-014, ADR-021 |
| **Open items** | OQ-1 (resolved, ADR-037), OQ-17 (custody decided, ADR-029), OQ-24 (resolved, ADR-030) |

## What Is Being Protected

| Asset | Why it matters |
|---|---|
| Funds on the Indodax account | Real money; losses are irreversible |
| The Indodax API key and secret | Authority to trade on that account |
| The integrity of the ledger and audit log | Basis for every decision about autonomy |
| The kill switch | The last line of defense |
| The owner's position data | Sensitive; reveals strategy and holdings |

## Actors

| Actor | Capability |
|---|---|
| External attacker who obtains the API key | Can place and cancel orders as the owner. **Cannot withdraw** (ADR-013) |
| Attacker with a database dump | Gets ciphertext, trading history, and positions |
| Attacker with the dump and the analysis API's secrets | Same, and would recover the key **if** the Trader reused `AIDSS_JWT_SECRET` (it must not) |
| Attacker with access to the host or container | Can read the environment, including the master key, and the running process |
| Malicious or manipulated data source (news, social text, API responses) | Can attempt prompt injection or feed bad prices |
| The owner (error) | Fat-finger limits, wrong promotion, approving blindly |
| A software defect | A bug can place runaway or wrong orders |

## Trust Boundaries

Owner and browser, the operator API, the Trader process, the database role boundary (ADR-021), the exchange
connection, the analysis platform interface (read-only), the notification service. See
`03-NETWORK-AND-TRUST-BOUNDARIES.md`.

## Threats and Controls

| # | Threat | Control | Residual |
|---|---|---|---|
| T1 | API key leaks and the attacker trades the account (wash trades, dumping positions, burning fees) | No withdrawal permission (ADR-013); encrypted storage with a dedicated master key (ADR-014); never logged or returned; rotation; unexpected-order detection through reconciliation (an order the Trader did not place appears as `ORDER_MISSING_LOCALLY` and halts) | **The key cannot be IP-locked**; the attacker can trade until rotated. Accepted |
| T2 | Funds withdrawn | No withdrawal code; startup refuses a key reporting `canWithdraw` or `canWithdrawFiat` | None in the Trader. If the owner creates a key with withdrawal elsewhere, the Trader detects it |
| T3 | Database dump exposes the key | Fernet ciphertext; master key not in the database or the dump | If the dump and the host's key file are both obtained, the key is recoverable |
| T4 | Master key reuse ties the key to the analysis API | Dedicated master key in a host file secret (ADR-014, ADR-029) | Anyone with root on the host can read it |
| T5 | Runaway or wrong orders from a bug | Risk Engine as the only path; limits; idempotent write-ahead orders; one instance; paper then approval before auto | Limits are only as good as the owner's numbers (OQ-9) |
| T6 | Duplicate orders from a retry or two instances | `clientOrderId` idempotency (ADR-024); lease (ADR-027) | None known |
| T7 | Bad or manipulated price (stale feed, spoofed data) | Freshness guard; price-deviation guard against the order book; reconciliation | A coherent but wrong feed can still mislead stops |
| T8 | **Position has no stop while the Trader or feed is down** | Watchdog alert; exposure limits (ADR-009); runbook | **Accepted (ADR-007).** No exchange-side stop exists |
| T9 | Clock manipulation or drift | Skew check against `server_time`; `recvWindow` | A bad clock halts trading |
| T10 | Prompt injection via news or social text | AI is veto-only and typed (ADR-004) | A spurious veto, a missed trade |
| T11 | UI abuse: clickjacking or CSRF on approve and kill | Bearer auth rather than ambient cookies; `Idempotency-Key`; approval bound to intent hash; confirmation fields; frame protection headers | An XSS on the front end could act as the owner; the front end is reviewed accordingly |
| T12 | Compromised notification channel used to control the Trader | The channel is outbound only; it can never approve or kill | An attacker could read alerts (redaction limits what) |
| T13 | Tampered audit log or ledger | Append-only privileges; proposed hash chain; reconciliation against the exchange | A database owner role could alter history; backups help |
| T14 | Supply-chain compromise (a malicious dependency or image) | Pinned dependencies, lockfile, image scanning, private image repository | See `07` |
| T15 | Owner error: loose limits, hasty promotion, blind approval | Mandatory limits; promotion gates; approval card shows risk and headroom; unset means disabled | Judgement stays human |
| T16 | Reconciliation gap beyond 7 days of history | Runbook; reconcile frequently | An outage longer than 7 days needs manual review |
| T17 | Exchange-side event: maintenance, suspension, delisting | Pair state checks; `-1016` handling; `FLATTEN` reports unsellable pairs | Cannot trade a suspended pair |
| T18 | Rate-limit ban or key lock for excessive requests | Throttle below limits; backoff | An unexplained `-2015` disables trading |
| T19 | Leak through notifications or logs | Redaction rules; tests for secrets and balances in messages and logs | Positions leak at the stated detail |
| T20 | Public container image exposes code | **Private before production (ADR-030).** Public is allowed during development with no secrets, no configuration values, and no owner numbers in the image. Anything pushed while public must be assumed copied. The analysis images were pushed as public on 2026-11-14 | Trading logic and tests are visible until the image is made private; make it private before T5-06 |

## Accepted Residual Risks (owner-visible)

1. **No stop while the Trader is down** (T8).
2. **Key cannot be IP-restricted** (T1).
3. **Market risk itself**: the system bounds and explains losses; it does not prevent them.
4. **Compliance and tax** are outside the system (OQ-1).

## Review

This model is revisited at every release (`12-DELIVERY-PLAN/05`) and after any security-relevant change or
incident.

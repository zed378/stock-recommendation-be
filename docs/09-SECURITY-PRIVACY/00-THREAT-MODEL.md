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

## Independent Security Review Packet (T6-01, prepared for owner's chosen reviewer)

The owner selects the independent reviewer before T5-06 (`TASKS/PHASE-T6-HARDENING-AND-RELEASE.md` T6-01). This
section summarises the attack surface, automated security proofs (`tests/trader/test_security_s1_s17.py`), and
known open items so the reviewer can inspect the exact files without relying on author claims.

### 1. Scope and Key Files to Inspect

| Area | Files | What to verify |
|---|---|---|
| Operator HTTP API & RBAC | `src/aidss_trader/api/app.py`, `src/aidss_trader/auth/` | Every `/trader/v1/*` route requires bearer auth (`TokenVerifier`), checks role (`trader` or `admin` per ADR-048), requires `Idempotency-Key` on mutating POST/PUT/DELETE, and enforces single-use 5-minute step-up grants (`StepUp`, ADR-046) on `FLATTEN`, `AUTO` promotion, loosening risk limits/allowlist/thresholds, and credential rotation |
| OpenAPI route enumeration | `src/aidss_trader/api/openapi.py`, `tests/trader/test_security_s1_s17.py` (`test_s5_*`) | No withdrawal, deposit-address, fiat, or arbitrary manual order-entry route exists anywhere in the router or OpenAPI schema |
| Exchange connector & key guard | `src/aidss_trader/connector/`, `src/aidss_trader/livecheck/` | Allowlisted TAPIv2 endpoints only; startup and reconciliation refuse keys where `canWithdraw` or `canWithdrawFiat` is true (`S3`, ADR-013) |
| Credential encryption & redaction | `src/aidss_trader/credentials/`, `src/aidss_trader/logsafe.py` | Fernet encryption keyed exclusively from `AIDSS_TRADER_MASTER_KEY_FILE` (never derived from `AIDSS_JWT_SECRET`, `S4`); API responses return `masked_hint` only (`S1`, `S2`); logs and error strings scrub secrets (`S16`) |
| Kill switch independence | `src/aidss_trader/killswitch/`, `src/aidss_trader/__main__.py` | `HALT`, `CANCEL`, and `FLATTEN` work via HTTP API and CLI even when the Strategy Engine or analysis API is down (`A12`); no automatic code path can invoke `FLATTEN` (`S6`, ADR-036) |
| Database privilege boundary | `alembic_trader/versions/0001_foundation.py`..`0007_backtest_runs.py`, `deploy/trader/isolate_analysis_role.sql`, `tests/trader/test_privileges_postgres.py` | `trader_rw` has `SELECT, INSERT` only on `audit_log`, `risk_limit`, `fill`, `ledger_entry`, `order_event`, `backtest_run`; `trader_monitor` has `SELECT` on `trading.lease` only; `aidss_app` has zero access to `schema trading` |

### 2. Automated Security Test Status (`S1`–`S17`)

Recorded in `MEMORY/records/2026-11-15-t6-security-and-resilience-tests.md`:
- **Passing on the mock (`25 passed`):** `S1` (secrets never in API responses/logs), `S2` (unreadable ciphertext fails closed), `S3` (`canWithdraw` rejected), `S4` (master key independent of JWT secret), `S5` (no withdrawal/deposit/fiat/order-entry routes in OpenAPI), `S6` (Risk Engine precedes all manager orders; only KillSwitch sends emergency `FLATTEN`), `S7` (`Idempotency-Key` enforced and replay-checked), `S8` (CSP, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Cache-Control: no-store`, `Referrer-Policy: no-referrer`), `S9` (auth required on all `/trader/v1/*` except `/health`), `S10` (step-up grant bound to user, scope, single use, 5-min TTL), `S11` (hash-chain tamper detection on `audit_log`), `S12` (AI context cannot construct or mutate order fields), `S14` (redaction on notifications), `S16` (safe logging on disk/handler failure), `S17` (no key-shaped literals in tracked files).
- **Open / Divergent items for reviewer attention:**
  1. **`S13` (`xfail`):** Dependencies in `pyproject.toml` use `>=` lower bounds without a committed lockfile.
  2. **`S15`:** The analysis platform allows an `admin` to step down (`allow_self=True`) while protecting the last admin; it cannot escalate privileges, which differs slightly from the literal wording in `11/05`.
  3. **Host DB isolation (Jalur 1):** `deploy/trader/isolate_analysis_role.sql` is prepared and tested (`test_privileges_postgres.py`), awaiting owner approval to run on `10.1.200.13`.

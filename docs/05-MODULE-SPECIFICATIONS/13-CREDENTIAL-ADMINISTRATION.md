# 13 — Credential Administration

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Security Engineer |
| **Decided by** | ADR-013, ADR-014 |
| **Open items** | OQ-17 (custody decided, ADR-029) |

Manages the single Indodax API key and secret (FR-T31).

## Permissions Required of the Key (ADR-013)

Reading and Spot Trading only. Never IDR and Crypto Withdrawal. Indodax requires a **dedicated TAPIv2 key**
generated at `https://indodax.com/trade_api`; an older key cannot be reused. A key without withdrawal
permission **cannot be IP-restricted**, which is a stated, accepted residual risk.

## Storage (ADR-014)

| Aspect | Rule |
|---|---|
| Where | `trading.credential`, ciphertext only |
| Cipher | Fernet |
| Key | A dedicated master key held as a **file secret** on the host and read-only in the container, path in `AIDSS_TRADER_MASTER_KEY_FILE` (ADR-014, ADR-029), separate from `AIDSS_JWT_SECRET`. A database dump alone, or a dump plus the analysis API's secrets, does not reveal the credential |
| Returned by any API | **Never.** Only a masked hint (the last four characters) and the last successful test time |
| Logged | **Never**, including in errors and in raw-response storage |
| In memory | Decrypted only inside the connector, only while signing |

Contrast: `aidss.security.secrets` derives its key from `AIDSS_JWT_SECRET`. Reusing it for the Trader would
tie the exchange key's safety to a secret the analysis API also holds. The Trader does not reuse it.

## Flows

### Store

The owner submits the key and secret over the authenticated operator API (write-only fields). The Trader
encrypts, stores, and immediately runs the **read-only test**.

### Test (read-only)

Calls `GET /api/v2/account`. It checks: authentication succeeds; `canTrade` is true; `canWithdraw` and
`canWithdrawFiat` are false. Any other result marks the credential **unusable**, the Trader stays
`DISABLED`, and the failure is shown with the reason (not with any key material). A test never places or
cancels an order.

### Rotate (atomic)

1. The owner generates a new key at Indodax and submits it.
2. The Trader tests the new key read-only.
3. Only on success it swaps the active credential in one transaction. There is never a moment with no valid
   key.
4. The owner revokes the old key at Indodax. The Trader reminds them and, at the next reconciliation, would
   notice if the old key still works (it cannot tell, so it only reminds).

Indodax's docs note that after a key is regenerated, **crypto withdrawals via API** are limited for 24
hours; that is not relevant to a key without withdrawal.

### Remove

Deletes the ciphertext, sets the state `DISABLED`, and audits.

## Master Key Custody (ADR-029)

A file on the host with strict permissions, outside git, mounted read-only into the container, and excluded from
every backup. Anyone with root on the host can read it. Changing it makes the stored credential unreadable until
the owner re-enters it; this is handled as a normal "credential unreadable, stay `DISABLED`" case, not a silent
failure. The generation procedure, exact path and permissions, rotation schedule, and re-entry procedure are
written into the runbooks (`10-OPERATIONS/06-RUNBOOKS.md`); they are operational details, not open decisions.

## Audit

Every store, test, rotate, and remove writes an audit row with actor and time and **never the value**
(FR-T33). A notification states that the credential changed and by whom.

## Tests (planned)

The key never appears in any API response, log line, or stored raw response; the test refuses a key with
withdrawal permission; rotation never leaves no valid key; an unreadable ciphertext leaves the Trader
`DISABLED` and alerts.

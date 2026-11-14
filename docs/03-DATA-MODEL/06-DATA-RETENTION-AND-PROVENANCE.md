# 06 — Data Retention and Provenance

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Security Engineer |
| **Open items** | OQ-1 (resolved, ADR-037), OQ-20 (decided, ADR-040) |

## Provenance

Every row says what kind of data it is and where it came from (`00-CANONICAL-DOMAIN-MODEL.md`):

| Field | Values |
|---|---|
| `origin` | `LIVE`, `PAPER`, `BACKTEST` |
| `source` | `exchange`, `local`, `simulated` |
| Timestamps | Our `created_at`, plus the source's own time where one exists |

A screen, report, or export that shows paper or backtest figures says so on the figure.

## Retention

Retention periods for financial records may be set by law or tax rules. That is not analysed here (OQ-1),
so the safe default is to **keep**.

| Data | Default | Reason |
|---|---|---|
| `fill`, `ledger_entry`, `order`, `order_event` | Keep indefinitely | Financial record |
| `audit_log`, `kill_switch_event`, `breaker_event`, `mode_change` | Keep indefinitely | Accountability |
| `reconciliation_run`, `reconciliation_difference` | Keep indefinitely | Evidence of correctness |
| `candle` | Keep | Reproducible backtests |
| `price_snapshot` | Rolling window, length to be set | High volume, low long-term value |
| Raw API responses in `order_event.raw_response` | Redacted; kept with the event | Diagnosis |
| `trading_event` | Rolling window, length to be set | Notification source |
| Application logs | Rolling window, length to be set | Operations |
| `credential` (old ciphertext) | Deleted on rotation | Minimize exposure |

Rolling-window lengths are operational settings, not decisions made here.

## What Is Never Stored

- The API secret or key in plaintext, anywhere.
- Request signatures.
- The master key.

## Redaction in Stored Raw Responses

Raw responses are stored with headers removed and any account identifier (`uid`) and balances omitted
unless the stored record is a balance snapshot. See `../09-SECURITY-PRIVACY/05-SENSITIVE-DATA-REDACTION.md`.

## Backups

Backups of the `trading` schema are a recovery asset and a leak risk. They contain the encrypted credential
but **not** the master key; the key and the dump are never stored together
(`../10-OPERATIONS/04-BACKUP-RESTORE-AND-RECOVERY.md`).

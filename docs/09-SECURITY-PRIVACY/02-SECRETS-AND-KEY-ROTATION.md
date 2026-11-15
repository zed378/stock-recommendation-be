# 02 — Secrets and Key Rotation

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Security Engineer |
| **Decided by** | ADR-013, ADR-014 |
| **Open items** | OQ-17 (custody decided, ADR-029) |

## Inventory

| Secret | Held where | Used by |
|---|---|---|
| Indodax key and secret | `trading.credential` ciphertext | Connector, while signing |
| Master key | A file secret on the host, mounted read-only into the container; the environment holds only the path `AIDSS_TRADER_MASTER_KEY_FILE` (ADR-029) | Credential store |
| Host liveness script's Telegram token | A root-only file on the host, separate from the Trader's database (ADR-039) | The out-of-process liveness check |
| `trader_rw` database password | Trader container environment | Database connection |
| `trader_owner` database password | Deploy-time only, not in the running container | Migrations |
| Notification channel token | `trading.credential`-style ciphertext | Notifier |
| Analysis platform service credential | Ciphertext | Analysis Bridge |

## Rules

1. **Never literal.** No secret in source, documentation, fixtures, logs, images, Compose files committed
   to git, or commit messages.
2. **The master key is not derived from `AIDSS_JWT_SECRET`.** The existing `aidss.security.secrets` derives
   its Fernet key from the JWT secret; the Trader must not reuse it (ADR-014).
3. **Dump and key are separate.** Backups of the database never sit beside the master key.
4. **Write-only fields.** No API returns a secret; the credential screen shows only a masked hint.
5. **Decrypt late, forget early.** The plaintext exists only while one signature is computed.
6. **No secrets in images.** The Trader image has none baked in. This matters because the analysis images
   were pushed to a public Docker Hub repository; a leaked layer is permanent.
7. **Scan before commit.** A secret scan runs in CI and locally. Indodax's own pages contain sample keys;
   those are never copied in either.

## Rotation

| Secret | When | Procedure |
|---|---|---|
| Indodax key | On suspicion, on a schedule the owner sets (OQ-17), and after any host incident | `05-MODULE-SPECIFICATIONS/13`: new key, read-only test, atomic swap, revoke old |
| Master key | On suspicion of exposure, and when custody changes | Re-encrypt: decrypt with the old key and re-encrypt with the new in one maintenance step, or re-enter credentials. Both must be rehearsed (OQ-17) |
| DB passwords | On suspicion | Standard role password change and redeploy |
| Channel token | On suspicion | Revoke at the provider, store the new one |

If the master key is lost or changed, the stored credential becomes **unreadable** and the Trader stays
`DISABLED` with a clear message; it never trades with a guessed or empty credential.

## Custody (ADR-029)

The master key is a file on the deployment host (`~/.aidss-trader-master.key`), outside git, readable only by the
account the Trader runs as (`chmod 0600`, uid 1000 inside the container) and root, mounted read-only into the
container at `/run/secrets/trader_master_key`. It is **excluded from every backup** and never stored beside a
database dump. Anyone with root on the host can read it.

### Generation, Path, and Permissions

```sh
# Generate a fresh 32-byte URL-safe Fernet key (refuses to overwrite an existing file):
docker run --rm -v "$HOME:/out" zed378/aidss-trader:<commit-tag> \
  python -m aidss_trader generate-master-key --out /out/.aidss-trader-master.key
chmod 0600 "$HOME/.aidss-trader-master.key"
```

### Master-Key Loss or Rotation (Re-Entry Procedure)

There is deliberately **only one copy** of `~/.aidss-trader-master.key` on the host so a database dump cannot be
paired with a backed-up master key (ADR-014, ADR-029). If the file is lost, corrupted, or rotated after a host
incident:

1. Ensure trading is `HALTED` (or stop the `trader` container). When the master key changes or is unreadable, the
   Trader fails closed (`credential.readable == false`), refuses to sign any request, and stays `DISABLED` /
   `HALTED`.
2. If rotating an existing file, remove or rename the old `~/.aidss-trader-master.key` and generate a new one with
   the command above (`chmod 0600`). Do **not** copy the old file into the database backup directory.
3. Restart the `trader` container so it mounts the new `/run/secrets/trader_master_key` file.
4. Open `/trader/credentials` in the operator UI. Both `indodax` and `telegram` will report `readable: false`
   ("Stored credential cannot be decrypted with the current master key").
5. Generate or retrieve the Read + Spot Trade TAPIv2 key from Indodax (and the Telegram bot token from BotFather),
   enter each in `/trader/credentials`, complete the password step-up (ADR-046), and save. The server tests the
   candidate key read-only (`GET /api/v2/account`, refusing `canWithdraw` or `canWithdrawFiat`, ADR-013) before
   replacing the unreadable ciphertext and writing an audit row.
6. Verify `/trader/credentials` shows `readable: true` and `last_test_ok: true`, then run reconciliation before
   resuming (`10-OPERATIONS/06-RUNBOOKS.md` R10).

## Detection

- A reconciliation that finds an order the Trader did not place is treated as a possible key compromise
  (`ORDER_MISSING_LOCALLY`), and the runbook starts with rotating the key.
- `permission_changed` (the account reporting `canWithdraw`) is `CRITICAL`.
- The credential screen shows the time of the last successful test, so a long-unrotated key is visible.

## Generation

Master key and passwords are generated from a cryptographically secure source and are long and random. The
procedure is written in `10-OPERATIONS/00-ENVIRONMENTS-AND-CONFIG.md` once decided; no example value is
given in these documents.

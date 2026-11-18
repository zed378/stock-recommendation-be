# 06 — Runbooks

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | DevOps Engineer, Risk Engineer |
| **Decided by** | ADR-007, ADR-010, ADR-022 |
| **Open items** | OQ-26 (decided, ADR-039) |

Written for the Owner, who is the only operator. Each is a procedure to follow while stressed, so each
starts with what to do **first**. Procedures are verified in drills before live use
(`12-DELIVERY-PLAN/05`). Until then they are drafts.

Manual steps on the exchange use the Indodax website or app. These documents do not describe Indodax's
screens because they were not reviewed here.

---

## R1 — The Trader is down and positions are open

**Why it matters:** no stop is monitored (ADR-007).

1. Treat it as urgent. Check whether any pair is moving sharply.
2. If you cannot restore the Trader quickly, **act at the exchange manually**: close or protect positions on
   the Indodax app or website. Do not wait for the Trader.
3. In parallel, check the host and container (`docker ps`, logs) and why it stopped.
4. When it restarts it will evaluate stops first and reconcile. Expect `HALTED` if anything differs.
5. Do not resume until you have read the reconciliation result.

## R2 — Using the kill switch

| Situation | Action |
|---|---|
| Something looks wrong but nothing is urgent | `HALT` |
| Orders may be wrong or duplicated | `CANCEL` |
| You must exit everything now | `FLATTEN` (confirmation required; it sells at market) |
| UI or API unreachable | The command-line kill tool on the host (`05/08`) |
| Trader itself unreachable | The Indodax app or website directly |

After any tier, check the step results, then reconcile. Resume only with a note and an understanding of why.

## R3 — Reconciliation difference

1. Read the difference kind and both values.
2. Check Indodax: was an order placed or cancelled outside the Trader? A deposit, a fee, a manual trade?
3. If an order you did not place exists, suspect the key: **go to R7**.
4. Record the cause. If the ledger is wrong, add an `ADJUSTMENT` with a reason. Never edit rows.
5. Reconcile again; resume only when clean.

## R4 — An order is `UNKNOWN`

1. The Trader is already querying by `clientOrderId`. Wait for its attempts.
2. If it is not found, **check Indodax yourself** (open orders, history). Do not assume.
3. Record the finding. Only you can confirm "not found". The pair stays held until you do.
4. Never re-send the order by hand from the Trader; there is no such control.

## R5 — Clock skew (`-1021`)

1. Check the host's time and NTP. Fix the clock.
2. The Trader halts until skew is within tolerance. Resume after reconciling.

## R6 — `-2015` Access denied

Possible causes: Trade API disabled, account locked, key permission changed, an IP rule, or a wrong key
version.

1. Check the key's permissions and status at Indodax.
2. Test the credential from the credential screen (read-only).
3. If the key was regenerated, store the new one. The Trader stays `DISABLED` meanwhile.

## R7 — Suspected key compromise

1. `CANCEL` (or `FLATTEN` if you judge it necessary).
2. **Revoke the key at Indodax immediately**, then generate a new TAPIv2 key (Read plus Trade only).
3. Review the order and trade history at Indodax for activity you did not make.
4. Rotate the master key if the host may be compromised (`09/02`).
5. Reconcile, record an incident (`07`), and resume only when satisfied.

## R8 — Exchange maintenance or a suspended pair

`-1016` or a maintenance flag suspends the pair automatically. Open positions on it cannot be sold until it
reopens; `FLATTEN` reports it. Decide whether to reduce exposure elsewhere.

## R9 — Restore from backup

`04-BACKUP-RESTORE-AND-RECOVERY.md`. Reconcile before resuming.

### Off-host encrypted copy

Run from **Git Bash** (or POSIX bash; PowerShell pipes corrupt binary streams) on the owner's workstation:

```sh
bash deploy/trader/backup_offhost.sh [--dest DIR] [--host infra@10.1.200.13]
```

The script streams `docker exec stocks-postgres-1 pg_dumpall -U aidss --quote-all-identifiers | gzip -6` over SSH directly into `openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt`. Remote Bash uses pipefail so a failed dump is not hidden by gzip success. Type and confirm the passphrase silently; it travels through a pipe file descriptor, never an argument, environment variable or disk file. Keep it in the owner's custody outside the backup directory. The test-only `--passphrase-fd N` reads one line from an existing descriptor; `--source-cmd` runs a local command and must never be taken from an untrusted source.

The default directory is `$HOME/aidss-offhost-backups`, created under umask 077. Output names are `aidss-pg_dumpall-<UTC>.sql.gz.enc` and `.enc.sha256`, mode 600 (Windows filesystem ACLs must be checked separately). Existing names, including sidecars, are refused. Failed sources, invalid dumps and interrupted runs remove partial outputs owned by this run. No plaintext backup is written locally or remotely. Verification decrypts into `gzip -t` and a streaming structure check for roles, COPY termination and the cluster footer, printing counts and size only. A passing check is not proof of recoverability or a complete database snapshot. `pg_dumpall` takes separate database snapshots; freeze writers for a migration fingerprint comparison.

Keep `~/.aidss-trader-master.key` separate (R10). AES-CBC plus this unkeyed checksum detects accidental corruption but is not authenticated encryption; an attacker able to replace both files can replace the checksum. Protect the destination and independently retain its checksum. Do not pass the passphrase through shell history or PowerShell pipelines.

Before trusting a real copy, rehearse in a fresh, isolated PostgreSQL 16 container with pgvector, no published ports, no application containers and a disposable data volume. Check the sidecar first with `sha256sum -c <file>.enc.sha256` from its directory. Then, in Bash with pipefail enabled:

```sh
set -o pipefail
openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -in <backup>.sql.gz.enc \
  | gunzip | docker exec -i <scratch-container> psql -U postgres
```

OpenSSL prompts on the terminal. Replace angle-bracket placeholders before use; never target production. Inspect every restore error (the bootstrap role/database may already exist), compare roles, schema versions and table counts to the captured source fingerprint, and verify append-only privileges. `deploy/trader/rehearse_restore.sh --full` documents the count/privilege checks but creates its own dump, so it does not test this encrypted cluster file. `deploy/production/restore.sh` supports a cluster stream into a fresh stack with application containers stopped; follow `09-MIGRATION-RUNBOOK.md` for that variant. Remove the scratch resources and record real timings and evidence. The script prints a restore example but never executes it. No production copy or restore is implied by local fixture tests.

## R10 — Credential unreadable (master key lost, corrupted, or rotated)

The master key (`~/.aidss-trader-master.key`, mounted at `/run/secrets/trader_master_key`) has only one copy on the
host so it is never paired with a database dump (ADR-014, ADR-029). While the key is missing or differs from the one
that encrypted `trading.credential`, the Trader fails closed (`readable = false`) and stays `HALTED` / `DISABLED`.

1. Confirm trading is `HALTED` (`GET /trader/v1/status` or the header state bar). If positions are open on Indodax,
   monitor or manage them manually on the Indodax website/app while credentials are being restored (R1).
2. On the host (`10.1.200.13` as `infra`), do **not** move or copy `~/.aidss-trader-master.key` into any backup
   folder. If the file was lost or must be rotated:
   ```sh
   rm -f "$HOME/.aidss-trader-master.key"
   docker run --rm -v "$HOME:/out" zed378/aidss-trader:<commit-tag> \
     python -m aidss_trader generate-master-key --out /out/.aidss-trader-master.key
   chmod 0600 "$HOME/.aidss-trader-master.key"
   ```
3. Recreate or restart the `trader` container via the stdin Compose override so the new secret file is mounted:
   ```sh
   cd ~/stocks
   set -a; . ~/.aidss-trader.env; set +a
   docker compose -f docker-compose.yml -f - up -d --no-build trader < ~/aidss-trader.override.yml
   ```
4. Open `/trader/credentials` in the browser. Each previously stored item (`indodax`, `telegram`) will display
   the unreadable warning (`readable: false`).
5. Re-enter the Indodax TAPIv2 key and secret (Read + Spot Trade only; if rotating after a suspected compromise,
   revoke the old key at Indodax first per R7) and the Telegram bot token. Each save requires your account password
   for step-up authentication (ADR-046) and runs a read-only test before overwriting the ciphertext.
6. Confirm both credentials report `readable: true` and a passing test timestamp, check reconciliation, and only
   then resume explicitly with a note.

## R11 — Notification channel down

In-app alerts still exist. Check the app. Fix the channel token or provider issue.

## R12 — Breaker tripped

Read which limit and the values. Decide whether the cause is market behavior or a defect. Leave it halted
until you understand it; resume is explicit and needs a note.

## R13 — Host PostgreSQL hardening and `aidss_app` role isolation (ADR-021)

The analysis stack (`api` and `worker`) must connect as the limited role `aidss_app` (which owns `schema public`
and has zero privileges on `schema trading`), never as the bootstrap superuser `aidss`, and host port 5432 must not
be exposed to the network.

1. **Pre-check active connections** before closing port 5432:
   ```sh
   docker exec stocks-postgres-1 psql -U aidss -d aidss -c \
     "SELECT client_addr, usename, application_name, state FROM pg_stat_activity WHERE client_addr IS NOT NULL;"
   ```
2. **Rehearse on a scratch clone first** (never run untested role changes on `aidss` directly):
   ```sh
   sh deploy/trader/rehearse_isolation.sh stocks-postgres-1 aidss aidss
   ```
   The script clones `aidss` into a temporary scratch database via `pg_dump | psql`, applies `deploy/trader/isolate_analysis_role.sql`, assigns a random temporary password via stdin, verifies `aidss_app` attributes and `schema trading` denial, times `deploy/trader/rollback_analysis_role.sql`, and drops both the scratch database and `aidss_app` on exit.
   The rehearsal scripts read `deploy/trader/*.sql` by relative path and the VM has no repository checkout, so run them from a
   copy of `deploy/trader/` placed by the owner (or the main agent) for the duration of the run, and delete it afterwards. Do not leave
   dumps on the host: the scripts use `umask 077` and remove their dump on exit.
3. **Apply to `aidss`** after owner approval and a fresh `pg_dump` backup:
   - Run `deploy/trader/isolate_analysis_role.sql` as superuser `aidss`.
   - Set random passwords for `aidss_app` and rotate the superuser `aidss` password (`ALTER ROLE ... PASSWORD`),
     recording `AIDSS_APP_DATABASE_URL` in `~/.aidss-trader.env` (mode `0600`).
   - Apply the Compose override (`deploy/trader/docker-compose.trader.yml`) via stdin so `postgres` unpublishes host
     port 5432 (`ports: !reset []`) and `api` / `worker` connect via `AIDSS_APP_DATABASE_URL`.
4. **Rollback** if the analysis API or worker fails startup or migration:
   - Run `deploy/trader/rollback_analysis_role.sql` as superuser `aidss` to return `public` object ownership to
     `aidss`.
   - Point `AIDSS_APP_DATABASE_URL` in `~/.aidss-trader.env` back to the superuser URL and re-run `docker compose up -d --no-build`.

## R14 — Out-of-process liveness monitor and restore rehearsal (T6-03, T6-04)

### Installing the host liveness monitor (`deploy/trader/check_liveness.py`, ADR-039)

Do **not** enable the scheduled monitor until the Trader is intentionally running (while the Trader container is stopped or idle without a lease, a stale-heartbeat check will alert).

1. As `root` on the host (`10.1.200.13`), create `/root/.aidss-monitor-telegram.env` with mode `0600`:
   ```sh
   install -m 0600 /dev/null /root/.aidss-monitor-telegram.env
   cat <<'EOF' > /root/.aidss-monitor-telegram.env
   TELEGRAM_BOT_TOKEN=<your-bot-token>
   TELEGRAM_CHAT_ID=<your-chat-id>
   EOF
   ```
2. Set a password for `trader_monitor` in PostgreSQL (`ALTER ROLE trader_monitor PASSWORD '...';`) and store
   `AIDSS_MONITOR_DATABASE_URL` in `/root/.aidss-monitor-db.env` (mode `0600`).
3. Test the check once manually (it exits `0` when the heartbeat in `trading.lease` is ≤ 15 s old, or `1` and sends
   a Telegram message when stale):
   ```sh
   set -a; . /root/.aidss-monitor-db.env; set +a
   python3 /path/to/deploy/trader/check_liveness.py \
     --token-file /root/.aidss-monitor-telegram.env \
     --state-file /var/run/aidss-trader-liveness.json \
     --max-age-s 15 --cooldown-s 300
   ```
4. Schedule via root `crontab` (or a systemd timer) every minute once the Trader is running.

### Running the non-destructive restore rehearsal (`deploy/trader/rehearse_restore.sh`, ADR-040)

1. On the host (`10.1.200.13`), run:
   ```sh
   sh deploy/trader/rehearse_restore.sh stocks-postgres-1 aidss aidss
   # Or for a full-database dump rehearsal (both `public` and `trading`):
   sh deploy/trader/rehearse_restore.sh --full stocks-postgres-1 aidss aidss
   ```
2. The script dumps `schema trading` (or the full database with `--full`), creates a temporary scratch database (`aidss_restore_rehearsal_<timestamp>`),
   applies `bootstrap.sql`, restores the dump, verifies table counts and that `trader_rw` cannot `UPDATE`/`DELETE`
   `trading.audit_log` or `trading.ledger_entry` while `trader_monitor` can only `SELECT` `trading.lease`, prints
   the elapsed time in seconds, and drops the scratch database.
3. Record the output and elapsed seconds in `MEMORY/records/` before checking the T6-03 box in `12-DELIVERY-PLAN/05`.


## R15 — Updating the Trader image's dependencies (ADR-050, ADR-053)

The Trader image installs from `requirements-trader.lock`, a hash-pinned lock compiled from `requirements-trader.in`. A build either gets exactly
those files or fails (`pip install --require-hashes --no-deps`). Nothing updates by itself, so someone has to do this on purpose: when a security
advisory names one of the 28 packages, when `pyproject.toml` raises a bound, or before a release.

1. Edit `requirements-trader.in` only if a requirement is added, removed, or its bound changes. A bound must match `pyproject.toml` (a test checks it);
   a new third-party import in `src/aidss_trader` or `alembic_trader` must be added here (another test names the missing one).
2. Regenerate the lock inside the same Python as the image, not on the workstation (hashes are per platform):
   ```sh
   docker run --rm -v "$PWD:/w" -w /w python:3.12-slim sh -c      "pip install -q uv && uv pip compile requirements-trader.in --generate-hashes       --python-version 3.12 --python-platform linux --no-header -o requirements-trader.lock"
   ```
   The compile step overwrites the header comment; restore it from git (`git diff` shows it) so the regeneration command stays in the file.
   To move one package only, add `--upgrade-package <name>` to the `uv pip compile` command.
3. Read `git diff requirements-trader.lock` by package name and version, not by hash. Anything that was not expected to move is a reason to stop.
4. Build the image (`docker build -f Dockerfile.trader`), then check: `pip check` in the image is clean; every module under `aidss_trader` imports; a throwaway
   PostgreSQL accepts `alembic upgrade head` as `trader_owner`; the Trader started as `trader_rw` reports `HALTED`, `healthy`, and answers `/trader/v1/status`
   with `401`; and the Trader tests pass inside the image's own dependency set (see `MEMORY/records/2026-11-15-trader-image-own-dependencies.md`).
5. Run `python -m pytest tests/trader tests/test_architecture_constraints.py` and `ruff check src tests alembic_trader deploy`. Commit the lock, a record in
   `MEMORY/records/`, and the index line together. Deploying the new image is a separate step with its own approval; the Trader stays `HALTED`.

The base image is the floating tag `python:3.12-slim`, so the operating-system layer changes with each build; pinning its digest would stop that but also stop OS
security patches (ADR-050, option 3, not adopted).

## R16 — Anchor stale or failing (ADR-054)

`deploy/trader/aidss-anchor-watch.sh` (draft cron `deploy/trader/aidss-anchor-watch.cron`, not installed) checks `anchor.jsonl` and `anchor.log` under `AIDSS_ANCHOR_DIR` (default `/var/lib/aidss-anchor`) without calling Docker or the database. It requires an explicit positive `AIDSS_ANCHOR_MAX_AGE_S` (no hidden default; owner decision):

- Exit `0`: latest `rc=0` line in `anchor.log` is newer than `AIDSS_ANCHOR_MAX_AGE_S` and latest run succeeded.
- Exit `1`: latest `rc=0` is stale or missing, or latest run failed with a non-`2` exit code (check cron status, `AIDSS_TRADER_DATABASE_URL`, and `anchor.log`).
- Exit `2`: latest run exited `2` (`user.crit` logged; audit chain or external anchor verification failed — `HALT` the Trader and investigate DB/anchor integrity before resuming).
- Exit `3`: `AIDSS_ANCHOR_MAX_AGE_S` is unset or invalid (or test clock invalid).
- Exit `4`: `anchor.jsonl` or `anchor.log` is missing, empty, or unreadable.

If `AIDSS_ANCHOR_ALERT_CMD` is set to an executable path, the watcher invokes it once with a fixed status message (no log contents, no built-in token or sender).

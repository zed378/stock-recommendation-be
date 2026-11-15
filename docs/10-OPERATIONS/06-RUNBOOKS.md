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

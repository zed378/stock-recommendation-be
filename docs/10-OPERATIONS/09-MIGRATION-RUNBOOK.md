# 09 — Migration Runbook: moving AIDSS to another host

| | |
|---|---|
| **Status** | Draft, 2026-11-17. The kit is rehearsed on synthetic data and its compose file is proven equal to the running stack; **no real migration has been done and no timing is measured** |
| **Owner** | The Owner, with the DevOps role |
| **Kit** | `deploy/production/` (`docker-compose.production.yml`, `production.env.example`, `preflight.sh`, `restore.sh`, `fingerprint.sh`) |
| **Related** | `04-BACKUP-RESTORE-AND-RECOVERY.md`, `06-RUNBOOKS.md` (R9, R10, R13), ADR-001, ADR-014, ADR-021, ADR-027, ADR-029 |

This is for moving the Compose stack as it runs today (PostgreSQL, api, worker, frontend, trader) to another Linux host. It is written so
that you can start on any day without remembering how the current host was put together. Read section 1 first: most of what makes a move
go wrong is something that lives on the host and not in the repository.

## 1. What moves, and what does not

| Thing | Where it lives today | How it moves | Byte for byte? |
|---|---|---|---|
| Database: analysis data, the `trading` schema, **roles and their password hashes** | Docker volume `stocks_postgres_data` (about 509 MB on disk, about 71 MB as a gzipped dump) | `pg_dumpall` streamed, encrypted in transit, restored with `restore.sh` | n/a (use `fingerprint.sh`) |
| `AIDSS_JWT_SECRET` | `~/stocks/.env` | Typed or copied by you, never through chat | **Yes.** A different value logs everyone out and makes every stored provider key unreadable (`security/secrets.py`) |
| Trader master key | `~/.aidss-trader-master.key` (44 bytes, mode 600) | A separate channel from the dump, **never inside a backup** (ADR-014, ADR-029, R10) | **Yes.** Without it the Trader's stored credentials are unreadable and it fails closed |
| Database URLs and passwords | `~/.aidss-trader.env` (`AIDSS_APP_DATABASE_URL`, trader URLs) | Copied with the `.env`; the passwords inside the URLs match the role hashes in the dump | Yes |
| Other settings and API keys (`AIDSS_ENVIRONMENT`, AI endpoint and key, market-data keys) | `~/stocks/.env` | Merged into the new `.env` | Yes: the old values were not all defaults |
| Compose file | `~/stocks/docker-compose.yml` plus a stdin override | **Replaced by** `deploy/production/docker-compose.production.yml` and one `.env` | n/a |
| Images | Docker Hub, `zed378/aidss-*` (public today) | Pulled on the new host by tag or digest | n/a |
| `stocks_storage_data` volume (`/app/var`) | Docker volume | Empty today (0 files, 4 KB); **check again before the move** | If it has files, copy them |
| Audit anchor file | `/var/lib/aidss-anchor/anchor.jsonl` once `aidss-anchor` is installed (ADR-054) | Copy it, then `chattr +a` on the new host | Yes: it is the tamper evidence; a new file starts the chain over |
| **Host glue that does not move by itself** | `cloudflared` (systemd, token in `/etc/cloudflared/token`) and the Cloudflare DNS; netbird; cron (`aidss-anchor`); firewall; NTP; SSH and deploy credentials | Rebuilt by hand, see section 5 | n/a |
| Backups | `~/aidss-backups/`, same host as the database | Leave them behind or copy them encrypted; delete the plaintext ones on the old host afterwards | n/a |

## 2. What is special about the Trader

- **Never two writers.** The Trader holds a database lease (ADR-027); still, never start it on the new host while the old one is running, and never
  resume trading on either until the other is stopped and the first has reconciled.
- **Move while `HALTED`.** It is `HALTED` today and has never touched an exchange. If that ever changes before a move: halt, wait until no order is open on the exchange,
  and after the move let the reconciler run and read its result before resuming (the exchange is the source of truth, ADR-022).
- **Source IP at the exchange.** An Indodax API key may be restricted by source address (`06-INTEGRATIONS`); add the new host's address before the key is ever used from there.
  There is no stored key today, so this is a reminder for the day there is one.
- **Credentials.** After the restore the Trader's credential screen must say `readable`; if it does not, the master key is not the old one.
- **Clock.** The Trader halts when the clock is more than 250 ms off (ADR-041). `preflight.sh` fails if NTP is not synchronised.
- **Paper evidence continues.** Paper fills, the ledger and the audit chain are in the database and arrive with it. Do not "start fresh" to make a move easier: the four weeks of paper (ADR-020) would restart.

## 3. Before the day (can be done any time, with no downtime)

1. **A new host:** Linux, x86-64 (the published images are `linux/amd64` only; for ARM build multi-arch images first), Docker with Compose v2, NTP running, at least 5 GB free, a user whose uid you will pass as `AIDSS_TRADER_UID`/`GID` (default 1000).
2. **Copy the kit:** the three scripts, `docker-compose.production.yml` and `production.env.example` into one directory, for example `/opt/aidss`.
3. **Build the new `.env`** from the old files: `~/stocks/.env` + `~/.aidss-trader.env` + `POSTGRES_PASSWORD` (any new random value; it is only read on first start) + `AIDSS_TRADER_MASTER_KEY_PATH` + the three image pins.
   Pin by tag or digest: `docker buildx imagetools inspect zed378/aidss-api:latest` prints the digest. Never `latest` for the Trader. `chmod 600 .env`.
4. **Run `sh preflight.sh`** on the new host. Every FAIL is a reason not to start. It checks the machine, the `.env` (as text, never sourced), the master key file (present, mode 600, 44 bytes), the compose file, and that each image can be found in the registry.
5. **Lower the DNS TTL** if you plan to change records (not needed if the same Cloudflare tunnel is moved, section 5).
6. **Rehearse once with the real dump on a scratch host**, following section 4 from the top, and write down the real timings in your copy of this page. The kit was only rehearsed on synthetic data in throw-away containers
   (`tests/trader/test_migration_kit.py`); a real dump is what shows a surprise (an extension, a role, a size).

## 4. The cutover

Times below are **estimates, not measurements** (labelled): expect minutes of restore for a 71 MB dump and an outage of about 15 to 30 minutes end to end if nothing surprises you.

**A. Freeze the old host** (it stays intact; it is only stopped)

1. Halt the Trader from the Trader screen (note it), or `POST /trader/v1/kill {"tier":"HALT"}`. Confirm `trading_state` is `HALTED`.
2. Stop the writers, **not PostgreSQL**: `docker stop stocks-frontend-1 stocks-trader-1 stocks-worker-1 stocks-api-1`. The worker keeps writing (`job_queue`, `alerts`, `leader_leases`), so counts only match once it is stopped.
3. `AIDSS_ENV_FILE=~/stocks/.env sh fingerprint.sh > fingerprint-old.txt` (read-only; prints counts, versions, roles, the trading state, the audit head, and short hashes of the JWT secret and the master key).

**B. Capture**

4. The dump, streamed and encrypted: `deploy/trader/backup_offhost.sh` when it exists; until then, on the old host
   `docker exec stocks-postgres-1 pg_dumpall -U aidss --quote-all-identifiers | gzip -6 | openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt -out dump.sql.gz.enc` (passphrase typed at the prompt) and copy the file with `scp`. Note the `sha256sum`.
5. The `.env`, the master key file and (if present) `anchor.jsonl`: **separate channels**, your own credentials, never chat, never the dump's channel. Keep the master key out of every backup.

**C. Restore on the new host**

6. `docker compose -f docker-compose.production.yml up -d postgres` and nothing else (the api runs migrations when it starts; a restore over the tables it just made fails).
7. `openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -in dump.sql.gz.enc | gunzip | sh restore.sh`. It refuses if an application container is running or the database already has tables. It tolerates only "already exists" (the image creates the `aidss` role and database before the dump does).
8. `AIDSS_ENV_FILE=.env sh fingerprint.sh > fingerprint-new.txt` and `diff fingerprint-old.txt fingerprint-new.txt`. **It must be empty.** A difference in a count, in the roles, in the Alembic heads or in a secret hash stops the move.

**D. Bring up, one service at a time, always `--no-deps`**

9. `docker compose -f docker-compose.production.yml up -d --no-deps api` and wait for `healthy` (its start runs `alembic upgrade head`, a no-op when the heads match), then `worker`, `frontend`, `trader` the same way.
10. The Trader must come up `HALTED` with the state it had. Do not resume it.

**E. Verify before any traffic**

`docker ps` (all healthy); `curl -s 127.0.0.1:5173/api/health`; sign in through a browser pointed at the new host (an `/etc/hosts` entry or an SSH tunnel to port 5173); the Trader pages load, the status is `HALTED`, the credential page says `readable` if one is stored;
the Admin AI providers page lists the providers and a test call works (proves the JWT secret is the old one); `docker exec <trader> python -m aidss_trader healthcheck` exits 0; the logs hold no traceback.

**F. Move the traffic**

11. With the same Cloudflare tunnel: install `cloudflared` on the new host with the same tunnel token (`/etc/cloudflared/token`, a systemd unit), start it, check `curl -sI https://aidss.zedth.my.id/`, then stop and disable it on the old host. Two connectors for one tunnel run side by side, so there is no gap.
    The tunnel's service points at `127.0.0.1:5173`, which is where the new frontend listens.
12. Another way in (a reverse proxy or a new tunnel) means a DNS change; use the lowered TTL and check from outside the LAN.
13. Install the cron for `aidss-anchor`, copy `anchor.jsonl`, `chattr +a` it, run it once. Re-apply the firewall plan (`08-HOST-FIREWALL-PLAN.md`) and the NTP and backup arrangements.

**Rollback.** Until the new host has accepted a write the old one is intact: start its containers (`docker start stocks-api-1 stocks-worker-1 stocks-frontend-1 stocks-trader-1`), start its `cloudflared`, stop the new one. After the new host has accepted writes the databases diverge:
rolling back means losing them, or dumping the new one and restoring it back with this same procedure in the other direction. Keep the old host untouched, and stopped, for a stated period (suggested: two weeks) before it is wiped.

## 5. After the move

- Record it in `MEMORY/records/` with the real timings and every surprise; update the host address and paths in `CLAUDE.md` and the runbooks.
- On the old host: stop the stack, `shred` the plaintext dumps in the home directory and `~/aidss-backups/`, remove the volumes, `~/.aidss-pg-superuser`, both env files, `~/.aidss-trader-master.key`, `/etc/cloudflared/token`.
- **Rotate what travelled:** the database role passwords (R13 shows how), the SSH password, and the Cloudflare tunnel token, because each existed on two hosts for a while. The JWT secret and the master key are not rotated casually (see section 1).
- Make a first off-host backup from the new host and rehearse a restore from it (R9); the new host has the same single-failure-domain weakness as the old one until you do.

## 6. Cautions and variants

- **Architecture:** ARM needs images built for it; `preflight.sh` warns.
- **Managed PostgreSQL** (not covered): `pg_dumpall` restores need role creation rights that managed services withhold, and the `vector` extension must be allowed; plan a `pg_dump` per database plus a script for the roles and grants (`deploy/trader/bootstrap.sql`, `isolate_analysis_role.sql`).
- **Growth:** `job_queue` is the largest table by rows (tens of thousands today); a retention rule shrinks the dump and the restore.
- **Compose behaviour:** the `up` rules of `CLAUDE.md` (Traps) apply on the new host too: `--no-deps`, one service at a time, `docker ps` before and after, and pin the PostgreSQL image (`AIDSS_POSTGRES_IMAGE`) to a digest so a moving tag cannot recreate the database container.
- **What is proven and what is not:** the compose file's effective configuration for all five services was compared with the running stack on 2026-11-17 and is identical (images, ports, volumes, secrets, dependencies, health checks, user, hash of the whole environment);
  the restore, the guards and the fingerprint were rehearsed on throw-away containers; the preflight script was syntax-checked. Not proven: a restore of the real dump, a real second host, the tunnel move, the timings, and the Indodax side.

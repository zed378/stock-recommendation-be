# Host hardening step 1: `pg_dumpall` backup of the production PostgreSQL (2026-11-16)

First step of the host hardening plan (runbook R15, `deploy/trader/isolate_analysis_role.sql`), which requires "a fresh backup" before any role or password change. Nothing else of the plan was applied.

## What was done

- Cluster dump of `stocks-postgres-1` (PostgreSQL 16) as superuser `aidss`: `pg_dumpall --quote-all-identifiers | gzip -6`, on the VM as `infra`, `umask 077`, into a new directory
  `~/aidss-backups/` (mode `0700`; the older `~/backups/` is owned by root and could not be used). File `pg_dumpall-20261116T100117Z.sql.gz`, 71,658,336 bytes, mode `0600`,
  sha256 `2c71e9d93cfda9857b2fcc717f0ec2e391175640a8c05eb0326025dad9584748`. Source database size 339 MB.
- The master key `~/.aidss-trader-master.key` was **not** copied into the backup directory (ADR-014, ADR-029, runbook R10).

## Verification

- `gzip -t` passed; the dump ends with `PostgreSQL database cluster dump complete`; it holds one `CREATE DATABASE`, 77 `COPY` blocks and the roles `aidss`, `trader_owner`, `trader_rw`, `trader_monitor`.
- Restore rehearsal: the dump was loaded into a throw-away `pgvector/pgvector:pg16` container (`--network none`, tmpfs data, random password, removed afterwards). Only 2 stderr lines, both "already exists" (the
  default `postgres` database and role). Row counts of all 77 base tables, live against restored, were identical (diff empty); examples: `public.users` 3 rows, every `trading.*` table 0 rows except
  `trading.alembic_version` 1 (the Trader has never traded, consistent with `HALTED`).

## Limits and risks

- The backup is on the same host as the database, so a lost or compromised host loses both. An off-host copy has not been made; it would put the dump (users table, password hashes of the roles, encrypted
  credential rows) on another machine and is the owner's call.
- No retention or rotation: the single file stays until the owner says otherwise.
- The restore rehearsal proves the dump loads and counts match on PostgreSQL 16; it does not exercise the application against the restored data.

## Next steps of the plan (each needs the owner's go-ahead)

1. Apply `isolate_analysis_role.sql` as `aidss` (creates `aidss_app`), then set passwords and record `AIDSS_APP_DATABASE_URL`.
2. Switch api and worker to `aidss_app`, unpublish port 5432 through the Compose override, rotate the superuser password.
3. Rollback path: `rollback_analysis_role.sql` and the restore of this dump.

---

## Step 1 applied: role `aidss_app` created on production (2026-11-16, after the owner's go-ahead)

Rehearsal first, on the VM, because the earlier rehearsals ran on a local PostgreSQL 18: `rehearse_isolation.sh stocks-postgres-1 aidss aidss` against a scratch clone of `aidss` on the production PostgreSQL 16 (clone 12s, isolation under 1s,
rollback under 1s; `aidss_app` not superuser, owns every `public` table, `trading.audit_log` denied for it, DDL in `public` allowed). The scripts were placed in `~/rh` for the run and the directory, the scratch database and the temporary role were removed afterwards.

Applied for real, as superuser `aidss` in database `aidss`, with `ON_ERROR_STOP=1` (the file is one transaction): `deploy/trader/isolate_analysis_role.sql`. Then a random 48-hex-character password was set through stdin
(`ALTER ROLE aidss_app PASSWORD`, never on a command line) and `AIDSS_APP_DATABASE_URL=postgresql+psycopg://aidss_app:<password>@postgres:5432/aidss` was appended to `~/.aidss-trader.env` (mode `0600`). No password appears in this repository, the log or the shell history.
The helper scripts and the SQL copy on the host were deleted.

Verified after: connecting as `aidss_app` over TCP works and reads `public.users` (3 rows); `select count(*) from trading.audit_log` fails with `permission denied for schema trading`; the role is `rolsuper=f, rolcreatedb=f, rolcreaterole=f, rolbypassrls=f`;
no `public` table has an owner other than `aidss_app`; all containers stayed healthy (nothing was restarted), Trader healthcheck exit 0, `trading_state` `HALTED`, `/api/health` 200.

Not changed on purpose: `api` and `worker` still connect as the superuser `aidss` (`docker-compose.yml` on the host carries `AIDSS_DATABASE_URL: postgresql+psycopg://aidss:aidss@postgres:5432/aidss`, a literal weak password, which the next step replaces through the override),
port 5432 is still published, and the superuser password is unchanged. Until step 2 the isolation is prepared, not in force.

Rollback of step 1: run `rollback_analysis_role.sql` as `aidss` (returns ownership of `public` objects to `aidss`, rehearsed at under 1s on the clone), then `DROP ROLE aidss_app` once nothing connects as it, and remove the `AIDSS_APP_DATABASE_URL` line from `~/.aidss-trader.env`. The pre-change dump is `~/aidss-backups/pg_dumpall-20261116T100117Z.sql.gz`.

Next (needs the owner's go-ahead): step 2, switch `api` and `worker` to `aidss_app` through the override, unpublish port 5432 (`ports: !reset []`), then rotate the superuser password; check the pre-step `pg_stat_activity` for any outside client first (R13, point 1).

---

## Step 2 applied: api and worker on `aidss_app`, port 5432 closed, superuser password rotated (2026-11-16, after the owner's go-ahead)

Pre-check (R13 point 1): `pg_stat_activity` showed only Compose-network clients (`172.22.0.x`: api, worker, trader), none from outside. Three sub-steps, each verified before the next, all through the stdin Compose override
(`up -d --no-build <service>`, env from `~/.aidss-trader.env`); `docker-compose.yml` on the host was not edited.

- **2a, api and worker as `aidss_app`:** override sets `AIDSS_DATABASE_URL: ${AIDSS_APP_DATABASE_URL}` for both; only `api` and `worker` were recreated. `docker compose config` resolved both to `aidss_app`.
  After: `pg_stat_activity` shows `aidss_app` for both, `trader_rw` for the Trader, no `aidss` connection; api healthy, `/health` 200, worker started with the leader lease; no error in the api log.
- **2b, port 5432 closed:** override adds `postgres: ports: !reset []` (as in `deploy/trader/docker-compose.trader.yml`); `postgres` was recreated (same volume, data kept). Before: a TCP connect from the owner's workstation to `10.1.200.13:5432` succeeded;
  after: `Connection refused`, `ss -ltn` shows nothing on 5432. The Trader, api and worker reconnected on their own; the api's realtime listener logged one reconnect warning at the restart and was listening again within a second.
- **2c, superuser password:** `ALTER ROLE aidss PASSWORD` with a random 48-hex-character value through stdin, stored only in `~/.aidss-pg-superuser` (mode `0600`, outside the file Compose reads). From another container the old password `aidss` is now refused
  (`password authentication failed`); the new one works. Administration through `docker exec stocks-postgres-1 psql -U aidss` is unchanged (the image's `pg_hba.conf` trusts the local socket and `127.0.0.1` inside the container).

Verified after all three: containers healthy, Trader healthcheck exit 0 and `trading_state` `HALTED`, `/`, `/login` and `/api/health` answer 200.

Still open, not part of this step:
- The host's `docker-compose.yml` keeps `AIDSS_DATABASE_URL: ...aidss:aidss@...` and `POSTGRES_PASSWORD` defaults for a fresh start without the override; with the password rotated that URL no longer works, so `up` **without** the stdin override would start api and worker
  that cannot connect. The deploy recipe must keep using the override (it already does); the base file on the host should be fixed by the owner or the main agent.
- Other ports published on the host: api `7153` and frontend `5173` (reachable directly, bypassing the reverse proxy); not examined here.
- The superuser password and `AIDSS_APP_DATABASE_URL` are single copies on the host; the backup `~/aidss-backups/pg_dumpall-20261116T100117Z.sql.gz` is on the same host.
- Not exercised: a logged-in user flow and a worker job run as `aidss_app` after the change (health, connections and logs only).

Rollback of step 2: set `AIDSS_DATABASE_URL` back to the superuser in the override (using the stored superuser password) and recreate `api` and `worker`; re-add `ports: ["5432:5432"]` to bring the published port back; the dump is the last resort.

---

## Step 3: ports 7153 and 5173, public API docs, and an unplanned database outage (2026-11-16 to 2026-11-17)

Findings, measured from the owner's workstation and the host: `10.1.200.13:7153` (api) and `:5173` (frontend) answered from the LAN; the host has no firewall (`ufw` inactive, `INPUT` policy `ACCEPT`);
the api answered `/docs`, `/openapi.json` and `/health` without a token (`/health` reports `"environment":"development"`), and `https://aidss.zedth.my.id/api/docs` and `/api/openapi.json` answered 200 through Cloudflare without signing in.
`AIDSS_ENVIRONMENT=development` only changes that echo (`is_production` is not used elsewhere in `src/aidss`). The JWT secret starts with the repository's default prefix `dev-only-change-me` followed by 27 random-looking characters;
it was not rotated (a rotation makes stored provider keys unreadable) and its value was never printed. The public site reaches the frontend through a host `cloudflared` (systemd) that connects to `127.0.0.1:5173`, not through the `wedding-staging` tunnel container.

Done with the owner's choices:
- **Port 7153 closed** (`api: ports: !reset []` in the stdin override, only `api` recreated). Connect from the workstation: refused. The public site and `/api/health` stayed 200.
- **Public API docs refused at the edge:** `frontend/nginx.conf` returns 404 for `/api/docs`, `/api/redoc`, `/api/openapi.json` and `/api/docs/oauth2-redirect` (a regex location ahead of the `/api/` proxy); a test in `tests/test_frontend_routing.py` pins both what is refused and what is not.
  Deployed as `aidss-frontend:57b8f97` (digest `sha256:eea57bf146d935a52780c975895457d8f4e6d1c981cbe659b7c38e11b9aed47a`), `latest` moved to it. Verified on production: the four paths answer 404, `/`, `/login`, `/watchlist`, `/trader` 200, `/trader/v1/status` 401, `/api/health` 200.
- **Port 5173 left as is, pending the owner:** the only client seen on it is the host's own `cloudflared` over loopback, so binding it to `127.0.0.1` would very likely keep the public site working and close LAN access, but it was not applied.

### Incident: PostgreSQL recreated twice, about 2 minutes 15 seconds of database outage

While deploying the frontend I ran `docker compose pull frontend` and then `up -d --no-build frontend` in one SSH command, both reading the override from stdin. The `up` recreated PostgreSQL: the local tag `pgvector/pgvector:pg16`
now points at a newer image (id `484e838076e0`, PostgreSQL 16.16, pgvector 0.8.6) than the one the running container was created from (an older image now untagged), and `up` without `--no-deps` recreates dependencies. Because `pull` had consumed the stdin, that `up` ran
with an empty override: the base `docker-compose.yml` (published 5432, the old superuser URL) was applied to PostgreSQL, the api recreate failed (`No such image: stocks-api:latest`), and the new PostgreSQL container was created but not started. Result: api and worker logged connection errors from
03:04:52 to about 03:07:07 UTC, the Trader restarted in a loop (restart counter 16 on the current container, includes earlier restarts), until I recreated PostgreSQL with the correct override. A second recreate followed (a few seconds) because the `up` was repeated.
Cause of the tag move: not established; a `pull` of the frontend with its dependencies is the likely trigger, unverified.

State after: PostgreSQL 16.16 with pgvector 0.8.6 (same major, clean start, no error in its log), data intact (`public.users` 3 rows, `trading_state` `HALTED`), api and worker reconnected as `aidss_app`, Trader as `trader_rw`, Trader healthcheck exit 0,
port 5432 not published (refused from the workstation), 7153 refused, all containers healthy. The pre-incident dump `~/aidss-backups/pg_dumpall-20261116T100117Z.sql.gz` was not needed. Any scheduled screen or job that ran inside the window may have failed once; none was checked.
Lessons recorded in `CLAUDE.md` (Traps): always `--no-deps`, one command per SSH call that reads stdin, check `docker ps` before and after. The PostgreSQL minor upgrade (older 16.x to 16.16) was an unintended side effect, not a decision.

---

## Step 4: port 5173 bound to 127.0.0.1 (2026-11-17, after the owner's go-ahead)

Before changing anything: over six seconds of public requests, all 12 sampled established connections to `:5173` had peer `127.0.0.1`, and the only other listener consumer is the host `cloudflared` (systemd, root), so the public site reaches the frontend over loopback and not over the LAN address.
`docker compose config` with the new override showed `host_ip: 127.0.0.1, published: 5173`.

Applied with one command: the stdin override gains `frontend: ports: !override ["127.0.0.1:5173:80"]`, `up -d --no-build --no-deps frontend` (only `stocks-frontend-1` recreated; PostgreSQL, api, worker and Trader untouched, uptimes unchanged).
Verified after: `docker ps` shows `127.0.0.1:5173->80/tcp`, healthy; the host listens on `127.0.0.1:5173` only; a request to `127.0.0.1:5173` on the host answers 200; public `/login` answered 200 eight times in a row, and `/`, `/watchlist`, `/trader`, `/admin`, `/api/health` 200, `/api/docs` 404, `/trader/v1/status` 401;
from the owner's workstation, `10.1.200.13` ports 5173, 7153 and 5432 are all refused; Trader healthcheck exit 0, `trading_state` `HALTED`.

Not verified: any consumer that reached `10.1.200.13:5173` directly over the LAN or the netbird interface (none was seen in the sample; it is cut off now); an internal DNS name for the site that might point at a LAN reverse proxy (the DNS suffix lookup `aidss.zedth.my.id.bodha.co.id` answered `10.10.10.6`, which was not probed).
Rollback: remove the `ports: !override` lines from the frontend block of the override and run the same single `up -d --no-build --no-deps frontend` (about 10 seconds; not rehearsed).

---

## Step 5: the host's `docker-compose.yml` hardened (2026-11-17, after the owner's go-ahead)

`~/stocks/docker-compose.yml` on the host was the development file copied there on 2026-09-01. It is owned by `root` and `~/stocks` is not writable by `infra`, so the edit ran through `sudo -n` (passwordless for `infra`, already used read-only for `ufw status`), limited to a script that edits that one file; owner and mode stayed `root:root 644`.
A backup was made first: `~/stocks/docker-compose.yml.bak-20261117`.

Changes (shown with the password and JWT secret lines masked): `AIDSS_DATABASE_URL` is now `${AIDSS_APP_DATABASE_URL:?...}` (the old `aidss:aidss` superuser URL is gone, and a bare `up` without the variable refuses instead of connecting as the superuser); the published ports `5432` and `7153` were removed and `5173` became
`127.0.0.1:5173:80`; `build: .` and `build: ./frontend` became `image: ${AIDSS_API_IMAGE:-zed378/aidss-api:latest}` and `image: ${AIDSS_FRONTEND_IMAGE:-zed378/aidss-frontend:latest}`, so an `up --build` can no longer replace a deployed image; a comment block says why.
`POSTGRES_PASSWORD` was first changed and then put back exactly: the change altered the database container's configuration hash, so the next `up` would have recreated PostgreSQL, the surprise behind the 2026-11-17 outage. The value is stale anyway (the superuser password was rotated) and is only read on first initialisation.

Verification (no container was touched; `docker compose config` and `up --dry-run` only): with the variable unset, `config` fails with `required variable AIDSS_APP_DATABASE_URL is missing a value`; with the stdin override, the effective configuration of all five services before and after differs only in the removed `build` flag of api, worker and frontend (image, ports, environment hash, user in the database URL, dependencies all identical);
`up -d --no-build --no-deps --dry-run` on all five services reports every container `Running` and no `Recreate`; the temporary helper files on the host were deleted.

Open at that point (corrected in step 6): the file's JWT line and the permissions of `~/stocks/.env`. **The claim made here that the compose file held the JWT secret as a literal was wrong**; see below.
Rollback: `sudo cp -p ~/stocks/docker-compose.yml.bak-20261117 ~/stocks/docker-compose.yml`.

---

## Step 6: JWT secret and `.env` permissions (2026-11-17, after the owner's go-ahead), and a correction

Inspection first, with no value printed (hashes, lengths and key names only). **Correction:** the host compose file does not hold the JWT secret. Its line was `AIDSS_JWT_SECRET: ${AIDSS_JWT_SECRET:-dev-only-change-me}`, the repository's public 18-character default; the real secret (45 characters) is in
`~/stocks/.env`, which compose reads automatically, and the running api and worker use that value (their value's hash differs from the default's). `~/stocks/.env` also holds the AI provider settings (`AIDSS_AI_API_KEY`, 7 characters) and the provider and environment switches; it is ignored by the host's git, was never committed, and only the `infra` user (the sole member of the `docker` group) exists besides root.

Changes: `~/stocks/.env` is now `infra:infra`, mode `600` (it was `root:root 644`; compose runs as `infra`, so it can still read it). The compose line became `AIDSS_JWT_SECRET: "${AIDSS_JWT_SECRET:?set AIDSS_JWT_SECRET (~/stocks/.env)}"`, so a missing or unreadable `.env` stops the start instead of silently running on the public default.
Backups: `docker-compose.yml.bak-20261117` (before step 5) and `docker-compose.yml.bak-20261117b` (before this edit); neither holds a secret.

Verification (no container touched): the effective configuration of all five services with the override is identical before and after (environment hashes equal, so the resolved secret is byte-identical); with `--env-file /dev/null` the base file refuses with `required variable AIDSS_JWT_SECRET is missing a value`; `up --dry-run` reports all five containers `Running`, no `Recreate`; the containers stayed healthy, the Trader healthcheck exit 0, public `/`, `/login`, `/api/health` 200.

Not changed: the secret's value (no rotation: a different secret makes stored provider keys unreadable, `security/secrets.py`); its predictable `dev-only-change-me` prefix, which is followed by 27 characters that were not examined for randomness beyond their length; the secret's presence in `docker inspect` output for anyone in the `docker` group.
Rollback: `sudo cp -p ~/stocks/docker-compose.yml.bak-20261117b ~/stocks/docker-compose.yml` and, if ever needed, `sudo chown root:root ~/stocks/.env && sudo chmod 644 ~/stocks/.env`.

# 02 — Deployment Architecture

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | DevOps Engineer |
| **Decided by** | ADR-021 |
| **Open items** | OQ-14 (resolved, ADR-028), OQ-24 (resolved, ADR-030) |

## Current Deployment (analysis platform, for context)

One host runs the Compose project `stocks` with `postgres`, `api`, `worker`, `frontend` and `trader`. Images are
pulled from Docker Hub by tag (`latest` for the analysis images, a commit tag for the Trader, never `latest`, ADR-053).
The Compose file on the host is root-owned and was hardened on 2026-11-17 (no superuser URL, nothing published but the
frontend on `127.0.0.1`, images pulled and never built); deployments still pass an override on standard input that adds the
`trader` service and pins the tags. The same stack is written down in the repository as `deploy/production/docker-compose.production.yml`
with one `.env` (`production.env.example`); its effective configuration was compared with the running stack and is identical.
Moving to another host is described in `09-MIGRATION-RUNBOOK.md`.

## Planned: the `trader` Service

| Aspect | Value |
|---|---|
| Image | `Dockerfile.trader`, built and pushed to a registry repository, tag = commit. **Public during development, private before T5-06 (ADR-030)** |
| Compose | A new service `trader` in the same project, defined with `image:` only (no `build:`), so a host-side rebuild cannot replace it |
| Depends on | `postgres` healthy |
| Restart | `always` |
| Instances | Exactly one active (ADR-027) |
| Environment | Infrastructure settings only (`00-ENVIRONMENTS-AND-CONFIG.md`) |
| Ports | None published by default; the operator surface exposure is OQ-14 |
| User | Non-root |
| Healthcheck | Process alive **and** lease held **and** last cycle recent. A container that runs but has not completed a cycle is unhealthy |
| Resources | A CPU and memory limit so a defect cannot starve the shared host |

Illustrative fragment (placeholders only; values come from the environment, never from this file):

```yaml
services:
  trader:
    image: <private-repo>/aidss-trader:<commit-tag>
    restart: always
    depends_on:
      postgres: { condition: service_healthy }
    environment:
      AIDSS_TRADER_DATABASE_URL: ${AIDSS_TRADER_DATABASE_URL}
      AIDSS_TRADER_MASTER_KEY_FILE: /run/secrets/trader_master_key
    secrets:
      - trader_master_key   # a file on the host, outside git, read-only in the container (ADR-029)
    # no ports published by default

secrets:
  trader_master_key:
    file: <path-on-host-outside-git>
```

## Database

Same PostgreSQL server and database, schema `trading`, role `trader_rw` for the service, `trader_owner` for
migrations run at deploy time (`03-DATA-MODEL/07`). The shared server remains a single failure domain.

## Network

Internal project network. Egress allowlist and trust boundaries: `09-SECURITY-PRIVACY/03`.

## Independent Liveness

The Trader's in-process watchdog dies with the process, so a **separate, out-of-process check** is also
required: something outside the Trader that alerts when its heartbeat stops (`05-SELF-OBSERVABILITY.md`, ADR-039).

## Host Considerations

| Item | Why it matters |
|---|---|
| NTP | `-1021` on skew; a drifting clock halts trading |
| Shared host | The Trader shares CPU, memory, and disk with analysis workloads and Kronos inference |
| Backups on the same host | A host loss loses the data and the backup together; off-host copies are manual (ADR-040) |
| Outbound connectivity | Loss of the route to Indodax degrades to `UNAVAILABLE` handling |

## Deployment Procedure

`03-RELEASE-AND-ROLLBACK.md`.

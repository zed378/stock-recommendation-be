# Indodax builder deployment and image cleanup

Owner authorized deployment and unused server/Docker Hub tag removal. Release code:
`85f7f4530b1450a990b4d1274618ca8ddf4acc5a`, merged to main.

## Deployed

Host `10.1.200.13`, Compose project `stocks`. Preflight found RUNNING, zero LIVE
positions and one PAPER position. The deployment explicitly HALTed the Trader
through KillSwitch (audited trigger `deploy`, actor `owner-deploy`). No resume,
promotion, strategy enablement or risk-number change occurred.

Backup `/home/infra/aidss-pre-85f7f45-trading.dump`: 1,616,784 bytes, custom format;
`pg_restore -l` succeeded, inventory saved alongside it. Same-host backup only.
Applied additive migration `0013_builder_review` as trader_owner using the new
image. Head verified; trader_rw has SELECT/INSERT only on the new review table.

Recreated only Trader/frontend with `--no-build --no-deps`, existing base Compose
and `/home/infra/aidss-deploy-85f7f45.json` override. Runtime settings and master-key
mount preserved. Both healthy after seven minutes. Immutable tag is `85f7f45`:

- Trader: `sha256:5bb2d8aee2808594a563fb5f20c1c361eed9c995af5cc5381c61b9bce0664474`.
- Frontend: `sha256:d52c51bfa4568b43ea620993e9fbfe1f8a202d695f63f54adaa5918e53c872d8`.

API, worker, postgres and existing Binance signals containers were not recreated.
The existing signals worker remains `721e40a`.

## Verification and findings

Internal frontend HTTP check succeeded. Builder schema directly on the Trader
answered 401 without authentication (route served and protected). Head is 0013,
builder_review count zero. State checked HALTED, zero LIVE positions.

Audit verification found a broken chain link at **seq 1423**. Extracting audit data
from the pre-deploy dump and ordering by seq found the same broken link at 1423,
confirming it predates this release. No audit history was rewritten. Final audit
count: 2876. Investigate the cause before live operation. The first HALT attempt
used an overlong trigger and rolled back; the short `deploy` trigger succeeded.

Public HTTPS requests from the host to `/trader/strategies` and builder API paths
received **403**. No public browser/authenticated UI verification is claimed;
internal HTTP and container health are the verified deployment checks.

## Cleanup

Docker Hub accessed through PowerShell and Docker's existing credential helper;
no registry password/token printed or stored in the repository.
Deleted **11 Docker Hub tags**:

- trader: latest, c5c1e41, 83fccca, e37cc82, f80bbe8.
- frontend: latest, e37cc82, f80bbe8.
- signals: 83fccca, e37cc82, 59eae42.

Retained active/rollback: trader 85f7f45/721e40a; frontend 85f7f45/83fccca;
signals 721e40a/c5c1e41. API latest/7878f7c/93a1151 retained for active/rollback.

Deleted **15 server-local image tags**, only AIDSS trader/frontend/signals. The
script protected every container-referenced image and used no force/global prune.
Active/rollback images retained. Workstation had only the two new release tags,
so nothing there needed removal. Other applications untouched.

## What Was Not Determined

New Indodax model worker is **not installed or activated**: it requires an operator
token, CPU Kronos provisioning and owner-set builder parameters/poll interval.
No model credentials minted, no model calls and no exchange requests issued by
deployment tools. Existing runtime public market polling remains configured.

No real model review, authenticated public browser test, PostgreSQL restore or
off-host copy performed. Backup inspection proves prior broken audit links, not
their cause. Trader remains HALTED. Rollback images retained; keep the additive
schema and investigate audit integrity before considering resume.

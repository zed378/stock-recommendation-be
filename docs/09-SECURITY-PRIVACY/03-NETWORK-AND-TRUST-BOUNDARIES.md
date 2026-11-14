# 03 — Network and Trust Boundaries

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Security Engineer, DevOps Engineer |
| **Decided by** | ADR-001, ADR-021 |
| **Open items** | OQ-14 (resolved, ADR-028) |

## Boundaries

| # | Boundary | Crossing | Control |
|---|---|---|---|
| B1 | Owner's browser and the operator API | HTTPS | Bearer auth, permissions, idempotency, confirmation fields |
| B2 | Operator API and the Trader's core | In process | Services only; routes never touch raw tables |
| B3 | Trader and PostgreSQL | TCP, internal network | Dedicated role `trader_rw`; schema `trading` only (ADR-021) |
| B4 | Trader and Indodax | Outbound HTTPS | Allowlisted hosts; signed requests; throttle |
| B5 | Trader and the analysis platform | Internal HTTP or a read-only view | Read-only, scoped credential, short timeout (ADR-032) |
| B6 | Trader and the notification service | Outbound HTTPS | Token; outbound only; no inbound commands |
| B7 | Analysis platform and the Trader's schema | Database role | **No write privilege** on `trading` |

## Egress Allowlist

The Trader may connect out only to:

- `api.indodax.com` and `indodax.com` (and the STP page's `tapi.indodax.com` if confirmed, `06/11` D1);
- the chosen notification service host;
- the analysis platform host;
- NTP, if the container manages time (otherwise the host does).

It never fetches a user-supplied URL, so there is no server-side request forgery path. The egress
allowlist is enforced at the container or host firewall, not only in code.

## Ingress

Only the operator surface, and only the owner. No exchange webhook exists in the documentation read, so there
is no inbound exchange callback to protect. The Trader exposes no unauthenticated route except a minimal
liveness probe that reveals no state.

## Containers and Hosts

| Item | Rule |
|---|---|
| Network | The `trader` container joins the project's internal network; no host port is published beyond what the operator surface needs (ADR-028) |
| Filesystem | Read-only root filesystem where practical; no secrets on disk |
| Privileges | Non-root user; no extra capabilities |
| Host | Time is NTP-disciplined (NFR-T08); the host's other containers are a shared failure domain |

## Data in Transit

TLS to Indodax and the notification service, verified certificates, no disabling of verification. The
operator surface is served over HTTPS at the edge.

## What Does Not Cross a Boundary

Account data to any AI service; credentials in any response or log; the master key anywhere but the Trader's
environment; order or position data into the analysis platform.

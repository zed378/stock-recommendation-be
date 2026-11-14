# 06 — Role and Permission Matrix

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Security Engineer |
| **Decided by** | ADR-015 |
| **Open items** | OQ-21 (resolved, ADR-033) |

## Existing Roles (from `aidss.security.rbac`)

`viewer`, `investor`, `admin`. Permissions today: `read:market_data`, `read:analysis`, `manage:own_data`,
`trigger:ingestion`, `manage:providers`, `read:audit_log`. A role alone never grants access to another
user's rows; ownership is checked in the query layer.

## New Role and Permissions

A new role `trader` (ADR-015) and these permissions, enforced by the **Trader's own** API:

| Permission | Meaning |
|---|---|
| `trade:view` | See positions, orders, PnL, limits, strategy state |
| `trade:approve` | Approve or deny an intent in `APPROVAL` mode |
| `trade:configure_strategy` | Edit strategy parameters (returns the strategy to `PAPER`) |
| `trade:configure_risk` | Change risk limits and the pair allowlist |
| `trade:promote` | Promote a strategy to the next mode |
| `trade:halt` | Trigger `HALT` |
| `trade:kill` | Trigger `CANCEL` and `FLATTEN` |
| `trade:resume` | Resume after a halt |
| `trade:manage_credentials` | Store, test, and rotate the Indodax key |
| `trade:read_audit` | Read the trading audit log |

## Matrix

| Action | trader | admin | investor | viewer |
|---|---|---|---|---|
| View positions, orders, PnL, limits | Yes | Yes | Yes | Yes |
| Read trading audit log | Yes | Yes | No | No |
| Approve or deny an intent | Yes | Yes (ADR-048) | No | No |
| Edit strategy parameters | Yes | Yes (ADR-048) | No | No |
| Change limits or allowlist | Yes | Yes (ADR-048) | No | No |
| Promote a strategy | Yes | Yes (ADR-048) | No | No |
| `HALT` | Yes | Yes | No | No |
| `CANCEL`, `FLATTEN` | Yes | Yes (ADR-048) | No | No |
| Resume after a halt | Yes | Yes (ADR-048) | No | No |
| Manage the Indodax credential | Yes | Yes (ADR-048) | No | No |

"View" for `investor` and `viewer` follows ADR-015's "existing roles are read-only". Positions are
sensitive; with one owner, no such users are expected, and the owner may switch this off
(`10-OPERATIONS/00-ENVIRONMENTS-AND-CONFIG.md`).

**Decided (ADR-048, superseding ADR-033):** `admin` holds every trader permission, at the owner's request. Step-up
authentication (ADR-046) still guards `FLATTEN`, promotion to `AUTO`, and loosening a limit, for both roles. The
audit log records the actor either way.

## Rules

- No role, including `trader`, can withdraw funds, because no such function exists (ADR-013).
- `trade:promote` and `trade:configure_risk` are never granted to an automated actor.
- A role change is audited and cannot be performed by the user whose role is changing.
- With a single owner there is no two-person control for promotion or limit increases (ADR-015). The audit
  log and the promotion gates are the compensating controls.

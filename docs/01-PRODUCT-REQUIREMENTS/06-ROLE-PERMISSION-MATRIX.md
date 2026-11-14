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
| Approve or deny an intent | Yes | No | No | No |
| Edit strategy parameters | Yes | No | No | No |
| Change limits or allowlist | Yes | No | No | No |
| Promote a strategy | Yes | No | No | No |
| `HALT` | Yes | Yes (ADR-033) | No | No |
| `CANCEL`, `FLATTEN` | Yes | No | No | No |
| Resume after a halt | Yes | No | No | No |
| Manage the Indodax credential | Yes | No | No | No |

"View" for `investor` and `viewer` follows ADR-015's "existing roles are read-only". Positions are
sensitive; with one owner, no such users are expected, and the owner may switch this off
(`10-OPERATIONS/00-ENVIRONMENTS-AND-CONFIG.md`).

**Decided (ADR-033):** `admin` may `HALT`. A halt only stops new orders, so
allowing more people to do it fails safe. `CANCEL`, `FLATTEN`, and `resume` stay with `trader`.

## Rules

- No role, including `trader`, can withdraw funds, because no such function exists (ADR-013).
- `trade:promote` and `trade:configure_risk` are never granted to an automated actor.
- A role change is audited and cannot be performed by the user whose role is changing.
- With a single owner there is no two-person control for promotion or limit increases (ADR-015). The audit
  log and the promotion gates are the compensating controls.

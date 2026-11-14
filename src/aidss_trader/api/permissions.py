"""Roles to permissions (docs/01-PRODUCT-REQUIREMENTS/06). Enforced here, never by the UI.

No role has an order-entry, withdrawal, deposit, or fiat permission because none exists.
`admin` may HALT (ADR-033); CANCEL, FLATTEN, and resume stay with `trader`.
"""

from __future__ import annotations

VIEW = "trade:view"
READ_AUDIT = "trade:read_audit"
APPROVE = "trade:approve"
CONFIGURE_STRATEGY = "trade:configure_strategy"
CONFIGURE_RISK = "trade:configure_risk"
PROMOTE = "trade:promote"
HALT = "trade:halt"
KILL = "trade:kill"
RESUME = "trade:resume"
MANAGE_CREDENTIALS = "trade:manage_credentials"

ALL = frozenset(
    {
        VIEW,
        READ_AUDIT,
        APPROVE,
        CONFIGURE_STRATEGY,
        CONFIGURE_RISK,
        PROMOTE,
        HALT,
        KILL,
        RESUME,
        MANAGE_CREDENTIALS,
    }
)

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "trader": ALL,
    "admin": frozenset({VIEW, READ_AUDIT, HALT}),
    "investor": frozenset({VIEW}),
    "viewer": frozenset({VIEW}),
}


def allowed(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())

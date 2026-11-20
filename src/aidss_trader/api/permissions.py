"""Roles to permissions (docs/01-PRODUCT-REQUIREMENTS/06). Enforced here, never by the UI.

No role has an order-entry, withdrawal, deposit, or fiat permission because none exists.
`admin` holds every trader permission (ADR-048, which supersedes ADR-033). Step-up
authentication still guards FLATTEN, promotion to AUTO, and loosening a limit for both roles.
"""

from __future__ import annotations

VIEW = "trade:view"
READ_AUDIT = "trade:read_audit"
APPROVE = "trade:approve"
CONFIGURE_STRATEGY = "trade:configure_strategy"
RECORD_BUILDER_REVIEW = "trade:record_builder_review"
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
        RECORD_BUILDER_REVIEW,
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
    "admin": ALL,
    "investor": frozenset({VIEW}),
    "viewer": frozenset({VIEW}),
    # A dedicated worker identity can read only exact-candle builder work and
    # append typed model reviews; it cannot change strategies or touch orders.
    "signal_worker": frozenset({VIEW, RECORD_BUILDER_REVIEW}),
}


def allowed(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())

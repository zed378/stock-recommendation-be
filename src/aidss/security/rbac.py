"""RBAC (Section 26).

Three roles: Viewer (read), Investor (manage their own data), Admin (manage
providers and system configuration). Per-user ownership is enforced separately
in the query layer - a role alone never grants access to another user's rows.
"""

from __future__ import annotations

from aidss.db.models.user import UserRole


class Permission:
    READ_MARKET_DATA = "read:market_data"
    READ_ANALYSIS = "read:analysis"
    MANAGE_OWN_DATA = "manage:own_data"
    TRIGGER_INGESTION = "trigger:ingestion"
    MANAGE_PROVIDERS = "manage:providers"
    READ_AUDIT_LOG = "read:audit_log"


_ROLE_PERMISSIONS: dict[UserRole, frozenset[str]] = {
    UserRole.VIEWER: frozenset(
        {Permission.READ_MARKET_DATA, Permission.READ_ANALYSIS}
    ),
    UserRole.INVESTOR: frozenset(
        {
            Permission.READ_MARKET_DATA,
            Permission.READ_ANALYSIS,
            Permission.MANAGE_OWN_DATA,
            Permission.TRIGGER_INGESTION,
        }
    ),
    UserRole.ADMIN: frozenset(
        {
            Permission.READ_MARKET_DATA,
            Permission.READ_ANALYSIS,
            Permission.MANAGE_OWN_DATA,
            Permission.TRIGGER_INGESTION,
            Permission.MANAGE_PROVIDERS,
            Permission.READ_AUDIT_LOG,
        }
    ),
}


def permissions_for(role: UserRole | str) -> frozenset[str]:
    if isinstance(role, str):
        try:
            role = UserRole(role)
        except ValueError:
            return frozenset()
    return _ROLE_PERMISSIONS.get(role, frozenset())


def has_permission(role: UserRole | str, permission: str) -> bool:
    return permission in permissions_for(role)

"""Operator commands that must not be HTTP endpoints.

    python -m aidss.cli list-users
    python -m aidss.cli grant-admin you@example.com
    python -m aidss.cli revoke-admin someone@example.com

Granting admin is deliberately **not** an API route. Any endpoint that hands
out the admin role is a privilege-escalation surface: it has to be guarded by
something, and whatever guards it becomes the new thing worth attacking. There
is also a bootstrapping problem no endpoint solves - registration creates
`investor` accounts, so with API-only promotion the first admin could never
exist without a back door shipped in the code.

Shell access to the deployment is a stronger proof of authority than any token,
and whoever has it can already read the database. So that is where this lives.

Every change is written to `audit_logs` with `actor_type=system`, because a
role change made outside the application is exactly the kind of event someone
will later need to account for.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from aidss.db.base import get_sessionmaker
from aidss.db.models import ActorType, AuditLog, User, UserRole


def _find(session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == email.strip().lower()))


def _set_role(email: str, role: UserRole) -> int:
    sessions = get_sessionmaker()
    session = sessions()
    try:
        user = _find(session, email)
        if user is None:
            print(f"No user with email {email!r}.", file=sys.stderr)
            return 1

        previous = user.role
        if previous == role:
            print(f"{user.email} is already {role.value}.")
            return 0

        user.role = role
        session.add(
            AuditLog(
                actor_type=ActorType.SYSTEM,
                actor_id="cli",
                action="role_change",
                entity="users",
                entity_id=str(user.id),
                before={"role": previous.value},
                after={"role": role.value},
            )
        )
        session.commit()
        print(f"{user.email}: {previous.value} -> {role.value}")
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def list_users() -> int:
    sessions = get_sessionmaker()
    session = sessions()
    try:
        users = session.scalars(select(User).order_by(User.email)).all()
        if not users:
            print("No users registered yet. Sign up in the web interface first.")
            return 0
        width = max(len(user.email) for user in users)
        for user in users:
            active = "" if user.is_active else "  (inactive)"
            print(f"  {user.email:<{width}}  {user.role.value}{active}")
        return 0
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m aidss.cli",
        description="Operator commands. Role changes are deliberately not API endpoints.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list-users", help="Every account and its role")

    grant = commands.add_parser("grant-admin", help="Promote an account to admin")
    grant.add_argument("email")

    revoke = commands.add_parser("revoke-admin", help="Demote an admin back to investor")
    revoke.add_argument("email")

    args = parser.parse_args(argv)

    if args.command == "list-users":
        return list_users()
    if args.command == "grant-admin":
        return _set_role(args.email, UserRole.ADMIN)
    if args.command == "revoke-admin":
        return _set_role(args.email, UserRole.INVESTOR)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

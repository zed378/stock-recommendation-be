"""FastAPI dependencies: database session, current user, RBAC enforcement."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from aidss.config import Settings, get_settings
from aidss.db.base import get_sessionmaker
from aidss.db.models import User
from aidss.security.rbac import has_permission
from aidss.security.tokens import TokenError, decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization: Bearer <token> header is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(credentials.credentials, settings)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = session.get(User, payload.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )
    # Re-checked on every request rather than only at sign-in. A token issued
    # before a suspension stays cryptographically valid for its whole hour, so
    # a ban that only guarded the login page would not take effect until the
    # banned user happened to sign out.
    blocked = user.sign_in_block()
    if blocked is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=blocked)
    return user


def require_permission(permission: str):
    """Dependency factory that enforces RBAC (Section 13)."""

    def _dependency(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user.role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role {user.role.value!r} lacks the {permission!r} permission",
            )
        return user

    return _dependency

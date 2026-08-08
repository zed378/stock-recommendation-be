"""FastAPI dependencies: database session, current user, RBAC enforcement."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from starlette.responses import Response

from aidss.config import Settings, get_settings
from aidss.db.base import get_sessionmaker
from aidss.db.models import User
from aidss.security.rbac import has_permission
from aidss.security.tokens import TokenError, decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_db(request: Request) -> Iterator[Session]:
    """The request-scoped session.

    The commit here is a backstop, not the normal path. FastAPI closes the
    exit stack that ends this generator *after* the response has gone out, so
    a client acting on the response can beat the commit to the database. That
    is not theoretical: registering and then signing in - which is exactly what
    the sign-up form does - failed five times in eight, because the row landed
    9-51ms after the 201 announcing it. `CommitBeforeResponse` commits while
    the request is still in flight; by the time this line runs there is
    normally nothing left to write.
    """
    session = get_sessionmaker()()
    request.state.db_session = session
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class CommitBeforeResponse(APIRoute):
    """Commit the request's session before its response leaves the process.

    Left to the dependency's own teardown, the commit happens after the client
    already holds the response - so "created" can be true in the reply and not
    yet true in the database. Every write-then-immediately-read pattern races
    it, and the interface is built on exactly that pattern: each mutation
    invalidates its query and refetches at once.

    It failed loudly on sign-up (register, then sign in with the same
    credentials, 401) and silently everywhere else, which is the worse half:
    a list that refetches a few milliseconds too early simply renders without
    the row somebody just added, and looks like a UI bug forever.

    Committing here is safe because the sessionmaker sets
    `expire_on_commit=False` - the ORM objects the response was built from keep
    their loaded attributes instead of triggering a reload against a session
    that is about to close.
    """

    def get_route_handler(self):  # noqa: ANN201
        handle = super().get_route_handler()

        async def commit_then_respond(request: Request) -> Response:
            response = await handle(request)
            session = getattr(request.state, "db_session", None)
            if session is not None and session.in_transaction():
                session.commit()
            return response

        return commit_then_respond


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
    """Dependency factory that enforces RBAC (Section 26)."""

    def _dependency(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user.role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role {user.role.value!r} lacks the {permission!r} permission",
            )
        return user

    return _dependency

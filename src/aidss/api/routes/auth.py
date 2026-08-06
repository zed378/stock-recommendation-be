"""Authentication endpoints (Section 10: /auth/login)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.api.deps import CommitBeforeResponse, get_current_user, get_db
from aidss.api.schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from aidss.config import Settings, get_settings
from aidss.db.models import ActorType, AuditLog, User
from aidss.security.passwords import PasswordPolicyError, hash_password, verify_password
from aidss.security.tokens import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"], route_class=CommitBeforeResponse)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, session: Session = Depends(get_db)) -> User:
    existing = session.scalar(select(User).where(User.email == payload.email.lower()))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email is already registered"
        )

    try:
        password_hash = hash_password(payload.password)
    except PasswordPolicyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    user = User(
        email=payload.email.lower(), password_hash=password_hash, full_name=payload.full_name
    )
    session.add(user)
    session.flush()
    session.add(
        AuditLog(
            actor_type=ActorType.USER,
            actor_id=str(user.id),
            action="register",
            entity="users",
            entity_id=str(user.id),
        )
    )
    return user


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    user = session.scalar(select(User).where(User.email == payload.email.lower()))
    # The same error for an unknown email and a wrong password, deliberately:
    # otherwise this endpoint becomes a way to enumerate registered accounts.
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password"
    )
    if user is None or not verify_password(payload.password, user.password_hash):
        raise invalid
    # Checked after the password, so this reveals nothing to someone who does
    # not already hold the credentials. The reason is included on purpose: this
    # is the account holder, and being locked out with no explanation leaves
    # them with nothing to act on and support with nothing to answer.
    blocked = user.sign_in_block()
    if blocked is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=blocked)

    token = create_access_token(user.id, user.role.value, settings)
    return TokenResponse(
        access_token=token,
        expires_at=datetime.now(UTC)
        + timedelta(minutes=settings.access_token_ttl_minutes),
    )


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> User:
    return user

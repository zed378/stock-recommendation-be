"""Administration of accounts and news sources (Section 13).

Two things live here, and they share one property: both are actions taken by
one person against something another person depends on. So every one of them
is audited, and every one of them is guarded against the ways an administrator
can lock the platform - or themselves - out.

Three guards, all of them load-bearing:

  * **No acting on yourself.** Suspending, banning, deleting, or demoting your
    own account either does nothing useful or is an accident.
  * **The last admin cannot be removed.** Promotion is deliberately a shell
    command rather than an endpoint (there is no route that grants admin, by
    design), so an organisation that demotes or deletes its only admin cannot
    recover through the product at all.
  * **Deleting takes the data with it.** Watchlists, portfolios, and the
    decision journal cascade. That is what deletion means, and it is why
    suspension exists beside it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aidss.api.deps import get_db, require_permission
from aidss.api.schemas import (
    AdminUserResponse,
    BanRequest,
    NewsSourceCreate,
    NewsSourceResponse,
    NewsSourceTestResponse,
    NewsSourceUpdate,
    RoleChangeRequest,
    SuspendRequest,
)
from aidss.collectors.normalization import normalize_ticker
from aidss.db.models import ActorType, Asset, AuditLog, NewsSource, User, UserRole, UserStatus
from aidss.security.rbac import Permission
from aidss.syndication.feeds import FeedParseError

router = APIRouter(prefix="/admin", tags=["admin"])


def _audit(
    session: Session, actor: User, action: str, entity: str, entity_id: str, after: dict | None
) -> None:
    session.add(
        AuditLog(
            actor_type=ActorType.USER,
            actor_id=str(actor.id),
            action=action,
            entity=entity,
            entity_id=entity_id,
            after=after,
        )
    )


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


def _to_user_response(user: User) -> AdminUserResponse:
    blocked = user.sign_in_block()
    return AdminUserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        status=user.status.value,
        # Computed by the same function the auth gate uses, so what an admin
        # reads here is by construction what the platform enforces.
        effective_status=user.status.value if blocked else UserStatus.ACTIVE.value,
        suspended_until=user.suspended_until,
        status_reason=user.status_reason,
        status_changed_at=user.status_changed_at,
        created_at=user.created_at,
    )


def _target(
    session: Session, user_id: uuid.UUID, actor: User, *, allow_self: bool = False
) -> User:
    """Resolve the account being acted on.

    `allow_self` is only true for a role change. Stepping down is a real thing
    an administrator does, and refusing it outright would also have made the
    last-admin guard unreachable - a guard that can never fire is not a guard,
    it is a comment. Suspending, banning, or deleting your own account is
    never a considered act, so those stay refused.
    """
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == actor.id and not allow_self:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot apply this to your own account",
        )
    return user


def _refuse_if_last_admin(session: Session, target: User) -> None:
    """Guard the one account that can still administer the platform.

    There is no endpoint that grants the admin role - promotion to the first
    admin is a shell command precisely so that a route cannot be an escalation
    surface. The corollary is that losing the last admin is unrecoverable from
    inside the product.
    """
    if target.role is not UserRole.ADMIN:
        return
    remaining = session.scalar(
        select(func.count(User.id)).where(User.id != target.id, User.role == UserRole.ADMIN)
    )
    if not remaining:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This is the only administrator. Promote another account first - "
                "otherwise no one can administer the platform and no endpoint can "
                "restore it."
            ),
        )


@router.get("/users", response_model=list[AdminUserResponse])
def list_users(
    q: str | None = Query(default=None, description="Match on email or name"),
    role: UserRole | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> list[AdminUserResponse]:
    stmt = select(User)
    if q:
        needle = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            func.lower(User.email).like(needle) | func.lower(User.full_name).like(needle)
        )
    if role is not None:
        stmt = stmt.where(User.role == role)
    rows = session.scalars(stmt.order_by(User.created_at.desc()).limit(limit)).all()
    return [_to_user_response(u) for u in rows]


@router.patch("/users/{user_id}/role", response_model=AdminUserResponse)
def change_role(
    user_id: uuid.UUID,
    payload: RoleChangeRequest,
    session: Session = Depends(get_db),
    actor: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> AdminUserResponse:
    """Promote or demote. Both directions, and stepping down is one of them."""
    target = _target(session, user_id, actor, allow_self=True)
    if payload.role is not UserRole.ADMIN:
        _refuse_if_last_admin(session, target)

    target.role = payload.role
    session.flush()
    _audit(session, actor, "role_change", "users", str(target.id), {"role": payload.role.value})
    return _to_user_response(target)


@router.post("/users/{user_id}/suspend", response_model=AdminUserResponse)
def suspend_user(
    user_id: uuid.UUID,
    payload: SuspendRequest,
    session: Session = Depends(get_db),
    actor: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> AdminUserResponse:
    target = _target(session, user_id, actor)
    _refuse_if_last_admin(session, target)

    if payload.until is not None:
        until = payload.until
        if until.tzinfo is None:
            until = until.replace(tzinfo=UTC)
        if until <= datetime.now(UTC):
            # A suspension that has already expired is a no-op dressed as an
            # action: the admin would see it applied and the user would sign
            # straight back in.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="The suspension deadline is already in the past",
            )
        target.suspended_until = until
    else:
        target.suspended_until = None

    target.status = UserStatus.SUSPENDED
    target.status_reason = payload.reason
    target.status_changed_at = datetime.now(UTC)
    session.flush()
    _audit(
        session,
        actor,
        "suspend",
        "users",
        str(target.id),
        {
            "until": target.suspended_until.isoformat() if target.suspended_until else None,
            "reason": payload.reason,
        },
    )
    return _to_user_response(target)


@router.post("/users/{user_id}/ban", response_model=AdminUserResponse)
def ban_user(
    user_id: uuid.UUID,
    payload: BanRequest,
    session: Session = Depends(get_db),
    actor: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> AdminUserResponse:
    """Indefinite, and never lifted by the clock. Still reversible by an admin.

    Distinct from delete on purpose: a ban keeps the account and its history,
    which is what an investigation needs and what an appeal needs.
    """
    target = _target(session, user_id, actor)
    _refuse_if_last_admin(session, target)

    target.status = UserStatus.BANNED
    target.suspended_until = None
    target.status_reason = payload.reason
    target.status_changed_at = datetime.now(UTC)
    session.flush()
    _audit(session, actor, "ban", "users", str(target.id), {"reason": payload.reason})
    return _to_user_response(target)


@router.post("/users/{user_id}/reinstate", response_model=AdminUserResponse)
def reinstate_user(
    user_id: uuid.UUID,
    session: Session = Depends(get_db),
    actor: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> AdminUserResponse:
    target = _target(session, user_id, actor)
    target.status = UserStatus.ACTIVE
    target.suspended_until = None
    target.status_reason = None
    target.status_changed_at = datetime.now(UTC)
    session.flush()
    _audit(session, actor, "reinstate", "users", str(target.id), None)
    return _to_user_response(target)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: uuid.UUID,
    session: Session = Depends(get_db),
    actor: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> None:
    """Remove an account and everything personal hanging off it.

    Watchlists, portfolios, and journal entries cascade. That is what deletion
    means here, and it is not recoverable - which is the reason ban exists
    beside it rather than instead of it.
    """
    target = _target(session, user_id, actor)
    _refuse_if_last_admin(session, target)

    # Audited before the row goes, so the record survives the deletion. The
    # email is kept in the log on purpose: "some account was deleted" answers
    # nothing six months later.
    _audit(
        session,
        actor,
        "delete_user",
        "users",
        str(target.id),
        {"email": target.email, "role": target.role.value},
    )
    session.delete(target)
    session.flush()


# ---------------------------------------------------------------------------
# News sources
# ---------------------------------------------------------------------------


def _to_source_response(session: Session, source: NewsSource) -> NewsSourceResponse:
    ticker = None
    if source.asset_id is not None:
        asset = session.get(Asset, source.asset_id)
        ticker = asset.ticker if asset else None
    return NewsSourceResponse(
        id=source.id,
        name=source.name,
        feed_url=source.feed_url,
        ticker=ticker,
        is_active=source.is_active,
        is_templated=source.is_templated,
        last_fetched_at=source.last_fetched_at,
        last_status=source.last_status,
        last_error=source.last_error,
        last_entry_count=source.last_entry_count,
        consecutive_failures=source.consecutive_failures,
        created_at=source.created_at,
    )


def _require_http(url: str) -> str:
    """Only http(s).

    An administrator is trusted, but `file://` here would turn a configuration
    field into a way to read the container's filesystem through the feed
    parser - and the trust that matters is not the admin's, it is everyone
    downstream of a compromised admin session.
    """
    trimmed = url.strip()
    if not trimmed.lower().startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A feed URL must start with http:// or https://",
        )
    return trimmed


@router.get("/news-sources", response_model=list[NewsSourceResponse])
def list_news_sources(
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> list[NewsSourceResponse]:
    rows = session.scalars(select(NewsSource).order_by(NewsSource.name)).all()
    return [_to_source_response(session, s) for s in rows]


@router.post(
    "/news-sources", response_model=NewsSourceResponse, status_code=status.HTTP_201_CREATED
)
def create_news_source(
    payload: NewsSourceCreate,
    session: Session = Depends(get_db),
    actor: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> NewsSourceResponse:
    url = _require_http(payload.feed_url)

    asset_id = None
    if payload.ticker:
        ticker = normalize_ticker(payload.ticker)
        asset = session.scalar(select(Asset).where(Asset.ticker == ticker))
        if asset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No asset {ticker}; add it to a watchlist first",
            )
        asset_id = asset.id

    if session.scalar(select(NewsSource).where(NewsSource.feed_url == url)) is not None:
        # Checked rather than left to the unique constraint, which would come
        # back as a 500 with a database message in it.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That feed URL is already configured"
        )

    source = NewsSource(
        name=payload.name.strip(),
        feed_url=url,
        asset_id=asset_id,
        is_active=payload.is_active,
    )
    session.add(source)
    session.flush()
    _audit(session, actor, "create", "news_sources", str(source.id), {"feed_url": url})
    return _to_source_response(session, source)


@router.patch("/news-sources/{source_id}", response_model=NewsSourceResponse)
def update_news_source(
    source_id: uuid.UUID,
    payload: NewsSourceUpdate,
    session: Session = Depends(get_db),
    actor: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> NewsSourceResponse:
    source = session.get(NewsSource, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    if payload.name is not None:
        source.name = payload.name.strip()
    if payload.feed_url is not None:
        source.feed_url = _require_http(payload.feed_url)
    if payload.is_active is not None:
        source.is_active = payload.is_active
        if payload.is_active:
            # Re-enabling clears the count that disabled it, so a feed switched
            # back on is not one failure away from switching off again.
            source.consecutive_failures = 0

    session.flush()
    _audit(session, actor, "update", "news_sources", str(source.id), None)
    return _to_source_response(session, source)


@router.delete("/news-sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_news_source(
    source_id: uuid.UUID,
    session: Session = Depends(get_db),
    actor: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> None:
    source = session.get(NewsSource, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    _audit(session, actor, "delete", "news_sources", str(source.id), {"name": source.name})
    session.delete(source)
    session.flush()


@router.post("/news-sources/{source_id}/test", response_model=NewsSourceTestResponse)
def test_news_source(
    source_id: uuid.UUID,
    ticker: str | None = Query(default=None, description="Substituted into a templated URL"),
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> NewsSourceTestResponse:
    """Fetch this feed now and report what came back.

    Without it, adding a source means waiting for a schedule and then guessing
    from an empty result whether the URL was wrong, the feed was empty, or
    nothing in it mentioned the ticker. The sample headlines answer the
    question the count cannot: is this the feed you meant?
    """
    import httpx

    from aidss.plugins.adapters.news_rss import RssNewsProvider

    source = session.get(NewsSource, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    url = source.feed_url
    if source.is_templated:
        if not ticker:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="This feed URL contains {ticker}; supply a ticker to test it",
            )
        url = url.replace("{ticker}", normalize_ticker(ticker))

    provider = RssNewsProvider(session)
    try:
        entries = provider._fetch(url)  # noqa: SLF001 - the test *is* the fetch
    except (httpx.HTTPError, FeedParseError) as exc:
        return NewsSourceTestResponse(ok=False, entries=0, error=f"{type(exc).__name__}: {exc}")

    newest = max((e.published_at for e in entries), default=None)
    return NewsSourceTestResponse(
        ok=True,
        entries=len(entries),
        sample=[e.title for e in entries[:5]],
        newest_published_at=newest,
    )

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

import time
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aidss.api.deps import CommitBeforeResponse, get_db, require_permission
from aidss.api.pagination import paginate
from aidss.api.schemas import (
    AdminUserCreate,
    AdminUserResponse,
    AIProviderResponse,
    AIProviderTestResponse,
    AIProviderWrite,
    BanRequest,
    IssuerResponse,
    IssuerUpdateRequest,
    JobAcceptedResponse,
    NewsSourceCreate,
    NewsSourceResponse,
    NewsSourceTestResponse,
    NewsSourceUpdate,
    Page,
    PlatformSettingsResponse,
    PlatformSettingsUpdate,
    RoleChangeRequest,
    SuspendRequest,
)
from aidss.collectors.normalization import normalize_ticker
from aidss.config import get_settings
from aidss.db.models import (
    ActorType,
    AIProviderConfig,
    Asset,
    AuditLog,
    Issuer,
    NewsSource,
    User,
    UserRole,
    UserStatus,
)
from aidss.jobs.queue import enqueue
from aidss.llm.provisioning import provider_from_row
from aidss.news.schedules import next_run_at
from aidss.news.tagging import (
    MIN_ALIAS_LENGTH,
    effective_aliases,
    is_usable_alias,
    normalise,
)
from aidss.platform.settings import (
    NEWS_SWEEP_CRON,
    REGISTRATION_OPEN,
    all_settings,
    set_setting,
)
from aidss.plugins.errors import PluginNotFoundError
from aidss.plugins.registry import get_plugin_class
from aidss.security.passwords import PasswordPolicyError, hash_password
from aidss.security.rbac import Permission
from aidss.security.secrets import encrypt_secret
from aidss.security.secrets import hint as secret_hint
from aidss.syndication.feeds import FeedParseError

router = APIRouter(prefix="/admin", tags=["admin"], route_class=CommitBeforeResponse)


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



@router.get("/users", response_model=Page[AdminUserResponse])
def list_users(
    q: str | None = Query(default=None, description="Match on email or name"),
    role: UserRole | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> Page[AdminUserResponse]:
    stmt = select(User)
    if q:
        needle = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            func.lower(User.email).like(needle) | func.lower(User.full_name).like(needle)
        )
    if role is not None:
        stmt = stmt.where(User.role == role)
    rows, total = paginate(session, stmt, User.created_at.desc(), limit, offset)
    return Page(
        items=[_to_user_response(u) for u in rows], total=total, limit=limit, offset=offset
    )


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


@router.get("/news-sources", response_model=Page[NewsSourceResponse])
def list_news_sources(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> Page[NewsSourceResponse]:
    rows, total = paginate(session, select(NewsSource), NewsSource.name, limit, offset)
    return Page(
        items=[_to_source_response(session, row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


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
        url = _require_http(payload.feed_url)
        if url != source.feed_url:
            clash = session.scalar(
                select(NewsSource).where(
                    NewsSource.feed_url == url, NewsSource.id != source.id
                )
            )
            if clash is not None:
                # Checked rather than left to the unique constraint, which would
                # surface as a 500 with a database message in it.
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="That feed URL is already configured",
                )
        source.feed_url = url

    # Present in the body at all, even as null, means the binding is being
    # changed. Omitted means it is not - a distinction `None` alone cannot make.
    if "ticker" in payload.model_fields_set:
        if payload.ticker:
            ticker = normalize_ticker(payload.ticker)
            asset = session.scalar(select(Asset).where(Asset.ticker == ticker))
            if asset is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No asset {ticker}; add it to a watchlist first",
                )
            source.asset_id = asset.id
        else:
            source.asset_id = None

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
        entries = provider.fetch(url)
    except (httpx.HTTPError, FeedParseError) as exc:
        detail = f"{type(exc).__name__}: {exc}"
        # Recorded, so the "failing" filter can find it - that is what testing
        # is for. Not counted towards the failure streak, though: debugging one
        # URL twenty times would otherwise switch the source off.
        provider.record(source, count=None, error=detail, count_failure=False)
        return NewsSourceTestResponse(ok=False, entries=0, error=detail)

    provider.record(source, count=len(entries), error=None)
    newest = max((e.published_at for e in entries), default=None)
    return NewsSourceTestResponse(
        ok=True,
        entries=len(entries),
        sample=[e.title for e in entries[:5]],
        newest_published_at=newest,
    )


# ---------------------------------------------------------------------------
# The listed-company directory, and reading every feed at once
# ---------------------------------------------------------------------------


@router.post(
    "/news-sources/fetch-all",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def fetch_all_news_sources(
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> JobAcceptedResponse:
    """Read every active feed now and store everything in it.

    Queued rather than run here. Twenty feeds over the open internet is not
    work that fits in a request, and holding it on one is how the analysis
    ended up returning proxy timeouts.

    Deduplicated per minute: this is a button, and a button gets pressed twice.
    """
    minute = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M")
    result = enqueue(
        session,
        "news.sweep",
        {"user_id": str(user.id)},
        dedup_key=f"news-sweep:{minute}",
    )
    return JobAcceptedResponse(
        job_id=result.job_id,
        job_type="news.sweep",
        deduplicated=result.deduplicated,
        poll_url=f"/jobs/{result.job_id}",
        note=(
            "A sweep is already running; this returns that job."
            if result.deduplicated
            else "Reading every active feed. You will be notified when it finishes."
        ),
    )


@router.post(
    "/issuers/sync", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED
)
def sync_issuers(
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> JobAcceptedResponse:
    """Refresh the IDX company directory that news tagging matches against."""
    minute = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M")
    result = enqueue(
        session,
        "issuers.sync",
        {"user_id": str(user.id)},
        dedup_key=f"issuers-sync:{minute}",
    )
    return JobAcceptedResponse(
        job_id=result.job_id,
        job_type="issuers.sync",
        deduplicated=result.deduplicated,
        poll_url=f"/jobs/{result.job_id}",
        note=(
            "A synchronisation is already running; this returns that job."
            if result.deduplicated
            else "Reading the IDX company directory."
        ),
    )


@router.post(
    "/news/retag", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED
)
def retag_news(
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> JobAcceptedResponse:
    """Attribute stories already stored that carry no tags.

    The reason a correction is worth making: an alias fixed today should be
    able to reach the archive, not only whatever arrives tomorrow.
    """
    minute = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M")
    result = enqueue(
        session,
        "news.tag_backfill",
        {"user_id": str(user.id)},
        dedup_key=f"news-retag:{minute}",
    )
    return JobAcceptedResponse(
        job_id=result.job_id,
        job_type="news.tag_backfill",
        deduplicated=result.deduplicated,
        poll_url=f"/jobs/{result.job_id}",
        note="Tagging stories that have no issuer yet.",
    )


def _issuer_payload(issuer: Issuer) -> IssuerResponse:
    """Serialised with the effective alias list computed alongside the stored one."""
    return IssuerResponse(
        **{
            field: getattr(issuer, field)
            for field in (
                "id", "ticker", "name", "sector", "sub_sector",
                "listing_board", "website", "is_listed", "synced_at",
            )
        },
        aliases=[str(a) for a in (issuer.aliases or [])],
        effective_aliases=effective_aliases(
            issuer.name, issuer.ticker, [str(a) for a in (issuer.aliases or [])]
        ),
    )


@router.get("/issuers", response_model=Page[IssuerResponse])
def list_issuers(
    search: str | None = Query(default=None, description="Matches the code or the name"),
    listed_only: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> Page[IssuerResponse]:
    """Browse the directory. Searchable, because it holds nearly a thousand rows
    and scrolling to find one is not browsing."""
    stmt = select(Issuer)
    if listed_only:
        stmt = stmt.where(Issuer.is_listed.is_(True))
    if search:
        pattern = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            func.lower(Issuer.ticker).like(pattern) | func.lower(Issuer.name).like(pattern)
        )
    rows, total = paginate(session, stmt, Issuer.ticker, limit, offset)
    return Page(
        items=[_issuer_payload(issuer) for issuer in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/issuers/{issuer_id}", response_model=IssuerResponse)
def update_issuer(
    issuer_id: uuid.UUID,
    payload: IssuerUpdateRequest,
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> IssuerResponse:
    """Correct an issuer's aliases.

    Aliases are refused rather than silently dropped when they would match
    everything: "Bank" as an alias is not a narrow tag, it is several hundred
    wrong ones, and an administrator who typed it deserves to be told so rather
    than to discover it in the tags a week later.
    """
    issuer = session.get(Issuer, issuer_id)
    if issuer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issuer not found")

    cleaned: list[str] = []
    refused: list[str] = []
    for raw in payload.aliases:
        alias = normalise(str(raw))
        if not alias:
            continue
        if not is_usable_alias(alias):
            refused.append(str(raw))
            continue
        if alias not in cleaned:
            cleaned.append(alias)

    if refused:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"These are too general to use as aliases: {refused}. An alias must be "
                f"at least {MIN_ALIAS_LENGTH} characters and must not be a single "
                "ordinary word - it would tag every story containing it."
            ),
        )

    issuer.aliases = cleaned
    session.flush()
    return _issuer_payload(issuer)


# ---------------------------------------------------------------------------
# Platform settings, accounts created by an admin, and AI providers
# ---------------------------------------------------------------------------


@router.get("/settings", response_model=PlatformSettingsResponse)
def read_platform_settings(
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> PlatformSettingsResponse:
    return PlatformSettingsResponse(**all_settings(session))


@router.patch("/settings", response_model=PlatformSettingsResponse)
def update_platform_settings(
    payload: PlatformSettingsUpdate,
    session: Session = Depends(get_db),
    actor: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> PlatformSettingsResponse:
    """Change operator settings. Only the keys sent are touched.

    Both are audited. Closing registration and changing when the platform reads
    the news are the kind of decisions someone asks about a month later, and an
    audit row is the only answer that does not depend on memory.
    """
    if payload.news_sweep_cron is not None and payload.news_sweep_cron.strip():
        # Validated here rather than discovered by the scheduler at 3am, where
        # the failure is a sweep that silently never runs.
        try:
            next_run_at(payload.news_sweep_cron.strip())
        except Exception as exc:  # noqa: BLE001 - the parser raises its own types
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Not a usable cron expression: {exc}",
            ) from exc

    before = all_settings(session)
    cron = None if payload.news_sweep_cron is None else payload.news_sweep_cron.strip()
    for key, value in ((REGISTRATION_OPEN, payload.registration_open), (NEWS_SWEEP_CRON, cron)):
        if value is not None:
            set_setting(session, key, value, by=actor.id)

    after = all_settings(session)
    _audit(
        session,
        actor,
        action="platform_settings.update",
        entity="platform_settings",
        entity_id="-",
        before=before,
        after=after,
    )
    return PlatformSettingsResponse(**after)


@router.post("/users", response_model=AdminUserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AdminUserCreate,
    session: Session = Depends(get_db),
    actor: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> AdminUserResponse:
    """Create an account on somebody's behalf.

    Exists because registration can be closed, and an operator who closed it
    still needs to onboard people. Without this the only ways in are reopening
    the door for everyone or editing the database.

    Unlike self-registration this may set a role, which makes it the one route
    that can mint an admin. It is guarded by `MANAGE_PROVIDERS` - so only an
    existing admin can - and audited, because "who made this account an admin"
    is a question that gets asked exactly once, urgently.
    """
    if session.scalar(select(User).where(User.email == payload.email.lower())):
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
        email=payload.email.lower(),
        password_hash=password_hash,
        full_name=payload.full_name,
        role=payload.role,
    )
    session.add(user)
    session.flush()
    _audit(
        session,
        actor,
        action="user.create",
        entity="users",
        entity_id=str(user.id),
        before=None,
        after={"email": user.email, "role": user.role.value},
    )
    return _to_user_response(user)


@router.get("/ai-providers", response_model=list[AIProviderResponse])
def list_ai_providers(
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> list[AIProviderConfig]:
    """Every configured provider, in fallback order.

    Not paginated, unlike the other admin lists: the point of this screen is
    seeing the chain, and a chain split across pages is not a chain anybody can
    read.
    """
    return list(
        session.scalars(select(AIProviderConfig).order_by(AIProviderConfig.priority)).all()
    )


@router.post(
    "/ai-providers", response_model=AIProviderResponse, status_code=status.HTTP_201_CREATED
)
def create_ai_provider(
    payload: AIProviderWrite,
    session: Session = Depends(get_db),
    actor: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> AIProviderConfig:
    if session.scalar(select(AIProviderConfig).where(AIProviderConfig.name == payload.name)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A provider named {payload.name!r} already exists",
        )
    _check_adapter(payload.adapter_name)
    row = AIProviderConfig(name=payload.name)
    _apply_provider(row, payload)
    session.add(row)
    session.flush()
    _audit(
        session,
        actor,
        action="ai_provider.create",
        entity="ai_providers",
        entity_id=str(row.id),
        before=None,
        after=_provider_audit(row),
    )
    return row


@router.patch("/ai-providers/{provider_id}", response_model=AIProviderResponse)
def update_ai_provider(
    provider_id: uuid.UUID,
    payload: AIProviderWrite,
    session: Session = Depends(get_db),
    actor: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> AIProviderConfig:
    row = session.get(AIProviderConfig, provider_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    _check_adapter(payload.adapter_name)
    before = _provider_audit(row)
    _apply_provider(row, payload)
    session.flush()
    _audit(
        session,
        actor,
        action="ai_provider.update",
        entity="ai_providers",
        entity_id=str(row.id),
        before=before,
        after=_provider_audit(row),
    )
    return row


@router.delete("/ai-providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ai_provider(
    provider_id: uuid.UUID,
    session: Session = Depends(get_db),
    actor: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> None:
    row = session.get(AIProviderConfig, provider_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    _audit(
        session,
        actor,
        action="ai_provider.delete",
        entity="ai_providers",
        entity_id=str(row.id),
        before=_provider_audit(row),
        after=None,
    )
    session.delete(row)


@router.post("/ai-providers/{provider_id}/test", response_model=AIProviderTestResponse)
def test_ai_provider(
    provider_id: uuid.UUID,
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> AIProviderTestResponse:
    """Ask this provider one trivial question, now.

    Without it, a wrong URL or a stale key is discovered by an analysis failing
    twenty minutes later, with the reason buried in a worker log. The prompt is
    deliberately tiny: this establishes reachability and authentication, not
    that the model is any good.
    """
    row = session.get(AIProviderConfig, provider_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")

    settings = get_settings()
    started = time.monotonic()
    try:
        provider = provider_from_row(row, settings)
        result = provider.chat(
            [{"role": "user", "content": "Reply with the single word: ok"}],
            model=row.default_model or settings.ai_chat_model,
            max_tokens=5,
        )
        elapsed = int((time.monotonic() - started) * 1000)
        row.last_status, row.last_error = "ok", None
        row.last_checked_at = datetime.now(UTC)
        session.flush()
        return AIProviderTestResponse(
            ok=True,
            latency_ms=elapsed,
            model=getattr(result, "model", None) or row.default_model,
            reply=(getattr(result, "content", "") or "")[:200],
        )
    except Exception as exc:  # noqa: BLE001 - adapters raise their own hierarchies
        detail = f"{type(exc).__name__}: {exc}"[:500]
        row.last_status, row.last_error = "failed", detail
        row.last_checked_at = datetime.now(UTC)
        session.flush()
        return AIProviderTestResponse(ok=False, error=detail)


def _check_adapter(adapter_name: str) -> None:
    try:
        get_plugin_class("ai", adapter_name)
    except PluginNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"No AI adapter named {adapter_name!r} is registered",
        ) from exc


def _apply_provider(row: AIProviderConfig, payload: AIProviderWrite) -> None:
    """Copy the writable fields, handling the credential's three intents.

    Omitted keeps what is stored, empty clears it, a value replaces it. An
    admin editing the model name expects the first; a switch to a local model
    needing no key expects the second; and collapsing them would make one of
    those impossible to express.
    """
    row.name = payload.name
    row.adapter_name = payload.adapter_name
    row.base_url = payload.base_url or None
    row.default_model = payload.default_model or None
    row.role = payload.role
    row.priority = payload.priority
    row.is_active = payload.is_active
    row.self_hosted = payload.self_hosted
    row.timeout_seconds = payload.timeout_seconds
    row.input_cost_per_1k = payload.input_cost_per_1k
    row.output_cost_per_1k = payload.output_cost_per_1k

    if payload.api_key is None:
        return
    if payload.api_key == "":
        row.api_key_ciphertext, row.api_key_hint = None, None
        return
    row.api_key_ciphertext = encrypt_secret(payload.api_key)
    row.api_key_hint = secret_hint(payload.api_key)


def _provider_audit(row: AIProviderConfig) -> dict[str, object]:
    """What goes in the audit trail. Never the credential, not even encrypted."""
    return {
        "name": row.name,
        "adapter_name": row.adapter_name,
        "base_url": row.base_url,
        "default_model": row.default_model,
        "role": row.role,
        "priority": row.priority,
        "is_active": row.is_active,
        "self_hosted": row.self_hosted,
        "has_api_key": bool(row.api_key_ciphertext),
    }

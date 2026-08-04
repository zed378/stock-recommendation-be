"""Watchlist endpoints (Section 10).

Items are grouped into **categories**. That is not a new concept bolted on:
`watchlists` has carried a `name` with a unique constraint per user since the
initial schema, and `watchlist_items` hangs off it. Every endpoint here simply
used to hardcode "Default", so a user could hold exactly one unnamed list. A
category *is* that name.

One consequence worth stating: because uniqueness is on
``(watchlist_id, asset_id)``, the same ticker can sit in several categories at
once. BBCA is a bank and a dividend payer, and forcing a choice between the two
would make the grouping less useful than no grouping.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from aidss.api.deps import get_db, require_permission
from aidss.api.schemas import (
    DEFAULT_CATEGORY,
    WatchlistCategoryResponse,
    WatchlistItemCreate,
    WatchlistItemMove,
    WatchlistItemResponse,
)
from aidss.collectors.normalization import normalize_ticker
from aidss.db.models import Asset, User, Watchlist, WatchlistItem
from aidss.security.rbac import Permission

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


def _category(session: Session, user: User, name: str) -> Watchlist:
    """Fetch the user's category by name, creating it on first use.

    Created rather than rejected because a category with no members is not a
    thing anyone wants to create, name, and then fill. The name is trimmed so
    "Perbankan" and "Perbankan " do not become two groups that look identical.
    """
    trimmed = name.strip() or DEFAULT_CATEGORY
    watchlist = session.scalar(
        select(Watchlist).where(Watchlist.user_id == user.id, Watchlist.name == trimmed)
    )
    if watchlist is None:
        watchlist = Watchlist(user_id=user.id, name=trimmed)
        session.add(watchlist)
        session.flush()
    return watchlist


def _owned_items(user: User):
    """Every item across every category this user owns.

    The join to `watchlists` is the ownership check. Scoping only to the
    "Default" list - which is what this file used to do on delete - would have
    made an item in any other category impossible to remove once categories
    existed.
    """
    return (
        select(WatchlistItem, Asset, Watchlist.name)
        .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
        .join(Asset, Asset.id == WatchlistItem.asset_id)
        .where(Watchlist.user_id == user.id)
    )


def _to_response(item: WatchlistItem, asset: Asset, category: str) -> WatchlistItemResponse:
    return WatchlistItemResponse(
        id=item.id,
        ticker=asset.ticker,
        exchange=asset.exchange,
        note=item.note,
        added_at=item.added_at,
        category=category,
        name=asset.name,
        sector=asset.sector,
    )


@router.get("", response_model=list[WatchlistItemResponse])
def list_items(
    category: str | None = Query(default=None),
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> list[WatchlistItemResponse]:
    """Every item the user follows, optionally narrowed to one category.

    Unfiltered by default: the client groups them, and returning everything in
    one call means switching between categories costs no request.
    """
    stmt = _owned_items(user)
    if category:
        stmt = stmt.where(Watchlist.name == category.strip())
    rows = session.execute(stmt.order_by(Watchlist.name, Asset.ticker)).all()
    return [_to_response(item, asset, name) for item, asset, name in rows]


@router.get("/categories", response_model=list[WatchlistCategoryResponse])
def list_categories(
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> list[WatchlistCategoryResponse]:
    """Categories with their sizes.

    Empty ones are included: a category emptied by removing its last item still
    exists, and hiding it would make it look as though the removal deleted the
    group as well.
    """
    rows = session.execute(
        select(Watchlist.name, func.count(WatchlistItem.id))
        .outerjoin(WatchlistItem, WatchlistItem.watchlist_id == Watchlist.id)
        .where(Watchlist.user_id == user.id)
        .group_by(Watchlist.name)
        .order_by(Watchlist.name)
    ).all()
    return [WatchlistCategoryResponse(name=name, count=count) for name, count in rows]


@router.post("", response_model=WatchlistItemResponse, status_code=status.HTTP_201_CREATED)
def add_item(
    payload: WatchlistItemCreate,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> WatchlistItemResponse:
    ticker = normalize_ticker(payload.ticker)
    asset = session.scalar(
        select(Asset).where(Asset.ticker == ticker, Asset.exchange == payload.exchange)
    )
    if asset is None:
        # A watchlist entry may reference an asset the platform has never seen
        # before; registering it here keeps the flow to a single call.
        asset = Asset(ticker=ticker, exchange=payload.exchange)
        session.add(asset)
        session.flush()

    watchlist = _category(session, user, payload.category)
    existing = session.scalar(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == watchlist.id, WatchlistItem.asset_id == asset.id
        )
    )
    if existing is not None:
        # Scoped to this category, so the same ticker in a different one is not
        # a conflict - which is the point of having categories at all.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{asset.ticker} is already in {watchlist.name!r}",
        )

    item = WatchlistItem(watchlist_id=watchlist.id, asset_id=asset.id, note=payload.note)
    session.add(item)
    session.flush()
    return _to_response(item, asset, watchlist.name)


@router.patch("/{item_id}", response_model=WatchlistItemResponse)
def move_item(
    item_id: uuid.UUID,
    payload: WatchlistItemMove,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> WatchlistItemResponse:
    """Move an item to another category."""
    row = session.execute(_owned_items(user).where(WatchlistItem.id == item_id)).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    item, asset, current = row

    target = _category(session, user, payload.category)
    if target.name == current:
        return _to_response(item, asset, current)

    clash = session.scalar(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == target.id, WatchlistItem.asset_id == item.asset_id
        )
    )
    if clash is not None:
        # Checked rather than left to the unique constraint, which would
        # surface as a 500 with a database message in it.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{asset.ticker} is already in {target.name!r}",
        )

    item.watchlist_id = target.id
    session.flush()
    return _to_response(item, asset, target.name)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_item(
    item_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> None:
    # Scoped through the user's watchlists, which is what stops one user from
    # deleting another's row by guessing an id.
    row = session.execute(_owned_items(user).where(WatchlistItem.id == item_id)).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    session.delete(row[0])


@router.get("/search", response_model=list[WatchlistItemResponse])
def search(
    q: str = Query(min_length=1, max_length=120),
    category: str | None = Query(default=None),
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> list[WatchlistItemResponse]:
    """Search across ticker, company name, sector, category, and the user's note.

    Case-insensitive via `ilike`: tickers are stored upper case, but company
    names and notes are free text, and a case-sensitive `like` would make
    searching one's own note a guessing game about how it was typed.

    Two of the five fields are there for reasons worth stating. The **note** is
    where the reason for following an asset lives - "kandidat dividen",
    "menunggu laporan Q3" - and that is more often what someone is looking for
    than a code they already know. The **category** is searched because a user
    reading a group heading on screen and typing it into the box expects to
    find that group; leaving it out made the most obvious query return nothing.
    """
    pattern = f"%{q.strip()}%"
    stmt = _owned_items(user).where(
        or_(
            Asset.ticker.ilike(pattern),
            Asset.name.ilike(pattern),
            Asset.sector.ilike(pattern),
            WatchlistItem.note.ilike(pattern),
            Watchlist.name.ilike(pattern),
        )
    )
    if category:
        stmt = stmt.where(Watchlist.name == category.strip())
    rows = session.execute(stmt.order_by(Watchlist.name, Asset.ticker)).all()
    return [_to_response(item, asset, name) for item, asset, name in rows]

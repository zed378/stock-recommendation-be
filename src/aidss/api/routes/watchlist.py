"""Watchlist endpoints (Section 10)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.api.deps import get_db, require_permission
from aidss.api.schemas import WatchlistItemCreate, WatchlistItemResponse
from aidss.collectors.normalization import normalize_ticker
from aidss.db.models import Asset, User, Watchlist, WatchlistItem
from aidss.security.rbac import Permission

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


def _default_watchlist(session: Session, user: User) -> Watchlist:
    watchlist = session.scalar(
        select(Watchlist).where(Watchlist.user_id == user.id, Watchlist.name == "Default")
    )
    if watchlist is None:
        watchlist = Watchlist(user_id=user.id, name="Default")
        session.add(watchlist)
        session.flush()
    return watchlist


def _to_response(item: WatchlistItem, asset: Asset) -> WatchlistItemResponse:
    return WatchlistItemResponse(
        id=item.id,
        ticker=asset.ticker,
        exchange=asset.exchange,
        note=item.note,
        added_at=item.added_at,
    )


@router.get("", response_model=list[WatchlistItemResponse])
def list_items(
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> list[WatchlistItemResponse]:
    watchlist = _default_watchlist(session, user)
    rows = session.execute(
        select(WatchlistItem, Asset)
        .join(Asset, Asset.id == WatchlistItem.asset_id)
        .where(WatchlistItem.watchlist_id == watchlist.id)
        .order_by(Asset.ticker)
    ).all()
    return [_to_response(item, asset) for item, asset in rows]


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

    watchlist = _default_watchlist(session, user)
    existing = session.scalar(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == watchlist.id, WatchlistItem.asset_id == asset.id
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Asset is already on the watchlist"
        )

    item = WatchlistItem(watchlist_id=watchlist.id, asset_id=asset.id, note=payload.note)
    session.add(item)
    session.flush()
    return _to_response(item, asset)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_item(
    item_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> None:
    watchlist = _default_watchlist(session, user)
    item = session.scalar(
        select(WatchlistItem).where(
            # Scoping by watchlist_id is what stops one user from deleting
            # another user's row by guessing an id.
            WatchlistItem.id == item_id,
            WatchlistItem.watchlist_id == watchlist.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    session.delete(item)


@router.get("/search", response_model=list[WatchlistItemResponse])
def search(
    ticker: str = Query(min_length=1),
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> list[WatchlistItemResponse]:
    watchlist = _default_watchlist(session, user)
    rows = session.execute(
        select(WatchlistItem, Asset)
        .join(Asset, Asset.id == WatchlistItem.asset_id)
        .where(
            WatchlistItem.watchlist_id == watchlist.id,
            Asset.ticker.like(f"%{ticker.upper()}%"),
        )
        .order_by(Asset.ticker)
    ).all()
    return [_to_response(item, asset) for item, asset in rows]

"""Group A - Users & Personal Data (Section 6.2).

Everything here is the investor's own data: watchlists, portfolios, and the
decision journal. Portfolio positions are **always** user-entered
(``input_method``); nothing is synchronised from a brokerage account.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aidss.db.base import Base, enum_column, new_uuid, utcnow

if TYPE_CHECKING:
    from aidss.db.models.asset import Asset


class UserRole(StrEnum):
    """The minimal RBAC set from Section 13."""

    VIEWER = "viewer"
    INVESTOR = "investor"
    ADMIN = "admin"


class UserStatus(StrEnum):
    """Whether an account may be used, and why not.

    Replaces the earlier boolean ``is_active``. A boolean could say that an
    account was off but not whether that was a two-day suspension or a
    permanent ban, so the two had to be tracked somewhere else - and a flag
    that can disagree with the reason beside it is exactly how a banned
    account ends up able to sign in.
    """

    ACTIVE = "active"
    #: Time-boxed and reversible. Expires on its own; no job lifts it, because
    #: a suspension that outlives its own deadline because a worker was down is
    #: a punishment nobody chose.
    SUSPENDED = "suspended"
    #: Indefinite. An admin can still lift it, but the clock never will.
    BANNED = "banned"


class HoldingInputMethod(StrEnum):
    """Where a position came from. There is deliberately no ``broker_sync``."""

    MANUAL = "manual"
    IMPORT = "import"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(200), default=None)
    role: Mapped[UserRole] = mapped_column(enum_column(UserRole), default=UserRole.INVESTOR)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    status: Mapped[UserStatus] = mapped_column(
        enum_column(UserStatus), default=UserStatus.ACTIVE, index=True
    )
    #: When a suspension lifts itself. Null for an indefinite one and for a ban.
    suspended_until: Mapped[datetime | None] = mapped_column(default=None)
    #: What the admin gave as the reason. Shown to the account holder at sign-in:
    #: being locked out with no explanation is worse than the explanation.
    status_reason: Mapped[str | None] = mapped_column(Text, default=None)
    status_changed_at: Mapped[datetime | None] = mapped_column(default=None)

    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    def sign_in_block(self, now: datetime | None = None) -> str | None:
        """Why this account cannot be used right now, or ``None`` if it can.

        One function, used by the login check, by every authenticated request,
        and by the admin listing - so what an admin sees as an account's state
        is by construction the state the auth gate enforces. An expired
        suspension is computed, not swept up by a job: the deadline passing is
        the whole mechanism.
        """
        if self.status is UserStatus.BANNED:
            return self.status_reason or "This account has been banned."
        if self.status is UserStatus.SUSPENDED:
            now = now or datetime.now(UTC)
            until = self.suspended_until
            if until is not None:
                # Naive timestamps come back from SQLite, which has no tz type.
                if until.tzinfo is None:
                    until = until.replace(tzinfo=UTC)
                if until <= now:
                    return None
            return self.status_reason or "This account is suspended."
        return None

    @property
    def is_active(self) -> bool:
        """Kept as a read-only view for callers that only need the boolean.

        Derived rather than stored, so it cannot drift out of step with
        ``status`` the way a second column would.
        """
        return self.sign_in_block() is None

    watchlists: Mapped[list[Watchlist]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    portfolios: Mapped[list[Portfolio]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    journal_entries: Mapped[list[InvestmentJournalEntry]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), default="Default")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    user: Mapped[User] = relationship(back_populates="watchlists")
    items: Mapped[list[WatchlistItem]] = relationship(
        back_populates="watchlist", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_watchlist_user_name"),)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    watchlist_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    note: Mapped[str | None] = mapped_column(Text, default=None)
    added_at: Mapped[datetime] = mapped_column(default=utcnow)

    watchlist: Mapped[Watchlist] = relationship(back_populates="items")
    asset: Mapped[Asset] = relationship()

    __table_args__ = (
        UniqueConstraint("watchlist_id", "asset_id", name="uq_watchlist_item_asset"),
    )


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), default="Default")
    base_currency: Mapped[str] = mapped_column(String(3), default="IDR")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    user: Mapped[User] = relationship(back_populates="portfolios")
    holdings: Mapped[list[PortfolioHolding]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_portfolio_user_name"),)


class PortfolioHolding(Base):
    __tablename__ = "portfolio_holdings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    average_price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    # Keeps it unambiguous that this position was entered by the user rather
    # than automated against a brokerage account (Section 6.2, design notes).
    input_method: Mapped[HoldingInputMethod] = mapped_column(
        enum_column(HoldingInputMethod), default=HoldingInputMethod.MANUAL
    )
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    portfolio: Mapped[Portfolio] = relationship(back_populates="holdings")
    asset: Mapped[Asset] = relationship()

    __table_args__ = (
        UniqueConstraint("portfolio_id", "asset_id", name="uq_holding_portfolio_asset"),
    )


class UserPreference(Base):
    """Backing store for the Memory Manager (Section 14.2).

    Section 6.2 does not name this table, because the Memory Manager belongs to
    the AI layer that Phase 4 introduces. Interaction history already has a
    home in ``ai_conversations``/``ai_messages``; what had nowhere to live is
    the stated preference - risk appetite, investment horizon, preferred depth
    of explanation - that should shape analysis without being re-asked.

    Values are JSON so a new preference does not require a migration.
    """

    __tablename__ = "user_preferences"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(80))
    value: Mapped[dict[str, Any]] = mapped_column(default=dict)
    #: Whether the investor said this themselves or the system inferred it.
    #: Worth distinguishing: an inferred preference should never be presented
    #: back to the user as something they told us.
    source: Mapped[str] = mapped_column(String(20), default="stated")
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_preference_user_key"),)


class InvestmentJournalEntry(Base):
    """The investor's own decision log - the Reflection Agent's input (Phase 6+)."""

    __tablename__ = "investment_journal"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), default=None
    )
    decision: Mapped[str] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text, default=None)
    # Nullable: an investor does not always follow, or even reference, an
    # AI recommendation when making a decision.
    recommendation_ref: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recommendations.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    user: Mapped[User] = relationship(back_populates="journal_entries")

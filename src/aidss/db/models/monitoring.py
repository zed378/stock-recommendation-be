"""Group G - near-real-time monitoring and alerts.

Two tables, and the distinction between them matters. `quote_snapshots` is
observation: what the provider said, when, and how stale it admitted to being.
`alerts` is interpretation: a condition someone asked to be told about, which
was met.

Keeping them apart means an alert can always be traced back to the observation
that produced it, and a wrong alert can be diagnosed as either a bad rule or
bad data rather than leaving both suspects.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from aidss.db.base import Base, enum_column, new_uuid, utcnow


class AlertKind(StrEnum):
    """What happened. Never what to do about it.

    Closed for the same reason `NotificationEvent` is: every member names an
    observation, so no future caller can introduce an instruction-shaped alert
    by passing a different string. An alert says a level was crossed or a stance
    changed; the analysis screen - with its confidence, its counter-evidence,
    and its disclaimer - is where the reader decides what that means.
    """

    #: Price came within the configured distance of a stored support or
    #: resistance level.
    LEVEL_APPROACHED = "level_approached"
    LEVEL_CROSSED = "level_crossed"
    #: The latest analysis reached a different stance than the one before it.
    STANCE_CHANGED = "stance_changed"
    #: Price is consuming the session's auto-rejection band.
    LIMIT_PROXIMITY = "limit_proximity"
    #: Price reached the level a stored recommendation suggested as a stop.
    SUGGESTED_STOP_REACHED = "suggested_stop_reached"
    #: A move large relative to the asset's own recent volatility.
    UNUSUAL_MOVE = "unusual_move"

    # --- price against stored levels -------------------------------------
    #: Price came within the approach band of a stored *support* level. The
    #: mirror of `level_approached`, which only ever fired for resistance -
    #: so the one side people watch for a bounce was the one side never
    #: reported.
    SUPPORT_APPROACHED = "support_approached"
    #: Closed above a resistance level, or below a support level. Distinct
    #: from `level_crossed`, which is about a single trade printing through:
    #: these are stated on the close, which is what people mean by a break.
    RESISTANCE_BROKEN = "resistance_broken"
    SUPPORT_BROKEN = "support_broken"
    #: Broke a level and fell back under it within a few sessions.
    FALSE_BREAKOUT = "false_breakout"

    # --- volume ----------------------------------------------------------
    #: Volume at or above twice its own 20-day average.
    VOLUME_SPIKE = "volume_spike"
    #: A volume spike while the price has not yet moved much. Reported
    #: separately because the pairing is the point: busy *before* the move is
    #: a different observation from busy *because of* it.
    VOLUME_SPIKE_QUIET = "volume_spike_quiet"

    # --- moving averages and momentum -------------------------------------
    GOLDEN_CROSS = "golden_cross"
    DEATH_CROSS = "death_cross"
    #: The MACD line crossed its signal line. Direction carries which way.
    MACD_CROSSED = "macd_crossed"
    RSI_OVERSOLD = "rsi_oversold"
    RSI_OVERBOUGHT = "rsi_overbought"
    STOCHASTIC_OVERSOLD = "stochastic_oversold"
    STOCHASTIC_OVERBOUGHT = "stochastic_overbought"

    # --- session shape ----------------------------------------------------
    GAP_UP = "gap_up"
    GAP_DOWN = "gap_down"

    # --- position in the year's range -------------------------------------
    AT_52_WEEK_HIGH = "at_52_week_high"
    AT_52_WEEK_LOW = "at_52_week_low"

    # --- volatility --------------------------------------------------------
    #: Bollinger bands narrower than they have been in months. States the
    #: compression, not what follows it: a squeeze says the market has stopped
    #: disagreeing about price, and nothing about which way it resolves.
    VOLATILITY_SQUEEZE = "volatility_squeeze"
    #: A session whose range is far wider than this issuer's average.
    RANGE_EXPANSION = "range_expansion"

    #: Distance to the nearest resistance is at least twice the distance to the
    #: nearest support. A geometric observation about two stored levels, not a
    #: suggestion to take the trade.
    REWARD_TO_RISK_REACHED = "reward_to_risk_reached"

    #: A disclosed, dated event for this issuer falls inside the notice window.
    #: The alert states the date and what it is; it holds no view on what the
    #: event will do to the price, because nothing in this platform knows that.
    AGENDA_UPCOMING = "agenda_upcoming"

    #: Price fell a set percentage from its peak since a holding was opened.
    TRAILING_STOP_REACHED = "trailing_stop_reached"

    #: Net foreign buying or selling far above its own recent average.
    FOREIGN_FLOW_SPIKE = "foreign_flow_spike"

    #: Price at a stored support level while RSI is making a higher low. A
    #: combination rather than two alerts, because either alone says much less
    #: than the two together.
    SUPPORT_WITH_DIVERGENCE = "support_with_divergence"


class AlertDirection(StrEnum):
    UP = "up"
    DOWN = "down"
    NONE = "none"


class QuoteSnapshot(Base):
    """One observation of a price, with its staleness recorded.

    `is_delayed` is not decoration. The free sources this platform runs on are
    delayed by roughly fifteen minutes, and an interface that shows a delayed
    price without saying so invites decisions made on numbers that have already
    moved. The provider is asked rather than assumed - `supports_realtime()` -
    so switching to a live feed changes this field rather than a caveat
    somebody has to remember to delete.
    """

    __tablename__ = "quote_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True
    )
    price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    previous_close: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), default=None)
    #: As reported by the provider, not the time we stored it.
    quoted_at: Mapped[datetime] = mapped_column()
    observed_at: Mapped[datetime] = mapped_column(default=utcnow)
    source: Mapped[str] = mapped_column(String(60))
    is_delayed: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (Index("ix_quote_asset_observed", "asset_id", "observed_at"),)


class Alert(Base):
    """A condition someone asked to be told about, which was met."""

    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[AlertKind] = mapped_column(enum_column(AlertKind, length=30))
    direction: Mapped[AlertDirection] = mapped_column(
        enum_column(AlertDirection, length=10), default=AlertDirection.NONE
    )

    #: What was observed, and what it was compared against. Both stored so an
    #: alert read a week later still says why it fired, without depending on
    #: levels that have since been recomputed.
    observed_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), default=None)
    reference_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), default=None)

    #: A statement of fact, phrased as one. The stance, if any, travels in
    #: `context` as data rather than in prose that could read as a command.
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[dict[str, Any] | None] = mapped_column(default=None)

    triggered_at: Mapped[datetime] = mapped_column(default=utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column(default=None)

    #: Stops one condition from firing on every poll. Includes whatever makes
    #: the occurrence distinct - the level, the session, the stance - so a
    #: genuinely new crossing is not suppressed along with the repeats.
    dedup_key: Mapped[str] = mapped_column(String(200), unique=True)

    __table_args__ = (
        Index("ix_alert_user_triggered", "user_id", "triggered_at"),
        UniqueConstraint("dedup_key", name="uq_alert_dedup"),
    )

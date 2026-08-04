"""Domain types exchanged between layers.

These are the provider-agnostic contract: every provider adapter (Section 7)
must return these shapes, so Core Logic never sees a vendor's raw schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class Timeframe(StrEnum):
    """Timeframes the Indicator Engine supports (Section 5.3, multi-timeframe)."""

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1w"
    MN1 = "1M"

    @property
    def seconds(self) -> int:
        return _TIMEFRAME_SECONDS[self]


_TIMEFRAME_SECONDS: dict[Timeframe, int] = {
    Timeframe.M1: 60,
    Timeframe.M5: 300,
    Timeframe.M15: 900,
    Timeframe.M30: 1800,
    Timeframe.H1: 3600,
    Timeframe.H4: 14400,
    Timeframe.D1: 86400,
    Timeframe.W1: 604800,
    # Month length varies; this value is only used for ordering and rough
    # estimates, never for calendar arithmetic.
    Timeframe.MN1: 2592000,
}


class RecommendationLabel(StrEnum):
    """The graded labels of Section 5.4.

    Defined here rather than in either the database models or the prompt
    schemas, because both need it and two copies of a vocabulary drift apart.

    Every label names a *stance*, not an action. There is no `execute`, no
    `enter`, no `exit` - the vocabulary itself refuses to express an order.
    """

    STRONG_BUY = "strong_buy"
    BUY = "buy"
    WATCHLIST = "watchlist"
    HOLD = "hold"
    REDUCE = "reduce"
    SELL = "sell"

    @property
    def direction(self) -> int:
        """+1 constructive, 0 neutral, -1 cautious. Used for consistency checks."""
        return _LABEL_DIRECTION[self]

    @property
    def is_strong(self) -> bool:
        """Whether the label claims high conviction and must be backed by it."""
        return self in (RecommendationLabel.STRONG_BUY, RecommendationLabel.SELL)


_LABEL_DIRECTION: dict[RecommendationLabel, int] = {
    RecommendationLabel.STRONG_BUY: 1,
    RecommendationLabel.BUY: 1,
    RecommendationLabel.WATCHLIST: 0,
    RecommendationLabel.HOLD: 0,
    RecommendationLabel.REDUCE: -1,
    RecommendationLabel.SELL: -1,
}


class InvestmentHorizon(StrEnum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


@dataclass(frozen=True, slots=True)
class Candle:
    """One normalised OHLCV bar. The timestamp is always timezone-aware UTC."""

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("Candle.timestamp must be timezone-aware (UTC)")


@dataclass(frozen=True, slots=True)
class Quote:
    """Latest price for a single instrument."""

    ticker: str
    price: Decimal
    timestamp: datetime
    previous_close: Decimal | None = None
    volume: Decimal | None = None


@dataclass(frozen=True, slots=True)
class FundamentalPoint:
    """One reported financial metric for one period.

    A long, narrow shape rather than a wide record per period: providers expose
    wildly different metric sets, and a fixed set of columns would either omit
    what one provider offers or leave most of them null for the rest.
    """

    metric: str
    period: date
    value: Decimal | None
    #: "quarterly", "annual", "ttm", or "ytd". A quarterly figure compared
    #: against an annual one is a factor-of-four error waiting to happen, so
    #: the basis travels with the number.
    #:
    #: `ytd` is here because IDX reports year-to-date cumulative figures: a
    #: statement dated 30 September carries nine months of revenue. None of the
    #: other three describes that. Calling it annual overstates by a third,
    #: quarterly understates threefold, and `ttm` is a different window
    #: entirely - so the honest answer was a fourth basis rather than the
    #: nearest of three wrong ones.
    period_type: str = "quarterly"

    def __post_init__(self) -> None:
        allowed = {"quarterly", "annual", "ttm", "ytd"}
        if self.period_type not in allowed:
            raise ValueError(f"period_type must be one of {sorted(allowed)}")


@dataclass(frozen=True, slots=True)
class NewsArticle:
    """A raw article from a NewsProvider, before sentiment analysis."""

    source: str
    source_url: str
    headline: str
    published_at: datetime
    summary: str | None = None
    tickers: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """A message in the OpenAI-compatible contract (Section 12.2)."""

    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ChatCompletion:
    """A chat completion result, normalised across providers."""

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    raw: dict = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

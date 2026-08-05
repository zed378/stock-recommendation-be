"""IDX auto-rejection bands, and what can honestly be said about them.

The exchange refuses orders priced beyond a percentage of the previous day's
close. Hitting the ceiling is **Auto Reject Atas** (ARA); the floor is **Auto
Reject Bawah** (ARB). The band widens as the price falls, so a Rp 100 stock can
move a third in a day while a Rp 10,000 one cannot.

Two things this module is careful about.

**The bands are configuration, not constants.** IDX has revised them several
times - symmetric, then asymmetric during the 2020 drawdown, then back - and a
number hardcoded in a screener silently becomes wrong the day it changes. The
defaults below are the long-standing symmetric bands; override them if the
exchange moves and the platform has not been updated yet.

**Proximity is measurable; "will hit ARA" is not.** What can be computed from
stored data is how far today's price is from the ceiling the exchange will
enforce, and whether that gap is closing on unusual volume. That is a
screening observation. Calling it a prediction would attach a claim to it that
nothing here supports, so nothing here calls it one.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

#: (upper price bound exclusive, limit as a fraction). Ordered ascending; the
#: first band whose bound the reference price is below applies.
#:
#: Rp 50-200 -> 35%, Rp 200-5,000 -> 25%, above Rp 5,000 -> 20%.
DEFAULT_BANDS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal(200), Decimal("0.35")),
    (Decimal(5000), Decimal("0.25")),
)

#: Applied above the last band.
DEFAULT_TOP_BAND = Decimal("0.20")

#: The exchange's minimum tradable price. Below it, percentage reasoning stops
#: being meaningful because the tick size dominates.
MINIMUM_PRICE = Decimal(50)


@dataclass(frozen=True, slots=True)
class AutoRejectBand:
    """The ceiling and floor the exchange will enforce for one session."""

    reference_price: Decimal
    limit_fraction: Decimal
    ceiling: Decimal
    floor: Decimal

    def headroom(self, price: Decimal) -> Decimal | None:
        """How far ``price`` sits below the ceiling, as a fraction of the ceiling.

        0 means the ceiling is reached. None when the ceiling is not a usable
        denominator, which only happens for a nonsensical reference price -
        returning 0 there would read as "at the limit" and trigger a screen.
        """
        if self.ceiling <= 0:
            return None
        return (self.ceiling - price) / self.ceiling

    def proximity(self, price: Decimal) -> Decimal | None:
        """How much of the day's allowed upward move has been used, 0 to 1.

        1.0 means the price is at the ceiling. Values above 1 are clamped: a
        stored bar can exceed a band computed from a stale reference close, and
        reporting 1.4 would suggest the exchange allowed something it did not.
        """
        allowed = self.ceiling - self.reference_price
        if allowed <= 0:
            return None
        used = (price - self.reference_price) / allowed
        return max(Decimal(0), min(Decimal(1), used))


def limit_fraction(
    reference_price: Decimal,
    *,
    bands: tuple[tuple[Decimal, Decimal], ...] = DEFAULT_BANDS,
    top_band: Decimal = DEFAULT_TOP_BAND,
) -> Decimal:
    for bound, fraction in bands:
        if reference_price < bound:
            return fraction
    return top_band


def auto_reject_band(
    reference_price: Decimal,
    *,
    bands: tuple[tuple[Decimal, Decimal], ...] = DEFAULT_BANDS,
    top_band: Decimal = DEFAULT_TOP_BAND,
) -> AutoRejectBand | None:
    """The band for one session, or None when the reference price is unusable.

    None rather than a guess: a zero or negative previous close means the data
    is wrong, and inventing a band on top of bad data produces a screen result
    that looks as considered as any other.
    """
    if reference_price is None or reference_price < MINIMUM_PRICE:
        return None

    fraction = limit_fraction(reference_price, bands=bands, top_band=top_band)
    return AutoRejectBand(
        reference_price=reference_price,
        limit_fraction=fraction,
        ceiling=reference_price * (Decimal(1) + fraction),
        floor=reference_price * (Decimal(1) - fraction),
    )

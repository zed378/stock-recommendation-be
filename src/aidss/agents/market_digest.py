"""What the platform currently knows about the market, in one block.

The other chat modes are anchored on an issuer: pick a ticker, ask about it.
That is the wrong shape for most of what people actually want to ask - "what is
moving today", "what looks oversold", "what could I look at with two hundred
thousand rupiah" - none of which names a company, and all of which the platform
can answer from data it already has.

Without this the free-form mode would be a general-purpose chatbot wearing the
platform's name: fluent about markets in the abstract and unable to say a
single true thing about *this* exchange today. With it, a question about a
budget is answered from the actual closing prices of the actual issuers that
actually matched something on the last scan.

**Nothing here is fetched.** Every figure is read from what the scan already
stored, so the digest costs a few queries rather than a round trip to a
provider - which is what makes it affordable to attach on every turn.

**The digest is evidence, never a shortlist.** It carries what matched, not
what to do, and it is deliberately ordered by criteria count rather than by
anything resembling attractiveness. An ordering that implied a ranking would
put the platform's thumb on the scale before the model had even read the
question.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.db.models import Issuer, MarketScanResult

#: Issuers carried into the prompt. Enough that a budget question has real
#: candidates to work with, few enough that the block stays a digest rather
#: than becoming the whole scan pasted into a prompt.
SAMPLE_SIZE = 40

#: Price bands, in rupiah. Present because the most common question this mode
#: gets is shaped by what the asker can afford, and a model asked to filter
#: eight hundred prices in its head does it badly.
BANDS: tuple[tuple[str, Decimal, Decimal | None], ...] = (
    ("under_100", Decimal(0), Decimal(100)),
    ("100_to_500", Decimal(100), Decimal(500)),
    ("500_to_2000", Decimal(500), Decimal(2000)),
    ("2000_to_10000", Decimal(2000), Decimal(10000)),
    ("above_10000", Decimal(10000), None),
)


def _plain(value: Decimal) -> str:
    """A price without the column's trailing scale.

    `Numeric(24, 8)` reads back as "500.00000000", which is the same number and
    a worse thing to put in a prompt: it spends tokens on zeroes and invites a
    model to treat the precision as meaningful.
    """
    trimmed = value.normalize()
    # `normalize` turns 50000 into 5E+4, which is correct and unreadable.
    return format(trimmed, "f")


def _band(close: Decimal | None) -> str | None:
    if close is None:
        return None
    for name, low, high in BANDS:
        if close >= low and (high is None or close < high):
            return name
    return None


def build(session: Session, *, on_date: date | None = None) -> dict[str, Any]:
    """The market as the last scan left it.

    Returns an empty digest when nothing has been scanned. Empty rather than
    partial: a block that names a session date with no issuers under it reads
    as a market where nothing happened, which is a different claim from "this
    platform has not looked yet".
    """
    from aidss.monitoring.scan import latest_scan_date

    on_date = on_date or latest_scan_date(session)
    if on_date is None:
        return {}

    rows = list(
        session.scalars(
            select(MarketScanResult).where(MarketScanResult.session_date == on_date)
        ).all()
    )
    if not rows:
        return {}

    names = {
        issuer.ticker: issuer.name
        for issuer in session.scalars(
            select(Issuer).where(Issuer.ticker.in_([row.ticker for row in rows] or [""]))
        ).all()
    }

    counts: Counter[str] = Counter()
    bands: Counter[str] = Counter()
    for row in rows:
        counts.update(row.matched or [])
        band = _band(row.close)
        if band:
            bands[band] += 1

    # Ordered by how many criteria each issuer met, which is a count of
    # observations rather than a judgement. Ties broken by ticker so the same
    # scan always produces the same block - a digest that reshuffles between
    # turns makes an answer impossible to reproduce.
    ranked = sorted(rows, key=lambda row: (-(row.matched_count or 0), row.ticker))

    return {
        "session_date": on_date.isoformat(),
        "issuers_scanned": len(rows),
        "issuers_with_a_match": sum(1 for row in rows if row.matched),
        # How many issuers met each criterion, so the model can see which
        # observations are common today and which are rare. Without it, a
        # criterion that fired for four hundred issuers reads as significant.
        "criteria_frequency": dict(counts.most_common()),
        "issuers_per_price_band": dict(bands),
        "sample": [
            {
                "ticker": row.ticker,
                "name": names.get(row.ticker),
                "close": _plain(row.close) if row.close is not None else None,
                "matched": list(row.matched or []),
            }
            for row in ranked[:SAMPLE_SIZE]
        ],
        "sample_note": (
            f"The {min(SAMPLE_SIZE, len(ranked))} issuers that met the most criteria on "
            f"{on_date.isoformat()}, ordered by how many they met. That ordering counts "
            "observations; it is not a ranking by quality, expected return, or "
            "suitability, and it must not be presented as one."
        ),
    }


def affordable(digest: dict[str, Any], budget: Decimal, *, lot_size: int = 100) -> list[dict]:
    """The sampled issuers whose one-lot cost fits a budget.

    IDX trades in lots of a hundred, so a share priced at 3,000 costs 300,000
    to buy at all. A budget question answered against the share price rather
    than the lot price is wrong by two orders of magnitude, and wrong in the
    direction that makes something look affordable when it is not.
    """
    out = []
    for entry in digest.get("sample") or []:
        close = entry.get("close")
        if close is None:
            continue
        lot_cost = Decimal(str(close)) * lot_size
        if lot_cost <= budget:
            out.append({**entry, "one_lot_cost": _plain(lot_cost)})
    return out

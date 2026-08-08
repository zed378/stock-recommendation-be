"""Deterministic scoring that runs before any model is called.

A full multi-agent run is a dozen model calls. Most of them are spent the same
way whether the issuer moved four percent on triple volume or sat unchanged on
a quiet tape - the pipeline has no way to tell those apart before it starts,
so it pays for the second case at the price of the first.

This reads the numbers the platform already computed - the market scan's stored
signals, the criteria that matched, the indicator snapshot - and decides two
things: how deep the run should go, and which model tier should serve it. Both
decisions are made from arithmetic, before any prompt exists.

**It does not predict anything.** The score answers "how much is happening with
this issuer", which is a statement about the last few sessions and is settled
by the time it is read. It carries no view on direction and no probability of
anything. Naming matters here more than usual: a number attached to a ticker is
read as a forecast unless the code it lives in is careful, so nothing in this
module is called a signal, a prediction, or a confidence.

The saving is real but bounded, and worth stating honestly: triage cannot make
a thorough analysis cheaper. It can only avoid buying a thorough analysis for
an issuer where nothing happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from aidss.llm.router import TaskComplexity

#: Matched criteria at or above this count mean the scan already found several
#: things worth explaining, which is what a deep run is for.
BUSY_CRITERIA = 3

#: Session range against the issuer's own average true range. Measured that way
#: rather than as a fixed percentage because two percent is an ordinary day for
#: one issuer and a violent one for another, and a single threshold would treat
#: a sleepy utility and a small-cap the same.
NOTABLE_RANGE = Decimal("1.5")

#: Volume relative to its own recent average.
NOTABLE_VOLUME = Decimal("1.8")


class Depth(StrEnum):
    """How much of the pipeline this run is worth."""

    #: Everything, on the strongest configured model.
    FULL = "full"
    #: The usual set of analyzers.
    STANDARD = "standard"
    #: Quiet issuer. Analyzers that need something to have happened are skipped
    #: and the rest are served by the cheap tier.
    LIGHT = "light"


@dataclass(frozen=True, slots=True)
class Triage:
    """The pre-analysis decision, with the arithmetic that produced it."""

    depth: Depth
    score: float
    #: Plain-language facts behind the depth, in the reader's vocabulary.
    #: Present for the same reason the screen lists its criteria: a routing
    #: decision that cannot be explained is a routing decision nobody will
    #: trust when it is wrong.
    because: list[str]

    @property
    def complexity(self) -> TaskComplexity:
        """Which model tier serves this run."""
        return TaskComplexity.LIGHT if self.depth is Depth.LIGHT else TaskComplexity.COMPLEX

    def as_payload(self) -> dict[str, Any]:
        return {
            "depth": self.depth.value,
            "score": round(self.score, 3),
            "because": list(self.because),
        }


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def assess(
    *,
    matched: list[str] | None = None,
    signals: dict[str, Any] | None = None,
    requested_full: bool = False,
) -> Triage:
    """Decide the depth of a run from what is already stored.

    `requested_full` is the reader pressing "run analysis" on a specific
    issuer. That always earns a full run regardless of how quiet the tape is:
    somebody asking about a stock directly has a reason the numbers do not
    know about, and answering them with the cheap path would make the feature
    feel broken exactly when it is being used deliberately.
    """
    matched = matched or []
    signals = signals or {}
    because: list[str] = []
    score = 0.0

    if requested_full:
        return Triage(
            depth=Depth.FULL,
            score=1.0,
            because=["analysis was requested for this issuer directly"],
        )

    if len(matched) >= BUSY_CRITERIA:
        score += 0.5
        because.append(f"{len(matched)} scan criteria matched")
    elif matched:
        score += 0.2 * len(matched)
        because.append(f"{len(matched)} scan criteria matched")

    spread = _decimal(signals.get("range_ratio"))
    if spread is not None and spread >= NOTABLE_RANGE:
        score += 0.3
        because.append(f"session range is {spread:.1f}x the issuer's average true range")

    volume = _decimal(signals.get("volume_ratio"))
    if volume is not None and volume >= NOTABLE_VOLUME:
        score += 0.2
        because.append(f"volume is {volume:.1f}x its recent average")

    if score >= 0.5:
        depth = Depth.FULL
    elif score > 0:
        depth = Depth.STANDARD
    else:
        depth = Depth.LIGHT
        because.append("nothing in the stored numbers stands out for this issuer")

    return Triage(depth=depth, score=min(score, 1.0), because=because)


def triage_for(session, ticker: str, *, requested_full: bool = False) -> Triage:
    """`assess` against the most recent stored scan for one ticker.

    Falls back to a standard run when the issuer has never been scanned. Not
    light: an unscanned issuer is one nothing is known about, and "nothing is
    known" is not the same finding as "nothing is happening".
    """
    from sqlalchemy import select

    from aidss.db.models import MarketScanResult

    if requested_full:
        return assess(requested_full=True)

    row = session.scalar(
        select(MarketScanResult)
        .where(MarketScanResult.ticker == ticker.upper())
        .order_by(MarketScanResult.session_date.desc())
        .limit(1)
    )
    if row is None:
        return Triage(
            depth=Depth.STANDARD,
            score=0.0,
            because=["this issuer has not been scanned yet"],
        )
    return assess(matched=list(row.matched or []), signals=dict(row.signals or {}))

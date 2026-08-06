"""Keeping the listed-company directory in step with the exchange.

The directory exists so news can be attributed to a company. That makes its
*completeness* the property that matters: a story about an issuer missing from
the table is not mis-tagged, it is silently untagged, and nothing downstream
can tell the difference between "no company was mentioned" and "the company
mentioned is not in our list".

Sourced from IDX's own company-profile endpoint - the same public origin the
fundamentals adapter already reads, so this adds no new dependency and no new
question about where the data came from.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.db.models import Issuer
from aidss.news.tagging import derive_aliases

logger = logging.getLogger("aidss.issuers")


@dataclass
class DirectorySync:
    """What one synchronisation did."""

    added: int = 0
    updated: int = 0
    unchanged: int = 0
    delisted: int = 0
    skipped: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.added + self.updated + self.unchanged

    def as_payload(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "delisted": self.delisted,
            "total": self.total,
            "skipped": self.skipped[:20],
        }


def _listing_date(raw: Any) -> date | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _clean(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text[:limit] if text else None


def sync_directory(session: Session, rows: list[dict[str, Any]]) -> DirectorySync:
    """Upsert the exchange's company list into ``issuers``.

    Idempotent, and re-runnable as often as anyone likes: matching is on the
    ticker, so a second pass updates rather than duplicates.

    Two decisions worth naming:

      * **Aliases already present are kept.** They are the one part of a row a
        person can correct, and an import that recomputed them would silently
        discard that correction on the next scheduled run - the surest way to
        make an editable field useless.
      * **Issuers that vanish from the feed are marked, not deleted.** Their
        news is still in the database and still refers to them. A tag pointing
        at a row that no longer exists is worse than one pointing at a company
        that no longer trades.
    """
    report = DirectorySync()
    existing = {issuer.ticker: issuer for issuer in session.scalars(select(Issuer)).all()}
    seen: set[str] = set()

    for row in rows:
        ticker = _clean(row.get("KodeEmiten"), 20)
        name = _clean(row.get("NamaEmiten"), 300)
        if not ticker or not name:
            # A row without a code or a name cannot be matched against or
            # displayed. Recorded rather than dropped quietly.
            report.skipped.append(str(row.get("KodeEmiten") or row.get("NamaEmiten") or "?"))
            continue

        ticker = ticker.upper()
        seen.add(ticker)
        fields = {
            "name": name,
            "sector": _clean(row.get("Sektor"), 120),
            "sub_sector": _clean(row.get("SubSektor"), 120),
            "industry": _clean(row.get("Industri"), 120),
            "listing_board": _clean(row.get("PapanPencatatan"), 60),
            "listed_on": _listing_date(row.get("TanggalPencatatan")),
            "website": _clean(row.get("Website"), 300),
            "is_listed": True,
        }

        issuer = existing.get(ticker)
        if issuer is None:
            session.add(
                Issuer(ticker=ticker, aliases=derive_aliases(name), **fields)
            )
            report.added += 1
            continue

        changed = [key for key, value in fields.items() if getattr(issuer, key) != value]
        if not issuer.aliases:
            # Derived only when there is nothing to lose. A row whose aliases
            # were curated keeps them.
            issuer.aliases = derive_aliases(name)
            changed.append("aliases")
        if changed:
            for key, value in fields.items():
                setattr(issuer, key, value)
            issuer.synced_at = datetime.now(UTC)
            report.updated += 1
        else:
            report.unchanged += 1

    for ticker, issuer in existing.items():
        if ticker not in seen and issuer.is_listed:
            issuer.is_listed = False
            report.delisted += 1

    session.flush()
    logger.info("issuer directory synchronised", extra=report.as_payload())
    return report

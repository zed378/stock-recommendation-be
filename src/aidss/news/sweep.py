"""Reading every configured feed once, then working out who each story is about.

The scheduled pipeline is ticker-driven: for each asset somebody watches, ask
the provider for news about it. That shape has a floor it cannot get under - a
story is only ever seen because a ticker went looking for it, so coverage of a
company nobody watches is not merely untagged, it is never fetched at all. And
a general feed gets re-read once per watched ticker, with everything not
matching that one ticker discarded each time.

This sweep runs the other way. Every active feed is read once, everything it
carries is stored, and attribution happens afterwards against the full
issuer directory. An article naming six banks is tagged to six banks rather
than filed under whichever one happened to fetch it.

The two coexist deliberately. The schedules keep their guarantee of freshness
per watched ticker; this fills in everything around them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.db.models import Issuer, NewsItem, NewsItemIssuer, NewsSource
from aidss.domain.types import NewsArticle
from aidss.news.collector import content_hash
from aidss.news.tagging import IssuerMatcher, IssuerPattern

logger = logging.getLogger("aidss.news")

#: Entries taken from any one feed in a single sweep. A feed that returns its
#: whole archive should not turn one press of a button into fifty thousand
#: inserts.
MAX_ENTRIES_PER_SOURCE = 200


@dataclass
class SweepReport:
    """What one sweep read, stored and attributed."""

    sources_read: int = 0
    sources_failed: int = 0
    fetched: int = 0
    inserted: int = 0
    duplicates: int = 0
    tagged: int = 0
    untagged: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        return {
            "sources_read": self.sources_read,
            "sources_failed": self.sources_failed,
            "fetched": self.fetched,
            "inserted": self.inserted,
            "duplicates": self.duplicates,
            "tagged": self.tagged,
            "untagged": self.untagged,
            "failures": self.failures[:20],
        }


def build_matcher(session: Session) -> IssuerMatcher:
    """The matcher for every issuer currently listed.

    Built once per sweep rather than per article: the directory is a thousand
    rows, and rebuilding it for each of several hundred stories would dominate
    the run.
    """
    issuers = session.scalars(select(Issuer).where(Issuer.is_listed.is_(True))).all()
    return IssuerMatcher(
        [
            IssuerPattern(
                issuer.id,
                issuer.ticker,
                issuer.name,
                tuple(str(a) for a in (issuer.aliases or [])),
            )
            for issuer in issuers
        ]
    )


def tag_item(session: Session, item: NewsItem, matcher: IssuerMatcher) -> int:
    """Attribute one story, replacing whatever it was attributed to before.

    Replacing rather than adding, because re-tagging exists precisely for when
    the directory or an alias has changed. Leaving the old tags in place would
    make a corrected alias unable to undo the wrong tag it caused.
    """
    tags = matcher.match(item.headline, item.body_summary)

    existing = session.scalars(
        select(NewsItemIssuer).where(NewsItemIssuer.news_item_id == item.id)
    ).all()
    keep = {tag.issuer_id for tag in tags}
    for row in existing:
        if row.issuer_id not in keep:
            session.delete(row)
    already = {row.issuer_id for row in existing if row.issuer_id in keep}

    for tag in tags:
        if tag.issuer_id in already:
            continue
        session.add(
            NewsItemIssuer(
                news_item_id=item.id,
                issuer_id=tag.issuer_id,
                ticker=tag.ticker,
                method=tag.method,
                matched_text=tag.matched_text[:200],
            )
        )
    return len(tags)


def tag_untagged(session: Session, *, limit: int = 500) -> dict[str, Any]:
    """Attribute stories that have no tags yet.

    Bounded, because this runs over whatever the database already holds and an
    unbounded pass over a year of news would hold a transaction open for
    minutes. Called repeatedly it converges; the count returned says whether
    another pass is worth running.
    """
    matcher = build_matcher(session)
    tagged_ids = select(NewsItemIssuer.news_item_id).distinct()
    items = session.scalars(
        select(NewsItem)
        .where(NewsItem.id.not_in(tagged_ids))
        .order_by(NewsItem.published_at.desc())
        .limit(limit)
    ).all()

    tagged = 0
    for item in items:
        if tag_item(session, item, matcher):
            tagged += 1
    session.flush()
    return {"considered": len(items), "tagged": tagged, "untagged": len(items) - tagged}


def sweep_all_sources(session: Session, provider: Any) -> SweepReport:
    """Read every active feed and store and attribute everything in it.

    A feed that fails does not stop the sweep. One dead URL out of twenty must
    not cost the other nineteen their news - which is the behaviour that made
    the old pipeline's silence so hard to notice.
    """
    report = SweepReport()
    sources = list(
        session.scalars(
            select(NewsSource)
            .where(NewsSource.is_active.is_(True))
            .order_by(NewsSource.name)
        ).all()
    )
    if not sources:
        # Not an empty result. Zero sources means nobody configured any, and
        # reporting "no news" would let that sit unnoticed indefinitely - the
        # exact condition this subsystem was already found in once.
        raise ValueError("no active news sources are configured")

    matcher = build_matcher(session)
    seen_in_run: set[str] = set()

    for source in sources:
        url = source.feed_url
        if "{ticker}" in url:
            # A templated feed is a search URL; without a ticker to put in it
            # there is nothing to fetch. The per-ticker schedules cover these.
            continue
        try:
            entries = provider.fetch(url)
        except Exception as exc:  # noqa: BLE001 - httpx and the parser raise broadly
            report.sources_failed += 1
            report.failures.append({"source": source.name, "error": f"{type(exc).__name__}: {exc}"})
            provider.record(source, count=None, error=str(exc)[:500])
            continue

        report.sources_read += 1
        provider.record(source, count=len(entries), error=None)

        for entry in entries[:MAX_ENTRIES_PER_SOURCE]:
            report.fetched += 1
            article = NewsArticle(
                headline=entry.title,
                summary=entry.summary,
                source=source.name,
                source_url=entry.link,
                published_at=entry.published_at,
            )
            digest = content_hash(article)
            if digest in seen_in_run:
                report.duplicates += 1
                continue
            seen_in_run.add(digest)
            if session.scalar(select(NewsItem.id).where(NewsItem.dedup_hash == digest)):
                report.duplicates += 1
                continue

            item = NewsItem(
                # Left null on purpose. `asset_id` records which asset's
                # scheduled fetch retrieved an article; nothing retrieved this
                # one on an asset's behalf, and filling it in with a tag would
                # conflate "who fetched it" with "who it is about".
                asset_id=None,
                source=source.name[:120],
                source_url=article.source_url[:1000],
                dedup_hash=digest,
                headline=article.headline[:500],
                body_summary=article.summary,
                published_at=article.published_at,
            )
            session.add(item)
            session.flush()
            report.inserted += 1

            if tag_item(session, item, matcher):
                report.tagged += 1
            else:
                report.untagged += 1

    session.flush()
    logger.info("news sweep finished", extra=report.as_payload())
    return report

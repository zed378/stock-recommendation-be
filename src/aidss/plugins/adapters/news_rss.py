"""News from RSS and Atom feeds an administrator configures.

The first real ``NewsProvider`` in the tree. Until this existed the only one was
a fixture that manufactured plausible headlines for tests - and it was also the
configured default, so the entire scheduled pipeline ran end to end, reported
success, and stored nothing a person had written.

Sources live in the database rather than in settings, because the people who
decide which publications to follow are not the people who redeploy the stack.

Three behaviours worth stating outright:

  * **A broken feed is recorded, not swallowed.** Each source keeps its last
    status, its last error, and a failure count. A feed that started answering
    404 is otherwise indistinguishable from a feed with no news, which is the
    exact condition this subsystem sat in unnoticed.
  * **No sources configured is an error, not an empty result.** Returning zero
    articles would tell the schedule there was no news, and it would go on
    saying that forever.
  * **Feeds are fetched once per pass, not once per ticker.** A general
    headline feed serves every asset; without the cache a watchlist of fifty
    would fetch the same URL fifty times and earn a rate limit.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.config import Settings
from aidss.db.models import Asset, NewsSource
from aidss.domain.types import NewsArticle
from aidss.plugins.errors import ProviderUnavailableError
from aidss.plugins.interfaces import NewsProvider
from aidss.plugins.registry import register
from aidss.syndication.feeds import FeedEntry, FeedParseError, mentions, parse_feed

logger = logging.getLogger("aidss.news")

#: Feeds refuse a default httpx agent often enough to be worth setting.
_USER_AGENT = "Mozilla/5.0 (compatible; aidss/0.1; +https://github.com/)"

#: A feed document past this is not a feed. Read as a stream and abandoned at
#: the limit, so a hostile or broken endpoint cannot serve gigabytes into
#: memory before the parser ever sees it.
MAX_FEED_BYTES = 4 * 1024 * 1024

#: How long a fetched feed stays reusable within a pass. Long enough that one
#: ingestion run over a whole watchlist reuses it, short enough that a manual
#: re-run minutes later sees anything new.
CACHE_TTL_SECONDS = 300

#: Consecutive failures before a source is deactivated automatically. Kept
#: high: a publication having a bad afternoon should not need an admin to turn
#: it back on.
FAILURE_DEACTIVATE_THRESHOLD = 20


@dataclass(slots=True)
class _CacheEntry:
    fetched_at: float
    entries: list[FeedEntry]


#: Keyed by resolved URL. Module-level so it survives across the several
#: provider instances one worker pass constructs.
_CACHE: dict[str, _CacheEntry] = {}


def clear_cache() -> None:
    """Drop the fetched-feed cache. For tests and for a manual re-run."""
    _CACHE.clear()


@register
class RssNewsProvider(NewsProvider):
    name: ClassVar[str] = "rss"

    def __init__(self, session: Session | None = None, *, timeout: float = 15.0) -> None:
        self._session = session
        self._timeout = timeout

    @classmethod
    def from_settings(cls, settings: Settings) -> RssNewsProvider:
        return cls(timeout=float(settings.http_timeout_seconds))

    def bind_session(self, session: Session) -> RssNewsProvider:
        self._session = session
        return self

    # --- reading the configured sources ---------------------------------

    def _sources(self, asset_id: uuid.UUID | None) -> list[NewsSource]:
        """Active feeds that apply to this asset: its own, plus the general ones."""
        assert self._session is not None
        stmt = select(NewsSource).where(NewsSource.is_active.is_(True))
        if asset_id is None:
            stmt = stmt.where(NewsSource.asset_id.is_(None))
        else:
            stmt = stmt.where(
                (NewsSource.asset_id == asset_id) | (NewsSource.asset_id.is_(None))
            )
        return list(self._session.scalars(stmt.order_by(NewsSource.name)).all())

    def _asset_for(self, ticker: str) -> Asset | None:
        assert self._session is not None
        return self._session.scalar(select(Asset).where(Asset.ticker == ticker.upper()))

    # --- fetching --------------------------------------------------------

    def fetch(self, url: str) -> list[FeedEntry]:
        """Read and parse one feed. Public because the admin Test button is a
        legitimate caller - reaching into a private method to run a probe would
        be the same code with worse manners."""
        cached = _CACHE.get(url)
        if cached is not None and time.monotonic() - cached.fetched_at < CACHE_TTL_SECONDS:
            return cached.entries

        with httpx.Client(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/rss+xml, */*"},
        ) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_FEED_BYTES:
                        raise FeedParseError(
                            f"feed exceeded {MAX_FEED_BYTES} bytes and was abandoned"
                        )
                    chunks.append(chunk)

        entries = parse_feed(b"".join(chunks))
        _CACHE[url] = _CacheEntry(fetched_at=time.monotonic(), entries=entries)
        return entries

    def record(
        self,
        source: NewsSource,
        *,
        count: int | None,
        error: str | None,
        count_failure: bool = True,
    ) -> None:
        """Write what happened to this feed onto the feed itself.

        `count_failure` is false when an administrator pressed Test. The
        outcome is still recorded - that is the point of testing, and the
        "failing" filter has to be able to find it - but a probe must not push
        a feed towards being switched off. Debugging a URL twenty times would
        otherwise disable it.
        """
        assert self._session is not None
        source.last_fetched_at = datetime.now(UTC)
        if error is None:
            source.last_status = "ok"
            source.last_error = None
            source.last_entry_count = count or 0
            source.consecutive_failures = 0
        else:
            source.last_status = "failed"
            # Truncated: some servers answer with an entire HTML error page,
            # and the column is for reading, not for archiving their markup.
            source.last_error = error[:500]
            if count_failure:
                source.consecutive_failures += 1
                if source.consecutive_failures >= FAILURE_DEACTIVATE_THRESHOLD:
                    source.is_active = False
        self._session.flush()

    # --- the contract -----------------------------------------------------

    def get_news(self, ticker: str, start: datetime, end: datetime) -> list[NewsArticle]:
        if self._session is None:  # pragma: no cover - a wiring mistake, not a state
            raise ProviderUnavailableError(
                self.name,
                "the RSS provider needs a database session; "
                "build it with get_news_provider(session=...)",
                retryable=False,
            )

        asset = self._asset_for(ticker)
        sources = self._sources(asset.id if asset else None)
        if not sources:
            # Not an empty result. Zero articles would tell the schedule there
            # was no news and it would keep saying so; this says the platform
            # has nowhere to look.
            raise ProviderUnavailableError(
                self.name,
                "no active news sources are configured - add one under Admin > News sources",
                retryable=False,
            )

        articles: list[NewsArticle] = []
        seen_links: set[str] = set()
        failures: list[str] = []

        for source in sources:
            url = source.feed_url.replace("{ticker}", ticker.upper())
            try:
                entries = self.fetch(url)
            except (httpx.HTTPError, FeedParseError) as exc:
                failures.append(f"{source.name}: {exc}")
                self.record(source, count=None, error=f"{type(exc).__name__}: {exc}")
                logger.warning(
                    "news feed unavailable", extra={"source": source.name, "url": url}
                )
                continue

            self.record(source, count=len(entries), error=None)

            # A templated URL asked the publisher for this ticker, and a
            # feed bound to one asset is about that asset. Neither needs the
            # keyword filter, which would only discard entries that qualify.
            targeted = source.is_templated or source.asset_id is not None

            for entry in entries:
                if not (start <= entry.published_at <= end):
                    continue
                if entry.link in seen_links:
                    # The same story syndicated across two configured feeds.
                    # The collector deduplicates too, on a content hash; this
                    # just avoids carrying the duplicate that far.
                    continue
                if not targeted and not mentions(
                    f"{entry.title} {entry.summary or ''}",
                    ticker,
                    asset.name if asset else None,
                ):
                    continue

                seen_links.add(entry.link)
                articles.append(
                    NewsArticle(
                        source=source.name,
                        source_url=entry.link,
                        headline=entry.title,
                        published_at=entry.published_at,
                        summary=entry.summary,
                        tickers=(ticker.upper(),),
                    )
                )

        if not articles and failures and len(failures) == len(sources):
            # Every configured feed failed. Reported as an outage so the
            # schedule's failure counter moves, rather than as a quiet day.
            raise ProviderUnavailableError(self.name, "; ".join(failures)[:500])

        articles.sort(key=lambda a: a.published_at, reverse=True)
        return articles

    def health_check(self) -> bool:
        """True when there is at least one active source to read.

        A provider that reports healthy with nothing configured is how this
        subsystem stayed broken without appearing to be.
        """
        if self._session is None:
            return False
        return bool(self._sources(None)) or bool(
            self._session.scalar(
                select(NewsSource).where(NewsSource.is_active.is_(True)).limit(1)
            )
        )

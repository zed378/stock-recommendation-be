"""Reading every feed once, and attributing what comes back.

The tagging rules themselves are covered in `test_news_tagging.py`. What is
tested here is the part that touches the database: that a sweep stores what it
read, that it attributes it to the right issuers, that a dead feed does not
take the others down with it, and that re-running is not a way to pay twice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from aidss.collectors.issuers import sync_directory
from aidss.db.models import Issuer, NewsItem, NewsItemIssuer, NewsSource, TagMethod
from aidss.news.sweep import sweep_all_sources, tag_untagged
from aidss.syndication.feeds import FeedEntry, FeedParseError

#: Shaped exactly like the rows IDX's company-profile endpoint returns.
IDX_ROWS = [
    {
        "KodeEmiten": "BBRI",
        "NamaEmiten": "PT Bank Rakyat Indonesia (Persero) Tbk",
        "Sektor": "Keuangan",
        "SubSektor": "Bank",
        "Industri": "Bank",
        "PapanPencatatan": "Utama",
        "TanggalPencatatan": "2003-11-10T00:00:00",
        "Website": "www.bri.co.id",
        "EfekEmiten_Saham": True,
    },
    {
        "KodeEmiten": "AADI",
        "NamaEmiten": "PT Adaro Andalan Indonesia Tbk",
        "Sektor": "Energi",
        "SubSektor": "Minyak, Gas & Batu Bara",
        "PapanPencatatan": "Utama",
        "TanggalPencatatan": "2024-12-05T00:00:00",
        "EfekEmiten_Saham": True,
    },
]


class StubFeeds:
    """A news provider standing in for the RSS one.

    Only `fetch` and `record` are used by the sweep, which is the whole point
    of the sweep taking a provider rather than reaching for one.
    """

    def __init__(self, feeds: dict[str, list[FeedEntry] | Exception]) -> None:
        self.feeds = feeds
        self.recorded: list[tuple[str, int | None, str | None]] = []
        self.fetches: list[str] = []

    def fetch(self, url: str) -> list[FeedEntry]:
        self.fetches.append(url)
        result = self.feeds.get(url, [])
        if isinstance(result, Exception):
            raise result
        return result

    def record(self, source, *, count, error, count_failure=True) -> None:  # noqa: ANN001
        self.recorded.append((source.name, count, error))


def entry(title: str, link: str, summary: str | None = None) -> FeedEntry:
    return FeedEntry(
        title=title,
        link=link,
        summary=summary,
        published_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
    )


@pytest.fixture
def directory(session):
    sync_directory(session, IDX_ROWS)
    return session


def add_source(session, name: str, url: str, *, active: bool = True) -> NewsSource:
    source = NewsSource(name=name, feed_url=url, is_active=active)
    session.add(source)
    session.flush()
    return source


# --- the directory ----------------------------------------------------------


def test_the_directory_is_imported_from_the_exchange_rows(session) -> None:
    report = sync_directory(session, IDX_ROWS)

    assert report.added == 2
    bbri = session.scalar(select(Issuer).where(Issuer.ticker == "BBRI"))
    assert bbri.name == "PT Bank Rakyat Indonesia (Persero) Tbk"
    assert bbri.sector == "Keuangan"
    assert bbri.listed_on.isoformat() == "2003-11-10"
    assert bbri.aliases, "aliases must be derived on import or nothing matches by name"


def test_re_importing_updates_rather_than_duplicates(session) -> None:
    sync_directory(session, IDX_ROWS)
    changed = [dict(IDX_ROWS[0], NamaEmiten="PT Bank Rakyat Indonesia Tbk"), IDX_ROWS[1]]

    report = sync_directory(session, changed)

    assert report.added == 0
    assert report.updated == 1
    assert report.unchanged == 1
    assert session.scalar(select(Issuer).where(Issuer.ticker == "BBRI")).name == (
        "PT Bank Rakyat Indonesia Tbk"
    )


def test_a_curated_alias_survives_the_next_synchronisation(session) -> None:
    """Derivation cannot know that BBRI is "BRI". Somebody types it in, and the
    next scheduled sync must not quietly throw it away - an editable field that
    resets on a timer is worse than no field at all."""
    sync_directory(session, IDX_ROWS)
    bbri = session.scalar(select(Issuer).where(Issuer.ticker == "BBRI"))
    bbri.aliases = ["bri", "bank rakyat indonesia"]
    session.flush()

    sync_directory(session, IDX_ROWS)

    session.refresh(bbri)
    assert "bri" in bbri.aliases


def test_an_issuer_that_leaves_the_feed_is_marked_not_deleted(session) -> None:
    """Its news still refers to it. A tag pointing at a deleted row is worse
    than one pointing at a company that no longer trades."""
    sync_directory(session, IDX_ROWS)

    report = sync_directory(session, [IDX_ROWS[0]])

    assert report.delisted == 1
    gone = session.scalar(select(Issuer).where(Issuer.ticker == "AADI"))
    assert gone is not None and gone.is_listed is False


# --- the sweep --------------------------------------------------------------


def test_a_sweep_stores_and_attributes_what_it_reads(directory) -> None:
    session = directory
    source = add_source(session, "Market Wire", "https://feed.test/all")
    provider = StubFeeds(
        {
            "https://feed.test/all": [
                entry("Saham BBRI menguat setelah laporan", "https://news.test/1"),
                entry("Adaro Andalan Indonesia rampungkan akuisisi", "https://news.test/2"),
                entry("Cuaca cerah di Jakarta akhir pekan ini", "https://news.test/3"),
            ]
        }
    )

    report = sweep_all_sources(session, provider)

    assert report.inserted == 3
    assert report.tagged == 2
    assert report.untagged == 1, "a story about nobody must be stored, just untagged"

    tags = session.scalars(select(NewsItemIssuer)).all()
    assert {(t.ticker, t.method) for t in tags} == {
        ("BBRI", TagMethod.TICKER_CODE),
        ("AADI", TagMethod.ALIAS),
    }
    assert provider.recorded == [("Market Wire", 3, None)]
    assert source.consecutive_failures == 0


def test_the_fetched_article_is_not_filed_under_an_asset(directory) -> None:
    """`asset_id` means "whose scheduled fetch retrieved this". Nothing
    retrieved a swept article on an asset's behalf, and writing a tag into that
    column would conflate who fetched it with who it is about."""
    session = directory
    add_source(session, "Market Wire", "https://feed.test/all")
    provider = StubFeeds(
        {"https://feed.test/all": [entry("Saham BBRI menguat", "https://news.test/1")]}
    )

    sweep_all_sources(session, provider)

    item = session.scalar(select(NewsItem))
    assert item.asset_id is None
    assert session.scalar(select(NewsItemIssuer)).ticker == "BBRI"


def test_one_dead_feed_does_not_cost_the_others_their_news(directory) -> None:
    """The behaviour that made this subsystem's earlier silence so hard to
    notice was a failure that stopped everything and reported nothing."""
    session = directory
    add_source(session, "Broken", "https://feed.test/broken")
    add_source(session, "Working", "https://feed.test/ok")
    provider = StubFeeds(
        {
            "https://feed.test/broken": FeedParseError("not a feed"),
            "https://feed.test/ok": [entry("Saham BBRI menguat", "https://news.test/1")],
        }
    )

    report = sweep_all_sources(session, provider)

    assert report.sources_failed == 1
    assert report.sources_read == 1
    assert report.inserted == 1
    assert report.failures[0]["source"] == "Broken"


def test_sweeping_twice_does_not_store_the_story_twice(directory) -> None:
    session = directory
    add_source(session, "Market Wire", "https://feed.test/all")
    provider = StubFeeds(
        {"https://feed.test/all": [entry("Saham BBRI menguat", "https://news.test/1")]}
    )

    sweep_all_sources(session, provider)
    second = sweep_all_sources(session, provider)

    assert second.inserted == 0
    assert second.duplicates == 1
    assert len(session.scalars(select(NewsItem)).all()) == 1


def test_an_inactive_source_is_not_read(directory) -> None:
    session = directory
    add_source(session, "Off", "https://feed.test/off", active=False)
    add_source(session, "On", "https://feed.test/on")
    provider = StubFeeds({"https://feed.test/on": []})

    sweep_all_sources(session, provider)

    assert provider.fetches == ["https://feed.test/on"]


def test_a_templated_feed_is_skipped_by_the_sweep(directory) -> None:
    """Its URL is a search that needs a ticker put into it; there is nothing to
    fetch without one. The per-ticker schedules are what read those."""
    session = directory
    add_source(session, "Search", "https://feed.test/q?s={ticker}")
    add_source(session, "General", "https://feed.test/all")
    provider = StubFeeds({"https://feed.test/all": []})

    sweep_all_sources(session, provider)

    assert provider.fetches == ["https://feed.test/all"]


def test_no_configured_sources_is_an_error(directory) -> None:
    """Returning zero articles would tell the caller there was no news, and it
    would go on saying that forever."""
    with pytest.raises(ValueError, match="no active news sources"):
        sweep_all_sources(directory, StubFeeds({}))


# --- re-tagging what is already stored --------------------------------------


def test_stories_already_in_the_database_can_be_attributed(directory) -> None:
    """Tagging arrived after the news did."""
    session = directory
    session.add(
        NewsItem(
            source="Older",
            source_url="https://news.test/old",
            dedup_hash="old-1",
            headline="Bank Rakyat Indonesia umumkan dividen",
            published_at=datetime.now(UTC) - timedelta(days=3),
        )
    )
    session.flush()

    result = tag_untagged(session)

    assert result == {"considered": 1, "tagged": 1, "untagged": 0}
    assert session.scalar(select(NewsItemIssuer)).ticker == "BBRI"


def test_re_tagging_removes_a_tag_a_corrected_alias_no_longer_justifies(directory) -> None:
    """The point of being able to correct an alias is undoing the wrong tags it
    caused. Tags that were only added rather than replaced would make the
    correction unable to reach them."""
    session = directory
    aadi = session.scalar(select(Issuer).where(Issuer.ticker == "AADI"))
    aadi.aliases = ["proyek nusantara baru"]
    session.flush()

    item = NewsItem(
        source="Wire",
        source_url="https://news.test/x",
        dedup_hash="x-1",
        headline="Proyek Nusantara Baru dimulai pekan ini",
        published_at=datetime.now(UTC),
    )
    session.add(item)
    session.flush()
    tag_untagged(session)
    assert session.scalar(select(NewsItemIssuer)).ticker == "AADI"

    # The alias was wrong; it is removed and the archive re-tagged.
    aadi.aliases = []
    session.flush()
    from aidss.news.sweep import build_matcher, tag_item

    tag_item(session, item, build_matcher(session))
    session.flush()

    assert session.scalars(select(NewsItemIssuer)).all() == []


def test_a_tagged_story_reaches_the_analysis_for_that_ticker(directory) -> None:
    """The point of tagging. A sector story naming six banks was previously
    filed under whichever one's schedule happened to fetch it, and was invisible
    to the other five - so five analyses reasoned without evidence that was
    already in the database."""
    from aidss.agents.context import ContextBuilder
    from aidss.collectors.market_data import MarketDataCollector
    from aidss.config import Settings
    from aidss.domain.types import Timeframe
    from aidss.plugins.registry import get_market_data_provider

    session = directory
    collector = MarketDataCollector(
        get_market_data_provider(Settings(market_data_provider="fixture"))
    )
    asset = collector.get_or_create_asset(session, "BBRI")

    add_source(session, "Market Wire", "https://feed.test/all")
    sweep_all_sources(
        session,
        StubFeeds(
            {
                "https://feed.test/all": [
                    entry(
                        "Saham BBRI dan AADI kompak menguat",
                        "https://news.test/sector",
                    )
                ]
            }
        ),
    )

    context = ContextBuilder(session, now=datetime(2026, 8, 2, tzinfo=UTC)).build(
        asset, Timeframe.D1
    )

    assert [a["headline"] for a in context.news] == [
        "Saham BBRI dan AADI kompak menguat"
    ], "a story tagged to this issuer must reach its analysis even though no schedule fetched it"

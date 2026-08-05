"""The RSS news provider, and the parsing under it.

This subsystem shipped broken: the only `NewsProvider` in the tree was a
fixture that manufactured plausible headlines, and it was also the configured
default - so the scheduled pipeline ran end to end, reported success, and
stored nothing a person had written. These tests are about the parts of a real
feed that are easy to get wrong and impossible to notice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from aidss.db.models import Asset, NewsSource
from aidss.plugins.adapters.news_rss import RssNewsProvider, clear_cache
from aidss.plugins.errors import ProviderUnavailableError
from aidss.syndication.feeds import FeedParseError, mentions, parse_feed

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Pasar Modal</title>
    <item>
      <title>BBCA membukukan laba kuartal kedua</title>
      <link>https://example.com/bbca-laba?utm_source=rss</link>
      <description>&lt;p&gt;Bank &lt;b&gt;Central&lt;/b&gt; Asia melaporkan.&lt;/p&gt;</description>
      <pubDate>Tue, 04 Aug 2026 09:30:00 +0700</pubDate>
    </item>
    <item>
      <title>ADRO menaikkan produksi</title>
      <link>https://example.com/adro</link>
      <description>Adaro menaikkan target.</description>
      <pubDate>Mon, 03 Aug 2026 02:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Item with no date at all</title>
      <link>https://example.com/undated</link>
    </item>
  </channel>
</rss>
"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Bursa</title>
  <entry>
    <title>TLKM expands its data centre footprint</title>
    <link rel="alternate" href="https://example.com/tlkm"/>
    <summary>Telkom Indonesia announced.</summary>
    <published>2026-08-04T02:30:00Z</published>
  </entry>
</feed>
"""


# --- parsing ----------------------------------------------------------------


def test_rss_entries_are_read_with_their_dates_in_utc() -> None:
    entries = parse_feed(RSS)
    assert [e.title for e in entries] == [
        "BBCA membukukan laba kuartal kedua",
        "ADRO menaikkan produksi",
    ]
    # +07:00 in the feed, stored as UTC.
    assert entries[0].published_at == datetime(2026, 8, 4, 2, 30, tzinfo=UTC)


def test_an_entry_without_a_date_is_dropped_rather_than_dated_now() -> None:
    """Filling in "now" would put it inside every window a schedule asks for,
    so every re-fetch would look like news."""
    assert all(e.title != "Item with no date at all" for e in parse_feed(RSS))


def test_html_is_stripped_from_summaries() -> None:
    """Feed summaries are routinely HTML fragments. Removed here, so nothing
    downstream has to decide whether a stored field is safe to put in the DOM."""
    summary = parse_feed(RSS)[0].summary
    assert summary == "Bank Central Asia melaporkan."


def test_atom_is_read_by_the_same_pass() -> None:
    [entry] = parse_feed(ATOM)
    assert entry.title == "TLKM expands its data centre footprint"
    # Atom puts the URL in an attribute, RSS in the element text.
    assert entry.link == "https://example.com/tlkm"
    assert entry.published_at == datetime(2026, 8, 4, 2, 30, tzinfo=UTC)


def test_something_that_is_not_a_feed_is_reported_as_such() -> None:
    with pytest.raises(FeedParseError):
        parse_feed(b"<html><body>404 Not Found</body></html>")


# --- matching ---------------------------------------------------------------


def test_a_ticker_matches_on_a_word_boundary() -> None:
    """IDX codes are four letters. Substring matching would file every article
    containing "banks" under BANK."""
    assert mentions("BBCA naik 2%", "BBCA", None)
    assert not mentions("Pembahasan BBCADEF lain", "BBCA", None)


def test_the_company_name_matches_too() -> None:
    """Much Indonesian coverage names the company and never prints the code."""
    assert mentions("Bank Central Asia mencatat laba", "BBCA", "PT Bank Central Asia Tbk")


def test_a_bare_corporate_form_never_matches() -> None:
    """"PT" and "Tbk" appear in every Indonesian company name and carry no
    signal; without stripping them, one article would match every issuer."""
    assert not mentions("PT lain Tbk mengumumkan", "BBCA", "PT Tbk")


# --- the provider -----------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_cache():
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def asset(session) -> Asset:
    row = Asset(ticker="BBCA", exchange="IDX", name="PT Bank Central Asia Tbk")
    session.add(row)
    session.flush()
    return row


def _serve(monkeypatch, payload: bytes | Exception) -> list[str]:
    """Answer every fetch with one canned response, recording the URLs asked for."""
    asked: list[str] = []

    def fake_fetch(self, url: str):  # noqa: ANN001, ANN202
        asked.append(url)
        if isinstance(payload, Exception):
            raise payload
        return parse_feed(payload)

    monkeypatch.setattr(RssNewsProvider, "fetch", fake_fetch)
    return asked


def test_no_configured_sources_is_an_error_not_a_quiet_day(session, asset) -> None:
    """Zero articles would tell the schedule there was no news, and it would go
    on saying that forever - which is exactly the state this subsystem was in."""
    provider = RssNewsProvider(session)
    with pytest.raises(ProviderUnavailableError, match="no active news sources"):
        provider.get_news(
            "BBCA", datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 8, 5, tzinfo=UTC)
        )


def test_a_general_feed_is_filtered_to_the_ticker(session, asset, monkeypatch) -> None:
    session.add(NewsSource(name="Pasar Modal", feed_url="https://example.com/feed.xml"))
    session.flush()
    _serve(monkeypatch, RSS)

    articles = RssNewsProvider(session).get_news(
        "BBCA", datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 8, 5, tzinfo=UTC)
    )
    # The ADRO story is in the same feed and is not about this issuer.
    assert [a.headline for a in articles] == ["BBCA membukukan laba kuartal kedua"]
    assert articles[0].source == "Pasar Modal"


def test_a_templated_url_is_substituted_and_not_filtered(
    session, asset, monkeypatch
) -> None:
    """The publisher already did the searching; filtering again would only
    discard entries that qualify."""
    session.add(
        NewsSource(name="Cari", feed_url="https://example.com/search?q={ticker}")
    )
    session.flush()
    asked = _serve(monkeypatch, RSS)

    articles = RssNewsProvider(session).get_news(
        "BBCA", datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 8, 5, tzinfo=UTC)
    )
    assert asked == ["https://example.com/search?q=BBCA"]
    # Both entries survive, including the one that never says BBCA.
    assert len(articles) == 2


def test_a_feed_bound_to_one_asset_is_not_filtered(session, asset, monkeypatch) -> None:
    session.add(
        NewsSource(name="IR BBCA", feed_url="https://example.com/ir.xml", asset_id=asset.id)
    )
    session.flush()
    _serve(monkeypatch, RSS)

    articles = RssNewsProvider(session).get_news(
        "BBCA", datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 8, 5, tzinfo=UTC)
    )
    assert len(articles) == 2


def test_articles_outside_the_window_are_left_out(session, asset, monkeypatch) -> None:
    session.add(NewsSource(name="Pasar Modal", feed_url="https://example.com/feed.xml"))
    session.flush()
    _serve(monkeypatch, RSS)

    articles = RssNewsProvider(session).get_news(
        "BBCA",
        datetime(2026, 8, 4, 12, tzinfo=UTC),
        datetime(2026, 8, 5, tzinfo=UTC),
    )
    assert articles == []


def test_a_failing_feed_is_written_onto_the_feed(session, asset, monkeypatch) -> None:
    """A feed that started answering 404 is otherwise indistinguishable from a
    feed with no news."""
    source = NewsSource(name="Broken", feed_url="https://example.com/gone.xml")
    session.add(source)
    session.flush()
    _serve(monkeypatch, httpx.ConnectError("nope"))

    with pytest.raises(ProviderUnavailableError):
        RssNewsProvider(session).get_news(
            "BBCA", datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 8, 5, tzinfo=UTC)
        )

    assert source.last_status == "failed"
    assert source.consecutive_failures == 1
    assert "ConnectError" in source.last_error


def test_a_successful_fetch_clears_an_earlier_failure(session, asset, monkeypatch) -> None:
    source = NewsSource(
        name="Pasar Modal",
        feed_url="https://example.com/feed.xml",
        last_status="failed",
        consecutive_failures=3,
    )
    session.add(source)
    session.flush()
    _serve(monkeypatch, RSS)

    RssNewsProvider(session).get_news(
        "BBCA", datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 8, 5, tzinfo=UTC)
    )
    assert source.last_status == "ok"
    assert source.consecutive_failures == 0
    assert source.last_entry_count == 2


def test_an_inactive_source_is_not_read(session, asset, monkeypatch) -> None:
    session.add(
        NewsSource(name="Off", feed_url="https://example.com/off.xml", is_active=False)
    )
    session.flush()
    _serve(monkeypatch, RSS)

    with pytest.raises(ProviderUnavailableError, match="no active news sources"):
        RssNewsProvider(session).get_news(
            "BBCA", datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 8, 5, tzinfo=UTC)
        )


def test_the_same_story_in_two_feeds_is_carried_once(session, asset, monkeypatch) -> None:
    session.add_all(
        [
            NewsSource(name="A", feed_url="https://example.com/a.xml"),
            NewsSource(name="B", feed_url="https://example.com/b.xml"),
        ]
    )
    session.flush()
    _serve(monkeypatch, RSS)

    articles = RssNewsProvider(session).get_news(
        "BBCA", datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 8, 5, tzinfo=UTC)
    )
    assert len(articles) == 1


def test_a_feed_is_fetched_once_across_many_tickers(session, monkeypatch) -> None:
    """A watchlist of fifty would otherwise fetch the same general feed fifty
    times in one pass and earn a rate limit."""
    for ticker in ("BBCA", "BBRI", "TLKM"):
        session.add(Asset(ticker=ticker, exchange="IDX"))
    session.add(NewsSource(name="Pasar Modal", feed_url="https://example.com/feed.xml"))
    session.flush()

    calls: list[str] = []
    real_fetch = RssNewsProvider.fetch

    def counting_fetch(self, url: str):  # noqa: ANN001, ANN202
        calls.append(url)
        return real_fetch(self, url)

    def fake_get(self, url, **kwargs):  # noqa: ANN001, ANN202, ARG001
        raise AssertionError("should have been served from cache")

    monkeypatch.setattr(RssNewsProvider, "fetch", counting_fetch)
    monkeypatch.setattr(
        httpx.Client,
        "stream",
        lambda self, method, url, **kw: _FakeStream(RSS),  # noqa: ARG005
    )

    window = (datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 8, 5, tzinfo=UTC))
    provider = RssNewsProvider(session)
    for ticker in ("BBCA", "BBRI", "TLKM"):
        provider.get_news(ticker, *window)

    # Asked for three times, actually fetched once.
    assert len(calls) == 3
    assert _FakeStream.opened == 1


class _FakeStream:
    """Stands in for httpx's streaming response context manager."""

    opened = 0

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self):  # noqa: ANN204
        type(self).opened += 1
        return self

    def __exit__(self, *exc) -> None:  # noqa: ANN002
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self):  # noqa: ANN201
        yield self._payload


@pytest.fixture(autouse=True)
def _reset_stream_counter():
    _FakeStream.opened = 0
    yield


def test_the_window_boundary_is_inclusive(session, asset, monkeypatch) -> None:
    session.add(NewsSource(name="Pasar Modal", feed_url="https://example.com/feed.xml"))
    session.flush()
    _serve(monkeypatch, RSS)

    exact = datetime(2026, 8, 4, 2, 30, tzinfo=UTC)
    articles = RssNewsProvider(session).get_news("BBCA", exact, exact + timedelta(seconds=1))
    assert len(articles) == 1

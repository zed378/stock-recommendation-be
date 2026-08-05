"""Parsing RSS 2.0 and Atom into articles.

Written rather than pulled in, because the job is narrow: take bytes, return
entries with a headline, a link, a summary, and a date. `feedparser` handles far
more of the world's malformed XML than this does, and if feeds in the wild turn
out to need that, swapping this module for it is a contained change - the rest
of the platform only sees `FeedEntry`.

Both formats are handled by one pass. RSS puts entries in ``channel/item`` with
``pubDate``; Atom puts them in ``entry`` with ``published`` or ``updated``. The
shapes differ, the meaning does not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

#: Atom lives in a namespace; RSS does not. Matching on the local name covers
#: both without carrying a namespace map that every feed spells differently.
_ATOM = "{http://www.w3.org/2005/Atom}"

#: Entries beyond this are ignored. A feed is a recent-items list; one
#: returning tens of thousands is malformed or hostile, and either way the
#: schedule only asked for a window of days.
MAX_ENTRIES = 500

#: RSS 2.0, Atom, and RSS 1.0 respectively. Anything else that happens to be
#: well-formed XML is not a feed, however cleanly it parsed.
_FEED_ROOTS = frozenset({"rss", "feed", "rdf"})

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


class FeedParseError(ValueError):
    """The bytes were not a feed this can read."""


@dataclass(frozen=True, slots=True)
class FeedEntry:
    title: str
    link: str
    summary: str | None
    published_at: datetime


def _text(element: ElementTree.Element | None) -> str | None:
    if element is None:
        return None
    value = "".join(element.itertext()).strip()
    return value or None


def _strip_html(value: str | None) -> str | None:
    """Feed summaries are routinely HTML fragments.

    Stored as text and shown in a list, so the markup is noise at best. Removed
    here rather than at render time, so nothing downstream has to decide whether
    a given field is safe to put in the DOM.
    """
    if value is None:
        return None
    cleaned = _WHITESPACE_RE.sub(" ", _TAG_RE.sub(" ", value)).strip()
    return cleaned or None


def _parse_date(raw: str | None) -> datetime | None:
    """RFC 822 (RSS) or ISO 8601 (Atom), whichever this turns out to be."""
    if not raw:
        return None
    raw = raw.strip()

    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        parsed = None

    if parsed is None:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None

    # A feed that omits the offset is read as UTC rather than as local time:
    # the platform stores everything in UTC, and guessing the server's zone
    # would shift every article by however many hours that host happens to be.
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _link_of(entry: ElementTree.Element) -> str | None:
    """RSS puts the URL in the element text; Atom puts it in an attribute."""
    rss_link = _text(entry.find("link"))
    if rss_link:
        return rss_link

    for link in entry.iter(f"{_ATOM}link"):
        rel = link.get("rel", "alternate")
        if rel == "alternate" and link.get("href"):
            return link.get("href")

    # Some feeds carry only a guid, and a guid that is a URL is the article.
    guid = _text(entry.find("guid"))
    return guid if guid and guid.startswith("http") else None


def parse_feed(payload: bytes) -> list[FeedEntry]:
    """Entries from one feed document, newest-first order left as published.

    Entries missing a title, a link, or a usable date are dropped rather than
    filled in: a dateless article cannot be placed in the window a schedule
    asked for, and inventing "now" would make every re-fetch look like news.
    """
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise FeedParseError(str(exc)) from exc

    # An HTML error page is well-formed XML often enough to matter: a server
    # answering 404 with a styled page parses cleanly and yields no entries,
    # which reads downstream as "no news today" and stays that way forever.
    # The root tag is what separates a feed from a document that merely parsed.
    tag = root.tag.rsplit("}", 1)[-1].lower()
    if tag not in _FEED_ROOTS:
        raise FeedParseError(
            f"root element is <{tag}>, which is not a feed "
            f"(expected one of {sorted(_FEED_ROOTS)})"
        )

    nodes = root.findall(".//item") or list(root.iter(f"{_ATOM}entry"))

    entries: list[FeedEntry] = []
    for node in nodes[:MAX_ENTRIES]:
        title = _strip_html(_text(node.find("title")) or _text(node.find(f"{_ATOM}title")))
        link = _link_of(node)
        published = _parse_date(
            _text(node.find("pubDate"))
            or _text(node.find(f"{_ATOM}published"))
            or _text(node.find(f"{_ATOM}updated"))
            or _text(node.find("{http://purl.org/dc/elements/1.1/}date"))
        )
        if not title or not link or published is None:
            continue

        summary = _strip_html(
            _text(node.find("description"))
            or _text(node.find(f"{_ATOM}summary"))
            or _text(node.find(f"{_ATOM}content"))
        )
        entries.append(
            FeedEntry(title=title, link=link, summary=summary, published_at=published)
        )

    return entries


def mentions(text: str, ticker: str, company: str | None) -> bool:
    """Whether a headline or summary is about this issuer.

    Word-boundary matching on the code, because IDX tickers are four letters
    and substring matching would put every article containing "banks" under
    BANK. The company name is matched too, since much Indonesian coverage names
    the company and never prints the code.

    This is a filter, not a classifier: it will miss an article that refers to
    an issuer only by a nickname, and that limit is worth stating rather than
    papering over with fuzzy matching that would let unrelated stories through.
    """
    haystack = text.lower()
    if re.search(rf"\b{re.escape(ticker.lower())}\b", haystack):
        return True

    if company:
        name = company.lower().strip()
        # Corporate forms carry no signal and appear in every Indonesian
        # company name, so a bare "PT Tbk" must never be what matched.
        for noise in ("pt ", " tbk", " (persero)", " persero"):
            name = name.replace(noise, " ")
        name = _WHITESPACE_RE.sub(" ", name).strip()
        if len(name) >= 4 and name in haystack:
            return True

    return False

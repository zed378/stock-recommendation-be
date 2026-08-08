"""The issuer calendar: dated facts, and nothing about what they imply.

This is the only surface in the product that looks forward, which makes it the
one most likely to be read as a prediction. Most of what follows guards that
rather than the plumbing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select

from aidss.db.models import (
    AgendaKind,
    AgendaSource,
    Alert,
    AlertKind,
    Asset,
    IssuerAgenda,
    NewsItem,
    NewsItemIssuer,
    User,
    Watchlist,
    WatchlistItem,
)
from aidss.monitoring.agenda import AgendaEntry, raise_notices, store_entries, upcoming
from aidss.news.agenda_extract import entries_from, extract


def entry(ticker="BBRI", kind=AgendaKind.RUPS, on=date(2026, 8, 20), title="RUPST") -> AgendaEntry:
    return AgendaEntry(
        ticker=ticker, kind=kind, scheduled_for=on, title=title, source=AgendaSource.MANUAL
    )


# --- storage ----------------------------------------------------------------


def test_re_importing_a_calendar_corrects_rather_than_duplicates(session) -> None:
    """Corrections are the normal case: a meeting moves, a reporting date
    slips. An import that inserted a second row would show both with nothing
    to say which is current."""
    store_entries(session, [entry(title="RUPST")])
    store_entries(session, [entry(title="RUPST (revised venue)")])

    rows = session.scalars(select(IssuerAgenda)).all()
    assert len(rows) == 1
    assert rows[0].title == "RUPST (revised venue)"


def test_a_rescheduled_event_is_a_new_row(session) -> None:
    """Keyed on the date, so moving a meeting does not overwrite the record
    that it was once planned for the earlier one."""
    store_entries(session, [entry(on=date(2026, 8, 20))])
    store_entries(session, [entry(on=date(2026, 8, 27))])

    assert len(session.scalars(select(IssuerAgenda)).all()) == 2


def test_only_future_events_are_listed(session) -> None:
    store_entries(
        session,
        [entry(on=date(2026, 7, 1), title="past"), entry(on=date(2026, 8, 20), title="ahead")],
    )

    rows, total = upcoming(session, on_date=date(2026, 8, 8))

    assert total == 1
    assert rows[0].title == "ahead"


def test_the_calendar_can_be_narrowed_to_a_watchlist(session) -> None:
    store_entries(session, [entry(ticker="BBRI"), entry(ticker="TLKM")])

    _, total = upcoming(session, on_date=date(2026, 8, 8), tickers=["BBRI"])

    assert total == 1


# --- notices ----------------------------------------------------------------


def watched(session, ticker: str) -> User:
    user = User(email=f"{ticker.lower()}@example.com", password_hash="x")
    asset = Asset(ticker=ticker, exchange="IDX", name=ticker)
    session.add_all([user, asset])
    session.flush()
    watchlist = Watchlist(user_id=user.id, name="Default")
    session.add(watchlist)
    session.flush()
    session.add(WatchlistItem(watchlist_id=watchlist.id, asset_id=asset.id))
    session.flush()
    return user


def test_a_notice_fires_for_a_watched_issuer(session) -> None:
    watched(session, "BBRI")
    store_entries(session, [entry(on=date(2026, 8, 12))])

    result = raise_notices(session, on_date=date(2026, 8, 8))

    assert result["raised"] == 1
    alert = session.scalars(select(Alert)).first()
    assert alert.kind is AlertKind.AGENDA_UPCOMING


def test_no_notice_for_an_issuer_nobody_follows(session) -> None:
    """The calendar covers the whole exchange and is browsable in full, but an
    unsolicited notice about a company nobody here expressed interest in is
    not information, it is noise arriving on a schedule."""
    watched(session, "BBRI")
    store_entries(session, [entry(ticker="TLKM", on=date(2026, 8, 12))])

    assert raise_notices(session, on_date=date(2026, 8, 8))["raised"] == 0


def test_one_event_produces_one_notice_not_one_per_day(session) -> None:
    """Keyed on the event rather than the day. Otherwise a meeting a week out
    announces itself every morning until it happens."""
    watched(session, "BBRI")
    store_entries(session, [entry(on=date(2026, 8, 12))])

    raise_notices(session, on_date=date(2026, 8, 8))
    raise_notices(session, on_date=date(2026, 8, 9))

    assert len(session.scalars(select(Alert)).all()) == 1


def test_an_event_beyond_the_window_waits(session) -> None:
    watched(session, "BBRI")
    store_entries(session, [entry(on=date(2026, 9, 30))])

    assert raise_notices(session, on_date=date(2026, 8, 8))["raised"] == 0


def test_a_mechanical_date_gets_a_longer_notice(session) -> None:
    """An ex-date moves the quote by the dividend whatever anybody thinks, and
    a reader who did not know is looking at a chart that appears to have fallen
    for no reason."""
    watched(session, "BBRI")
    store_entries(session, [entry(kind=AgendaKind.EX_DATE, on=date(2026, 8, 20))])

    assert raise_notices(session, on_date=date(2026, 8, 8))["raised"] == 1


def test_the_notice_states_the_date_and_nothing_more(session) -> None:
    """A date feels like it implies an action, which makes this the most
    tempting place in the platform to put one."""
    watched(session, "BBRI")
    store_entries(session, [entry(on=date(2026, 8, 12))])
    raise_notices(session, on_date=date(2026, 8, 8))

    message = session.scalars(select(Alert)).first().message.lower()

    for word in ("buy", "sell", "beli", "jual", "before", "opportunity", "expect"):
        assert word not in message


def test_two_watchers_are_each_told(session) -> None:
    """`dedup_key` is globally unique, so a key without the user in it means
    whoever is processed second is never told at all."""
    watched(session, "BBRI")
    second = User(email="other@example.com", password_hash="x")
    session.add(second)
    session.flush()
    asset = session.scalars(select(Asset)).first()
    watchlist = Watchlist(user_id=second.id, name="Default")
    session.add(watchlist)
    session.flush()
    session.add(WatchlistItem(watchlist_id=watchlist.id, asset_id=asset.id))
    store_entries(session, [entry(on=date(2026, 8, 12))])

    assert raise_notices(session, on_date=date(2026, 8, 8))["raised"] == 2


# --- extraction from coverage ------------------------------------------------


def article(headline: str, published=datetime(2026, 8, 1, tzinfo=UTC)) -> NewsItem:
    return NewsItem(
        source="test",
        source_url=f"https://example.test/{abs(hash(headline))}",
        dedup_hash=str(abs(hash(headline))),
        headline=headline,
        published_at=published,
    )


def test_a_dated_meeting_is_extracted() -> None:
    found = entries_from(article("BBRI gelar RUPST pada 20 Agustus 2026"), ["BBRI"])

    assert len(found) == 1
    assert found[0].kind is AgendaKind.RUPS
    assert found[0].scheduled_for == date(2026, 8, 20)


def test_a_missing_year_is_anchored_on_publication() -> None:
    """Anchored on the article rather than on today, so re-running the
    extractor months later does not silently move every date it already
    found."""
    found = entries_from(article("RUPS TLKM digelar 20 Agustus"), ["TLKM"])

    assert found[0].scheduled_for == date(2026, 8, 20)


def test_a_date_that_already_passed_is_rejected() -> None:
    """Coverage reports events that happened at least as often as it announces
    ones that will. Rolling this into next year would publish a meeting eleven
    months out that nobody scheduled."""
    assert entries_from(article("RUPS BBRI digelar 20 Juli"), ["BBRI"]) == []


def test_a_year_end_article_still_rolls_into_january() -> None:
    """The case the rejection above must not break: a December article naming a
    January date means next January, and it is fifty-one days out."""
    found = entries_from(
        article("RUPS BBRI digelar 20 Januari", published=datetime(2026, 12, 1, tzinfo=UTC)),
        ["BBRI"],
    )

    assert found[0].scheduled_for == date(2027, 1, 20)


def test_several_dates_in_one_article_are_left_alone() -> None:
    """A dividend timetable lists cum, ex, record and payment. Picking one of
    four would be a coin flip printed as a calendar entry."""
    found = entries_from(
        article("Jadwal dividen BBRI: cum date 12 Agustus, ex date 13 Agustus 2026"),
        ["BBRI"],
    )

    assert found == []


def test_an_event_with_no_date_is_left_alone() -> None:
    assert entries_from(article("BBRI akan menggelar RUPS tahun ini"), ["BBRI"]) == []


def test_an_article_with_no_event_word_produces_nothing() -> None:
    assert entries_from(article("Harga saham BBRI naik pada 12 Agustus 2026"), ["BBRI"]) == []


def test_a_sector_article_dates_every_issuer_it_names() -> None:
    found = entries_from(
        article("Bank BUMN kompak gelar RUPS 20 Agustus 2026"), ["BBRI", "BMRI", "BBNI"]
    )

    assert {item.ticker for item in found} == {"BBRI", "BMRI", "BBNI"}


def test_extraction_only_reads_tagged_coverage(session) -> None:
    """An article nobody could attribute to an issuer cannot produce a calendar
    entry for one, and guessing here would put a date on the wrong company."""
    untagged = article("RUPST digelar 20 Agustus 2026")
    session.add(untagged)
    session.flush()

    assert extract(session)["added"] == 0


def test_extracted_entries_say_where_they_came_from(session) -> None:
    """A weaker source than an exchange filing, and treated as one: the reader
    is the only one who can decide how much to lean on it."""
    from aidss.db.models import Issuer

    issuer = Issuer(ticker="BBRI", name="Bank Rakyat Indonesia")
    item = article("BBRI gelar RUPST pada 20 Agustus 2026")
    session.add_all([issuer, item])
    session.flush()
    session.add(
        NewsItemIssuer(
            news_item_id=item.id,
            issuer_id=issuer.id,
            ticker="BBRI",
            method="ticker_code",
            matched_text="BBRI",
        )
    )
    session.flush()

    extract(session)

    row = session.scalars(select(IssuerAgenda)).first()
    assert row.source is AgendaSource.NEWS
    assert row.source_url


# --- the endpoint -----------------------------------------------------------


def test_the_calendar_response_carries_its_caveat(client, auth_headers) -> None:
    body = client.get("/agenda", headers=auth_headers).json()

    caveat = body["caveat"].lower()
    assert "holds no view" in caveat
    assert "can move" in caveat


def test_only_an_admin_can_type_an_entry(client, auth_headers) -> None:
    """A calendar entry is a dated claim about a company that the platform then
    repeats to everyone watching it."""
    response = client.post(
        "/admin/agenda",
        headers=auth_headers,
        json={"ticker": "BBRI", "kind": "rups", "scheduled_for": "2026-08-20", "title": "RUPST"},
    )

    assert response.status_code == 403


def test_an_admin_can_type_an_entry(client, admin_headers) -> None:
    response = client.post(
        "/admin/agenda",
        headers=admin_headers,
        json={"ticker": "bbri", "kind": "rups", "scheduled_for": "2026-08-20", "title": "RUPST"},
    )

    assert response.status_code == 201
    assert response.json()["ticker"] == "BBRI"


def test_an_unknown_kind_is_refused(client, admin_headers) -> None:
    response = client.post(
        "/admin/agenda",
        headers=admin_headers,
        json={
            "ticker": "BBRI",
            "kind": "merger_rumour",
            "scheduled_for": "2026-08-20",
            "title": "x",
        },
    )

    assert response.status_code == 422

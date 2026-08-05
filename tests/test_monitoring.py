"""Alerts: what fires, what does not fire twice, and what an alert may say.

An alert is the most dangerous surface here. It arrives unbidden, it is read in
seconds, and it is stripped of everything the analysis screen surrounds a
stance with. So the wording rules are tested as behaviour, not left to review.

The other half is deduplication. A condition that is true stays true, so a rule
evaluated every few minutes fires every few minutes unless the occurrence - the
level, the session, the stance - is part of the key.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidss.db.models import Alert, AlertDirection, AlertKind, Asset, User
from aidss.monitoring.alerts import evaluate, record
from aidss.security.passwords import hash_password

ASSET = uuid.uuid4()
NOW = datetime(2026, 8, 5, 7, 30, tzinfo=UTC)


def call(**overrides):
    base = dict(
        asset_id=ASSET,
        ticker="BBCA",
        price=Decimal(10000),
        previous_close=Decimal(10000),
        now=NOW,
    )
    base.update(overrides)
    return evaluate(**base)


def kinds(candidates) -> set[AlertKind]:
    return {c.kind for c in candidates}


# --- what fires ------------------------------------------------------------


def test_nothing_fires_on_an_unremarkable_observation() -> None:
    """A monitor that alerts on every poll is one people turn off."""
    assert call() == []


def test_crossing_a_resistance_level_fires_once_upward() -> None:
    found = call(price=Decimal(10600), previous_price=Decimal(10400),
                 resistance_levels=[Decimal(10500)])
    assert AlertKind.LEVEL_CROSSED in kinds(found)
    assert found[0].direction is AlertDirection.UP


def test_approaching_a_level_is_distinct_from_crossing_it() -> None:
    """Two different facts. Collapsing them would make "crossed" fire before
    anything crossed."""
    found = call(price=Decimal(10400), resistance_levels=[Decimal(10500)])
    assert kinds(found) == {AlertKind.LEVEL_APPROACHED}


def test_a_level_far_away_says_nothing() -> None:
    assert call(price=Decimal(9000), resistance_levels=[Decimal(10500)]) == []


def test_falling_through_support_fires_downward() -> None:
    found = call(price=Decimal(8900), previous_price=Decimal(9100),
                 support_levels=[Decimal(9000)])
    assert AlertKind.LEVEL_CROSSED in kinds(found)
    assert found[0].direction is AlertDirection.DOWN


def test_a_crossing_needs_a_previous_price_to_be_a_crossing() -> None:
    """Without one, "price is above resistance" is true on every poll after the
    first and the alert becomes a running commentary."""
    found = call(price=Decimal(10600), resistance_levels=[Decimal(10500)])
    assert AlertKind.LEVEL_CROSSED not in kinds(found)


def test_reaching_the_suggested_stop_is_reported_as_reached() -> None:
    """Not "triggered": nothing is triggered, because nothing here can act."""
    found = call(price=Decimal(8700), suggested_stop=Decimal(8700))
    assert AlertKind.SUGGESTED_STOP_REACHED in kinds(found)
    assert "reached" in found[0].message.lower()


def test_a_stance_change_fires_and_carries_both_values() -> None:
    found = call(stance="sell", previous_stance="buy")
    alert = next(c for c in found if c.kind is AlertKind.STANCE_CHANGED)
    assert alert.context == {"from": "buy", "to": "sell"}


def test_an_unchanged_stance_says_nothing() -> None:
    assert call(stance="buy", previous_stance="buy") == []


def test_a_first_analysis_does_not_count_as_a_change() -> None:
    """Comparing against nothing would fire on every asset's first analysis."""
    assert call(stance="buy", previous_stance=None) == []


# --- the auto-rejection band ----------------------------------------------


def test_consuming_most_of_the_upward_band_is_reported() -> None:
    found = call(price=Decimal(12000), previous_close=Decimal(10000))
    assert AlertKind.LIMIT_PROXIMITY in kinds(found)


def test_reaching_the_ceiling_says_so_differently_from_approaching_it() -> None:
    near = call(price=Decimal(11800), previous_close=Decimal(10000))
    at = call(price=Decimal(12000), previous_close=Decimal(10000))
    near_message = next(c for c in near if c.kind is AlertKind.LIMIT_PROXIMITY).message
    at_message = next(c for c in at if c.kind is AlertKind.LIMIT_PROXIMITY).message
    assert "reached the exchange's upper auto-rejection limit" in at_message
    assert "reached the exchange's upper auto-rejection limit" not in near_message


def test_a_modest_rise_does_not_trip_the_band_alert() -> None:
    assert AlertKind.LIMIT_PROXIMITY not in kinds(
        call(price=Decimal(10300), previous_close=Decimal(10000))
    )


# --- unusual relative to the asset itself ---------------------------------


def test_an_unusual_move_is_judged_against_the_assets_own_volatility() -> None:
    """An absolute percentage would flag every small-cap daily and never flag a
    large-cap having its worst day in years."""
    found = call(
        price=Decimal(10600), previous_close=Decimal(10000), daily_volatility=Decimal("0.02")
    )
    assert AlertKind.UNUSUAL_MOVE in kinds(found)


def test_the_same_move_is_ordinary_for_a_more_volatile_asset() -> None:
    found = call(
        price=Decimal(10600), previous_close=Decimal(10000), daily_volatility=Decimal("0.08")
    )
    assert AlertKind.UNUSUAL_MOVE not in kinds(found)


def test_without_a_volatility_reading_nothing_is_called_unusual() -> None:
    found = call(price=Decimal(10600), previous_close=Decimal(10000))
    assert AlertKind.UNUSUAL_MOVE not in kinds(found)


# --- what an alert may say -------------------------------------------------


#: Word-boundary patterns, as the architecture test does for identifiers.
#: "BBCA traded above a level" is a statement of fact and must pass; a bare
#: "trade" as a verb must not. A substring match rejects both, which would push
#: the wording towards evasive circumlocution rather than towards clarity.
INSTRUCTION_PATTERNS = (
    r"\bbuy\b",
    r"\bsell\b",
    r"\btrade\b",
    r"\border\b",
    r"\bexecute\b",
    r"\bshould\b",
    r"\brecommend\b",
)


@pytest.mark.parametrize("kind", list(AlertKind))
def test_no_alert_kind_reads_as_an_instruction(kind: AlertKind) -> None:
    """The enum is closed so no future caller can invent an instruction-shaped
    alert by passing a different string."""
    for pattern in INSTRUCTION_PATTERNS:
        assert not re.search(pattern, kind.value.lower())


def test_no_alert_message_reads_as_an_instruction() -> None:
    """A push notification saying "SELL BBCA" is a trading signal whatever the
    rest of the product says about itself."""
    produced = [
        *call(price=Decimal(10600), previous_price=Decimal(10400),
              resistance_levels=[Decimal(10500)]),
        *call(price=Decimal(8900), previous_price=Decimal(9100),
              support_levels=[Decimal(9000)]),
        *call(price=Decimal(8700), suggested_stop=Decimal(8700)),
        *call(price=Decimal(12000), previous_close=Decimal(10000)),
        *call(stance="sell", previous_stance="buy"),
        *call(price=Decimal(10600), previous_close=Decimal(10000),
              daily_volatility=Decimal("0.02")),
    ]
    assert len(produced) >= 6, "the sample must cover every kind that can fire"
    for candidate in produced:
        lowered = candidate.message.lower()
        for pattern in INSTRUCTION_PATTERNS:
            assert not re.search(pattern, lowered), (
                f"{candidate.kind.value}: {candidate.message}"
            )


def test_a_stance_change_message_points_at_the_analysis_rather_than_stating_one() -> None:
    """The stance travels as data; the message sends the reader to where the
    confidence and the counter-evidence are."""
    alert = next(c for c in call(stance="sell", previous_stance="buy"))
    assert "see the analysis" in alert.message.lower()
    assert "sell" not in alert.message.lower()


# --- deduplication ---------------------------------------------------------


@pytest.fixture
def stored(session):
    user = User(
        email="watcher@example.com", password_hash=hash_password("correct-horse-battery")
    )
    asset = Asset(ticker="BBCA", exchange="IDX")
    session.add_all([user, asset])
    session.flush()
    return user, asset


def test_the_same_condition_is_recorded_once(session, stored) -> None:
    """A condition that is true stays true; without this the monitor becomes a
    running commentary."""
    user, asset = stored
    candidates = evaluate(
        asset_id=asset.id, ticker="BBCA", price=Decimal(12000),
        previous_close=Decimal(10000), now=NOW,
    )
    assert record(session, user.id, asset.id, candidates)
    assert record(session, user.id, asset.id, candidates) == []


def test_a_new_session_alerts_again(session, stored) -> None:
    """Yesterday's limit alert must not silence today's."""
    user, asset = stored
    today = evaluate(
        asset_id=asset.id, ticker="BBCA", price=Decimal(12000),
        previous_close=Decimal(10000), now=NOW,
    )
    tomorrow = evaluate(
        asset_id=asset.id, ticker="BBCA", price=Decimal(12000),
        previous_close=Decimal(10000), now=NOW + timedelta(days=1),
    )
    assert record(session, user.id, asset.id, today)
    assert record(session, user.id, asset.id, tomorrow)


def test_two_users_watching_one_asset_are_each_told(session, stored) -> None:
    """A shared key would mean whoever polls second is never alerted at all."""
    user, asset = stored
    other = User(
        email="second@example.com", password_hash=hash_password("correct-horse-battery")
    )
    session.add(other)
    session.flush()

    candidates = evaluate(
        asset_id=asset.id, ticker="BBCA", price=Decimal(12000),
        previous_close=Decimal(10000), now=NOW,
    )
    assert record(session, user.id, asset.id, candidates)
    assert record(session, other.id, asset.id, candidates)


def test_a_different_stance_change_is_a_different_occurrence(session, stored) -> None:
    """buy->sell and sell->buy are two events, not one repeated."""
    user, asset = stored
    first = evaluate(asset_id=asset.id, ticker="BBCA", price=Decimal(10000),
                     previous_close=Decimal(10000), stance="sell", previous_stance="buy",
                     now=NOW)
    back = evaluate(asset_id=asset.id, ticker="BBCA", price=Decimal(10000),
                    previous_close=Decimal(10000), stance="buy", previous_stance="sell",
                    now=NOW)
    assert record(session, user.id, asset.id, first)
    assert record(session, user.id, asset.id, back)


def test_a_stored_alert_keeps_what_it_was_measured_against(session, stored) -> None:
    """Read a week later it must still say why it fired, without depending on
    levels that have since been recomputed."""
    user, asset = stored
    candidates = evaluate(
        asset_id=asset.id, ticker="BBCA", price=Decimal(10600),
        previous_close=Decimal(10000), previous_price=Decimal(10400),
        resistance_levels=[Decimal(10500)], now=NOW,
    )
    [alert] = [a for a in record(session, user.id, asset.id, candidates)
               if a.kind is AlertKind.LEVEL_CROSSED]
    assert alert.observed_price == Decimal(10600)
    assert alert.reference_price == Decimal(10500)


# --- the orchestration, against a real database ----------------------------
#
# The pure rules above were well covered and a wrong column name still reached
# production: `AnalysisResult.created_at` does not exist, and nothing that only
# exercised `evaluate` could have known. These tests run the part that touches
# the database.


class StubProvider:
    """A market data provider that answers from memory."""

    name = "stub"

    def __init__(self, price: Decimal, previous_close: Decimal, *, realtime: bool = False):
        self._price = price
        self._previous_close = previous_close
        self._realtime = realtime
        self.asked: list[str] = []

    def get_quote(self, ticker: str):
        from aidss.domain.types import Quote

        self.asked.append(ticker)
        return Quote(
            ticker=ticker,
            price=self._price,
            timestamp=NOW,
            previous_close=self._previous_close,
        )

    def get_historical_candles(self, *args, **kwargs):  # pragma: no cover - unused
        return []

    def supports_realtime(self) -> bool:
        return self._realtime


class FailingProvider(StubProvider):
    def get_quote(self, ticker: str):
        from aidss.plugins.errors import ProviderUnavailableError

        raise ProviderUnavailableError("stub", "symbol not found", retryable=False)


@pytest.fixture
def watched(session, stored):
    """One user following one asset, through a real watchlist row."""
    from aidss.db.models import Watchlist, WatchlistItem

    user, asset = stored
    watchlist = Watchlist(user_id=user.id, name="Default")
    session.add(watchlist)
    session.flush()
    session.add(WatchlistItem(watchlist_id=watchlist.id, asset_id=asset.id))
    session.flush()
    return user, asset


def test_a_pass_stores_an_observation(session, watched) -> None:
    from aidss.monitoring.poller import poll_watched_assets

    user, asset = watched
    provider = StubProvider(Decimal(10000), Decimal(9800))
    report = poll_watched_assets(session, provider, now=NOW)

    assert provider.asked == ["BBCA"]
    assert report.polled == 1
    assert report.quoted == 1


def test_a_pass_reads_the_latest_recommendation_without_exploding(session, watched) -> None:
    """The regression that reached production: the orchestration joined a
    column that does not exist, and only a database-touching test could see it."""
    from aidss.db.models import AnalysisResult, InvestmentHorizon, Recommendation
    from aidss.domain.types import RecommendationLabel
    from aidss.monitoring.poller import poll_watched_assets

    user, asset = watched
    result = AnalysisResult(asset_id=asset.id, analysis_type="technical")
    session.add(result)
    session.flush()
    session.add(
        Recommendation(
            analysis_result_id=result.id,
            label=RecommendationLabel.BUY,
            confidence=70.0,
            reasoning="x",
            bullish_scenario="x",
            bearish_scenario="x",
            horizon=InvestmentHorizon.MEDIUM,
            suggested_stop=Decimal(9000),
            language="en",
        )
    )
    session.flush()

    report = poll_watched_assets(session, StubProvider(Decimal(8900), Decimal(9800)), now=NOW)
    assert report.quoted == 1
    # The stored stop was reached, so the pass must have read it.
    assert report.alerts_raised >= 1


def test_an_unreachable_ticker_does_not_end_the_pass(session, watched) -> None:
    """A delisted symbol would otherwise silently stop monitoring for
    everything after it."""
    from aidss.monitoring.poller import poll_watched_assets

    report = poll_watched_assets(session, FailingProvider(Decimal(1), Decimal(1)), now=NOW)
    assert report.polled == 1
    assert report.quoted == 0
    assert report.unavailable


def test_the_delay_of_the_source_is_recorded(session, watched) -> None:
    """An interface presenting a delayed price as current invites decisions on
    numbers that have already moved."""
    from sqlalchemy import select

    from aidss.db.models import QuoteSnapshot
    from aidss.monitoring.poller import poll_watched_assets

    poll_watched_assets(session, StubProvider(Decimal(10000), Decimal(9800)), now=NOW)
    snapshot = session.scalar(select(QuoteSnapshot))
    assert snapshot is not None
    assert snapshot.is_delayed is True
    assert snapshot.source == "stub"


def test_a_realtime_provider_is_recorded_as_such(session, watched) -> None:
    from sqlalchemy import select

    from aidss.db.models import QuoteSnapshot
    from aidss.monitoring.poller import poll_watched_assets

    poll_watched_assets(
        session, StubProvider(Decimal(10000), Decimal(9800), realtime=True), now=NOW
    )
    assert session.scalar(select(QuoteSnapshot)).is_delayed is False


def test_one_provider_call_serves_every_follower(session, watched) -> None:
    """Two people watching BBCA should cost one call, not two."""
    from aidss.db.models import User, Watchlist, WatchlistItem
    from aidss.monitoring.poller import poll_watched_assets

    _, asset = watched
    other = User(
        email="third@example.com", password_hash=hash_password("correct-horse-battery")
    )
    session.add(other)
    session.flush()
    watchlist = Watchlist(user_id=other.id, name="Default")
    session.add(watchlist)
    session.flush()
    session.add(WatchlistItem(watchlist_id=watchlist.id, asset_id=asset.id))
    session.flush()

    provider = StubProvider(Decimal(12000), Decimal(10000))
    report = poll_watched_assets(session, provider, now=NOW)

    assert provider.asked == ["BBCA"], "the asset was quoted once"
    # ...and each follower was alerted separately.
    assert report.alerts_raised == 2


def test_an_asset_nobody_follows_is_not_polled(session, stored) -> None:
    """Provider quota spent on assets nobody asked about is quota wasted."""
    from aidss.monitoring.poller import poll_watched_assets

    provider = StubProvider(Decimal(10000), Decimal(9800))
    report = poll_watched_assets(session, provider, now=NOW)
    assert report.polled == 0
    assert provider.asked == []


def test_alerts_are_scoped_to_their_owner(session, stored) -> None:
    from sqlalchemy import select

    user, asset = stored
    candidates = evaluate(
        asset_id=asset.id, ticker="BBCA", price=Decimal(12000),
        previous_close=Decimal(10000), now=NOW,
    )
    record(session, user.id, asset.id, candidates)

    rows = session.scalars(select(Alert).where(Alert.user_id == user.id)).all()
    assert rows
    assert all(a.user_id == user.id for a in rows)


# --- announcing what monitoring observed -----------------------------------
#
# The alerts screen only helps someone already looking at it. These cover the
# notification that tells them there is something to look at - and, more
# importantly, that it cannot cost them the alerts if it goes wrong.


def _notifications(session, user_id):
    from sqlalchemy import select

    from aidss.db.models import Notification

    return list(
        session.scalars(
            select(Notification).where(Notification.user_id == user_id)
        ).all()
    )


def test_raising_an_alert_notifies_its_owner(session, watched) -> None:
    from aidss.monitoring.poller import poll_watched_assets

    user, _ = watched
    report = poll_watched_assets(session, StubProvider(Decimal(12000), Decimal(10000)), now=NOW)
    assert report.alerts_raised >= 1

    [note] = _notifications(session, user.id)
    assert note.event == "monitoring_alert"
    assert "BBCA" in note.message
    assert note.context["tickers"] == ["BBCA"]
    assert note.context["count"] == report.alerts_raised


def test_a_quiet_pass_notifies_nobody(session, watched) -> None:
    """An unremarkable session must not produce a notification saying so, or
    the feature trains people to ignore it."""
    from aidss.monitoring.poller import poll_watched_assets

    user, _ = watched
    report = poll_watched_assets(session, StubProvider(Decimal(10000), Decimal(10000)), now=NOW)
    assert report.alerts_raised == 0
    assert _notifications(session, user.id) == []


def test_many_alerts_in_one_pass_arrive_as_one_notification(session, watched) -> None:
    """A pass covering a whole watchlist on a day the market moves raises one
    alert per asset. Sending one notification each means a dozen arriving within
    a second of one another, which is how a feature gets muted."""
    from sqlalchemy import select

    from aidss.db.models import Watchlist, WatchlistItem
    from aidss.monitoring.poller import poll_watched_assets

    user, _ = watched
    watchlist = session.scalars(
        select(Watchlist).where(Watchlist.user_id == user.id)
    ).one()
    for ticker in ("BBRI", "TLKM", "ASII"):
        extra = Asset(ticker=ticker, exchange="IDX")
        session.add(extra)
        session.flush()
        session.add(WatchlistItem(watchlist_id=watchlist.id, asset_id=extra.id))
    session.flush()

    report = poll_watched_assets(session, StubProvider(Decimal(12000), Decimal(10000)), now=NOW)
    assert report.alerts_raised == 4, "one per followed asset"

    [note] = _notifications(session, user.id)
    assert note.context["count"] == 4
    assert sorted(note.context["tickers"]) == ["ASII", "BBCA", "BBRI", "TLKM"]


def test_two_followers_are_each_notified_separately(session, watched) -> None:
    from aidss.db.models import User, Watchlist, WatchlistItem
    from aidss.monitoring.poller import poll_watched_assets

    user, asset = watched
    other = User(
        email="fourth@example.com", password_hash=hash_password("correct-horse-battery")
    )
    session.add(other)
    session.flush()
    watchlist = Watchlist(user_id=other.id, name="Default")
    session.add(watchlist)
    session.flush()
    session.add(WatchlistItem(watchlist_id=watchlist.id, asset_id=asset.id))
    session.flush()

    poll_watched_assets(session, StubProvider(Decimal(12000), Decimal(10000)), now=NOW)

    assert len(_notifications(session, user.id)) == 1
    assert len(_notifications(session, other.id)) == 1


def test_an_alert_notification_does_not_read_as_an_instruction(session, watched) -> None:
    """Same rule as the alerts themselves. A line read in two seconds, stripped
    of confidence and counter-evidence, must not tell anyone to transact."""
    from aidss.monitoring.poller import poll_watched_assets

    user, _ = watched
    poll_watched_assets(session, StubProvider(Decimal(12000), Decimal(10000)), now=NOW)

    [note] = _notifications(session, user.id)
    text = f"{note.subject} {note.message}".lower()
    for word in ("buy", "sell", "order", "execute", "trade", "beli", "jual"):
        assert not re.search(rf"\b{word}\b", text), f"{word!r} in {text!r}"


def test_a_broken_notifier_does_not_cost_the_alerts(session, watched, monkeypatch) -> None:
    """The alerts are already stored by the time this runs. Throwing here would
    discard a completed pass over an announcement."""
    from sqlalchemy import select

    from aidss.monitoring import poller

    def explode(*args, **kwargs):
        raise RuntimeError("notification backend is down")

    monkeypatch.setattr(poller.NotificationService, "notify", explode)

    user, _ = watched
    report = poller.poll_watched_assets(
        session, StubProvider(Decimal(12000), Decimal(10000)), now=NOW
    )

    assert report.alerts_raised >= 1
    assert session.scalars(select(Alert).where(Alert.user_id == user.id)).all()

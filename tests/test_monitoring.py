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

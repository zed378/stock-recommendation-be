"""Screens an investor writes themselves.

Two things carry most of the risk. The vocabulary is the only thing standing
between a rule and the query it becomes, so every way of getting a value into
SQL is tested for refusal. And the stored signals are JSON *strings*, so a
comparison done the obvious way is lexical - which returns a plausible list
rather than an error, and is therefore the failure most likely to survive
review.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from aidss.db.models import MarketScanResult
from aidss.screener.custom import (
    FIELDS,
    FieldType,
    InvalidRule,
    parse,
)
from aidss.screener.custom import run as run_screen

ON = date(2026, 8, 6)


def scanned(session, ticker: str, *, close="1000", matched=None, **signals) -> None:
    session.add(
        MarketScanResult(
            ticker=ticker,
            session_date=ON,
            close=Decimal(close),
            matched=matched or [],
            matched_count=len(matched or []),
            # Written the way the scan writes them: numbers as strings.
            signals={k: (str(v) if not isinstance(v, bool) else v) for k, v in signals.items()},
        )
    )
    session.flush()


# --- the trap ----------------------------------------------------------------


def test_numbers_are_compared_as_numbers_not_as_text(session) -> None:
    """The whole reason this module casts.

    `_serialisable` writes Decimals as strings, so "9.5000" and "10.0000" sort
    lexically with 9.5 *above* 10. A screen for "RSI below 10" would then
    return everything in the nineties - a list that looks entirely reasonable
    and is wrong.
    """
    scanned(session, "LOWRSI", rsi="9.5000")
    scanned(session, "HIGHRSI", rsi="92.0000")

    result = run_screen(
        session, parse([{"field": "rsi", "operator": "lt", "value": 10}]), on_date=ON
    )

    assert [row.ticker for row in result.rows] == ["LOWRSI"]


def test_the_same_trap_on_the_upper_bound(session) -> None:
    scanned(session, "SMALL", volume_ratio="2.0000")
    scanned(session, "BIG", volume_ratio="11.0000")

    result = run_screen(
        session, parse([{"field": "volume_ratio", "operator": "gt", "value": 10}]), on_date=ON
    )

    assert [row.ticker for row in result.rows] == ["BIG"]


def test_between_bounds_are_numeric_too(session) -> None:
    scanned(session, "INSIDE", close="1500")
    scanned(session, "ABOVE", close="9000")
    scanned(session, "BELOW", close="90")

    result = run_screen(
        session,
        parse([{"field": "close", "operator": "between", "value": [100, 2000]}]),
        on_date=ON,
    )

    assert [row.ticker for row in result.rows] == ["INSIDE"]


# --- the vocabulary is the security -----------------------------------------


def test_an_unknown_field_is_refused() -> None:
    with pytest.raises(InvalidRule, match="not a field"):
        parse([{"field": "rsi; drop table assets", "operator": "lt", "value": 1}])


def test_an_unknown_operator_is_refused() -> None:
    with pytest.raises(InvalidRule, match="cannot be applied"):
        parse([{"field": "rsi", "operator": "; delete from users --", "value": 1}])


def test_an_operator_from_the_wrong_type_is_refused() -> None:
    """`includes_any` is meaningful for the criteria list and meaningless for a
    number. Allowed through, it would compile into something nobody wrote."""
    with pytest.raises(InvalidRule):
        parse([{"field": "rsi", "operator": "includes_any", "value": ["gap_up"]}])


def test_a_non_numeric_value_is_refused() -> None:
    with pytest.raises(InvalidRule, match="not a number"):
        parse([{"field": "rsi", "operator": "lt", "value": "(select 1)"}])


def test_a_boolean_is_not_a_number() -> None:
    """`float(True)` is 1.0, so without this check `rsi < true` compiles."""
    with pytest.raises(InvalidRule, match="not a true/false"):
        parse([{"field": "rsi", "operator": "lt", "value": True}])


def test_a_backwards_range_is_refused() -> None:
    """Swapping silently would accept a rule written backwards and return a
    range its author did not ask for."""
    with pytest.raises(InvalidRule, match="is above"):
        parse([{"field": "close", "operator": "between", "value": [5000, 100]}])


def test_an_unknown_criterion_is_refused() -> None:
    with pytest.raises(InvalidRule, match="unknown criteria"):
        parse([{"field": "matched", "operator": "includes_any", "value": ["moon_phase"]}])


def test_a_value_reaches_sql_as_a_parameter_not_as_text(session) -> None:
    """The structural guarantee behind all of the above: whatever a caller
    sends is bound, so even a value that survives validation cannot alter the
    statement."""
    from aidss.screener.custom import build_query

    compiled = str(
        build_query(parse([{"field": "rsi", "operator": "lt", "value": 30}]), on_date=ON)
    )

    assert "30" not in compiled, "the literal was inlined rather than bound"


# --- absence is not a pass ----------------------------------------------------


def test_an_issuer_missing_the_value_is_left_out(session) -> None:
    """The same rule the horizon screen follows: a condition that could not be
    checked is not a condition that passed."""
    scanned(session, "HASRSI", rsi="20.0000")
    scanned(session, "NORSI")

    result = run_screen(
        session, parse([{"field": "rsi", "operator": "lt", "value": 30}]), on_date=ON
    )

    assert [row.ticker for row in result.rows] == ["HASRSI"]


def test_a_null_signal_is_left_out_too(session) -> None:
    scanned(session, "NULLRSI")
    session.scalar(
        __import__("sqlalchemy").select(MarketScanResult)
    ).signals = {"rsi": None}
    session.flush()

    result = run_screen(
        session, parse([{"field": "rsi", "operator": "lt", "value": 30}]), on_date=ON
    )

    assert result.rows == []


# --- rules narrow ------------------------------------------------------------


def test_every_rule_must_hold(session) -> None:
    """AND, unlike the criteria checkboxes, which are OR. A rule somebody wrote
    by hand is a requirement: adding one has to narrow the list, or building
    the screen does the opposite of what it felt like."""
    scanned(session, "BOTH", rsi="20.0000", volume_ratio="3.0000")
    scanned(session, "ONLYRSI", rsi="20.0000", volume_ratio="0.5000")

    result = run_screen(
        session,
        parse(
            [
                {"field": "rsi", "operator": "lt", "value": 30},
                {"field": "volume_ratio", "operator": "gte", "value": 2},
            ]
        ),
        on_date=ON,
    )

    assert [row.ticker for row in result.rows] == ["BOTH"]


def test_no_rules_returns_the_whole_scan(session) -> None:
    scanned(session, "AAAA")
    scanned(session, "BBBB")

    assert run_screen(session, [], on_date=ON).matched == 2


# --- criteria sets ------------------------------------------------------------


def test_includes_any_matches_an_overlap(session) -> None:
    scanned(session, "GAPPED", matched=["gap_up", "volume_spike"])
    scanned(session, "QUIET", matched=["rsi_oversold"])

    result = run_screen(
        session,
        parse([{"field": "matched", "operator": "includes_any", "value": ["gap_up"]}]),
        on_date=ON,
    )

    assert [row.ticker for row in result.rows] == ["GAPPED"]


def test_includes_all_needs_every_one(session) -> None:
    scanned(session, "BOTH", matched=["gap_up", "volume_spike"])
    scanned(session, "ONE", matched=["gap_up"])

    result = run_screen(
        session,
        parse(
            [
                {
                    "field": "matched",
                    "operator": "includes_all",
                    "value": ["gap_up", "volume_spike"],
                }
            ]
        ),
        on_date=ON,
    )

    assert [row.ticker for row in result.rows] == ["BOTH"]


def test_excludes_removes_them(session) -> None:
    scanned(session, "CLEAN", matched=["gap_up"])
    scanned(session, "FALLING", matched=["gap_up", "death_cross"])

    result = run_screen(
        session,
        parse([{"field": "matched", "operator": "excludes", "value": ["death_cross"]}]),
        on_date=ON,
    )

    assert [row.ticker for row in result.rows] == ["CLEAN"]


# --- telling the author whether it filters -----------------------------------


def test_the_denominator_is_reported(session) -> None:
    """A filter matching most of the exchange is not filtering, and the only
    thing that shows it is what it was measured against - the same lesson two
    built-in criteria taught by matching 44% and 36% before anyone looked."""
    for index in range(10):
        scanned(session, f"T{index:03d}", rsi="20.0000" if index < 8 else "80.0000")

    result = run_screen(
        session, parse([{"field": "rsi", "operator": "lt", "value": 30}]), on_date=ON
    )

    assert result.considered == 10
    assert result.matched == 8
    assert result.share == 0.8


def test_an_unscanned_market_is_an_empty_universe(session) -> None:
    result = run_screen(session, [])

    assert result.considered == 0
    assert result.rows == []


# --- the vocabulary itself ----------------------------------------------------


def test_the_field_list_is_derived_from_the_signals() -> None:
    """Listed by hand it goes stale the first time somebody adds a signal, and
    the failure is a field that exists in the data and cannot be filtered on."""
    from aidss.monitoring.signals import TechnicalSignals

    for name in TechnicalSignals.__slots__:
        if name == "as_of":
            continue
        assert name in FIELDS, f"{name} is stored but not filterable"


def test_boolean_signals_are_typed_as_booleans() -> None:
    assert FIELDS["bullish_divergence"].type is FieldType.BOOLEAN


def test_a_boolean_signal_can_be_filtered(session) -> None:
    scanned(session, "DIVERGING", bullish_divergence=True)
    scanned(session, "PLAIN", bullish_divergence=False)

    result = run_screen(
        session,
        parse([{"field": "bullish_divergence", "operator": "is", "value": True}]),
        on_date=ON,
    )

    assert [row.ticker for row in result.rows] == ["DIVERGING"]


# --- the endpoints ------------------------------------------------------------


def test_the_vocabulary_is_served(client, auth_headers) -> None:
    body = client.get("/screens/fields", headers=auth_headers).json()

    keys = {field["key"] for field in body["fields"]}
    assert {"rsi", "close", "matched", "volume_ratio"} <= keys
    assert "gap_up" in body["criteria"]


def test_a_refused_rule_explains_itself(client, auth_headers) -> None:
    """A rule is written by a person, so the reason it was refused has to be
    readable by one."""
    response = client.post(
        "/screens/preview",
        headers=auth_headers,
        json={"rules": [{"field": "nope", "operator": "lt", "value": 1}]},
    )

    assert response.status_code == 422
    assert "not a field" in response.json()["detail"]


def test_a_screen_saves_and_runs(client, auth_headers) -> None:
    created = client.post(
        "/screens",
        headers=auth_headers,
        json={
            "name": "Oversold on volume",
            "rules": [
                {"field": "rsi", "operator": "lt", "value": 30},
                {"field": "volume_ratio", "operator": "gte", "value": 2},
            ],
        },
    )

    assert created.status_code == 201
    screen_id = created.json()["id"]
    assert client.post(f"/screens/{screen_id}/run", headers=auth_headers).status_code == 200


def test_saving_the_same_name_replaces_rather_than_duplicates(client, auth_headers) -> None:
    body = {"name": "Mine", "rules": [{"field": "rsi", "operator": "lt", "value": 30}]}
    client.post("/screens", headers=auth_headers, json=body)
    client.post(
        "/screens",
        headers=auth_headers,
        json={**body, "rules": [{"field": "rsi", "operator": "lt", "value": 40}]},
    )

    screens = client.get("/screens", headers=auth_headers).json()
    assert len(screens) == 1
    assert screens[0]["rules"][0]["value"] == 40


def test_an_invalid_screen_is_refused_at_save_time(client, auth_headers) -> None:
    """A screen that saves cleanly and fails every time afterwards is worse
    than one that refuses to save."""
    response = client.post(
        "/screens",
        headers=auth_headers,
        json={"name": "Broken", "rules": [{"field": "rsi", "operator": "wat", "value": 1}]},
    )

    assert response.status_code == 422


def test_a_screen_belongs_to_its_author(client, auth_headers) -> None:
    import uuid

    assert (
        client.post(f"/screens/{uuid.uuid4()}/run", headers=auth_headers).status_code == 404
    )
    assert client.delete(f"/screens/{uuid.uuid4()}", headers=auth_headers).status_code == 404


# --- running a saved screen on its own schedule -------------------------------


def a_screen(session, user_id, *, name="Mine", cron="", rules=None, **kwargs):
    from aidss.db.models import SavedScreen

    row = SavedScreen(
        user_id=user_id,
        name=name,
        cron_expr=cron,
        rules=rules if rules is not None else [{"field": "rsi", "operator": "lt", "value": 30}],
        **kwargs,
    )
    session.add(row)
    session.flush()
    return row


def an_account(session, email="owner@example.com"):
    from aidss.db.models import User

    user = User(email=email, password_hash="x")
    session.add(user)
    session.flush()
    return user


def test_only_scheduled_screens_are_due(session) -> None:
    """A screen with no cron runs when somebody presses run, and never on its
    own. A filter running on a timer nobody set is a timer nobody asked for."""
    from aidss.screener.scheduled import due_screens

    user = an_account(session)
    a_screen(session, user.id, name="Manual", cron="")
    a_screen(session, user.id, name="Nightly", cron="0 18 * * 1-5")

    due = due_screens(session, now=datetime(2026, 8, 10, 12, tzinfo=UTC))

    assert [row.name for row in due] == ["Nightly"]


def test_a_schedule_just_set_runs_on_the_next_tick(session) -> None:
    """`next_run_at` is null until the first run. Waiting a full cycle to find
    out whether it works is how a feature feels broken on the day it is turned
    on."""
    from aidss.screener.scheduled import due_screens

    user = an_account(session)
    a_screen(session, user.id, cron="0 18 * * 1-5")

    assert len(due_screens(session, now=datetime(2026, 8, 10, 0, 1, tzinfo=UTC))) == 1


def test_a_run_records_itself_even_with_no_match(session) -> None:
    """Recorded, deliberately not announced. A screen that only speaks up on a
    match is indistinguishable from one that stopped running."""
    from aidss.db.models import Notification
    from aidss.screener.scheduled import run_due

    user = an_account(session)
    scanned(session, "QUIET", rsi="80.0000")
    screen = a_screen(session, user.id, cron="* * * * *")

    result = run_due(session, now=datetime(2026, 8, 10, 12, tzinfo=UTC))

    assert result["ran"] == 1
    assert screen.last_run_at is not None
    assert screen.last_match_count == 0
    assert session.scalars(select(Notification)).all() == []


def test_a_match_notifies_its_owner(session) -> None:
    from aidss.db.models import Notification
    from aidss.screener.scheduled import run_due

    user = an_account(session)
    scanned(session, "OVERSOLD", rsi="20.0000")
    a_screen(session, user.id, name="Oversold", cron="* * * * *")

    run_due(session, now=datetime(2026, 8, 10, 12, tzinfo=UTC))

    notification = session.scalars(select(Notification)).first()
    assert notification is not None
    assert notification.user_id == user.id


def test_the_notification_carries_facts_not_prose(session) -> None:
    """The sentence is composed by the client in whichever language is
    selected. The denominator travels with it, because "1 matched" says nothing
    without "of 2"."""
    from aidss.db.models import Notification
    from aidss.screener.scheduled import run_due

    user = an_account(session)
    scanned(session, "OVERSOLD", rsi="20.0000")
    scanned(session, "CALM", rsi="55.0000")
    a_screen(session, user.id, name="Oversold", cron="* * * * *")

    run_due(session, now=datetime(2026, 8, 10, 12, tzinfo=UTC))

    context = session.scalars(select(Notification)).first().context
    assert context["screen_name"] == "Oversold"
    assert context["matched"] == 1
    assert context["considered"] == 2
    assert context["tickers"] == ["OVERSOLD"]


def test_the_notification_never_says_what_to_do(session) -> None:
    from aidss.db.models import Notification
    from aidss.screener.scheduled import run_due

    user = an_account(session)
    scanned(session, "OVERSOLD", rsi="20.0000")
    a_screen(session, user.id, name="Oversold", cron="* * * * *")
    run_due(session, now=datetime(2026, 8, 10, 12, tzinfo=UTC))

    message = session.scalars(select(Notification)).first().message.lower()

    for word in ("buy", "sell", "beli", "jual", "should", "opportunity"):
        assert word not in message


def test_the_schedule_advances_so_it_does_not_refire(session) -> None:
    """Without advancing, a scheduler ticking every minute would notify every
    minute for as long as the match persisted."""
    from aidss.screener.scheduled import run_due

    user = an_account(session)
    scanned(session, "OVERSOLD", rsi="20.0000")
    screen = a_screen(session, user.id, cron="0 18 * * 1-5")

    now = datetime(2026, 8, 10, 12, tzinfo=UTC)
    run_due(session, now=now)

    assert screen.next_run_at is not None
    assert screen.next_run_at > now


def test_a_screen_whose_vocabulary_went_away_says_so(session) -> None:
    """Left silent it looks exactly like a screen that matches nothing - the
    failure the news-sources chapter is built around."""
    from aidss.screener.scheduled import run_due

    user = an_account(session)
    screen = a_screen(
        session,
        user.id,
        cron="* * * * *",
        rules=[{"field": "gone", "operator": "lt", "value": 1}],
    )

    result = run_due(session, now=datetime(2026, 8, 10, 12, tzinfo=UTC))

    assert result["failed"] == 1
    assert "not a field" in (screen.last_error or "")


def test_an_unusable_cron_disables_the_schedule(session) -> None:
    """Rather than raising every minute for the rest of the deployment."""
    from aidss.screener.scheduled import run_due

    user = an_account(session)
    screen = a_screen(session, user.id, cron="every other tuesday")

    run_due(session, now=datetime(2026, 8, 10, 12, tzinfo=UTC))

    assert screen.cron_expr == ""
    assert "not usable" in (screen.last_error or "")


def test_one_broken_screen_does_not_stop_the_others(session) -> None:
    """A saved screen is one person's filter. Letting a broken one silence
    everybody else's is the same mistake as a dead feed emptying the sweep."""
    from aidss.db.models import Notification
    from aidss.screener.scheduled import run_due

    user = an_account(session)
    scanned(session, "OVERSOLD", rsi="20.0000")
    a_screen(session, user.id, name="Broken", cron="* * * * *", rules=[{"field": "gone"}])
    a_screen(session, user.id, name="Working", cron="* * * * *")

    result = run_due(session, now=datetime(2026, 8, 10, 12, tzinfo=UTC))

    assert result["failed"] == 1
    assert result["ran"] == 1
    assert len(session.scalars(select(Notification)).all()) == 1


# --- the schedule endpoint ----------------------------------------------------


def _make_screen(client, auth_headers) -> str:
    return client.post(
        "/screens",
        headers=auth_headers,
        json={"name": "S", "rules": [{"field": "rsi", "operator": "lt", "value": 30}]},
    ).json()["id"]


def test_a_cron_is_validated_when_it_is_set(client, auth_headers) -> None:
    """Rather than discovered by the scheduler at three in the morning, where
    the failure is a screen that silently never runs."""
    screen_id = _make_screen(client, auth_headers)

    response = client.patch(
        f"/screens/{screen_id}/schedule",
        headers=auth_headers,
        json={"cron_expr": "every friday"},
    )

    assert response.status_code == 422
    assert "not a usable cron" in response.json()["detail"]


def test_setting_a_cron_computes_the_next_run(client, auth_headers) -> None:
    screen_id = _make_screen(client, auth_headers)

    body = client.patch(
        f"/screens/{screen_id}/schedule",
        headers=auth_headers,
        json={"cron_expr": "0 18 * * 1-5"},
    ).json()

    assert body["cron_expr"] == "0 18 * * 1-5"
    assert body["next_run_at"] is not None


def test_clearing_the_cron_turns_it_off(client, auth_headers) -> None:
    screen_id = _make_screen(client, auth_headers)
    client.patch(
        f"/screens/{screen_id}/schedule",
        headers=auth_headers,
        json={"cron_expr": "0 18 * * 1-5"},
    )

    body = client.patch(
        f"/screens/{screen_id}/schedule", headers=auth_headers, json={"cron_expr": ""}
    ).json()

    assert body["cron_expr"] == ""
    assert body["next_run_at"] is None


def test_scheduling_someone_elses_screen_is_a_404(client, auth_headers) -> None:
    import uuid

    response = client.patch(
        f"/screens/{uuid.uuid4()}/schedule", headers=auth_headers, json={"cron_expr": ""}
    )

    assert response.status_code == 404

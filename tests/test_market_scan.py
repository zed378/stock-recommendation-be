"""One analysis pass over the exchange, read by both the alerts and the screener.

The behaviour worth protecting is that there is only *one* pass. Alerts used to
evaluate conditions for watched tickers while the screener applied its own rules
to its own candidates, so a criterion could mean one thing on one screen and
something subtly different on the other.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from aidss.collectors.trading_summary import (
    candles_from_summaries,
    sync_summaries,
    tickers_with_history,
)
from aidss.db.models import AlertKind, DailyTradingSummary, MarketScanResult
from aidss.monitoring.scan import results_for, scan_tickers


def summary_row(ticker: str, on_date: date, close: float, **overrides) -> dict:
    """Shaped exactly like a row from the exchange's stock-summary endpoint."""
    return {
        "StockCode": ticker,
        "Date": datetime.combine(on_date, datetime.min.time()).isoformat(),
        "OpenPrice": overrides.get("open", close),
        "High": overrides.get("high", close * 1.01),
        "Low": overrides.get("low", close * 0.99),
        "Close": close,
        "Previous": overrides.get("previous", close),
        "Volume": overrides.get("volume", 1_000_000),
        "Value": overrides.get("value", 1_000_000 * close),
        "Frequency": overrides.get("frequency", 500),
        "ForeignBuy": overrides.get("foreign_buy", 100_000),
        "ForeignSell": overrides.get("foreign_sell", 100_000),
    }


def seed(session, ticker: str, sessions: int = 80, **overrides) -> None:
    start = date(2026, 1, 5)
    rows = []
    for index in range(sessions):
        on_date = start + timedelta(days=index)
        if on_date.weekday() >= 5:
            continue
        rows.append(summary_row(ticker, on_date, 100.0 + index * 0.1, **overrides))
    sync_summaries(session, rows)
    session.flush()


# --- turning session records into bars ---------------------------------------


def test_a_session_with_no_volume_is_not_a_bar(session) -> None:
    """IDX still publishes the issuer, with high, low and open at zero and the
    previous close carried forward. Kept as written, every such row is a bar
    whose range is the entire price, which destroys ATR and every average that
    touches it."""
    sync_summaries(
        session,
        [
            summary_row("AAAA", date(2026, 1, 5), 100.0),
            {
                **summary_row("AAAA", date(2026, 1, 6), 100.0),
                "Volume": 0,
                "High": 0,
                "Low": 0,
                "OpenPrice": 0,
            },
            summary_row("AAAA", date(2026, 1, 7), 101.0),
        ],
    )
    session.flush()

    rows = session.scalars(select(DailyTradingSummary)).all()
    bars = candles_from_summaries(rows)

    assert len(rows) == 3, "the untraded session is still stored"
    assert len(bars) == 2, "but it is not offered as a bar"


def test_a_missing_open_falls_back_to_the_previous_close(session) -> None:
    """Several hundred issuers publish OpenPrice as zero on an ordinary session
    even when they traded. The previous close is the only stand-in that leaves
    the bar internally consistent."""
    sync_summaries(
        session,
        [
            {
                **summary_row("BBBB", date(2026, 1, 5), 100.0),
                "OpenPrice": 0,
                "Previous": 98.0,
                "Low": 97.0,
            }
        ],
    )
    session.flush()

    bar = candles_from_summaries(session.scalars(select(DailyTradingSummary)).all())[0]

    assert bar.open == Decimal("98.0")
    assert bar.low <= bar.open <= bar.high


def test_bars_come_back_oldest_first(session) -> None:
    """Every indicator expects that, and reversing it silently inverts every
    crossing the scan reports."""
    seed(session, "CCCC", sessions=10)

    bars = candles_from_summaries(session.scalars(select(DailyTradingSummary)).all())

    assert bars == sorted(bars, key=lambda bar: bar.timestamp)


def test_history_is_counted_on_traded_sessions(session) -> None:
    """A name suspended for three months has a row for every one of those days
    and no information in any of them."""
    rows = [summary_row("DDDD", date(2026, 1, 5) + timedelta(days=i), 100.0) for i in range(5)]
    rows += [
        {**summary_row("DDDD", date(2026, 3, 1) + timedelta(days=i), 100.0), "Volume": 0}
        for i in range(60)
    ]
    sync_summaries(session, rows)
    session.flush()

    assert "DDDD" not in tickers_with_history(session, minimum=10)


# --- the scan ----------------------------------------------------------------


def test_an_issuer_without_enough_history_is_skipped(session) -> None:
    seed(session, "EEEE", sessions=20)

    report = scan_tickers(session, ["EEEE"])

    assert report.scanned == 0
    assert report.skipped == 1


def test_a_scan_stores_one_row_per_issuer(session) -> None:
    seed(session, "FFFF", sessions=120)

    report = scan_tickers(session, ["FFFF"])

    assert report.scanned == 1
    row = session.scalar(select(MarketScanResult).where(MarketScanResult.ticker == "FFFF"))
    assert row is not None
    assert row.matched_count == len(row.matched)
    assert row.signals, "the computed values must be stored so a result can be explained"


def test_re_scanning_replaces_rather_than_duplicates(session) -> None:
    seed(session, "GGGG", sessions=120)
    on_date = date(2026, 8, 6)

    scan_tickers(session, ["GGGG"], on_date=on_date)
    scan_tickers(session, ["GGGG"], on_date=on_date)

    rows = session.scalars(
        select(MarketScanResult).where(MarketScanResult.ticker == "GGGG")
    ).all()
    assert len(rows) == 1


def test_every_result_shares_the_run_date(session) -> None:
    """Keyed by each ticker's own last traded session, the screener could only
    return names that traded on the single most recent date, which silently
    drops every illiquid issuer - the part of the market a screener is most
    useful for."""
    seed(session, "HHHH", sessions=120)
    seed(session, "IIII", sessions=100)
    on_date = date(2026, 8, 6)

    scan_tickers(session, ["HHHH", "IIII"], on_date=on_date)

    rows = session.scalars(select(MarketScanResult)).all()
    assert {row.session_date for row in rows} == {on_date}


# --- reading it back ---------------------------------------------------------


def test_the_watchlist_scope_narrows_and_the_global_one_does_not(session) -> None:
    for ticker in ("JJJJ", "KKKK", "LLLL"):
        seed(session, ticker, sessions=120)
    on_date = date(2026, 8, 6)
    scan_tickers(session, ["JJJJ", "KKKK", "LLLL"], on_date=on_date)

    _, everything = results_for(session, on_date=on_date)
    narrowed, watched = results_for(session, on_date=on_date, tickers=["JJJJ"])

    assert everything == 3
    assert watched == 1
    assert [row.ticker for row in narrowed] == ["JJJJ"]


def test_an_empty_watchlist_is_not_the_same_as_no_filter(session) -> None:
    """Following nothing is a real answer, and returning the whole exchange for
    it would be the opposite of what the reader asked."""
    seed(session, "MMMM", sessions=120)
    on_date = date(2026, 8, 6)
    scan_tickers(session, ["MMMM"], on_date=on_date)

    _, total = results_for(session, on_date=on_date, tickers=[])

    assert total == 0


def test_results_are_ordered_by_how_many_criteria_matched(session) -> None:
    seed(session, "NNNN", sessions=120)
    seed(session, "OOOO", sessions=120, volume=5_000_000)
    on_date = date(2026, 8, 6)
    scan_tickers(session, ["NNNN", "OOOO"], on_date=on_date)

    rows, _ = results_for(session, on_date=on_date)

    counts = [row.matched_count for row in rows]
    assert counts == sorted(counts, reverse=True)


def test_the_criteria_filter_is_an_or_not_an_and(session) -> None:
    """A reader ticking three criteria wants anything showing one of them, not
    the rare name showing all three."""
    seed(session, "PPPP", sessions=120)
    on_date = date(2026, 8, 6)
    scan_tickers(session, ["PPPP"], on_date=on_date)
    row = session.scalar(select(MarketScanResult).where(MarketScanResult.ticker == "PPPP"))
    row.matched = [AlertKind.GOLDEN_CROSS.value]
    row.matched_count = 1
    session.flush()

    _, both = results_for(
        session,
        on_date=on_date,
        matched_any=[AlertKind.GOLDEN_CROSS, AlertKind.RSI_OVERSOLD],
    )
    _, neither = results_for(session, on_date=on_date, matched_any=[AlertKind.RSI_OVERSOLD])

    assert both == 1
    assert neither == 0


def test_the_scan_and_the_alerts_share_one_vocabulary() -> None:
    """A screener with its own private list of rules is how the two drift
    apart. Everything the scan reports has to come from an alert candidate."""
    from aidss.monitoring import scan

    source = Path(scan.__file__).read_text(encoding="utf-8")

    assert "candidate.kind.value" in source, (
        "matches must be recorded from the alert candidates themselves, not "
        "from a list the scan keeps separately"
    )


# --- searching ---------------------------------------------------------------


def test_the_scan_can_be_searched_by_ticker(session) -> None:
    """Nine hundred rows is too many to scroll, and the code is the thing a
    reader arrives already knowing."""
    for ticker in ("BBRI", "BBCA", "ADRO"):
        seed(session, ticker, sessions=120)
    on_date = date(2026, 8, 6)
    scan_tickers(session, ["BBRI", "BBCA", "ADRO"], on_date=on_date)

    rows, total = results_for(session, on_date=on_date, search="bb")

    assert total == 2
    assert {row.ticker for row in rows} == {"BBRI", "BBCA"}


def test_the_search_composes_with_the_watchlist_scope(session) -> None:
    """Both tabs are searchable, and the two filters are independent."""
    for ticker in ("BBRI", "BBCA"):
        seed(session, ticker, sessions=120)
    on_date = date(2026, 8, 6)
    scan_tickers(session, ["BBRI", "BBCA"], on_date=on_date)

    rows, total = results_for(
        session, on_date=on_date, tickers=["BBRI", "BBCA"], search="bbri"
    )

    assert total == 1
    assert rows[0].ticker == "BBRI"


def test_an_empty_search_is_not_a_filter(session) -> None:
    seed(session, "BBRI", sessions=120)
    on_date = date(2026, 8, 6)
    scan_tickers(session, ["BBRI"], on_date=on_date)

    assert results_for(session, on_date=on_date, search="   ")[1] == 1


# --- the schedule the operator controls --------------------------------------


def test_the_market_import_ships_with_a_working_default() -> None:
    """Unlike the news sweep this has one. Reading somebody else's feeds on a
    timer nobody asked for is a decision; this is the exchange publishing about
    its own market, and a screener idle until an operator finds a setting looks
    broken."""
    from aidss.news.schedules import next_run_at
    from aidss.platform.settings import DEFAULTS, MARKET_SCAN_CRON

    expression = DEFAULTS[MARKET_SCAN_CRON]

    assert expression, "the market schedule must have a default"
    assert next_run_at(expression), "and it must parse"


def test_the_firing_is_spread_rather_than_landing_on_the_second(session) -> None:
    """A request at exactly 18:00:00.000 every weekday is a schedule, and a
    schedule is what rate limiting is for."""
    from datetime import UTC, datetime

    from aidss.jobs.handlers import _jitter

    due = datetime(2026, 8, 6, 11, 0, tzinfo=UTC)
    offset = _jitter(session, due)

    assert 0 <= offset < 900


def test_the_spread_is_stable_for_one_due_time(session) -> None:
    """Drawn fresh each tick, the delay would wander every minute: the dedup
    key stops a second job being created, but a start time nobody can predict
    is one nobody can debug."""
    from datetime import UTC, datetime

    from aidss.jobs.handlers import _jitter

    due = datetime(2026, 8, 6, 11, 0, tzinfo=UTC)

    assert _jitter(session, due) == _jitter(session, due)


def test_the_spread_differs_between_days(session) -> None:
    from datetime import UTC, datetime

    from aidss.jobs.handlers import _jitter

    monday = datetime(2026, 8, 3, 11, 0, tzinfo=UTC)
    tuesday = datetime(2026, 8, 4, 11, 0, tzinfo=UTC)

    assert _jitter(session, monday) != _jitter(session, tuesday)


def test_clearing_the_market_cron_turns_the_import_off(session) -> None:
    from aidss.jobs.handlers import enqueue_daily_trading_summary
    from aidss.platform.settings import MARKET_SCAN_CRON, set_setting

    set_setting(session, MARKET_SCAN_CRON, "")

    assert enqueue_daily_trading_summary(session)["disabled"] is True


# --- the picks screen reads the same pass ------------------------------------


def test_the_screen_covers_issuers_with_no_asset_row(session) -> None:
    """The point of the change. The horizon screener read `historical_prices`,
    which exist only for assets somebody registered - a dozen against the
    exchange's eight hundred - so a whole-market screener was really a
    watchlist viewer. A list that can only show names you already follow cannot
    surface one you have not thought of."""
    from aidss.screener import Horizon, screen_stored

    for ticker in ("NNNN", "OOOO", "PPPP"):
        seed(session, ticker, sessions=120)
    on_date = date(2026, 8, 6)
    scan_tickers(session, ["NNNN", "OOOO", "PPPP"], on_date=on_date)

    result = screen_stored(session, Horizon.D7, on_date=on_date)

    assert result.considered == 3, "no Asset rows exist for any of these"
    assert {pick.ticker for pick in result.picks} == {"NNNN", "OOOO", "PPPP"}
    assert all(pick.asset_id is None for pick in result.picks)


def test_a_pick_carries_the_conditions_it_met(session) -> None:
    """A ranked list of tickers is read as a forecast unless every row can say
    why it is there. "Score 3.1 of 4.1, because these four things are true" can
    be argued with; "score 0.72" cannot."""
    from aidss.screener import Horizon, screen_stored

    seed(session, "QQQQ", sessions=140)
    on_date = date(2026, 8, 6)
    scan_tickers(session, ["QQQQ"], on_date=on_date)

    pick = screen_stored(session, Horizon.D7, on_date=on_date).picks[0]

    assert pick.out_of > 0
    assert pick.score == sum(item.weight for item in pick.met)
    assert all(item.describes for item in pick.met), "every met condition is explained"
    assert set(pick.unmet).isdisjoint({item.key for item in pick.met})


def test_the_watchlist_is_a_filter_not_a_different_universe(session) -> None:
    """Same pass, one filter apart, so a criterion cannot mean one thing with
    the box ticked and something else without it."""
    from aidss.screener import Horizon, screen_stored

    for ticker in ("RRRR", "SSSS"):
        seed(session, ticker, sessions=120)
    on_date = date(2026, 8, 6)
    scan_tickers(session, ["RRRR", "SSSS"], on_date=on_date)

    everything = screen_stored(session, Horizon.D7, on_date=on_date)
    narrowed = screen_stored(session, Horizon.D7, on_date=on_date, tickers=["RRRR"])

    assert everything.considered == 2
    assert [pick.ticker for pick in narrowed.picks] == ["RRRR"]
    kept = next(p for p in everything.picks if p.ticker == "RRRR")
    assert narrowed.picks[0].score == kept.score, "the same criteria, scored the same way"


def test_following_nothing_returns_nothing(session) -> None:
    from aidss.screener import Horizon, screen_stored

    seed(session, "TTTT", sessions=120)
    on_date = date(2026, 8, 6)
    scan_tickers(session, ["TTTT"], on_date=on_date)

    assert screen_stored(session, Horizon.D7, on_date=on_date, tickers=[]).picks == []


def test_no_scan_yet_is_an_empty_universe_not_an_empty_result(session) -> None:
    """"Nothing meets your conditions" and "nothing has been looked at yet" are
    different answers, and only one of them is about the market."""
    from aidss.screener import Horizon, screen_stored

    result = screen_stored(session, Horizon.D7)

    assert result.considered == 0
    assert result.picks == []


def test_every_horizon_is_stored_by_one_pass(session) -> None:
    """Four horizons read the same indicator snapshot, and the snapshot is the
    expensive part. Computing them separately per request is what made the
    screen unaffordable over the whole exchange in the first place."""
    from aidss.screener import Horizon

    seed(session, "UUUU", sessions=140)
    on_date = date(2026, 8, 6)
    scan_tickers(session, ["UUUU"], on_date=on_date)

    row = session.scalar(select(MarketScanResult).where(MarketScanResult.ticker == "UUUU"))

    assert set(row.horizon_scores) == {h.value for h in Horizon}


def test_a_row_scanned_before_the_horizons_existed_is_not_scored_as_zero(session) -> None:
    """Empty stored scores mean "not evaluated", not "met nothing". Ranked as
    zero, every pre-upgrade row would sit at the bottom of the screen looking
    like a considered judgement about the issuer."""
    from aidss.screener import Horizon, screen_stored

    seed(session, "VVVV", sessions=120)
    on_date = date(2026, 8, 6)
    scan_tickers(session, ["VVVV"], on_date=on_date)
    row = session.scalar(select(MarketScanResult).where(MarketScanResult.ticker == "VVVV"))
    row.horizon_scores = {}
    session.flush()

    result = screen_stored(session, Horizon.D7, on_date=on_date)

    assert result.picks == []
    assert result.insufficient_history == ["VVVV"]


def test_a_condition_that_could_not_be_checked_is_not_a_condition_failed(session) -> None:
    """The exchange table holds about sixty sessions an issuer, so the 200-bar
    average is null for every one of them. Counted as failures, the 30-day
    horizon reports a best-in-market score of 2.0 against a ceiling of 3.9 -
    and a reader sees a mediocre stock where the truth is that an issuer met
    everything anybody could measure."""
    from aidss.screener import Horizon, screen_stored

    # Enough to scan, nowhere near enough for the 200-bar average.
    seed(session, "WWWW", sessions=90)
    on_date = date(2026, 8, 6)
    scan_tickers(session, ["WWWW"], on_date=on_date)

    pick = screen_stored(session, Horizon.D30, on_date=on_date).picks[0]

    assert "above_long_average" in pick.unevaluable
    assert "above_long_average" not in pick.unmet
    assert pick.out_of < 3.9, "the ceiling excludes what could not be checked"


def test_a_ceiling_is_only_reduced_by_what_is_actually_missing(session) -> None:
    """Otherwise the fix trades one misleading number for another: a screen
    whose ceiling shrinks to whatever each issuer happened to meet would score
    everything at 100%."""
    from aidss.screener import Horizon, screen_stored

    seed(session, "XXXX", sessions=90)
    on_date = date(2026, 8, 6)
    scan_tickers(session, ["XXXX"], on_date=on_date)

    pick = screen_stored(session, Horizon.D30, on_date=on_date).picks[0]

    assert pick.unmet or pick.score < pick.out_of or not pick.unevaluable
    assert pick.score <= pick.out_of

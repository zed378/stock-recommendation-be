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

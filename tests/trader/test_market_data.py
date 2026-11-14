from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from aidss_trader.connector.types import Candle as C
from aidss_trader.connector.types import PairInfo
from aidss_trader.db.models import Candle, PairRule
from aidss_trader.market_data import (
    build_pair_rules,
    check_order,
    find_gaps,
    floor_to_increment,
    ingest_candles,
    is_stale,
    store_pair_rules,
    validate_candle,
)

D = Decimal
T0 = datetime(2026, 11, 1, tzinfo=UTC)
NOW = T0 + timedelta(days=3)


def cndl(hours: int, close: str = "105", **kw) -> C:
    base = dict(open=D("100"), high=D("110"), low=D("90"), close=D(close), volume=D("1"))
    base.update(kw)
    return C(open_time=T0 + timedelta(hours=hours), **base)


def test_candle_ingest_is_idempotent(session) -> None:
    batch = [cndl(0), cndl(4), cndl(8)]
    first = ingest_candles(session, "BTCIDR", "4H", batch, now=NOW)
    second = ingest_candles(session, "BTCIDR", "4H", batch, now=NOW)
    assert (first.inserted, second.inserted, second.duplicates) == (3, 0, 3)
    assert session.scalar(select(func.count()).select_from(Candle)) == 3


def test_unfinished_candle_is_excluded(session) -> None:
    now = T0 + timedelta(hours=6)  # the 4h candle opened at +4h is still running
    result = ingest_candles(session, "BTCIDR", "4H", [cndl(0), cndl(4)], now=now)
    assert result.inserted == 1 and result.unfinished == 1


@pytest.mark.parametrize(
    "candle,reason",
    [
        (cndl(0, high=D("80"), low=D("90")), "high below low"),
        (cndl(0, open=D("0")), "non-positive price"),
        (cndl(0, volume=D("-1")), "negative volume"),
        (cndl(0, close=D("200")), "open or close outside the high-low range"),
    ],
)
def test_bad_candles_are_rejected_not_repaired(session, candle, reason) -> None:
    assert validate_candle(candle) == reason
    result = ingest_candles(session, "BTCIDR", "4H", [candle], now=NOW)
    assert result.inserted == 0 and result.rejected[0][1] == reason
    assert session.scalar(select(func.count()).select_from(Candle)) == 0


def test_a_refetch_that_disagrees_is_a_conflict_and_does_not_overwrite(session) -> None:
    ingest_candles(session, "BTCIDR", "4H", [cndl(0, "105")], now=NOW)
    result = ingest_candles(session, "BTCIDR", "4H", [cndl(0, "106")], now=NOW)
    assert result.conflicts and result.inserted == 0
    assert session.scalar(select(Candle.close)) == D("105")


def test_gaps_are_found_and_are_not_zero(session) -> None:
    ingest_candles(session, "BTCIDR", "4H", [cndl(0), cndl(4), cndl(16)], now=NOW)
    assert find_gaps(session, "BTCIDR", "4H") == [T0 + timedelta(hours=8), T0 + timedelta(hours=12)]


def test_alignment_check_is_opt_in_because_the_boundary_is_unverified() -> None:
    odd = C(
        open_time=T0 + timedelta(minutes=7), open=D(1), high=D(2), low=D(1), close=D(1), volume=D(0)
    )
    assert validate_candle(odd, "4H") is None
    assert validate_candle(odd, "4H", check_alignment=True) is not None


# ------------------------------------------------------------------ pair rules


def pair(**kw) -> PairInfo:
    base = dict(
        pair="BTCIDR",
        ticker_id="btc_idr",
        base_asset="IDR",
        quote_asset="BTC",
        quantity_increment=D("0.00000001"),
        min_base_idr=D("50000"),
        min_traded_qty=D("0.0001"),
        maintenance=False,
        suspended=False,
        maker_fee_pct=None,
        taker_fee_pct=None,
        raw={"pricescale": 1000},
    )
    base.update(kw)
    return PairInfo(**base)


def rules(**kw):
    return build_pair_rules([pair(**kw)], {"btc_idr": D("1000")})["BTCIDR"]


def test_a_complete_pair_is_tradable() -> None:
    assert rules().tradable


@pytest.mark.parametrize(
    "kw,reason",
    [
        ({"quantity_increment": None}, "quantity increment missing"),
        ({"min_base_idr": None}, "order minimums missing"),
        ({"maintenance": True}, "pair in maintenance"),
        ({"suspended": True}, "market suspended"),
        ({"raw": {"pricescale": 1}}, "price increment disagrees with pricescale"),
    ],
)
def test_missing_or_contradictory_rules_block_the_pair(kw, reason) -> None:
    r = rules(**kw)
    assert not r.tradable and reason in r.blocked_reasons


def test_a_missing_price_increment_blocks_the_pair() -> None:
    r = build_pair_rules([pair()], {})["BTCIDR"]
    assert "price increment missing" in r.blocked_reasons


def test_order_below_minimum_is_not_created() -> None:
    r = rules()
    assert check_order(r, D("1236777000"), D("0.001")) == []
    assert "below the minimum quantity" in check_order(r, D("1236777000"), D("0.00001"))
    assert "below the minimum order value" in check_order(r, D("1000"), D("0.001"))


def test_precision_and_increment_violations_are_reported() -> None:
    r = rules()
    assert any("quantity" in x for x in check_order(r, D("1236777000"), D("0.0010000001")))
    assert any("price" in x for x in check_order(r, D("1236777500"), D("0.001")))


def test_a_blocked_pair_never_passes_check_order() -> None:
    assert check_order(rules(suspended=True), D("1236777000"), D("0.001"))[0].startswith(
        "pair blocked"
    )


@pytest.mark.parametrize(
    "value,inc,expected",
    [
        ("0.0010000001", "0.00000001", "0.00100000"),
        ("1999", "1000", "1000"),
        ("1000", "1000", "1000"),
    ],
)
def test_floor_rounds_down_never_up(value, inc, expected) -> None:
    assert floor_to_increment(D(value), D(inc)) == D(expected)


def test_pair_rules_are_stored_and_refreshed(session) -> None:
    store_pair_rules(session, {"BTCIDR": rules()}, NOW)
    store_pair_rules(session, {"BTCIDR": rules(maintenance=True)}, NOW + timedelta(minutes=1))
    row = session.get(PairRule, "BTCIDR")
    assert row.maintenance is True and "pair in maintenance" in row.blocked_reasons
    assert session.scalar(select(func.count()).select_from(PairRule)) == 1


def test_stale_price_is_marked_stale() -> None:
    assert is_stale(NOW - timedelta(seconds=31), NOW, 30)
    assert not is_stale(NOW - timedelta(seconds=30), NOW, 30)

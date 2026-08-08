"""Screening, and the line between a screen and a forecast.

The single most important property under test is what the output does *not*
claim. A ranked list of tickers is read as a prediction unless it says
otherwise, so the caveat, the naming, and the absence of any probability are
tested as behaviour rather than left to documentation.

The rest is arithmetic: the auto-rejection bands are exchange rules with known
values, and a screen that got them wrong would produce plausible-looking
nonsense - a Rp 100 stock judged against a Rp 10,000 stock's band.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidss.db.models import Asset
from aidss.domain.types import Candle, Timeframe
from aidss.market.idx_rules import MINIMUM_PRICE, auto_reject_band, limit_fraction
from aidss.screener import Horizon, screen
from aidss.screener.criteria import CRITERIA_BY_HORIZON, Reading, max_score
from aidss.screener.engine import SCREEN_CAVEAT

# --- IDX auto-rejection bands ---------------------------------------------


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        (Decimal(60), Decimal("0.35")),
        (Decimal(199), Decimal("0.35")),
        (Decimal(200), Decimal("0.25")),
        (Decimal(4999), Decimal("0.25")),
        (Decimal(5000), Decimal("0.20")),
        (Decimal(25000), Decimal("0.20")),
    ],
)
def test_the_band_widens_as_the_price_falls(price: Decimal, expected: Decimal) -> None:
    """A Rp 100 stock may move a third in a day; a Rp 10,000 one may not.

    Judging both against one number would flag the cheap one constantly and the
    expensive one never.
    """
    assert limit_fraction(price) == expected


def test_the_ceiling_and_floor_are_symmetric_around_the_reference() -> None:
    band = auto_reject_band(Decimal(1000))
    assert band is not None
    assert band.ceiling == Decimal(1250)
    assert band.floor == Decimal(750)


def test_a_price_below_the_exchange_minimum_has_no_usable_band() -> None:
    """Below Rp 50 the tick size dominates and percentage reasoning stops
    meaning anything. None rather than a guess: inventing a band on top of bad
    data produces a screen result that looks as considered as any other."""
    assert auto_reject_band(MINIMUM_PRICE - 1) is None
    assert auto_reject_band(Decimal(0)) is None


def test_proximity_reports_how_much_of_the_band_is_used() -> None:
    band = auto_reject_band(Decimal(1000))
    assert band is not None
    assert band.proximity(Decimal(1000)) == 0
    assert band.proximity(Decimal(1125)) == Decimal("0.5")
    assert band.proximity(Decimal(1250)) == 1


def test_proximity_is_clamped_rather_than_reporting_the_impossible() -> None:
    """A stored bar can exceed a band computed from a stale reference close, and
    reporting 1.4 would suggest the exchange allowed something it did not."""
    band = auto_reject_band(Decimal(1000))
    assert band is not None
    assert band.proximity(Decimal(2000)) == 1
    assert band.proximity(Decimal(500)) == 0


# --- criteria --------------------------------------------------------------


def reading(**overrides) -> Reading:
    base = dict(
        close=1000.0,
        indicators={},
        features={},
        levels={},
        breakout={},
        structure="ranging",
    )
    base.update(overrides)
    return Reading(**base)  # type: ignore[arg-type]


def test_a_missing_indicator_is_absent_not_neutral() -> None:
    """A screen that treated an absent RSI as 50 would rank an asset with no
    history alongside one that was measured and found neutral."""
    assert reading().indicator("rsi(period=14)") is None
    assert reading().feature("return_1b") is None


def test_no_criterion_fires_on_an_empty_reading() -> None:
    """Absence must never look like a met condition."""
    empty = reading()
    for horizon, criteria in CRITERIA_BY_HORIZON.items():
        fired = [c.key for c in criteria if c.test(empty)]
        assert not fired, f"{horizon.value} fired on no data: {fired}"


def test_every_criterion_has_a_human_readable_description() -> None:
    """A screen result must be able to say why an asset appeared in the
    reader's vocabulary, not as an opaque score."""
    for criteria in CRITERIA_BY_HORIZON.values():
        for criterion in criteria:
            assert criterion.describes
            assert not criterion.describes.endswith(".")


def test_criterion_keys_are_unique_within_a_horizon() -> None:
    for horizon, criteria in CRITERIA_BY_HORIZON.items():
        keys = [c.key for c in criteria]
        assert len(keys) == len(set(keys)), f"{horizon.value} has duplicate keys"


def test_max_score_matches_the_criteria() -> None:
    """Reported alongside the score so "3.1" reads as "3.1 out of 4.1" rather
    than as a number on an unstated scale."""
    for horizon, criteria in CRITERIA_BY_HORIZON.items():
        assert max_score(horizon) == pytest.approx(sum(c.weight for c in criteria))


def criterion_named(key: str):
    for criteria in CRITERIA_BY_HORIZON.values():
        for criterion in criteria:
            if criterion.key == key:
                return criterion
    raise AssertionError(f"no criterion named {key!r}")


def test_a_rising_bar_on_heavy_volume_meets_the_one_day_condition() -> None:
    met = reading(
        features={"return_1b": 0.02},
        indicators={"volume_ratio(period=20)": {"value": 2.0}},
    )
    assert criterion_named("up_on_above_average_volume").test(met)


def test_a_rising_bar_on_thin_volume_does_not() -> None:
    """Volume is the part that distinguishes a move from a drift."""
    thin = reading(
        features={"return_1b": 0.02},
        indicators={"volume_ratio(period=20)": {"value": 0.8}},
    )
    assert not criterion_named("up_on_above_average_volume").test(thin)


def test_resistance_proximity_is_relative_not_absolute() -> None:
    """Otherwise every cheap stock looks close to every level."""
    cheap = reading(close=100.0, levels={"resistance": [101.0]})
    expensive = reading(close=10000.0, levels={"resistance": [10100.0]})
    criterion = next(c for c in CRITERIA_BY_HORIZON[Horizon.D1] if c.key == "pressing_resistance")
    assert criterion.test(cheap)
    assert criterion.test(expensive)


# --- the engine ------------------------------------------------------------


def make_candles(count: int, start: float = 1000.0, step: float = 5.0) -> list[Candle]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    candles = []
    for i in range(count):
        close = start + step * i
        candles.append(
            Candle(
                timestamp=base + timedelta(days=i),
                open=Decimal(str(close - 2)),
                high=Decimal(str(close + 3)),
                low=Decimal(str(close - 4)),
                close=Decimal(str(close)),
                volume=Decimal("1000000"),
            )
        )
    return candles


def store(session, ticker: str, candles: list[Candle]) -> Asset:
    from aidss.db.models import HistoricalPrice

    asset = Asset(ticker=ticker, exchange="IDX")
    session.add(asset)
    session.flush()

    for candle in candles:
        session.add(
            HistoricalPrice(
                asset_id=asset.id,
                timeframe=Timeframe.D1.value,
                timestamp=candle.timestamp,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
                source="test",
            )
        )
    session.flush()
    return asset


def test_an_asset_with_too_little_history_is_named_not_scored(session) -> None:
    """Silently ranking a two-week listing against a five-year one compares two
    different measurements."""
    store(session, "SHORT", make_candles(10))
    result = screen(session, Horizon.D30)

    assert "SHORT" in result.insufficient_history
    assert not result.picks


def test_an_empty_universe_is_distinguishable_from_no_matches(session) -> None:
    """`considered` says which happened; an empty list alone does not."""
    result = screen(session, Horizon.D7)
    assert result.considered == 0
    assert result.picks == []


def test_a_rising_series_meets_conditions_and_says_which(session) -> None:
    store(session, "RISER", make_candles(250))
    result = screen(session, Horizon.D30)

    assert result.picks, "a steadily rising series should meet trend conditions"
    pick = result.picks[0]
    assert pick.ticker == "RISER"
    assert pick.met, "a pick with no stated reasons is a score nobody can check"
    assert all(m.describes for m in pick.met)


def test_unmet_criteria_are_reported_too(session) -> None:
    """"Why is this one *not* here" is asked as often as "why is it"."""
    store(session, "RISER", make_candles(250))
    pick = screen(session, Horizon.D1).picks[0]
    assert isinstance(pick.unmet, list)
    assert len(pick.met) + len(pick.unmet) == len(CRITERIA_BY_HORIZON[Horizon.D1])


def test_ranking_is_deterministic(session) -> None:
    """A ranking that reshuffles between identical runs cannot be reasoned about."""
    store(session, "AAAA", make_candles(250))
    store(session, "BBBB", make_candles(250))

    first = [p.ticker for p in screen(session, Horizon.D14).picks]
    second = [p.ticker for p in screen(session, Horizon.D14).picks]
    assert first == second


def test_the_limit_filter_excludes_assets_that_are_not_near_the_band(session) -> None:
    """A 0.5% daily step consumes almost none of a 25% band."""
    store(session, "CALM", make_candles(250, step=5.0))
    result = screen(session, Horizon.D1, near_limit_only=True)
    assert not result.picks


def test_limit_proximity_is_reported_when_it_can_be_computed(session) -> None:
    store(session, "RISER", make_candles(250))
    pick = screen(session, Horizon.D1).picks[0]
    assert pick.limit_proximity is not None
    assert 0.0 <= pick.limit_proximity.consumed <= 1.0


def test_the_score_is_reported_with_its_ceiling(session) -> None:
    store(session, "RISER", make_candles(250))
    pick = screen(session, Horizon.D7).picks[0]
    assert pick.out_of == pytest.approx(max_score(Horizon.D7))
    assert pick.score <= pick.out_of


def test_scoping_to_an_empty_asset_list_returns_nothing_rather_than_everything(
    session,
) -> None:
    """A watchlist-scoped screen for a user with no watchlist must not quietly
    become a screen of the whole market."""
    store(session, "RISER", make_candles(250))
    assert screen(session, Horizon.D7, asset_ids=[]).picks == []


# --- what the output must not claim ----------------------------------------


def test_every_result_carries_the_caveat(session) -> None:
    result = screen(session, Horizon.D7)
    assert result.caveat == SCREEN_CAVEAT


def test_the_caveat_says_it_is_not_a_forecast() -> None:
    lowered = SCREEN_CAVEAT.lower()
    assert "not a forecast" in lowered
    assert "not a probability" in lowered
    assert "not investment advice" in lowered
    assert "places no orders" in lowered


def test_the_caveat_explains_what_the_horizon_means() -> None:
    """Without this, "7d" is read as "will rise within seven days"."""
    assert "how long anything will take to happen" in SCREEN_CAVEAT


def test_no_output_field_is_named_as_a_prediction(session) -> None:
    """Naming is the only thing between a screen and being read as a forecast.

    The caveat is excluded from the scan on purpose: it is the one place the
    words *should* appear, because it is there to deny them.
    """
    store(session, "RISER", make_candles(250))
    payload = screen(session, Horizon.D7).as_dict()
    payload.pop("caveat")

    blob = str(payload).lower()
    for word in ("probability", "forecast", "prediction", "expected_return", "will_rise"):
        assert word not in blob, f"output uses forecast vocabulary: {word}"


# --- criteria that can actually fire ----------------------------------------


def test_every_criterion_can_fire_on_some_input() -> None:
    """A criterion testing for a value its source never produces is dead, and a
    dead criterion is invisible: it reads as a condition nothing happened to
    meet. `breakout_up_confirmed` tested `direction == "up"` while the detector
    says `"bullish"`, so 1.0 of the 1d horizon's 4.1 was unreachable for as long
    as the screen only ranked a dozen assets.

    Rather than assert against a hardcoded list of enum values - which would go
    stale in exactly the same way - this drives real bars through the real
    engine and requires each criterion to fire at least once.
    """
    from datetime import UTC, datetime, timedelta

    from aidss.domain.types import Candle
    from aidss.indicators.engine import IndicatorEngine
    from aidss.screener.criteria import CRITERIA_BY_HORIZON
    from aidss.screener.engine import _reading

    LAST = 259

    def series(shape, volume=lambda i: 1_000_000 + (i % 7) * 200_000) -> list[Candle]:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        bars = []
        for index in range(LAST + 1):
            close = shape(index)
            bars.append(
                Candle(
                    timestamp=start + timedelta(days=index),
                    open=Decimal(str(close)),
                    high=Decimal(str(close * 1.02)),
                    low=Decimal(str(close * 0.98)),
                    close=Decimal(str(close)),
                    volume=volume(index),
                )
            )
        return bars

    shapes = [
        (lambda i: 100 + i * 0.5, None),                    # steady climb
        (lambda i: 300 - i * 0.8, None),                    # steady fall
        (lambda i: 100 + (i % 20) * 2, None),               # sawtooth
        (lambda i: 100.0, None),                            # flat
        # A range broken on the very last bar. Breaking it earlier lets the
        # 20-bar window catch up, and the breakout stops being one.
        (lambda i: 100 + (40 if i == LAST else 0), None),
        # A dip and recovery, which is what the oversold-turning-up readings
        # are written to describe.
        (lambda i: 200 - min(i, 200) * 0.9 + max(0, i - 240) * 8, None),
        # A long slide that turns up two bars from the end. %K reacts before
        # %D, so the cross happens while both are still low - which is the
        # whole shape "turning up from a low reading" names.
        (lambda i: 300 - min(i, LAST - 2) * 0.9 + max(0, i - (LAST - 2)) * 3, None),
        # Rising into a volume surge, for the criteria that ask whether the
        # move is being paid for.
        (
            lambda i: 100 + i * 0.4,
            lambda i: 20_000_000 if i > LAST - 3 else 1_000_000,
        ),
    ]

    engine = IndicatorEngine()
    fired: set[str] = set()
    for shape, volume in shapes:
        bars = series(shape) if volume is None else series(shape, volume)
        reading = _reading(bars, engine)
        if reading is None:
            continue
        for criteria in CRITERIA_BY_HORIZON.values():
            for criterion in criteria:
                try:
                    if criterion.test(reading):
                        fired.add(criterion.key)
                except (TypeError, ValueError):
                    pass

    everything = {c.key for criteria in CRITERIA_BY_HORIZON.values() for c in criteria}
    assert everything - fired == set(), (
        "these criteria never fired on any shape, which usually means they test "
        "for a value their source does not produce"
    )

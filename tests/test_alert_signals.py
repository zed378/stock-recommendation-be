"""The alert conditions read from stored bars.

Every rule here is stated on a *crossing* rather than on a state, and most of
these tests exist to hold that line. "RSI is below 30" is true on the day it
crosses and on every day of the downtrend after it; a rule written that way
fires daily and is switched off within a week. "RSI crossed below 30" happens
once, which is what an interruption is worth.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidss.db.models import AlertDirection, AlertKind
from aidss.domain.types import Candle
from aidss.monitoring.alerts import evaluate_signals
from aidss.monitoring.signals import TechnicalSignals, compute_signals

ASSET = uuid.uuid4()


def fire(**signals) -> dict[AlertKind, object]:
    """The candidates a bundle produces, keyed by kind."""
    candidates = evaluate_signals(
        asset_id=ASSET,
        ticker="BBRI",
        price=signals.pop("price", Decimal("1000")),
        support_levels=signals.pop("support_levels", None),
        signals=TechnicalSignals(as_of=datetime(2026, 8, 6, tzinfo=UTC).date(), **signals),
    )
    return {candidate.kind: candidate for candidate in candidates}


# --- volume -----------------------------------------------------------------


def test_volume_at_twice_its_average_is_a_spike() -> None:
    fired = fire(volume_ratio=Decimal("2.4"), previous_close=Decimal("1000"))

    assert AlertKind.VOLUME_SPIKE in fired
    assert "2.4x" in fired[AlertKind.VOLUME_SPIKE].message


def test_ordinary_volume_is_not(fire_ratio=None) -> None:
    assert AlertKind.VOLUME_SPIKE not in fire(volume_ratio=Decimal("1.9"))


def test_a_spike_before_the_price_has_run_is_reported_separately() -> None:
    """The pairing is the point: busy *before* the move is a different thing to
    look at from busy *because of* it, and a reader filtering for the first
    cannot recover it from the combined alert."""
    fired = fire(
        volume_ratio=Decimal("3.0"), previous_close=Decimal("1000"), price=Decimal("1020")
    )

    assert AlertKind.VOLUME_SPIKE in fired
    assert AlertKind.VOLUME_SPIKE_QUIET in fired
    assert "+2.0%" in fired[AlertKind.VOLUME_SPIKE_QUIET].message


def test_a_spike_after_a_large_move_is_only_a_spike() -> None:
    fired = fire(
        volume_ratio=Decimal("3.0"), previous_close=Decimal("1000"), price=Decimal("1080")
    )

    assert AlertKind.VOLUME_SPIKE in fired
    assert AlertKind.VOLUME_SPIKE_QUIET not in fired, "8% is not 'has not moved much'"


# --- moving averages --------------------------------------------------------


def test_the_fast_average_crossing_up_is_a_golden_cross() -> None:
    fired = fire(
        previous_fast_ma=Decimal("99"),
        previous_slow_ma=Decimal("100"),
        fast_ma=Decimal("101"),
        slow_ma=Decimal("100"),
    )

    assert AlertKind.GOLDEN_CROSS in fired
    assert fired[AlertKind.GOLDEN_CROSS].direction is AlertDirection.UP


def test_the_fast_average_crossing_down_is_a_death_cross() -> None:
    fired = fire(
        previous_fast_ma=Decimal("101"),
        previous_slow_ma=Decimal("100"),
        fast_ma=Decimal("99"),
        slow_ma=Decimal("100"),
    )

    assert AlertKind.DEATH_CROSS in fired


def test_staying_above_is_not_a_cross() -> None:
    """The rule that keeps this from firing every day for a year."""
    fired = fire(
        previous_fast_ma=Decimal("105"),
        previous_slow_ma=Decimal("100"),
        fast_ma=Decimal("106"),
        slow_ma=Decimal("100"),
    )

    assert AlertKind.GOLDEN_CROSS not in fired
    assert AlertKind.DEATH_CROSS not in fired


def test_a_missing_previous_value_is_not_a_cross() -> None:
    """Otherwise the first session with enough history to compute either line
    reports a crossing - which is a property of the data starting, not of the
    market."""
    fired = fire(fast_ma=Decimal("101"), slow_ma=Decimal("100"))

    assert AlertKind.GOLDEN_CROSS not in fired


# --- momentum ---------------------------------------------------------------


def test_rsi_crossing_below_thirty() -> None:
    fired = fire(previous_rsi=Decimal("31"), rsi=Decimal("28"))

    assert AlertKind.RSI_OVERSOLD in fired
    assert "28.0" in fired[AlertKind.RSI_OVERSOLD].message


def test_rsi_already_below_thirty_is_not_an_event() -> None:
    assert AlertKind.RSI_OVERSOLD not in fire(previous_rsi=Decimal("25"), rsi=Decimal("22"))


def test_rsi_crossing_above_seventy() -> None:
    assert AlertKind.RSI_OVERBOUGHT in fire(previous_rsi=Decimal("69"), rsi=Decimal("72"))


def test_stochastic_bands_behave_the_same_way() -> None:
    assert AlertKind.STOCHASTIC_OVERSOLD in fire(
        previous_stochastic_k=Decimal("22"), stochastic_k=Decimal("18")
    )
    assert AlertKind.STOCHASTIC_OVERBOUGHT in fire(
        previous_stochastic_k=Decimal("78"), stochastic_k=Decimal("83")
    )
    assert AlertKind.STOCHASTIC_OVERSOLD not in fire(
        previous_stochastic_k=Decimal("15"), stochastic_k=Decimal("12")
    )


def test_macd_crossing_its_signal_line_carries_the_direction() -> None:
    up = fire(
        previous_macd=Decimal("-1"),
        previous_macd_signal=Decimal("0"),
        macd=Decimal("1"),
        macd_signal=Decimal("0"),
    )
    down = fire(
        previous_macd=Decimal("1"),
        previous_macd_signal=Decimal("0"),
        macd=Decimal("-1"),
        macd_signal=Decimal("0"),
    )

    assert up[AlertKind.MACD_CROSSED].direction is AlertDirection.UP
    assert down[AlertKind.MACD_CROSSED].direction is AlertDirection.DOWN


# --- session shape ----------------------------------------------------------


def test_an_opening_gap_up() -> None:
    fired = fire(session_open=Decimal("1050"), previous_close=Decimal("1000"))

    assert AlertKind.GAP_UP in fired
    assert "+5.0%" in fired[AlertKind.GAP_UP].message


def test_an_opening_gap_down() -> None:
    assert AlertKind.GAP_DOWN in fire(
        session_open=Decimal("950"), previous_close=Decimal("1000")
    )


def test_a_small_opening_difference_is_not_a_gap() -> None:
    fired = fire(session_open=Decimal("1005"), previous_close=Decimal("1000"))

    assert AlertKind.GAP_UP not in fired and AlertKind.GAP_DOWN not in fired


# --- a break that did not hold ----------------------------------------------


def test_a_failed_breakout_is_reported() -> None:
    fired = fire(failed_breakout_level=Decimal("1200"), price=Decimal("1150"))

    assert AlertKind.FALSE_BREAKOUT in fired
    assert fired[AlertKind.FALSE_BREAKOUT].direction is AlertDirection.DOWN


# --- support with divergence ------------------------------------------------


def test_support_and_divergence_together() -> None:
    """One alert rather than two: either half alone says much less than the
    pair. "Near support" is a location, "RSI made a higher low" is a
    measurement, and together they are the setup people watch for."""
    fired = fire(
        bullish_divergence=True,
        price=Decimal("1010"),
        support_levels=[Decimal("1000")],
    )

    assert AlertKind.SUPPORT_WITH_DIVERGENCE in fired
    assert "1,000.00" in fired[AlertKind.SUPPORT_WITH_DIVERGENCE].message


def test_divergence_away_from_support_is_not_reported() -> None:
    fired = fire(
        bullish_divergence=True, price=Decimal("1500"), support_levels=[Decimal("1000")]
    )

    assert AlertKind.SUPPORT_WITH_DIVERGENCE not in fired


def test_support_without_divergence_is_not_this_alert() -> None:
    fired = fire(price=Decimal("1010"), support_levels=[Decimal("1000")])

    assert AlertKind.SUPPORT_WITH_DIVERGENCE not in fired


# --- deduplication ----------------------------------------------------------


def test_every_candidate_is_keyed_to_its_session() -> None:
    """These are statements about a session, so they must repeat once per
    session and not once per poll - the scheduler runs this every few minutes."""
    candidates = evaluate_signals(
        asset_id=ASSET,
        ticker="BBRI",
        price=Decimal("1000"),
        signals=TechnicalSignals(
            as_of=datetime(2026, 8, 6, tzinfo=UTC).date(),
            volume_ratio=Decimal("3"),
            previous_close=Decimal("1000"),
            previous_rsi=Decimal("31"),
            rsi=Decimal("28"),
        ),
    )

    assert candidates
    for candidate in candidates:
        assert candidate.dedup_key.endswith("2026-08-06"), candidate.dedup_key
        assert str(ASSET) in candidate.dedup_key


# --- computing the bundle from bars -----------------------------------------


def bars(closes: list[float], *, volumes: list[float] | None = None) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Candle(
            timestamp=start + timedelta(days=index),
            open=Decimal(str(close)),
            high=Decimal(str(close * 1.01)),
            low=Decimal(str(close * 0.99)),
            close=Decimal(str(close)),
            volume=Decimal(str((volumes or [1_000_000] * len(closes))[index])),
        )
        for index, close in enumerate(closes)
    ]


def test_too_little_history_says_nothing_rather_than_guessing() -> None:
    """A newly listed issuer has no 50-day average. That is an ordinary state,
    not an error, and every rule treats a missing value as "cannot say"."""
    signals = compute_signals(bars([100, 101, 102]))

    assert signals.slow_ma is None
    assert signals.rsi is None
    assert not evaluate_signals(
        asset_id=ASSET, ticker="BBRI", price=Decimal("102"), signals=signals
    )


def test_an_empty_history_is_handled() -> None:
    assert compute_signals([]).as_of is None


def test_the_volume_ratio_is_measured_against_this_issuer_s_own_average() -> None:
    """An absolute threshold would flag every liquid stock and never flag an
    illiquid one having its busiest day in a year."""
    volumes = [1_000_000.0] * 25 + [3_000_000.0]
    signals = compute_signals(bars([100.0] * 26, volumes=volumes))

    assert signals.volume_ratio is not None
    assert signals.volume_ratio > Decimal("2")


def test_a_break_that_held_is_not_a_false_breakout() -> None:
    rising = [100.0] * 25 + [110.0, 112.0, 114.0]
    assert compute_signals(bars(rising)).failed_breakout_level is None


def test_a_break_that_gave_way_is_reported_as_false() -> None:
    """Judged on closes, not intraday highs: a wick through a level and a
    session that closed above it are different events, and only the second is
    what anybody means by a breakout."""
    reversed_break = [100.0] * 25 + [110.0, 105.0, 99.0]

    assert compute_signals(bars(reversed_break)).failed_breakout_level == Decimal("100.0")


@pytest.mark.parametrize("field", ["fast_ma", "rsi", "stochastic_k", "volume_ratio"])
def test_a_flat_series_still_computes(field: str) -> None:
    """A perfectly flat price is degenerate for several of these - a zero range
    divides by zero in the stochastic - and must not raise."""
    signals = compute_signals(bars([100.0] * 60))

    assert getattr(signals, field) is not None


# --- the year's range, volatility, and geometry ------------------------------


def test_price_at_its_yearly_high() -> None:
    fired = fire(price=Decimal("995"), year_high=Decimal("1000"), year_low=Decimal("500"))

    assert AlertKind.AT_52_WEEK_HIGH in fired
    assert AlertKind.AT_52_WEEK_LOW not in fired


def test_price_at_its_yearly_low() -> None:
    fired = fire(price=Decimal("505"), year_high=Decimal("1000"), year_low=Decimal("500"))

    assert AlertKind.AT_52_WEEK_LOW in fired


def test_price_in_the_middle_of_the_year_s_range_is_neither() -> None:
    fired = fire(price=Decimal("750"), year_high=Decimal("1000"), year_low=Decimal("500"))

    assert AlertKind.AT_52_WEEK_HIGH not in fired
    assert AlertKind.AT_52_WEEK_LOW not in fired


def test_a_squeeze_is_measured_against_this_issuer_s_own_bands() -> None:
    """An absolute width says nothing: bands two percent wide are a squeeze on
    a volatile miner and ordinary on a utility."""
    fired = fire(bandwidth=Decimal("0.02"), bandwidth_percentile=Decimal("0.05"))

    assert AlertKind.VOLATILITY_SQUEEZE in fired
    assert AlertKind.VOLATILITY_SQUEEZE not in fire(
        bandwidth=Decimal("0.02"), bandwidth_percentile=Decimal("0.5")
    )


def test_the_squeeze_message_states_compression_and_stops_there() -> None:
    """"Bands are narrow" is an observation. "A big move is coming" is a
    forecast, and which way it resolves is exactly what a squeeze cannot say."""
    message = fire(bandwidth_percentile=Decimal("0.05"))[
        AlertKind.VOLATILITY_SQUEEZE
    ].message.lower()

    for forecast in ("will", "expect", "coming", "breakout soon", "about to"):
        assert forecast not in message, message


def test_a_wide_session_is_reported_as_range_expansion() -> None:
    fired = fire(range_ratio=Decimal("2.6"))

    assert AlertKind.RANGE_EXPANSION in fired
    assert AlertKind.RANGE_EXPANSION not in fire(range_ratio=Decimal("1.4"))


def test_reward_to_risk_needs_both_sides() -> None:
    """A ratio computed against an imagined support is a number with no
    measurement behind it - and exactly the sort a reader treats as though
    there were."""
    from aidss.monitoring.alerts import evaluate_geometry

    assert not evaluate_geometry(
        asset_id=ASSET,
        ticker="BBRI",
        price=Decimal("1000"),
        support_levels=[Decimal("900")],
        resistance_levels=[],
    )


def test_reward_to_risk_is_reported_when_the_ratio_is_reached() -> None:
    from aidss.monitoring.alerts import evaluate_geometry

    candidates = evaluate_geometry(
        asset_id=ASSET,
        ticker="BBRI",
        price=Decimal("1000"),
        support_levels=[Decimal("950")],
        resistance_levels=[Decimal("1150")],
    )

    assert [c.kind for c in candidates] == [AlertKind.REWARD_TO_RISK_REACHED]
    assert candidates[0].context["ratio"].startswith("3")


def test_a_thin_reward_to_risk_is_not_reported() -> None:
    from aidss.monitoring.alerts import evaluate_geometry

    assert not evaluate_geometry(
        asset_id=ASSET,
        ticker="BBRI",
        price=Decimal("1000"),
        support_levels=[Decimal("950")],
        resistance_levels=[Decimal("1050")],
    )


# --- trailing stop ----------------------------------------------------------


def test_a_trailing_stop_is_measured_from_the_peak_not_the_entry() -> None:
    from aidss.monitoring.alerts import evaluate_trailing_stop

    candidates = evaluate_trailing_stop(
        asset_id=ASSET,
        ticker="BBRI",
        price=Decimal("900"),
        peak_since_entry=Decimal("1000"),
        drop_fraction=Decimal("0.10"),
    )

    assert [c.kind for c in candidates] == [AlertKind.TRAILING_STOP_REACHED]
    assert candidates[0].reference_price == Decimal("1000")


def test_a_smaller_fall_is_not_a_trailing_stop() -> None:
    from aidss.monitoring.alerts import evaluate_trailing_stop

    assert not evaluate_trailing_stop(
        asset_id=ASSET,
        ticker="BBRI",
        price=Decimal("950"),
        peak_since_entry=Decimal("1000"),
        drop_fraction=Decimal("0.10"),
    )


def test_the_trailing_stop_says_reached_rather_than_triggered() -> None:
    """Nothing is triggered, because nothing here can act. The word choice is
    the whole distinction, and it is the same one the suggested stop makes."""
    from aidss.monitoring.alerts import evaluate_trailing_stop

    message = evaluate_trailing_stop(
        asset_id=ASSET,
        ticker="BBRI",
        price=Decimal("900"),
        peak_since_entry=Decimal("1000"),
        drop_fraction=Decimal("0.10"),
    )[0].message.lower()

    for word in ("triggered", "sell", "exit now", "cut loss"):
        assert word not in message, message


# --- the discipline every kind is under --------------------------------------


def test_no_alert_kind_names_an_instruction() -> None:
    """`AlertKind` is a closed enum of *observations*. The moment a member
    reads as an instruction, a notification becomes a trading signal no matter
    what the rest of the product says about itself."""
    forbidden = ("buy", "sell", "exit", "enter", "take_profit", "cut")
    offenders = [
        kind.value
        for kind in AlertKind
        for word in forbidden
        if word in kind.value.split("_")
    ]
    assert not offenders, offenders

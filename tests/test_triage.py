"""Deciding how much reasoning an issuer is worth, before any model is called.

The property under test is not that the arithmetic is right - it is trivially
right - but that the decision can only ever *lower* cost, never quality where
quality was asked for, and that it never becomes a claim about direction.
"""

from __future__ import annotations

from datetime import date

import pytest

from aidss.agents.triage import Depth, assess, triage_for
from aidss.llm.router import TaskComplexity


def test_a_quiet_issuer_gets_the_cheap_tier() -> None:
    """The whole point. A dozen model calls cost the same whether the issuer
    moved violently or did nothing, and without triage the pipeline has no way
    to tell those apart before it starts paying."""
    triage = assess(matched=[], signals={})

    assert triage.depth is Depth.LIGHT
    assert triage.complexity is TaskComplexity.LIGHT


def test_a_busy_issuer_gets_the_strong_tier() -> None:
    triage = assess(matched=["gap_up", "volume_spike", "golden_cross"], signals={})

    assert triage.depth is Depth.FULL
    assert triage.complexity is TaskComplexity.COMPLEX


def test_asking_about_an_issuer_directly_always_earns_a_full_run() -> None:
    """Somebody who opened a stock and pressed the button has a reason the
    stored numbers do not know about. Serving them the cheap path makes the
    feature feel broken exactly when it is being used on purpose."""
    triage = assess(matched=[], signals={}, requested_full=True)

    assert triage.depth is Depth.FULL
    assert triage.complexity is TaskComplexity.COMPLEX


def test_the_decision_says_why() -> None:
    """A routing decision that cannot be explained is one nobody will trust
    when it is wrong - and it will sometimes be wrong."""
    triage = assess(matched=["gap_up"], signals={"volume_ratio": "3.0"})

    assert triage.because
    assert any("volume" in reason for reason in triage.because)


def test_the_score_never_becomes_a_direction() -> None:
    """A number attached to a ticker is read as a forecast unless the code is
    careful. Two issuers moving equally hard, one up and one down, must triage
    identically: the score measures how much is happening, not which way."""
    rising = assess(signals={"range_ratio": "2.5", "volume_ratio": "3.0"})
    falling = assess(
        matched=["gap_down"], signals={"range_ratio": "2.5", "volume_ratio": "3.0"}
    )

    assert rising.complexity is falling.complexity


def test_the_payload_carries_no_direction_or_probability_words() -> None:
    """Guards the vocabulary rather than the arithmetic. The failure this
    prevents is somebody later adding a helpful "likely" to a `because` line."""
    payload = assess(matched=["gap_up", "volume_spike", "rsi_oversold"]).as_payload()

    text = " ".join(payload["because"]).lower()
    for word in ("likely", "expect", "predict", "probability", "will rise", "buy"):
        assert word not in text


def test_an_unscanned_issuer_is_standard_rather_than_light(session) -> None:
    """"Nothing is known about this issuer" and "nothing is happening to it"
    are different findings, and only the second one justifies spending less."""
    triage = triage_for(session, "ZZZZ")

    assert triage.depth is Depth.STANDARD


def test_triage_reads_the_stored_scan(session) -> None:
    from aidss.db.models import MarketScanResult

    session.add(
        MarketScanResult(
            ticker="YYYY",
            session_date=date(2026, 8, 6),
            matched=["gap_up", "volume_spike", "golden_cross"],
            matched_count=3,
            signals={"volume_ratio": "4.0"},
        )
    )
    session.flush()

    assert triage_for(session, "yyyy").depth is Depth.FULL


def test_a_malformed_stored_signal_does_not_raise(session) -> None:
    """The signals column is JSON written by a different subsystem. A value it
    cannot parse must cost the run its bonus, not the run itself."""
    triage = assess(signals={"volume_ratio": "not a number", "range_ratio": None})

    assert triage.depth is Depth.LIGHT


@pytest.mark.parametrize(
    ("cap", "agent_tier", "expected"),
    [
        (TaskComplexity.LIGHT, TaskComplexity.COMPLEX, TaskComplexity.LIGHT),
        (TaskComplexity.LIGHT, TaskComplexity.LIGHT, TaskComplexity.LIGHT),
        (TaskComplexity.COMPLEX, TaskComplexity.LIGHT, TaskComplexity.LIGHT),
        (None, TaskComplexity.COMPLEX, TaskComplexity.COMPLEX),
    ],
)
def test_a_cap_only_ever_lowers(cap, agent_tier, expected) -> None:
    """Third row is the one that matters: an agent asking for the cheap tier
    asked for it on its own merits, and a high cap must not promote it."""
    from aidss.agents.base import AgentRunner

    class Stub:
        complexity = agent_tier

    runner = AgentRunner(gateway=None, complexity_cap=cap)  # type: ignore[arg-type]

    assert runner._tier(Stub()) is expected

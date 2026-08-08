"""How an analysis is framed for the investor reading it.

The Memory Manager has always known the investor's horizon and risk appetite,
and the context builder has always put them in the prompt variables - but a
template that never interpolates `{investor}` drops them on the floor. The
effect was a platform that asked people how they invest and then wrote every
analysis the same way.

Injected into the system message rather than added to each template, for the
reason that matters here: a rule that has to be repeated in eleven templates is
a rule that will be missing from the twelfth.

**Framing is not conclusion.** This changes emphasis, depth of explanation, and
which risks are worth spelling out. It must never change the stance, the
levels, or the confidence - two investors looking at the same issuer on the
same day are looking at the same facts, and a platform that told the cautious
one "sell" and the aggressive one "buy" would not be personalising, it would be
telling each of them what they wanted to hear.
"""

from __future__ import annotations

from typing import Any

#: What each horizon means for emphasis. Written as guidance about *what to
#: dwell on*, never as guidance about what to conclude.
_HORIZON: dict[str, str] = {
    "short": (
        "reads over days to a few weeks, so near-term levels, liquidity and "
        "session-scale volatility carry more weight than multi-year trends"
    ),
    "medium": (
        "reads over weeks to months, so trend structure and the next few "
        "reporting periods carry more weight than intraday detail"
    ),
    "long": (
        "reads over years, so balance-sheet durability, cash generation and "
        "competitive position carry more weight than current momentum"
    ),
}

_RISK: dict[str, str] = {
    "conservative": (
        "wants downside spelled out explicitly: what would have to go wrong, "
        "how far it has fallen before, and what the position looks like if the "
        "bearish case is the one that happens"
    ),
    "moderate": "wants upside and downside weighted evenly",
    "aggressive": (
        "is comfortable with volatility, so state it plainly rather than "
        "hedging every sentence - but do not omit a risk because it is "
        "unwelcome"
    ),
}

_EXPERIENCE: dict[str, str] = {
    "beginner": (
        "is new to market terminology: name each indicator in plain language "
        "the first time it appears, and say what it measures"
    ),
    "intermediate": "knows standard indicators and does not need them defined",
    "advanced": (
        "is fluent in technical and fundamental vocabulary; be concise and "
        "skip definitions"
    ),
}


def investor_framing(profile: dict[str, Any] | None) -> str:
    """A framing block for the system message, or empty when nothing is known.

    Empty rather than a default paragraph: a profile nobody stated should not
    produce instructions that read as though they did. The defaults in the
    Memory Manager exist so code has something to read, not so the model is
    told the investor asked for something.
    """
    if not profile:
        return ""

    lines: list[str] = []
    horizon = _HORIZON.get(str(profile.get("investment_horizon", "")))
    if horizon:
        lines.append(f"- Their horizon {horizon}.")
    risk = _RISK.get(str(profile.get("risk_appetite", "")))
    if risk:
        lines.append(f"- On risk, this reader {risk}.")
    experience = _EXPERIENCE.get(str(profile.get("experience_level", "")))
    if experience:
        lines.append(f"- On vocabulary, this reader {experience}.")

    if not lines:
        return ""

    body = "\n".join(lines)
    return (
        "\n\nWHO IS READING THIS\n"
        f"{body}\n"
        "Let this shape emphasis, ordering and how much you explain. It must "
        "not shape your conclusion: the stance, the levels and the confidence "
        "are properties of the evidence, not of who is reading. Never soften a "
        "risk or drop a contradicting indicator because of the profile above."
    )

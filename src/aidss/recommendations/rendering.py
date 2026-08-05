"""Producing the other language while the analysis is being written.

The reader is already waiting for the analysis. Doing the translation then -
once, into storage - costs a few seconds on a request that was going to take a
while anyway, and removes the wait from every subsequent view. Translating on
demand meant paying it every time somebody flipped the switch.

Two properties this has to have, and the second is the important one.

**Stored beside the original, not instead of it.** The prose columns keep the
text that passed schema validation and the execution-language guard; the
rendering sits in `translations` under its language. Nothing about the stored
stance, confidence, or prices is duplicated, so the two renderings cannot
disagree about what was concluded - only about the words.

**A failed translation must not fail the analysis.** The analysis is the
product; the translation is a convenience. An exception here would throw away a
completed multi-agent run because a rendering step timed out, which is a bad
trade in every direction. It is caught, logged, and left empty - and the
on-demand endpoint still works, so the feature degrades to what it was rather
than disappearing.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from aidss.db.models import Recommendation
from aidss.llm.errors import GatewayError
from aidss.llm.gateway import LLMGateway
from aidss.prompts.language import OutputLanguage
from aidss.prompts.translation import translatable_fields, translate

logger = logging.getLogger("aidss.recommendations")


def other_language(language: str) -> OutputLanguage:
    """The language a reader of `language` would want the switch to offer."""
    return OutputLanguage.EN if language == OutputLanguage.ID.value else OutputLanguage.ID


def prose_of(row: Recommendation) -> dict[str, Any]:
    """The fields worth rendering, read off a stored recommendation."""
    return translatable_fields(
        {
            "reasoning": row.reasoning,
            "supporting_factors": list(row.supporting_factors or []),
            "conflicting_factors": list(row.conflicting_factors or []),
            "risk_factors": list(row.risk_factors or []),
            "bullish_scenario": row.bullish_scenario,
            "bearish_scenario": row.bearish_scenario,
        }
    )


def render_translation(
    session: Session,
    gateway: LLMGateway,
    recommendation_id: uuid.UUID,
    *,
    target: OutputLanguage | None = None,
) -> bool:
    """Translate one stored recommendation and save the result. Never raises.

    Returns whether a translation was stored, so the caller can report it
    rather than having to guess from an absent field.
    """
    row = session.get(Recommendation, recommendation_id)
    if row is None:
        return False

    language = target or other_language(row.language)
    if language.value == row.language:
        # Nothing to do: the original is already in the requested language.
        return False

    fields = prose_of(row)
    if not fields:
        return False

    try:
        result = translate(gateway, fields, language)
    except (GatewayError, ValueError) as exc:
        # Caught deliberately. Losing a completed multi-agent analysis because
        # a rendering step failed is a bad trade in every direction, and the
        # on-demand endpoint remains as the fallback.
        logger.warning(
            "translation not stored with the analysis",
            extra={
                "recommendation_id": str(recommendation_id),
                "language": language.value,
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
        return False

    # Reassigned rather than mutated: SQLAlchemy does not track in-place edits
    # to a JSON column, so a `dict[...] = ...` would be silently discarded.
    row.translations = {
        **(row.translations or {}),
        language.value: {
            "fields": result.fields,
            "model": result.model,
            "is_machine_translation": True,
            "translated_at": datetime.now(UTC).isoformat(),
        },
    }
    session.flush()
    return True

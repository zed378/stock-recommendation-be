"""Memory Manager (Section 5.2).

Holds what the investor has told us about how they invest, so analysis can be
framed for a long-horizon holder rather than a day trader without asking again
every session.

Two deliberate limits. Preferences are scoped to a user and never leak across
accounts. And a preference is recorded with its ``source``: something the
investor stated is treated differently from something the system inferred,
because reflecting an inference back as "you told us" is how a product starts
being wrong about people confidently.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.db.models import UserPreference


class PreferenceKey:
    HORIZON = "investment_horizon"
    RISK_APPETITE = "risk_appetite"
    EXPERIENCE = "experience_level"
    EXPLANATION_DEPTH = "explanation_depth"
    PRIVACY_MODE = "privacy_mode"


#: Used when nothing is known. Chosen to be unremarkable: the alternative is a
#: system that assumes an aggressive short-horizon investor by default, which
#: would shape every analysis before the user has said anything.
DEFAULT_PREFERENCES: dict[str, Any] = {
    PreferenceKey.HORIZON: "medium",
    PreferenceKey.RISK_APPETITE: "moderate",
    PreferenceKey.EXPERIENCE: "intermediate",
    PreferenceKey.EXPLANATION_DEPTH: "standard",
    PreferenceKey.PRIVACY_MODE: "standard",
}


@dataclass(frozen=True, slots=True)
class InvestorMemory:
    """What the AI layer knows about this investor when analysis starts."""

    user_id: uuid.UUID | None
    preferences: dict[str, Any]

    @property
    def horizon(self) -> str:
        return str(self.preferences.get(PreferenceKey.HORIZON, "medium"))

    @property
    def risk_appetite(self) -> str:
        return str(self.preferences.get(PreferenceKey.RISK_APPETITE, "moderate"))

    @property
    def high_privacy(self) -> bool:
        """Whether this investor requires self-hosted inference (Section 12.10)."""
        return str(self.preferences.get(PreferenceKey.PRIVACY_MODE, "standard")) == "high"

    def as_prompt_context(self) -> dict[str, Any]:
        return {
            "investment_horizon": self.horizon,
            "risk_appetite": self.risk_appetite,
            "experience_level": self.preferences.get(PreferenceKey.EXPERIENCE, "intermediate"),
        }


class MemoryManager:
    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    def load(self, user_id: uuid.UUID | None) -> InvestorMemory:
        preferences = dict(DEFAULT_PREFERENCES)
        if self._session is not None and user_id is not None:
            rows = self._session.scalars(
                select(UserPreference).where(UserPreference.user_id == user_id)
            ).all()
            for row in rows:
                preferences[row.key] = row.value.get("value", row.value)
        return InvestorMemory(user_id=user_id, preferences=preferences)

    def remember(
        self,
        user_id: uuid.UUID,
        key: str,
        value: Any,
        *,
        source: str = "stated",
    ) -> UserPreference:
        if self._session is None:
            raise RuntimeError("remember() requires a database session")

        row = self._session.scalar(
            select(UserPreference).where(
                UserPreference.user_id == user_id, UserPreference.key == key
            )
        )
        if row is None:
            row = UserPreference(
                user_id=user_id, key=key, value={"value": value}, source=source
            )
            self._session.add(row)
        else:
            # A stated preference is never overwritten by an inferred one: the
            # investor's own words outrank the system's guess.
            if row.source == "stated" and source == "inferred":
                return row
            row.value = {"value": value}
            row.source = source
        self._session.flush()
        return row

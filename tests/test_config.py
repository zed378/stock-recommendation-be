"""Settings parsing, and the empty-string case that took a deployment down.

Environment variables are strings and have no null. Every deployment mechanism
therefore spells "unset" as empty - `${VAR:-}` in Compose, an unfilled key in a
ConfigMap, a blank line in an `.env` file - and a setting that cannot parse ""
fails at import time, before the process can say anything more useful than a
validation traceback.

That is not hypothetical: `AIDSS_DAILY_AI_BUDGET=` crashed the API container on
startup, nginx could then not resolve the backend and refused to start too, and
the whole site returned 502 from the edge. One unparsed empty string.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from aidss.config import Settings

BASE = {"jwt_secret": "test-secret-not-for-production-0123456789abcdef"}


def settings(**overrides) -> Settings:
    return Settings(**{**BASE, **overrides})


# --- empty means unset -----------------------------------------------------


def test_an_empty_budget_is_no_ceiling_not_a_parse_error() -> None:
    """The exact failure: Decimal("") raises, and the process exits."""
    assert settings(daily_ai_budget="").daily_ai_budget is None


def test_a_whitespace_only_budget_is_also_unset() -> None:
    """A trailing space in an env file is invisible and would otherwise be a
    different failure from an empty one."""
    assert settings(daily_ai_budget="   ").daily_ai_budget is None


def test_a_real_budget_still_parses() -> None:
    """The guard must not swallow the value it exists to protect."""
    assert settings(daily_ai_budget="25.50").daily_ai_budget == Decimal("25.50")


@pytest.mark.parametrize(
    "field", ["ai_api_key", "finnhub_api_key", "alphavantage_api_key"]
)
def test_an_empty_credential_is_none_not_an_empty_string(field: str) -> None:
    """So `is None` and falsiness agree about it. One saying set and the other
    unset is how a provider ends up constructed with a blank key and failing at
    the first call instead of at startup."""
    assert getattr(settings(**{field: ""}), field) is None


@pytest.mark.parametrize(
    "field", ["ai_api_key", "finnhub_api_key", "alphavantage_api_key"]
)
def test_a_real_credential_is_preserved(field: str) -> None:
    assert getattr(settings(**{field: "sk-abc123"}), field) == "sk-abc123"


def test_a_budget_that_is_not_a_number_still_fails() -> None:
    """Blank is unset; nonsense is an error. Silently treating "abc" as no
    ceiling would remove a spending limit somebody thought they had set."""
    with pytest.raises(ValidationError):
        settings(daily_ai_budget="abc")


# --- the settings the deployment depends on --------------------------------


def test_an_empty_embedding_model_disables_embeddings() -> None:
    """A supported configuration, not a broken one: retrieval falls back to
    BM25, and exact-token search is unaffected."""
    assert settings(ai_embedding_model="").embeddings_enabled is False


def test_a_named_embedding_model_enables_them() -> None:
    assert settings(ai_embedding_model="text-embedding-3-small").embeddings_enabled is True


def test_an_unknown_environment_is_refused() -> None:
    with pytest.raises(ValidationError):
        settings(environment="prod")


def test_the_suite_reads_no_dotenv_file() -> None:
    """A hermetic suite must not depend on an untracked local file.

    It used to: `Settings` read `.env` from the working directory, so a
    developer with `AIDSS_AI_EMBEDDING_MODEL=` in theirs got one test failure
    that a developer without it did not. The suite looked hermetic right up
    until two people compared notes.
    """
    import aidss.config

    assert aidss.config._ENV_FILE is None, (
        "the test suite is reading a dotenv file, so its result depends on "
        "whatever happens to be in the working directory"
    )


def test_the_composite_defaults_target_idx() -> None:
    """Alpha Vantage was tested against a real key and publishes nothing for
    IDX symbols, so it is the wrong default for this market."""
    current = settings()
    assert current.composite_price_provider == "yahoo"
    assert current.composite_fundamentals_provider == "idx"

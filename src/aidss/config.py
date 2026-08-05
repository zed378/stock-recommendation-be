"""Global configuration (Section 9, Configuration module).

Every value is read from the environment with the ``AIDSS_`` prefix. Provider
selection (AI / market data / news / storage) is configuration rather than a
constant in code, which is what makes FR-07 and Section 7 hold.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Which dotenv file to read, and whether to read one at all.
#:
#: Setting ``AIDSS_ENV_FILE`` to an empty string disables it. The test suite
#: does exactly that, because it must not depend on an untracked file that
#: differs per machine - a developer with a local `.env` was getting a
#: different suite result from one without, which is how this was found. A
#: hermetic suite that quietly reads whatever is lying in the working directory
#: is not hermetic.
_ENV_FILE = os.environ.get("AIDSS_ENV_FILE", ".env") or None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AIDSS_",
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "AI Investment Decision Support Platform"
    environment: str = "development"
    debug: bool = False

    # --- Database ---
    database_url: str = "postgresql+psycopg://aidss:aidss@localhost:5432/aidss"

    # --- Security (Section 13) ---
    jwt_secret: str = Field(default="dev-only-change-me", min_length=8)
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60

    # --- Active provider selection (Section 7) ---
    market_data_provider: str = "fixture"
    news_provider: str = "fixture"
    ai_provider: str = "openai_compatible"
    storage_provider: str = "local"

    # --- Provider credentials (Section 13: never hardcoded) ---
    finnhub_api_key: str | None = None
    alphavantage_api_key: str | None = None

    #: Market suffix appended to tickers for Yahoo Finance. IDX equities are
    #: `.JK` there (BBCA -> BBCA.JK). Set to an empty string for US symbols;
    #: tickers that already carry a suffix are never rewritten.
    yahoo_symbol_suffix: str = ".JK"

    #: The same idea for Alpha Vantage, which spells Jakarta `.JKT`. Separate
    #: settings rather than one shared value, because the suffixes genuinely
    #: differ per provider and a single one would be wrong for somebody.
    alphavantage_symbol_suffix: str = ".JKT"

    #: Whether the Alpha Vantage key is on a paid plan. Off by default, and it
    #: changes behaviour rather than just limits: `outputsize=full` is a
    #: premium entitlement that is *refused* on a free key rather than
    #: downgraded, so asking for it returns no data at all instead of less.
    #: Free keys therefore fetch `compact` - roughly the last 100 points.
    alphavantage_premium: bool = False

    #: Used only when `market_data_provider=composite`. The free sources have
    #: complementary holes - Yahoo serves prices but 401s on fundamentals,
    #: Alpha Vantage serves fundamentals but caps at 25 requests a day - so the
    #: working configuration draws each half from a different adapter.
    composite_price_provider: str = "yahoo"
    #: `idx` rather than `alphavantage`: Alpha Vantage was tested against a
    #: real key and publishes nothing at all for IDX symbols, so it is the
    #: right default only for a watchlist of US equities.
    composite_fundamentals_provider: str = "idx"

    #: Browser profile `curl_cffi` presents to IDX. The endpoint sits behind
    #: Cloudflare and refuses an ordinary HTTP client. Configurable because the
    #: profile that gets through is the thing most likely to need changing when
    #: this breaks.
    idx_impersonate: str = "chrome"

    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str | None = None
    ai_chat_model: str = "gpt-4o-mini"

    #: Whether the endpoint above runs on infrastructure you control.
    #:
    #: This is an **assertion by the operator**, not something the platform can
    #: work out. A URL says nothing about who owns the machine behind it: a
    #: self-hosted vLLM published at a public domain looks exactly like a
    #: third-party API, and a hostname heuristic gets that backwards in the
    #: dangerous direction.
    #:
    #: It gates the agents that handle personal financial data - portfolio,
    #: risk, journal reflection (Sections 12.10, 13). With this False they
    #: refuse to run rather than send positions to a third party, which is the
    #: safe default and the reason it is False.
    #:
    #: Set it True only if the inference actually happens on hardware you
    #: control. A localhost URL is detected automatically, so this exists for
    #: the case where it does not look local but is.
    ai_self_hosted: bool = False
    #: Leave **empty** when the endpoint serves no embedding model. Many
    #: self-hosted gateways front chat-only backends and answer `/embeddings`
    #: with 404 for every model they advertise; setting this to "" says so up
    #: front rather than discovering it once per batch.
    #:
    #: Retrieval then runs on BM25 alone. Exact-token search - a ticker, a
    #: metric name, a ratio - is unaffected and is most of what this domain
    #: asks. What is lost is paraphrase matching: a passage that answers the
    #: question while sharing none of its words.
    ai_embedding_model: str = "text-embedding-3-small"

    @property
    def embeddings_enabled(self) -> bool:
        return bool(self.ai_embedding_model.strip())

    #: Vector width of the embedding model. A property of the model, not of the
    #: schema: text-embedding-3-small is 1536, -3-large is 3072, nomic-embed-text
    #: is 768. PostgreSQL enforces it, so a mismatch fails the insert rather than
    #: storing something unusable.
    #:
    #: Changing it requires a migration and a re-index, which is unavoidable
    #: rather than a design flaw - vectors of different widths cannot be
    #: compared at all, so old rows would be meaningless either way.
    embedding_dimensions: int = 1536

    # --- Local storage ---
    local_storage_root: str = "./var/storage"

    # --- Operational guardrail (Section 6.3.4) ---
    min_schedule_interval_seconds: int = 300

    #: Outbound fundamentals calls allowed per UTC day, per provider account.
    #: Defaults to Alpha Vantage's free tier. Set to 0 for no ceiling - which
    #: means unlimited, not "spend nothing"; the distinction matters because
    #: most providers have no daily cap and a misread default would look
    #: exactly like an outage.
    fundamentals_daily_quota: int = 25

    #: How stale a figure may get before it is queued for refresh. Reported
    #: financials change quarterly, so refetching more often than this spends
    #: an allowance to rewrite identical numbers.
    fundamentals_refresh_interval_days: int = 30

    #: How often the scheduler queues a monitoring pass over followed assets.
    #:
    #: "Near real time" is the honest ceiling: the free sources are delayed by
    #: roughly fifteen minutes, so polling faster asks the same stale number
    #: more often. Five minutes keeps alerts responsive without pretending to a
    #: freshness nothing here has. Set to 0 to stop monitoring entirely.
    monitoring_interval_seconds: int = 300

    #: Ceiling on how many assets one scheduler tick may queue for refresh.
    #: The daily quota is the real limit; this stops a first run against a
    #: large watchlist from filling the queue with jobs that will spend the
    #: next fortnight being deferred.
    fundamentals_max_enqueued_per_tick: int = 5

    # --- Observability and hardening (Phase 9, Sections 2.6, 13) ---
    log_level: str = "INFO"
    json_logs: bool = True
    #: Per-client request ceiling. Generous by default: this protects the
    #: service from a runaway client, it is not a quota product.
    rate_limit_per_minute: int = 120
    #: HSTS is off unless explicitly enabled. Sending it over plain HTTP in
    #: development teaches the browser to refuse the local server.
    enable_hsts: bool = False
    #: Daily AI spend ceiling. None means unlimited - a deliberate default,
    #: because a surprise cap in production is worse than a surprise bill.
    daily_ai_budget: float | None = None
    #: Fraction of the budget at which a warning is raised (Section 12.9).
    budget_warning_threshold: float = 0.8

    @field_validator(
        "daily_ai_budget",
        "ai_api_key",
        "finnhub_api_key",
        "alphavantage_api_key",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        """An empty environment variable means "not set", not "the empty value".

        Environment variables are strings and have no null, so every deployment
        mechanism spells "unset" as empty: `${VAR:-}` in Compose, an unfilled
        key in a k8s ConfigMap, a blank line in an `.env` file. Without this,
        `AIDSS_DAILY_AI_BUDGET=` fails to parse as a number and the process
        exits before it can say anything more useful than a Pydantic
        traceback - which is exactly how it was found.

        Applied to the optional credentials too, so `is None` and falsiness
        agree about them rather than one saying set and the other unset.
        """
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("environment")
    @classmethod
    def _known_environment(cls, v: str) -> str:
        allowed = {"development", "testing", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"environment must be one of {sorted(allowed)}")
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()

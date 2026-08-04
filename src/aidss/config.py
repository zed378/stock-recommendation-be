"""Global configuration (Section 9, Configuration module).

Every value is read from the environment with the ``AIDSS_`` prefix. Provider
selection (AI / market data / news / storage) is configuration rather than a
constant in code, which is what makes FR-07 and Section 7 hold.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AIDSS_",
        env_file=".env",
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
    composite_fundamentals_provider: str = "alphavantage"

    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str | None = None
    ai_chat_model: str = "gpt-4o-mini"
    ai_embedding_model: str = "text-embedding-3-small"

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

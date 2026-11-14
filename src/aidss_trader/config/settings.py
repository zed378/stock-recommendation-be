"""Infrastructure settings, read from the container environment.

Only infrastructure lives here (docs/03-DATA-MODEL/08-SETTINGS-REGISTRY.md).
Anything that limits loss, and the exchange credential, is stored in the
database and edited through the audited operator surface instead.

The master key is never an environment value. The environment holds the
*path* of a file secret (ADR-029), so the key stays out of `docker inspect`
output and process listings.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TraderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AIDSS_TRADER_", env_file=None, extra="ignore")

    database_url: str
    master_key_file: Path | None = None

    # Configuration, not constants: Indodax's own documentation disagrees about
    # which host serves Trade API 2.0 (docs/06-INTEGRATIONS/11, D1). Unset until
    # the connector exists (T2).
    exchange_base_url: str | None = None
    public_base_url: str | None = None
    analysis_api_url: str | None = None

    instance_name: str = "trader-1"
    log_level: str = "INFO"
    heartbeat_file: Path = Path("/tmp/aidss-trader.heartbeat")

    # The owner's choice, ADR-043. Kept here because the lease must work before
    # any operational setting has been read from the database.
    lease_ttl_s: int = Field(default=15, gt=0)
    lease_heartbeat_s: int = Field(default=5, gt=0)

    @model_validator(mode="after")
    def _heartbeat_inside_ttl(self) -> TraderSettings:
        # A heartbeat that is not shorter than the TTL would let a healthy
        # holder lose its own lease between renewals.
        if self.lease_heartbeat_s >= self.lease_ttl_s:
            raise ValueError("lease_heartbeat_s must be shorter than lease_ttl_s")
        return self


@lru_cache
def get_settings() -> TraderSettings:
    return TraderSettings()  # type: ignore[call-arg]

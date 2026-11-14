"""Build the real components from settings: client, notifier, runtime, API.

Nothing here talks to the exchange when it is built. A missing setting leaves the
component out (no client, no API) and says so, instead of substituting a default:
with no exchange client the Trader observes and halts; with no analysis API URL it
serves no operator API, because it could not authenticate anyone.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from aidss_trader.api import ApiContext, create_app
from aidss_trader.auth import TokenVerifier
from aidss_trader.auth.stepup import StepUp
from aidss_trader.config import TraderSettings
from aidss_trader.connector.client import IndodaxClient
from aidss_trader.connector.throttle import Throttle
from aidss_trader.credentials import CredentialStore, CredentialUnreadable
from aidss_trader.killswitch import KillSwitch
from aidss_trader.notify import Channel, Notifier, TelegramChannel
from aidss_trader.promotion import Thresholds
from aidss_trader.runtime.loop import Runtime

logger = logging.getLogger("aidss_trader.runtime")

# How far below Indodax's documented limits the client stays. An engineering margin, not a
# loss limit: reaching a limit is a defect, so half the budget is left unused.
THROTTLE_HEADROOM = 0.5
CLIENT_TIMEOUT_S = 10
CLOCK_CHECK_INTERVAL_S = 60
MAX_SKEW_MS = 250  # ADR-041


def build_client(
    settings: TraderSettings, factory: sessionmaker[Session], fernet: Fernet | None
) -> IndodaxClient | None:
    if not (settings.exchange_base_url and settings.public_base_url):
        logger.warning("no exchange URLs configured: the Trader will observe and halt")
        return None
    if fernet is None:
        logger.warning("no master key: exchange credentials cannot be read")
        return None

    def credentials() -> tuple[str, str]:
        # Read per signature so a rotated key takes effect without a restart, and nothing
        # decrypted is kept in memory between calls.
        with factory() as s:
            found = CredentialStore(s, fernet).get("indodax")
        if found is None:
            raise CredentialUnreadable("no Indodax credential is stored")
        return found

    return _client(settings, credentials)


def _client(
    settings: TraderSettings, credentials: Callable[[], tuple[str, str]]
) -> IndodaxClient | None:
    if not (settings.exchange_base_url and settings.public_base_url):
        return None
    return IndodaxClient(
        exchange_base_url=settings.exchange_base_url,
        public_base_url=settings.public_base_url,
        credentials=credentials,
        throttle=Throttle(THROTTLE_HEADROOM),
        timeout_s=CLIENT_TIMEOUT_S,
        clock_check_interval_s=CLOCK_CHECK_INTERVAL_S,
        max_skew_ms=MAX_SKEW_MS,
    )


def build_candidate_client(settings: TraderSettings, key: str, secret: str) -> IndodaxClient | None:
    """A throwaway client for testing a key before it is stored. Its own throttle, because it
    is used for one read-only call; the key lives only in this closure."""
    return _client(settings, lambda: (key, secret))


def build_channel(factory: sessionmaker[Session], fernet: Fernet | None) -> Channel | None:
    if fernet is None:
        return None
    try:
        with factory() as s:
            found = CredentialStore(s, fernet).get("telegram")
    except CredentialUnreadable:
        return None
    return TelegramChannel(found[0], found[1]) if found and found[1] else None


def build_runtime(
    settings: TraderSettings, factory: sessionmaker[Session], fernet: Fernet | None
) -> Runtime:
    channel = build_channel(factory, fernet)
    client = build_client(settings, factory, fernet)
    return Runtime(
        factory,
        client,
        notifier=lambda s: Notifier(s, channel, link=settings.ui_url),
    )


def build_api(
    settings: TraderSettings,
    factory: sessionmaker[Session],
    runtime: Runtime,
    fernet: Fernet | None = None,
) -> FastAPI | None:
    if not settings.analysis_api_url:
        logger.warning("no analysis API URL: the operator API is not served")
        return None
    verifier = TokenVerifier(settings.analysis_api_url, timeout_s=5)
    notifier = runtime.notifier_factory  # the same channel the loop uses
    client = runtime.client
    return create_app(
        ApiContext(
            session_factory=factory,
            verifier=verifier,
            stepup=lambda s: StepUp(s, settings.analysis_api_url or "", verifier),
            notifier=notifier or (lambda s: Notifier(s, None)),
            killswitch=lambda s: KillSwitch(s, client),
            submit_approved=runtime.submit_approved,
            # Promotion thresholds are the owner's numbers (OQ-12) and are not stored yet, so
            # every one is unset and promotion stays blocked.
            thresholds=lambda: Thresholds(),
            freshness=runtime.freshness,
            # Without the master key no credential can be read or changed; the routes say so.
            credentials=lambda s: CredentialStore(s, fernet) if fernet is not None else None,
            exchange_client_for=lambda k, sec: build_candidate_client(settings, k, sec),
            stored_exchange_client=lambda: client,
            telegram_send=lambda token, chat, text: TelegramChannel(token, chat).send(text),
        )
    )


def serve_in_thread(app: FastAPI, host: str, port: int) -> threading.Thread:
    import uvicorn

    config = uvicorn.Config(app, host=host, port=port, log_level="info", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="trader-api", daemon=True)
    thread.start()
    return thread


def stop_requested(flag: threading.Event) -> Callable[[], bool]:
    return flag.is_set

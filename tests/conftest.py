"""Shared pytest fixtures.

Tests run against SQLite in-memory rather than PostgreSQL so the suite stays
fast and hermetic. The portable column types in ``aidss.db.base`` exist
precisely so a single set of model definitions works on both.
"""

from __future__ import annotations

import os
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

# Read no dotenv file. Set before anything imports `aidss.config`, because the
# file is resolved at class-definition time.
#
# Without this the suite reads whatever `.env` happens to be in the working
# directory, so its result depends on the developer's local configuration - a
# machine with `AIDSS_AI_EMBEDDING_MODEL=` set produced one failure that a
# machine without it did not. A hermetic suite that quietly reads an untracked
# file is not hermetic; it just looks that way until two people compare notes.
os.environ["AIDSS_ENV_FILE"] = ""

os.environ.setdefault("AIDSS_ENVIRONMENT", "testing")
os.environ.setdefault("AIDSS_DATABASE_URL", "sqlite+pysqlite:///:memory:")
# At least 32 bytes: shorter HMAC keys are accepted but warned about, and the
# warning would drown out anything useful in the test output.
os.environ.setdefault(
    "AIDSS_JWT_SECRET", "test-secret-not-for-production-0123456789abcdef"
)
os.environ.setdefault("AIDSS_MARKET_DATA_PROVIDER", "fixture")
os.environ.setdefault("AIDSS_NEWS_PROVIDER", "fixture")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import aidss.plugins  # noqa: E402, F401  (side effect: register adapters)
from aidss.config import get_settings  # noqa: E402
from aidss.db.base import Base, configure_engine, get_sessionmaker  # noqa: E402
from aidss.db.models import User, UserRole  # noqa: E402
from aidss.domain.types import Candle  # noqa: E402
from aidss.main import create_app  # noqa: E402
from aidss.security.passwords import hash_password  # noqa: E402


@pytest.fixture(autouse=True)
def _database():
    """Fresh schema per test - no state leaks between cases."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        # A single shared connection, otherwise each session would get its own
        # empty in-memory database.
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    configure_engine(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def session() -> Session:
    db = get_sessionmaker()()
    try:
        yield db
        db.commit()
    finally:
        db.close()


@pytest.fixture
def session_factory():
    """The sessionmaker itself, for code that opens a session of its own.

    Quota reservations do exactly that on purpose: they must commit
    independently of the caller's transaction, because the outbound call they
    authorise cannot be rolled back. Testing that needs two sessions over one
    database, which the shared in-memory connection already provides.
    """
    return get_sessionmaker()


@pytest.fixture
def settings():
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def investor_token(client: TestClient) -> str:
    client.post(
        "/auth/register",
        json={"email": "investor@example.com", "password": "correct-horse-battery"},
    )
    response = client.post(
        "/auth/login",
        json={"email": "investor@example.com", "password": "correct-horse-battery"},
    )
    return response.json()["access_token"]


@pytest.fixture
def auth_headers(investor_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {investor_token}"}


@pytest.fixture
def admin_headers(client: TestClient) -> dict[str, str]:
    # Uses its own short-lived session and closes it before the HTTP call:
    # the in-memory database is a single shared connection, so leaving an open
    # transaction around would interleave with the request's own session.
    db = get_sessionmaker()()
    try:
        db.add(
            User(
                email="admin@example.com",
                password_hash=hash_password("correct-horse-battery"),
                role=UserRole.ADMIN,
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "correct-horse-battery"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# --- Price series helpers --------------------------------------------------


def make_candles(
    count: int = 300,
    *,
    seed: int = 42,
    start_price: float = 1000.0,
    start: datetime | None = None,
) -> list[Candle]:
    """Deterministic OHLCV series for indicator tests.

    Seeded rather than random so a failure is always reproducible.
    """
    rng = random.Random(seed)
    start = start or datetime(2024, 1, 1, tzinfo=UTC)
    price = start_price
    candles: list[Candle] = []
    for i in range(count):
        change = rng.uniform(-0.02, 0.021)
        close = price * (1 + change)
        open_ = price
        high = max(open_, close) * (1 + rng.uniform(0, 0.01))
        low = min(open_, close) * (1 - rng.uniform(0, 0.01))
        candles.append(
            Candle(
                timestamp=start + timedelta(days=i),
                open=Decimal(str(round(open_, 4))),
                high=Decimal(str(round(high, 4))),
                low=Decimal(str(round(low, 4))),
                close=Decimal(str(round(close, 4))),
                volume=Decimal(str(rng.randint(1000, 100000))),
            )
        )
        price = close
    return candles


@pytest.fixture
def candles() -> list[Candle]:
    return make_candles()

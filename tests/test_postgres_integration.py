"""Behaviour PostgreSQL has and SQLite does not.

The hermetic suite runs on SQLite: fast, no setup, no shared state. That buys a
great deal, and it costs one specific thing - every place the two dialects
disagree is a place a test can pass while production fails.

That is not hypothetical here. The embedding columns are declared
``vector(1536)``; PostgreSQL enforces the width and SQLite stores JSON and
accepts anything. Twenty-five RAG tests passed green while every production
insert failed, and only a smoke test against a real database found it.

This file exists to cover that class rather than that instance. Each test
targets a specific divergence: type enforcement, storage format, transaction
semantics, and the concurrency primitives that have no SQLite equivalent at
all. Opt-in, because requiring a database to run `pytest` would push people
toward not running it.

    docker compose up -d postgres
    pytest -m postgres
"""

from __future__ import annotations

import os
import threading
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError, OperationalError, StatementError
from sqlalchemy.orm import sessionmaker

from aidss.db.base import Base
from aidss.db.models import (
    Asset,
    HistoricalPrice,
    JobQueueEntry,
    JobStatus,
    KnowledgeBaseDocument,
    KnowledgeChunk,
    LeaderLease,
    User,
    UserRole,
)
from aidss.domain.types import Timeframe
from aidss.jobs import queue
from aidss.jobs.leader import LeaseHolder
from aidss.security.passwords import hash_password

pytestmark = pytest.mark.postgres

DEFAULT_URL = "postgresql+psycopg://aidss:aidss@localhost:5432/aidss"

#: A schema of its own, created and dropped per run, so these tests cannot
#: touch data someone was looking at.
#:
#: The isolation is asserted below rather than assumed, and that is not
#: defensive habit - the first version of this file got it wrong. It placed
#: tables by putting the test schema first on ``search_path``, which fails in
#: a way that looks like success: ``create_all`` defaults to
#: ``checkfirst=True``, found the development tables through ``public`` on the
#: same path, skipped creating anything, and every test then read and wrote the
#: real tables. Teardown dropped them. Nothing failed; the tests passed.
#:
#: So placement now uses ``schema_translate_map``, which qualifies each
#: statement explicitly instead of leaving it to name resolution, and the
#: fixture verifies where the tables actually landed before any test runs.
TEST_SCHEMA = "aidss_integration_test"


def database_url() -> str:
    return os.environ.get("AIDSS_TEST_DATABASE_URL", DEFAULT_URL)


@pytest.fixture(scope="module")
def engine():
    """A connection to a real PostgreSQL, or a skip explaining why not."""
    url = database_url()
    try:
        engine = create_engine(url, poolclass=None)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            # An isolated schema rather than the public one: these tests create
            # and drop tables, and doing that in a database someone is using is
            # how a test suite destroys an afternoon's work. It did, once -
            # see the note on TEST_SCHEMA.
            connection.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
            connection.execute(text(f"CREATE SCHEMA {TEST_SCHEMA}"))
            connection.commit()
    except (OperationalError, DBAPIError) as exc:
        pytest.skip(
            f"No PostgreSQL at {url} ({type(exc).__name__}). "
            "Start one with `docker compose up -d postgres`, or set "
            "AIDSS_TEST_DATABASE_URL."
        )

    # Two separate mechanisms, doing two different jobs.
    #
    # `schema_translate_map` decides where our tables go: every unqualified
    # table reference is rewritten to the test schema, so placement is stated
    # in each statement rather than inferred from name resolution.
    #
    # `search_path` still needs `public`, but only so the `vector` *type* that
    # pgvector installs there can be found. It no longer places anything.
    engine = create_engine(
        url, connect_args={"options": "-csearch_path=public"}
    ).execution_options(schema_translate_map={None: TEST_SCHEMA})

    Base.metadata.create_all(engine)
    _assert_isolated(engine)
    yield engine

    # Dropping the schema is the only teardown. `Base.metadata.drop_all` is
    # deliberately not used: it emits unqualified DROPs, which is exactly the
    # ambiguity that cost a development database once already.
    engine.dispose()
    with create_engine(url).connect() as connection:
        connection.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
        connection.commit()


def _assert_isolated(engine) -> None:
    """Fail loudly if the tables did not land in the test schema.

    Without this the suite has no way to tell isolation from its absence -
    operating on the development tables passes every assertion in this file,
    right up until teardown removes them.
    """
    expected = {table.name for table in Base.metadata.sorted_tables}
    with create_engine(engine.url).connect() as connection:
        placed = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :schema"
                ),
                {"schema": TEST_SCHEMA},
            )
        }
    missing = expected - placed
    assert not missing, (
        f"{len(missing)} tables are not in {TEST_SCHEMA} (e.g. {sorted(missing)[:3]}). "
        "The suite would be operating on whatever schema they did resolve to - "
        "refusing to run rather than risk another database."
    )


@pytest.fixture
def sessions(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def pg(sessions):
    """A session that rolls back, so tests do not see each other's rows."""
    session = sessions()
    try:
        yield session
    finally:
        session.rollback()
        # Rollback alone leaves committed rows behind, and several of these
        # tests must commit to be meaningful.
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
        session.close()


# --- Type enforcement: the class of bug that motivated this file -----------


def test_a_wrong_width_embedding_is_rejected_by_the_database(pg) -> None:
    """The bug this file exists for.

    SQLite stores the vector as JSON and accepts any length. PostgreSQL
    declares `vector(1536)` and rejects a mismatch, so a suite that only ran on
    SQLite would pass while every production insert failed.
    """
    document = KnowledgeBaseDocument(title="probe")
    pg.add(document)
    pg.flush()

    pg.add(
        KnowledgeChunk(
            knowledge_base_id=document.id,
            chunk_index=0,
            chunk_text="text",
            embedding=[0.1] * 8,
        )
    )
    with pytest.raises((StatementError, DBAPIError)):
        pg.flush()


def test_a_correct_width_embedding_round_trips(pg) -> None:
    from aidss.config import get_settings

    width = get_settings().embedding_dimensions
    document = KnowledgeBaseDocument(title="probe")
    pg.add(document)
    pg.flush()

    vector = [i / width for i in range(width)]
    pg.add(
        KnowledgeChunk(
            knowledge_base_id=document.id, chunk_index=0, chunk_text="t", embedding=vector
        )
    )
    pg.commit()

    stored = pg.scalar(select(KnowledgeChunk))
    assert len(list(stored.embedding)) == width
    assert float(list(stored.embedding)[1]) == pytest.approx(1 / width, abs=1e-6)


# --- Storage format --------------------------------------------------------


def test_enum_columns_store_values_not_member_names(pg) -> None:
    """Checked against the raw column, which is the only thing that proves it.

    Reading it back through the ORM would map either form to the same enum and
    tell you nothing.
    """
    pg.add(
        User(
            email="pg-enum@example.com",
            password_hash=hash_password("correct-horse-battery"),
            role=UserRole.ADMIN,
        )
    )
    pg.commit()

    # Schema-qualified explicitly. `schema_translate_map` rewrites ORM
    # statements, not raw SQL - an unqualified name here would resolve through
    # `search_path` to whatever else happens to be called `users`, which is how
    # this test used to read the development table and pass either way.
    raw = pg.execute(text(f"SELECT role FROM {TEST_SCHEMA}.users LIMIT 1")).scalar_one()
    assert raw == "admin", f"stored {raw!r}; a dashboard filtering on 'admin' would miss it"


def test_jsonb_survives_a_round_trip(pg) -> None:
    """The column is JSON on SQLite and JSONB on PostgreSQL - different code paths."""
    payload = {
        "nested": {"list": [1, 2.5, "three"], "null": None},
        "unicode": "laporan keuangan – ringkasan",
    }
    pg.add(JobQueueEntry(job_type="probe", payload=payload))
    pg.commit()

    assert pg.scalar(select(JobQueueEntry)).payload == payload


def test_decimal_precision_survives_storage(pg) -> None:
    """Prices are Numeric(24, 8); a float round trip here would lose money."""
    asset = Asset(ticker="PREC", exchange="IDX")
    pg.add(asset)
    pg.flush()

    exact = Decimal("12345.12345678")
    pg.add(
        HistoricalPrice(
            asset_id=asset.id,
            timeframe=Timeframe.D1.value,
            timestamp=datetime(2025, 1, 1, tzinfo=UTC),
            open=exact,
            high=exact,
            low=exact,
            close=exact,
            volume=Decimal("1000"),
            source="test",
        )
    )
    pg.commit()

    stored = pg.scalar(select(HistoricalPrice))
    assert stored.close == exact
    assert isinstance(stored.close, Decimal)


def test_timestamps_come_back_as_utc(pg) -> None:
    """SQLite returns naive datetimes; the custom type has to fix both dialects."""
    jakarta = datetime(2025, 6, 2, 16, 0, tzinfo=UTC).astimezone()
    asset = Asset(ticker="TZ", exchange="IDX")
    pg.add(asset)
    pg.flush()

    pg.add(
        HistoricalPrice(
            asset_id=asset.id,
            timeframe=Timeframe.D1.value,
            timestamp=jakarta,
            open=Decimal("1"),
            high=Decimal("1"),
            low=Decimal("1"),
            close=Decimal("1"),
            volume=Decimal("1"),
            source="test",
        )
    )
    pg.commit()

    stored = pg.scalar(select(HistoricalPrice))
    assert stored.timestamp.tzinfo is not None
    assert stored.timestamp.utcoffset() == timedelta(0)
    assert stored.timestamp == jakarta


def test_constraints_are_actually_enforced(pg) -> None:
    """The confidence range check exists in the metadata; this proves it exists
    in the database too."""
    from aidss.db.models import AnalysisResult, Recommendation
    from aidss.domain.types import InvestmentHorizon, RecommendationLabel

    asset = Asset(ticker="CONS", exchange="IDX")
    pg.add(asset)
    pg.flush()
    result = AnalysisResult(asset_id=asset.id, analysis_type="probe")
    pg.add(result)
    pg.flush()

    pg.add(
        Recommendation(
            analysis_result_id=result.id,
            label=RecommendationLabel.HOLD,
            confidence=150.0,  # outside 0-100
            reasoning="x",
            bullish_scenario="x",
            bearish_scenario="x",
            horizon=InvestmentHorizon.MEDIUM,
        )
    )
    with pytest.raises(DBAPIError):
        pg.flush()


# --- Concurrency: no SQLite equivalent at all ------------------------------


def test_skip_locked_gives_each_job_to_exactly_one_worker(sessions, pg) -> None:
    """The claim that could not be tested before.

    SQLite has no SKIP LOCKED, so the hermetic suite exercises the optimistic
    fallback with one worker. This is the real thing: many threads, one queue,
    and every job claimed exactly once.
    """
    job_count = 40
    for i in range(job_count):
        queue.enqueue(pg, "probe.concurrent", {"n": i})
    pg.commit()

    claimed: list[tuple[str, uuid.UUID]] = []
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def worker(name: str) -> None:
        session = sessions()
        try:
            # Start together, so the threads actually contend rather than
            # politely taking turns.
            barrier.wait(timeout=10)
            # Two consecutive empty claims before giving up. A single empty
            # result can mean "another worker holds the last few rows right
            # now", and exiting on it would let one fast thread finish the
            # queue alone - which would pass this test without ever contending.
            misses = 0
            while misses < 2:
                entry = queue.claim(session, worker=name)
                if entry is None:
                    session.commit()
                    misses += 1
                    continue
                misses = 0
                job_id = entry.id
                session.commit()
                with lock:
                    claimed.append((name, job_id))
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    job_ids = [job_id for _, job_id in claimed]
    assert len(job_ids) == job_count, "some jobs were never claimed"
    assert len(set(job_ids)) == job_count, "a job was claimed by more than one worker"

    # Without this the test could pass with one thread doing everything, which
    # would prove nothing about concurrency at all.
    participants = {name for name, _ in claimed}
    assert len(participants) > 1, (
        f"only {participants} claimed anything - the threads never contended, "
        "so this run says nothing about SKIP LOCKED"
    )

    pg.expire_all()
    running = pg.scalars(
        select(JobQueueEntry).where(JobQueueEntry.status == JobStatus.RUNNING)
    ).all()
    assert len(running) == job_count


def test_only_one_scheduler_wins_a_genuine_race(sessions, pg) -> None:
    """Leader election under real contention, not sequential calls."""
    winners: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(10)
    now = datetime.now(UTC)

    def contend(name: str) -> None:
        session = sessions()
        try:
            barrier.wait(timeout=10)
            if LeaseHolder(holder=name, ttl_seconds=300).acquire(session, now=now):
                session.commit()
                with lock:
                    winners.append(name)
            else:
                session.rollback()
        except Exception:
            session.rollback()
        finally:
            session.close()

    threads = [threading.Thread(target=contend, args=(f"s{i}",)) for i in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(winners) == 1, f"{len(winners)} schedulers believed they were leader"
    pg.expire_all()
    assert pg.scalar(select(LeaderLease)).holder == winners[0]


def test_the_dedup_key_holds_under_concurrent_enqueue(sessions, pg) -> None:
    """Two schedulers enqueueing the same due schedule must produce one job."""
    barrier = threading.Barrier(6)
    results: list[bool] = []
    lock = threading.Lock()

    def enqueue_same() -> None:
        session = sessions()
        try:
            barrier.wait(timeout=10)
            outcome = queue.enqueue(session, "probe.dedup", dedup_key="shared-key")
            session.commit()
            with lock:
                results.append(outcome.created)
        except Exception:
            session.rollback()
            with lock:
                results.append(False)
        finally:
            session.close()

    threads = [threading.Thread(target=enqueue_same) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    pg.expire_all()
    rows = pg.scalars(
        select(JobQueueEntry).where(JobQueueEntry.job_type == "probe.dedup")
    ).all()
    assert len(rows) == 1, "the unique index did not hold under contention"
    assert sum(results) == 1, "more than one caller believed it created the job"


def test_a_unique_constraint_stops_a_duplicate_bar(pg) -> None:
    """Idempotent ingestion depends on this being enforced, not just intended."""
    asset = Asset(ticker="UNIQ", exchange="IDX")
    pg.add(asset)
    pg.flush()

    def bar() -> HistoricalPrice:
        return HistoricalPrice(
            asset_id=asset.id,
            timeframe=Timeframe.D1.value,
            timestamp=datetime(2025, 1, 1, tzinfo=UTC),
            open=Decimal("1"),
            high=Decimal("1"),
            low=Decimal("1"),
            close=Decimal("1"),
            volume=Decimal("1"),
            source="test",
        )

    pg.add(bar())
    pg.commit()

    pg.add(bar())
    with pytest.raises(DBAPIError):
        pg.commit()

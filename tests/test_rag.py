"""Chunking and RAG retrieval (Phase 7, Section 12, 9)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from aidss.db.models import Asset, KnowledgeBaseDocument, NewsItem
from aidss.plugins.adapters.ai_fixture import FixtureAIProvider
from aidss.rag.chunking import (
    DEFAULT_CHUNK_SIZE,
    MIN_CHUNK_SIZE,
    chunk_article,
    chunk_text,
)
from aidss.rag.engine import RAGEngine, cosine_similarity

# --- Chunking --------------------------------------------------------------


def test_empty_text_produces_no_chunks() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_short_text_stays_one_chunk() -> None:
    chunks = chunk_text("A short definition of the price-to-earnings ratio.")
    assert len(chunks) == 1


def test_long_text_is_split() -> None:
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(10))
    chunks = chunk_text(text, chunk_size=500, overlap=0)
    assert len(chunks) > 1
    assert all(c.text.strip() for c in chunks)


def test_splitting_prefers_paragraph_boundaries() -> None:
    """A chunk that ends mid-sentence retrieves as a fragment."""
    text = "\n\n".join(["First paragraph." * 20, "Second paragraph." * 20])
    chunks = chunk_text(text, chunk_size=400, overlap=0)
    assert len(chunks) >= 2
    # No chunk should begin with a lower-case continuation of a cut sentence.
    assert all(c.text[0].isupper() for c in chunks)


def test_an_oversized_paragraph_is_split_on_sentences() -> None:
    paragraph = " ".join(f"Sentence number {i} carries some content." for i in range(60))
    chunks = chunk_text(paragraph, chunk_size=300, overlap=0)
    assert len(chunks) > 1
    assert all(c.text.rstrip().endswith(".") for c in chunks)


def test_overlap_carries_context_across_the_seam() -> None:
    """A definition spanning a boundary must be findable from at least one side."""
    text = "\n\n".join(f"Block {i}. " + "content " * 40 for i in range(4))
    without = chunk_text(text, chunk_size=400, overlap=0)
    with_overlap = chunk_text(text, chunk_size=400, overlap=100)

    assert len(with_overlap) == len(without)
    assert len(with_overlap[1].text) > len(without[1].text)


def test_invalid_chunk_parameters_are_rejected() -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        chunk_text("text", chunk_size=0)
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("text", chunk_size=100, overlap=100)


def test_chunk_indexes_are_contiguous() -> None:
    text = "\n\n".join(f"Block {i}. " + "content " * 40 for i in range(6))
    chunks = chunk_text(text, chunk_size=400)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_every_article_chunk_carries_the_headline() -> None:
    """A body chunk without it retrieves as text about an unnamed company."""
    body = " ".join(f"Detail {i} about the quarter." for i in range(200))
    chunks = chunk_article("BBCA posts quarterly results", body, chunk_size=400)
    assert len(chunks) > 1
    assert all(c.text.startswith("BBCA posts quarterly results") for c in chunks)


def test_an_article_without_a_body_still_yields_its_headline() -> None:
    chunks = chunk_article("BBCA posts quarterly results", None)
    assert len(chunks) == 1
    assert "BBCA" in chunks[0].text


def test_chunk_size_default_is_sane() -> None:
    assert MIN_CHUNK_SIZE < DEFAULT_CHUNK_SIZE


# --- Similarity ------------------------------------------------------------


def test_identical_vectors_score_one() -> None:
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_orthogonal_vectors_score_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_a_zero_vector_scores_zero_rather_than_dividing() -> None:
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_mismatched_lengths_score_zero() -> None:
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0


# --- Indexing and retrieval ------------------------------------------------


@pytest.fixture
def engine(session) -> RAGEngine:
    return RAGEngine(session, FixtureAIProvider(), embedding_model="fixture-embed")


def add_document(session, engine: RAGEngine, title: str, content: str) -> KnowledgeBaseDocument:
    document = KnowledgeBaseDocument(title=title, category="education")
    session.add(document)
    session.flush()
    engine.index_document(document, content)
    return document


def test_indexing_creates_retrievable_chunks(session, engine: RAGEngine) -> None:
    add_document(
        session,
        engine,
        "RSI explained",
        "The relative strength index measures the speed of price changes. "
        "It ranges from zero to one hundred.",
    )
    results = engine.search_knowledge("relative strength index")
    assert results
    assert results[0].source == "knowledge_base"
    assert "relative strength" in results[0].text.lower()


def test_reindexing_replaces_rather_than_appends(session, engine: RAGEngine) -> None:
    """A corrected document must not leave its old text retrievable."""
    document = add_document(session, engine, "Note", "The original wording of this note.")
    engine.index_document(document, "The corrected wording of this note.")

    texts = " ".join(r.text for r in engine.search_knowledge("wording", limit=10))
    assert "corrected" in texts
    assert "original" not in texts


def test_results_are_ordered_by_similarity(session, engine: RAGEngine) -> None:
    add_document(session, engine, "A", "Dividend yield measures income relative to price.")
    add_document(session, engine, "B", "Moving averages smooth price over a window.")

    results = engine.search_knowledge("dividend yield income", limit=2)
    assert len(results) == 2
    assert results[0].score >= results[1].score


def test_searching_an_empty_knowledge_base_returns_nothing(engine: RAGEngine) -> None:
    assert engine.search_knowledge("anything") == []


def test_chunks_from_another_embedding_model_are_skipped(session) -> None:
    """Comparing two embedding spaces is arithmetic without meaning."""
    old = RAGEngine(session, FixtureAIProvider(), embedding_model="old-model")
    add_document(session, old, "Legacy", "Content embedded by a previous model.")

    current = RAGEngine(session, FixtureAIProvider(), embedding_model="new-model")
    assert current.search_knowledge("content") == []


# --- News indexing ---------------------------------------------------------


@pytest.fixture
def asset(session) -> Asset:
    row = Asset(ticker="BBCA", exchange="IDX")
    session.add(row)
    session.flush()
    return row


def add_news(session, asset: Asset, headline: str, summary: str, days_ago: int = 1) -> NewsItem:
    item = NewsItem(
        asset_id=asset.id,
        source="test",
        source_url=f"https://example.invalid/{headline[:20]}",
        dedup_hash=headline,
        headline=headline,
        body_summary=summary,
        published_at=datetime.now(UTC) - timedelta(days=days_ago),
    )
    session.add(item)
    session.flush()
    return item


def test_news_indexing_marks_items_as_indexed(session, engine: RAGEngine, asset) -> None:
    item = add_news(session, asset, "BBCA reports growth", "Net profit rose in the quarter.")
    report = engine.index_news([item])

    assert report.chunks_created > 0
    assert item.is_indexed is True


def test_already_indexed_items_are_not_embedded_again(session, engine: RAGEngine, asset) -> None:
    """Section 12.3: a retry must not pay for the same vectors twice."""
    item = add_news(session, asset, "BBCA reports growth", "Net profit rose in the quarter.")
    engine.index_news([item])

    second = engine.index_news([item])
    assert second.chunks_created == 0
    assert second.chunks_skipped == 1
    assert second.embed_calls == 0


def test_news_search_is_scoped_to_the_asset(session, engine: RAGEngine, asset) -> None:
    """The most similar article about another company is still another company."""
    other = Asset(ticker="TLKM", exchange="IDX")
    session.add(other)
    session.flush()

    add_news(session, asset, "BBCA earnings beat", "Profit rose sharply.")
    other_item = add_news(session, other, "TLKM earnings beat", "Profit rose sharply.")
    engine.index_news(
        session.scalars(select(NewsItem)).all()
    )

    results = engine.search_news("earnings", asset_id=asset.id, limit=10)
    assert results
    assert all(r.metadata["asset_id"] == str(asset.id) for r in results)
    assert str(other_item.asset_id) not in {r.metadata["asset_id"] for r in results}


def test_news_search_excludes_articles_outside_the_window(
    session, engine: RAGEngine, asset
) -> None:
    """Last year's headline is history, not sentiment."""
    add_news(session, asset, "Ancient news", "Something happened long ago.", days_ago=200)
    engine.index_news(session.scalars(select(NewsItem)).all())

    assert engine.search_news("something", asset_id=asset.id, window_days=30) == []
    assert engine.search_news("something", asset_id=asset.id, window_days=365)


def test_indexing_an_empty_list_is_a_no_op(engine: RAGEngine) -> None:
    report = engine.index_news([])
    assert report.chunks_created == 0
    assert report.embed_calls == 0


# --- Vector width ----------------------------------------------------------


def test_the_fixture_produces_vectors_at_the_configured_width() -> None:
    """A fixture whose shape differs from production tests the wrong thing."""
    from aidss.config import get_settings

    vectors = FixtureAIProvider().embed(["some text"])
    assert len(vectors[0]) == get_settings().embedding_dimensions


def test_the_fixture_is_deterministic() -> None:
    assert FixtureAIProvider().embed(["x"]) == FixtureAIProvider().embed(["x"])


def test_extension_does_not_repeat_the_same_block() -> None:
    """A repeated block would make every vector's halves identical."""
    from aidss.plugins.adapters.ai_fixture import _pseudo_vector

    vector = _pseudo_vector("text", 64)
    assert vector[:32] != vector[32:]


def test_a_wrong_width_vector_is_rejected_on_every_dialect(session, asset) -> None:
    """PostgreSQL enforces the width and SQLite does not.

    Without this check the suite would pass on SQLite while production rejected
    every insert - which is exactly what happened before the check existed.
    """
    from sqlalchemy.exc import StatementError

    engine = RAGEngine(session, FixtureAIProvider(dimensions=8))
    item = add_news(session, asset, "BBCA reports growth", "Net profit rose.")

    # SQLAlchemy wraps the type's ValueError, so the wrapper is what surfaces;
    # the message is what matters.
    with pytest.raises(StatementError, match="8 dimensions but the column expects"):
        engine.index_news([item])

    # The failed flush leaves the session unusable; roll back so teardown can
    # close it cleanly rather than raising a second, unrelated error.
    session.rollback()

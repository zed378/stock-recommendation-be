"""RAG Engine (Phase 7, Sections 6.3, 9).

Indexes knowledge base documents and news articles, and retrieves relevant
context for the agents.

Retrieval is **hybrid**: BM25 over the text and cosine similarity over the
embeddings, fused by reciprocal rank. Vector search alone handles paraphrase
well and exact tokens badly, and this domain is full of exact tokens - a
ticker, a metric name, a ratio. A query about BBCA that returns passages about
BBRI is semantically close and practically useless, and that is precisely the
mistake the lexical half does not make.

Three further design points:

  * **Vectors are stored with their model.** An embedding produced by one model
    is meaningless to another, so the model name is recorded per chunk and
    retrieval filters on it. Mixing two embedding spaces in one index produces
    results that look plausible and are noise.
  * **News retrieval is filtered before it is ranked.** A ticker filter and a
    recency window are applied first, because the most semantically similar
    article about a different company is still about a different company.
  * **Retrieval degrades rather than stops.** With no usable embeddings the
    lexical ranker still returns an ordering, so an embedding outage costs
    quality instead of the whole feature.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.db.models import (
    KnowledgeBaseDocument,
    KnowledgeChunk,
    NewsEmbedding,
    NewsItem,
)
from aidss.plugins.interfaces import AIProvider
from aidss.rag.chunking import chunk_article, chunk_text
from aidss.rag.fusion import reciprocal_rank_fusion
from aidss.rag.lexical import BM25Index

logger = logging.getLogger("aidss.rag")

#: How many chunks are embedded per provider call. Batching matters: one call
#: per chunk turns a 200-chunk document into 200 round trips.
EMBED_BATCH_SIZE = 32

#: Default recency window for news retrieval.
NEWS_WINDOW_DAYS = 30


@dataclass(slots=True)
class RetrievedChunk:
    text: str
    #: The fused score. Not a similarity - RRF scores are small and only
    #: meaningful relative to each other within one query.
    score: float
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Where each ranker placed this chunk, 1-based. A chunk the vector ranker
    #: loved but the lexical one never saw looks very different from one both
    #: agreed on, and that difference is what makes a wrong result debuggable.
    ranks: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "score": round(self.score, 6),
            "source": self.source,
            "metadata": self.metadata,
            "ranks": self.ranks,
        }


@dataclass(slots=True)
class IndexReport:
    documents: int = 0
    chunks_created: int = 0
    chunks_skipped: int = 0
    embed_calls: int = 0
    #: Set when the provider could not embed and the text was stored without a
    #: vector. Reported rather than raised, because the alternative is losing
    #: the text - but never silent, or a lexical-only index would look like a
    #: healthy one until somebody asked a paraphrase question.
    embeddings_unavailable: bool = False
    embed_error: str | None = None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity, returning 0 for a zero vector rather than dividing by it."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class RAGEngine:
    def __init__(
        self,
        session: Session,
        provider: AIProvider,
        *,
        embedding_model: str | None = "default",
    ):
        self._session = session
        self._provider = provider
        #: Recorded on every chunk so retrieval never compares vectors from
        #: two different embedding spaces.
        #:
        #: Empty or None means this deployment has no embedding model, and the
        #: engine runs lexical-only: no embedding call is attempted at all.
        #: That is a supported configuration rather than a degraded one - many
        #: self-hosted gateways serve chat and nothing else - and saying so up
        #: front beats a 404 per batch to learn the same thing.
        self._model = embedding_model or ""

    @property
    def embeddings_enabled(self) -> bool:
        return bool(self._model)

    # --- embedding -------------------------------------------------------

    def _embed(
        self, texts: list[str], report: IndexReport | None = None
    ) -> list[list[float] | None]:
        """Embed, or return Nones when the provider cannot.

        An embedding outage costs quality, not the feature. That was already
        true on the read side - a chunk with no vector is retrieved lexically -
        but the write side used to let the failure through, and the effect was
        far worse than degraded search: an ingestion job died, and the articles
        it was holding were lost with it.

        Not every deployment even has an embedding model. A gateway serving
        chat-only models answers `/embeddings` with 404 on every call, which is
        a permanent condition rather than an outage, and one the platform has
        to keep working under: BM25 does not need vectors.
        """
        if not self.embeddings_enabled:
            if report is not None:
                report.embeddings_unavailable = True
                report.embed_error = "no embedding model configured"
            return [None] * len(texts)

        vectors: list[list[float] | None] = []
        for start in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = texts[start : start + EMBED_BATCH_SIZE]
            try:
                vectors.extend(self._provider.embed(batch))
            except Exception as exc:  # noqa: BLE001 - any provider failure degrades the same way
                logger.warning(
                    "embedding unavailable; storing text without vectors",
                    extra={"error": f"{type(exc).__name__}: {exc}", "chunks": len(batch)},
                )
                vectors.extend([None] * len(batch))
                if report is not None:
                    report.embeddings_unavailable = True
                    report.embed_error = f"{type(exc).__name__}: {exc}"
                continue
            if report is not None:
                report.embed_calls += 1
        return vectors

    def _embed_query(self, query: str) -> list[float] | None:
        """The query side of the same problem.

        Retrieval already tolerates chunks with no vector. It did not tolerate
        failing to embed the *query*, so one 404 took out a search that BM25
        could have answered on its own.
        """
        if not self.embeddings_enabled:
            return None
        try:
            return self._provider.embed([query])[0]
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "embedding unavailable; falling back to lexical retrieval",
                extra={"error": f"{type(exc).__name__}: {exc}"},
            )
            return None

    # --- indexing --------------------------------------------------------

    def index_document(self, document: KnowledgeBaseDocument, text: str) -> IndexReport:
        """Chunk, embed, and store one knowledge base document.

        Re-indexing replaces the document's chunks rather than appending, so a
        corrected document does not leave its old text retrievable alongside
        the new.
        """
        report = IndexReport(documents=1)

        existing = self._session.scalars(
            select(KnowledgeChunk).where(KnowledgeChunk.knowledge_base_id == document.id)
        ).all()
        for row in existing:
            self._session.delete(row)
        self._session.flush()

        chunks = chunk_text(text)
        if not chunks:
            return report

        vectors = self._embed([c.text for c in chunks], report)
        for chunk, vector in zip(chunks, vectors, strict=True):
            self._session.add(
                KnowledgeChunk(
                    knowledge_base_id=document.id,
                    chunk_index=chunk.index,
                    chunk_text=chunk.text,
                    embedding=vector,
                    meta={
                        "title": document.title,
                        "category": document.category,
                        "embedding_model": self._model,
                    },
                )
            )
            report.chunks_created += 1

        self._session.flush()
        return report

    def index_news(self, items: list[NewsItem]) -> IndexReport:
        """Embed news articles that have not been indexed yet.

        Skipping already-indexed items is what stops a retried ingestion job
        from paying for the same embeddings twice (Section 6.3.3).
        """
        report = IndexReport()

        pending = [item for item in items if not item.is_indexed]
        report.chunks_skipped = len(items) - len(pending)
        if not pending:
            return report

        chunk_map: list[tuple[NewsItem, Any]] = []
        for item in pending:
            for chunk in chunk_article(item.headline, item.body_summary):
                chunk_map.append((item, chunk))

        if not chunk_map:
            for item in pending:
                item.is_indexed = True
            self._session.flush()
            return report

        vectors = self._embed([chunk.text for _, chunk in chunk_map], report)

        for (item, chunk), vector in zip(chunk_map, vectors, strict=True):
            self._session.add(
                NewsEmbedding(
                    news_item_id=item.id,
                    chunk_index=chunk.index,
                    chunk_text=chunk.text,
                    embedding=vector,
                    meta={
                        "asset_id": str(item.asset_id) if item.asset_id else None,
                        "published_at": item.published_at.isoformat(),
                        "source": item.source,
                        "embedding_model": self._model,
                    },
                )
            )
            report.chunks_created += 1

        for item in pending:
            item.is_indexed = True
        report.documents = len(pending)
        self._session.flush()
        return report

    # --- retrieval -------------------------------------------------------

    def search_knowledge(self, query: str, *, limit: int = 5) -> list[RetrievedChunk]:
        rows = self._session.scalars(select(KnowledgeChunk)).all()
        if not rows:
            return []
        return self._rank(
            [(r.chunk_text, r.embedding, r.meta or {}, "knowledge_base") for r in rows],
            query,
            limit,
        )

    def search_news(
        self,
        query: str,
        *,
        asset_id: uuid.UUID | None = None,
        window_days: int = NEWS_WINDOW_DAYS,
        limit: int = 5,
        now: datetime | None = None,
    ) -> list[RetrievedChunk]:
        """Retrieve news chunks, filtered before ranking.

        The most semantically similar article about a different company is
        still about a different company, and last year's headline is history
        rather than sentiment - so ticker and recency are hard filters, not
        score adjustments.
        """
        cutoff = (now or datetime.now(UTC)) - timedelta(days=window_days)

        stmt = select(NewsEmbedding).join(NewsItem, NewsItem.id == NewsEmbedding.news_item_id)
        stmt = stmt.where(NewsItem.published_at >= cutoff)
        if asset_id is not None:
            stmt = stmt.where(NewsItem.asset_id == asset_id)

        rows = self._session.scalars(stmt).all()
        if not rows:
            return []

        return self._rank(
            [(r.chunk_text, r.embedding, r.meta or {}, "news") for r in rows],
            query,
            limit,
        )

    def _rank(
        self,
        candidates: list[tuple[str, Any, dict[str, Any], str]],
        query: str,
        limit: int,
    ) -> list[RetrievedChunk]:
        """Rank candidates by lexical and vector similarity, fused.

        Hybrid rather than vector-only because financial questions are full of
        exact tokens - a ticker, a metric name, a ratio - and an embedding maps
        those onto "roughly finance words". A query about BBCA that returns
        passages about BBRI is semantically close and practically useless.

        When embeddings are unavailable the lexical half still ranks, so
        retrieval degrades rather than stops.
        """
        usable = [
            (text, embedding, meta, source)
            for text, embedding, meta, source in candidates
            # Vectors from another embedding model are skipped rather than
            # compared: the similarity would be arithmetic without meaning.
            if meta.get("embedding_model") in (None, self._model)
        ]
        if not usable:
            return []

        texts = [text for text, _, _, _ in usable]
        rankings: dict[str, list[float]] = {
            "lexical": BM25Index.build(texts).score(query)
        }

        vectors = [embedding for _, embedding, _, _ in usable]
        if any(v is not None for v in vectors):
            query_vector = self._embed_query(query)
            # No query vector means no vector ranking at all. Ranking every
            # chunk zero instead would add a ranker that says nothing, and RRF
            # would still let it vote.
            if query_vector is not None:
                rankings["vector"] = [
                    cosine_similarity(query_vector, list(v)) if v is not None else 0.0
                    for v in vectors
                ]

        fused = reciprocal_rank_fusion(rankings, limit=limit)
        results: list[RetrievedChunk] = []
        for entry in fused:
            text, _, meta, source = usable[entry.index]
            results.append(
                RetrievedChunk(
                    text=text,
                    score=entry.score,
                    source=source,
                    metadata=meta,
                    # Kept because "vector loved it, lexical never saw it" is
                    # the most useful thing to know when a result looks wrong.
                    ranks=entry.ranks,
                )
            )
        return results

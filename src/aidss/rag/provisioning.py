"""One place that builds a configured RAG engine.

Three call sites used to construct ``RAGEngine`` directly and each got the
constructor default, which meant the configured embedding model reached none of
them. That was survivable while every deployment had embeddings; it stopped
being survivable once "no embedding model at all" became a configuration the
platform supports, because two of the three would have carried on trying.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from aidss.config import Settings, get_settings
from aidss.plugins.interfaces import AIProvider
from aidss.plugins.registry import get_ai_provider
from aidss.rag.engine import RAGEngine


def build_rag(
    session: Session,
    *,
    provider: AIProvider | None = None,
    settings: Settings | None = None,
) -> RAGEngine:
    """A RAG engine wired to the configured embedding model, if there is one.

    An empty ``AIDSS_AI_EMBEDDING_MODEL`` puts the engine in lexical-only mode:
    text is still chunked, stored, and retrieved by BM25, and no embedding call
    is attempted. Exact-token retrieval - a ticker, a metric name, a ratio - is
    unaffected, which is most of what this domain asks of it.
    """
    settings = settings or get_settings()
    return RAGEngine(
        session,
        provider or get_ai_provider(settings),
        embedding_model=settings.ai_embedding_model.strip(),
    )

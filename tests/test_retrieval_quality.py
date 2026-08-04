"""Retrieval quality, measured rather than assumed.

The earlier RAG tests verified the plumbing - chunk, embed, store, filter,
rank - but not whether the *right* passage came back. They could not: the
fixture provider's embeddings are pseudo-random, so any ordering it produced
was noise, and a test asserting a particular result would have been asserting
the hash function.

The lexical half changes that. BM25 is deterministic and its answers follow
from the text, so relevance becomes checkable without a real embedding model.
That is most of why hybrid retrieval is here: it makes the domain's exact
tokens - a ticker, a metric name, a ratio - matchable, and it makes the whole
retrieval path testable.

What these tests do **not** claim: that semantic paraphrase retrieval works.
That needs a real embedding model and a judgement set, and it is still an open
gap.
"""

from __future__ import annotations

import pytest

from aidss.db.models import Asset, KnowledgeBaseDocument
from aidss.plugins.adapters.ai_fixture import FixtureAIProvider
from aidss.rag.engine import RAGEngine
from aidss.rag.fusion import reciprocal_rank_fusion
from aidss.rag.lexical import BM25Index, analyze, tokenize

# --- Tokenisation ----------------------------------------------------------


def test_financial_tokens_survive_tokenisation() -> None:
    """Splitting on the dot or slash would destroy the tokens that matter."""
    assert "bbca.jk" in tokenize("Price data for BBCA.JK today")
    assert "ev/ebitda" in tokenize("The EV/EBITDA multiple is elevated")
    assert "price-to-book" in tokenize("Its price-to-book ratio")


def test_a_compound_token_also_indexes_its_parts() -> None:
    """So "EBITDA" finds a passage that only says "EV/EBITDA"."""
    terms = analyze("The EV/EBITDA multiple")
    assert "ev/ebitda" in terms
    assert "ebitda" in terms


def test_stopwords_and_single_characters_are_dropped() -> None:
    assert tokenize("the price of a share") == ["price", "share"]
    assert tokenize("yang dan untuk harga") == ["harga"]


def test_tokenisation_is_case_insensitive() -> None:
    assert tokenize("BBCA bbca BbCa") == ["bbca", "bbca", "bbca"]


# --- BM25 ------------------------------------------------------------------


CORPUS = [
    "Dividend yield measures the annual dividend relative to the share price.",
    "The relative strength index measures the speed of recent price changes.",
    "EV/EBITDA compares enterprise value against operating earnings.",
    "BBCA is a large Indonesian bank listed on the IDX.",
    "BBRI is another large Indonesian bank listed on the IDX.",
]


def best_match(query: str, corpus: list[str] | None = None) -> str:
    corpus = corpus or CORPUS
    scores = BM25Index.build(corpus).score(query)
    return corpus[max(range(len(scores)), key=lambda i: scores[i])]


def test_the_relevant_passage_ranks_first() -> None:
    """The claim the old tests could not make."""
    assert "Dividend yield" in best_match("dividend yield")
    assert "relative strength index" in best_match("relative strength index")
    assert "EV/EBITDA" in best_match("EV/EBITDA multiple")


def test_a_ticker_query_does_not_return_a_different_ticker() -> None:
    """The exact failure vector search makes: BBRI is close to BBCA and wrong."""
    assert "BBCA" in best_match("BBCA")
    assert "BBRI" in best_match("BBRI")


def test_a_query_with_no_matching_terms_scores_zero() -> None:
    """Better than ranking something irrelevant first."""
    assert all(score == 0.0 for score in BM25Index.build(CORPUS).score("cryptocurrency mining"))


def test_a_rare_term_outweighs_a_common_one() -> None:
    """Two documents share "bank"; only one has the ticker."""
    scores = BM25Index.build(CORPUS).score("BBCA bank")
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    assert "BBCA" in CORPUS[ranked[0]]


def test_length_does_not_buy_relevance() -> None:
    """Without normalisation, padding a document would raise its score."""
    short = "Dividend yield explained."
    padded = "Dividend yield explained. " + ("Unrelated filler text. " * 50)
    scores = BM25Index.build([short, padded]).score("dividend yield")
    assert scores[0] > scores[1]


def test_repetition_saturates() -> None:
    """A term ten times over is not ten times as relevant."""
    once = BM25Index.build(["dividend yield"]).score("dividend")[0]
    many = BM25Index.build(["dividend " * 10]).score("dividend")[0]
    assert many > once
    assert many < once * 3


def test_idf_never_goes_negative() -> None:
    """The textbook formula turns negative for a term in most documents.

    A matching document would then score *worse* than a non-matching one.
    """
    corpus = ["price data"] * 10
    index = BM25Index.build(corpus)
    assert index.idf("price") > 0
    assert all(score >= 0 for score in index.score("price"))


def test_an_empty_index_and_an_empty_query_are_safe() -> None:
    assert BM25Index.build([]).score("anything") == []
    assert BM25Index.build(CORPUS).score("the and of") == [0.0] * len(CORPUS)


# --- Fusion ----------------------------------------------------------------


def test_agreement_between_rankers_wins() -> None:
    """Ranked well by both beats ranked first by one."""
    fused = reciprocal_rank_fusion(
        {
            "lexical": [0.0, 0.9, 0.8],  # ranks: doc1 first, doc2 second
            "vector": [0.9, 0.8, 0.7],  # ranks: doc0 first, doc1 second
        }
    )
    # doc1 is second in both; doc0 is first in one and absent from the other.
    assert fused[0].index == 1


def test_a_document_missing_from_one_ranker_still_competes() -> None:
    fused = reciprocal_rank_fusion({"lexical": [0.0, 0.0], "vector": [0.9, 0.1]})
    assert [r.index for r in fused] == [0, 1]


def test_zero_scores_are_dropped_not_ranked_last() -> None:
    """A zero BM25 score means the document contains none of the query terms.

    Ranking it would let it contribute purely by existing.
    """
    fused = reciprocal_rank_fusion({"lexical": [0.0, 0.5]})
    assert [r.index for r in fused] == [1]


def test_each_result_reports_where_every_ranker_placed_it() -> None:
    """"Vector loved it, lexical never saw it" is the useful diagnostic."""
    fused = reciprocal_rank_fusion({"lexical": [0.0, 0.9], "vector": [0.9, 0.1]})
    by_index = {r.index: r.ranks for r in fused}
    assert by_index[0] == {"vector": 1}
    assert by_index[1] == {"lexical": 1, "vector": 2}


def test_fusion_is_deterministic() -> None:
    """A ranking that reshuffles between identical queries cannot be debugged."""
    rankings = {"lexical": [0.5, 0.5, 0.5]}
    first = [r.index for r in reciprocal_rank_fusion(rankings)]
    second = [r.index for r in reciprocal_rank_fusion(rankings)]
    assert first == second == [0, 1, 2]


def test_weights_shift_the_balance() -> None:
    unweighted = reciprocal_rank_fusion({"lexical": [0.9, 0.1], "vector": [0.1, 0.9]})
    weighted = reciprocal_rank_fusion(
        {"lexical": [0.9, 0.1], "vector": [0.1, 0.9]}, weights={"vector": 5.0}
    )
    assert unweighted[0].index == 0
    assert weighted[0].index == 1


def test_the_limit_is_respected() -> None:
    assert len(reciprocal_rank_fusion({"lexical": [0.3, 0.2, 0.1]}, limit=2)) == 2


# --- End to end ------------------------------------------------------------


@pytest.fixture
def engine(session) -> RAGEngine:
    return RAGEngine(session, FixtureAIProvider(), embedding_model="fixture-embed")


def add_document(session, engine: RAGEngine, title: str, content: str) -> None:
    document = KnowledgeBaseDocument(title=title, category="education")
    session.add(document)
    session.flush()
    engine.index_document(document, content)


def test_the_right_document_is_retrieved_first(session, engine: RAGEngine) -> None:
    """The end-to-end claim: relevance, through the real retrieval path."""
    add_document(session, engine, "Dividend", CORPUS[0])
    add_document(session, engine, "RSI", CORPUS[1])
    add_document(session, engine, "EV/EBITDA", CORPUS[2])

    top = engine.search_knowledge("dividend yield", limit=1)
    assert top
    assert "Dividend yield" in top[0].text


def test_a_metric_query_finds_the_metric_not_a_neighbour(
    session, engine: RAGEngine
) -> None:
    add_document(session, engine, "A", CORPUS[2])
    add_document(session, engine, "B", CORPUS[1])

    top = engine.search_knowledge("EBITDA", limit=1)
    assert "EV/EBITDA" in top[0].text


def test_results_report_which_ranker_found_them(session, engine: RAGEngine) -> None:
    add_document(session, engine, "Dividend", CORPUS[0])
    results = engine.search_knowledge("dividend yield")

    assert results
    assert "lexical" in results[0].ranks or "vector" in results[0].ranks
    assert "ranks" in results[0].as_dict()


def test_retrieval_still_works_without_usable_embeddings(session, engine: RAGEngine) -> None:
    """An embedding outage should cost quality, not the whole feature."""
    from sqlalchemy import select

    from aidss.db.models import KnowledgeChunk

    add_document(session, engine, "Dividend", CORPUS[0])
    add_document(session, engine, "RSI", CORPUS[1])
    for chunk in session.scalars(select(KnowledgeChunk)).all():
        chunk.embedding = None
    session.flush()

    top = engine.search_knowledge("dividend yield", limit=1)
    assert top
    assert "Dividend yield" in top[0].text
    assert set(top[0].ranks) == {"lexical"}


def test_news_retrieval_ranks_the_matching_article_first(session, engine: RAGEngine) -> None:
    from datetime import UTC, datetime, timedelta

    from aidss.db.models import NewsItem

    asset = Asset(ticker="BBCA", exchange="IDX")
    session.add(asset)
    session.flush()

    for headline, summary in (
        ("BBCA raises its dividend", "The bank increased its dividend payout."),
        ("BBCA opens new branches", "The bank expanded its branch network."),
    ):
        session.add(
            NewsItem(
                asset_id=asset.id,
                source="test",
                source_url=f"https://example.invalid/{headline[:15]}",
                dedup_hash=headline,
                headline=headline,
                body_summary=summary,
                published_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
    session.flush()

    from sqlalchemy import select

    engine.index_news(list(session.scalars(select(NewsItem)).all()))
    top = engine.search_news("dividend payout", asset_id=asset.id, limit=1)

    assert top
    assert "dividend" in top[0].text.lower()

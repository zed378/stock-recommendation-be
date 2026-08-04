"""Combining lexical and vector rankings.

Reciprocal Rank Fusion rather than a weighted sum of scores, because the two
scores are not comparable. Cosine similarity lives in [-1, 1] and clusters
tightly - real passages often sit between 0.7 and 0.9, so the *spread* carries
the signal, not the value. BM25 is unbounded and depends on corpus statistics:
the same passage scores differently depending on what else was indexed. Adding
or averaging those means whichever happens to have the larger range quietly
dominates, and normalising per query makes the weights depend on the query.

RRF uses only *rank*, which both rankers agree on the meaning of. A document
ranked first by either is strong; one ranked well by both is stronger. It has
one parameter, and the published default works.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeVar

#: The RRF constant from the original paper. Damps the contribution of top
#: ranks so that being first rather than second is an advantage but not an
#: overwhelming one - which is what stops a single confident ranker from
#: overriding agreement between both.
RRF_K = 60

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class FusedResult:
    index: int
    score: float
    #: Where each ranker placed it, 1-based. Present only for the rankers that
    #: returned it at all. Kept because "vector loved it, lexical never saw it"
    #: is the single most useful thing to know when a result looks wrong.
    ranks: dict[str, int]


def _ranking(scores: Sequence[float], *, min_score: float = 0.0) -> list[int]:
    """Indices ordered best-first, dropping anything at or below ``min_score``.

    Zero-scoring documents are dropped rather than ranked last: a BM25 score of
    zero means the document contains none of the query terms, and giving it a
    rank would let it contribute to the fused score purely by existing.
    """
    candidates = [(i, s) for i, s in enumerate(scores) if s > min_score]
    candidates.sort(key=lambda pair: pair[1], reverse=True)
    return [i for i, _ in candidates]


def reciprocal_rank_fusion(
    rankings: dict[str, Sequence[float]],
    *,
    k: int = RRF_K,
    weights: dict[str, float] | None = None,
    limit: int | None = None,
) -> list[FusedResult]:
    """Fuse several score lists into one ranking.

    ``rankings`` maps a ranker's name to its score per document, all in the
    same document order. Weights are per ranker and default to 1.
    """
    weights = weights or {}
    fused: dict[int, float] = {}
    ranks: dict[int, dict[str, int]] = {}

    for name, scores in rankings.items():
        weight = weights.get(name, 1.0)
        for position, doc_index in enumerate(_ranking(scores), start=1):
            fused[doc_index] = fused.get(doc_index, 0.0) + weight / (k + position)
            ranks.setdefault(doc_index, {})[name] = position

    results = [
        FusedResult(index=i, score=score, ranks=ranks.get(i, {}))
        for i, score in fused.items()
    ]
    # Ties broken by document order so the same inputs always produce the same
    # output - a ranking that reshuffles between identical queries is one
    # nobody can debug.
    results.sort(key=lambda r: (-r.score, r.index))
    return results[:limit] if limit else results

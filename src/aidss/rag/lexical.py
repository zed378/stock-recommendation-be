"""BM25 lexical scoring for retrieval.

Vector search alone is a poor fit for a lot of what gets asked here. Financial
questions are full of exact tokens - a ticker (BBCA), a metric name
(EV/EBITDA), a ratio (P/BV) - and an embedding maps those onto "roughly finance
words", losing the distinction between the one the user typed and its
neighbours. A query for BBCA that returns passages about BBRI is semantically
close and practically useless.

BM25 covers exactly that: it rewards documents containing the query's terms,
weights rare terms above common ones, and does not reward a long document
merely for being long. Combined with vector search it catches what the other
misses, which is the case for hybrid retrieval.

Implemented here rather than pulled in, for two reasons. It is about eighty
lines of well-specified arithmetic. And a dependency would still need the same
Indonesian-aware tokenisation, so the interesting part would have been ours
regardless.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

#: Standard BM25 parameters. k1 controls how fast term frequency saturates - a
#: term appearing ten times is not ten times as relevant as once. b controls
#: length normalisation.
K1 = 1.5
B = 0.75

#: Words carrying no discriminating power, in both languages this platform
#: serves. Deliberately short: an aggressive stop list removes terms that turn
#: out to matter, and BM25's IDF already discounts common words.
STOPWORDS: frozenset[str] = frozenset(
    {
        # English
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
        "have", "in", "is", "it", "its", "of", "on", "or", "that", "the", "to",
        "was", "were", "will", "with", "what", "how", "does", "do", "this",
        # Indonesian
        "adalah", "akan", "atau", "dan", "dari", "di", "ini", "itu", "juga",
        "ke", "kepada", "pada", "untuk", "yang", "dengan", "dalam", "apa",
        "bagaimana", "sebagai", "oleh", "tidak",
    }
)

#: Keeps letters, digits, and the punctuation that carries meaning inside
#: financial terms: the dot in BBCA.JK, the slash in EV/EBITDA, the hyphen in
#: price-to-book. Splitting on those would destroy the very tokens BM25 is
#: here to match.
_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[./-][A-Za-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    """Lower-cased tokens, with stopwords and single characters removed."""
    tokens = [match.group(0).lower() for match in _TOKEN.finditer(text)]
    return [t for t in tokens if len(t) > 1 and t not in STOPWORDS]


def expand(token: str) -> list[str]:
    """A compound token plus its parts.

    ``ev/ebitda`` should match a passage saying "EBITDA", and ``bbca.jk``
    should match one saying "BBCA". Indexing only the whole token would make
    those misses; indexing only the parts would lose the compound. Both are
    cheap.
    """
    parts = re.split(r"[./-]", token)
    if len(parts) == 1:
        return [token]
    return [token, *(p for p in parts if len(p) > 1)]


def analyze(text: str) -> list[str]:
    """Tokenise and expand - the full indexing pipeline for one document."""
    return [term for token in tokenize(text) for term in expand(token)]


@dataclass
class BM25Index:
    """An in-memory BM25 index over a set of documents.

    Built per query rather than maintained, because the candidate set here is
    already narrowed by ticker and recency filters before ranking. Indexing a
    few dozen chunks costs microseconds; maintaining a persistent inverted
    index would cost a whole subsystem.
    """

    k1: float = K1
    b: float = B
    _docs: list[list[str]] = field(default_factory=list)
    _freqs: list[Counter[str]] = field(default_factory=list)
    _doc_freq: Counter[str] = field(default_factory=Counter)
    _avg_len: float = 0.0

    @classmethod
    def build(cls, documents: list[str], **kwargs: float) -> BM25Index:
        index = cls(**kwargs)  # type: ignore[arg-type]
        for document in documents:
            terms = analyze(document)
            index._docs.append(terms)
            index._freqs.append(Counter(terms))
            index._doc_freq.update(set(terms))
        total = sum(len(d) for d in index._docs)
        index._avg_len = total / len(index._docs) if index._docs else 0.0
        return index

    @property
    def size(self) -> int:
        return len(self._docs)

    def idf(self, term: str) -> float:
        """Inverse document frequency, in the form that cannot go negative.

        The textbook BM25 IDF turns negative for a term present in more than
        half the corpus, which would make a matching document score *worse*
        than a non-matching one. The +1 inside the log is the standard fix.
        """
        n = self.size
        df = self._doc_freq.get(term, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def score(self, query: str) -> list[float]:
        """BM25 score per document, in the order they were supplied."""
        if not self._docs:
            return []

        terms = analyze(query)
        scores = [0.0] * self.size
        if not terms:
            return scores

        for term in set(terms):
            if term not in self._doc_freq:
                continue
            idf = self.idf(term)
            for i, freq in enumerate(self._freqs):
                tf = freq.get(term, 0)
                if tf == 0:
                    continue
                length_norm = 1 - self.b + self.b * (len(self._docs[i]) / self._avg_len)
                scores[i] += idf * (tf * (self.k1 + 1)) / (tf + self.k1 * length_norm)
        return scores

"""Text chunking for retrieval (Phase 7, Section 6.3.3 step 8).

Chunking decides what retrieval can ever find. A chunk that splits a sentence
in half retrieves as a fragment neither half of which answers anything; a chunk
holding a whole document retrieves the document's average topic rather than the
passage you needed.

The strategy here is boundary-aware with overlap: split on paragraph breaks
first, fall back to sentences, and carry a little context across the seam so a
fact stated at a boundary is not lost to both neighbours.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Target chunk size in characters. Roughly 250 tokens - large enough to hold a
#: complete thought, small enough that an embedding still represents it rather
#: than an average of several.
DEFAULT_CHUNK_SIZE = 1000

#: Characters repeated from the previous chunk. Without overlap, a definition
#: that begins one chunk and is used in the next becomes unretrievable from
#: either.
DEFAULT_OVERLAP = 150

#: Below this a chunk carries too little to be worth an embedding call.
MIN_CHUNK_SIZE = 80

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True, slots=True)
class Chunk:
    index: int
    text: str

    @property
    def size(self) -> int:
        return len(self.text)


def _split_long_block(block: str, chunk_size: int) -> list[str]:
    """Break an oversized paragraph on sentence boundaries.

    A hard character cut would sever a sentence, so sentences are packed until
    the next one would overflow. A single sentence longer than the whole chunk
    size is kept intact rather than mangled - a truncated sentence retrieves
    worse than a slightly oversized one.
    """
    sentences = _SENTENCE_END.split(block)
    parts: list[str] = []
    current = ""

    for sentence in sentences:
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= chunk_size:
            current = f"{current} {sentence}"
        else:
            parts.append(current)
            current = sentence
    if current:
        parts.append(current)
    return parts


def chunk_text(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    min_size: int = MIN_CHUNK_SIZE,
) -> list[Chunk]:
    """Split text into overlapping, boundary-aware chunks."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")

    cleaned = text.strip()
    if not cleaned:
        return []

    blocks: list[str] = []
    for paragraph in _PARAGRAPH_BREAK.split(cleaned):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= chunk_size:
            blocks.append(paragraph)
        else:
            blocks.extend(_split_long_block(paragraph, chunk_size))

    # Pack blocks up to the target size, so a document of short paragraphs does
    # not become a chunk per line.
    packed: list[str] = []
    current = ""
    for block in blocks:
        if not current:
            current = block
        elif len(current) + 2 + len(block) <= chunk_size:
            current = f"{current}\n\n{block}"
        else:
            packed.append(current)
            current = block
    if current:
        packed.append(current)

    chunks: list[Chunk] = []
    for i, body in enumerate(packed):
        if overlap and i > 0:
            tail = packed[i - 1][-overlap:]
            body = f"{tail}\n\n{body}" if tail else body
        # A trailing scrap is dropped only when it is the sole content of its
        # chunk; a short final paragraph that follows real text is kept.
        if len(body.strip()) < min_size and len(packed) > 1:
            continue
        chunks.append(Chunk(index=len(chunks), text=body.strip()))

    return chunks


def chunk_article(
    headline: str, summary: str | None, *, chunk_size: int = DEFAULT_CHUNK_SIZE
) -> list[Chunk]:
    """Chunk a news article, with the headline prefixed to every chunk.

    The headline names the subject; a chunk from the middle of a body without
    it retrieves as text about an unnamed company. Repeating it costs a few
    tokens and makes every chunk independently meaningful.
    """
    body = (summary or "").strip()
    if not body:
        return [Chunk(index=0, text=headline.strip())] if headline.strip() else []

    prefix = f"{headline.strip()}\n\n"
    budget = max(MIN_CHUNK_SIZE, chunk_size - len(prefix))
    return [
        Chunk(index=chunk.index, text=f"{prefix}{chunk.text}")
        for chunk in chunk_text(body, chunk_size=budget)
    ]

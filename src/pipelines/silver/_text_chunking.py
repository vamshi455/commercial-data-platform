"""Pure-Python text chunking — the tested source of truth for the RAG track.

Kept dependency-free (no pyspark / no dlt) so it runs under plain pytest off
cluster. The DLT silver module (``document_chunking.py``) inlines a copy of
``chunk_text`` because serverless DLT cannot reliably import a .py from
/Workspace files — this module remains the source of truth (same convention as
``src/pipelines/_common.py``). Keep the two copies in sync.

Chunking model
--------------
A token-approximate sliding window: we split on whitespace (1 word ~= 1 token
for English prose, close enough for retrieval sizing), emit windows of
``max_tokens`` words with ``overlap`` words carried into the next window so a
sentence spanning a boundary still appears whole in at least one chunk.
"""
from __future__ import annotations


def chunk_text(text: str | None, max_tokens: int = 800, overlap: int = 100) -> list[str]:
    """Split ``text`` into overlapping, retrieval-sized chunks.

    Args:
        text: the source text (a PDF page or Excel sheet). ``None``/blank -> [].
        max_tokens: target words per chunk (~tokens). Must be > 0.
        overlap: words carried from the end of one chunk into the start of the
            next. Must be >= 0 and < ``max_tokens`` (else no forward progress).

    Returns:
        A list of chunk strings, in document order. Short text yields one chunk.
    """
    if max_tokens <= 0:
        raise ValueError("max_tokens must be > 0")
    if overlap < 0 or overlap >= max_tokens:
        raise ValueError("overlap must be >= 0 and < max_tokens")

    if not text or not text.strip():
        return []

    words = text.split()
    if len(words) <= max_tokens:
        return [" ".join(words)]

    step = max_tokens - overlap
    chunks: list[str] = []
    for start in range(0, len(words), step):
        window = words[start:start + max_tokens]
        if window:
            chunks.append(" ".join(window))
        if start + max_tokens >= len(words):
            break
    return chunks

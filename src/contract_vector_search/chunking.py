"""Contract-aware recursive text chunking — PURE PYTHON, no Spark, no Databricks.

This module is deliberately dependency-free so it can be unit-tested locally
(``tests/test_contract_chunking.py``) without a cluster. The silver task imports
these functions and applies them per-document.

Chunking strategy (see spec ``docs/specs/contract-vector-search.md`` §Silver)
----------------------------------------------------------------------------
Recursive splitter with **contract-aware separators**: we try to break on the
most semantically meaningful boundary that exists in the text, falling back to
finer boundaries only when a chunk is still too large.

Separator priority (high -> low):
  1. Clause / structural headers: ``ARTICLE``, ``SECTION``, ``WHEREAS``,
     ``NOW THEREFORE`` and numbered clauses at line-start (``\\n1.`` ``\\n2.`` ...).
  2. Paragraph breaks (blank line).
  3. Single newline.
  4. Sentence end (". ").
  5. Space.
  6. Hard character cut (last resort).

Targets: ~1000 tokens per chunk, ~150 token overlap. We approximate tokens as
``chars / CHARS_PER_TOKEN`` (~4) to avoid pulling in a tokenizer at chunk time;
the embedding endpoint does the real tokenization. "Never split mid-clause when
a separator is available" falls out of the priority order: a clause boundary is
always preferred over a mid-sentence cut.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

CHARS_PER_TOKEN = 4  # rough English heuristic; keeps chunking tokenizer-free
DEFAULT_TARGET_TOKENS = 1000
DEFAULT_OVERLAP_TOKENS = 150

# Ordered high -> low. Each entry is a regex; we split *keeping* the separator
# with the following text (so a header stays attached to its clause body).
_SEPARATOR_PATTERNS: list[str] = [
    r"(?=\n\s*ARTICLE\b)",
    r"(?=\n\s*SECTION\b)",
    r"(?=\n\s*WHEREAS\b)",
    r"(?=\n\s*NOW,?\s+THEREFORE\b)",
    r"(?=\n\s*\d+\.\s)",   # numbered clause at line start: "\n1. ", "\n12. "
    r"\n\s*\n",             # paragraph break
    r"\n",                  # single newline
    r"(?<=[.?!])\s+",       # sentence boundary
    r"\s+",                 # any whitespace
]


@dataclass(frozen=True)
class Chunk:
    """One emitted chunk. ``seq`` is 0-based position within its source file."""
    seq: int
    text: str


def estimate_tokens(text: str) -> int:
    """Approximate token count without a tokenizer (chars / CHARS_PER_TOKEN)."""
    return max(1, len(text) // CHARS_PER_TOKEN)


def _split_keep(text: str, pattern: str) -> list[str]:
    """Split on ``pattern`` and drop empties. Lookahead patterns keep the sep."""
    parts = re.split(pattern, text)
    return [p for p in parts if p and p.strip()]


def _recursive_split(text: str, target_chars: int, sep_idx: int = 0) -> list[str]:
    """Break ``text`` into pieces each <= ``target_chars`` using separator ladder.

    Tries the separator at ``sep_idx``; any resulting piece still too large is
    re-split with the next-finer separator. Pieces already small enough are kept
    whole (this is what preserves clauses intact).
    """
    if len(text) <= target_chars:
        return [text.strip()] if text.strip() else []

    if sep_idx >= len(_SEPARATOR_PATTERNS):
        # No separators left: hard-cut on character boundary.
        return [text[i : i + target_chars].strip()
                for i in range(0, len(text), target_chars)]

    pieces = _split_keep(text, _SEPARATOR_PATTERNS[sep_idx])
    if len(pieces) <= 1:
        # Separator didn't actually divide the text; try the next one.
        return _recursive_split(text, target_chars, sep_idx + 1)

    # Greedily pack adjacent pieces up to target, recursing into any piece that
    # is itself oversized.
    out: list[str] = []
    buf = ""
    for piece in pieces:
        if len(piece) > target_chars:
            if buf.strip():
                out.append(buf.strip())
                buf = ""
            out.extend(_recursive_split(piece, target_chars, sep_idx + 1))
            continue
        if len(buf) + len(piece) <= target_chars:
            buf += piece
        else:
            if buf.strip():
                out.append(buf.strip())
            buf = piece
    if buf.strip():
        out.append(buf.strip())
    return [p for p in out if p]


def _apply_overlap(chunks: list[str], overlap_chars: int) -> list[str]:
    """Prepend a tail slice of the previous chunk to each chunk for context."""
    if overlap_chars <= 0 or len(chunks) <= 1:
        return chunks
    out = [chunks[0]]
    for i in range(1, len(chunks)):
        tail = chunks[i - 1][-overlap_chars:]
        # Start the overlap at a whitespace boundary so we don't slice a word.
        space = tail.find(" ")
        if space != -1:
            tail = tail[space + 1 :]
        out.append((tail + " " + chunks[i]).strip())
    return out


def chunk_text(
    text: str,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    """Split a full document into overlapping, contract-aware chunks.

    Returns a list of :class:`Chunk` with contiguous 0-based ``seq`` values.
    Empty/whitespace input yields an empty list (caller dead-letters it).
    """
    if not text or not text.strip():
        return []
    target_chars = target_tokens * CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * CHARS_PER_TOKEN
    base = _recursive_split(text, target_chars)
    with_overlap = _apply_overlap(base, overlap_chars)
    return [Chunk(seq=i, text=c) for i, c in enumerate(with_overlap) if c.strip()]


def make_chunk_id(source_file: str, chunk_seq: int) -> str:
    """Deterministic gold primary key: ``sha2(source_file || ':' || seq, 256)``.

    Matches the spec exactly. Stable across re-runs -> re-processing the same
    file MERGEs onto the same rows instead of duplicating (idempotency).
    """
    return hashlib.sha256(f"{source_file}:{chunk_seq}".encode("utf-8")).hexdigest()

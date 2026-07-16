"""Turn an ``ai_parse_document`` result into text + real page numbers.

Why this module exists: the silver notebook used to inline a `_extract_text`
helper that probed for `document.text` / `document.pages[].content`. The actual
shape is `document.elements[].content`, with the page carried on
`elements[].bbox[].page_id` — so the probe missed and the helper fell back to
`str(parsed)`, silently writing **the raw JSON of the parse result** into
`chunk_text`. Every embedding, metadata regex, and agent citation was then built
from JSON instead of contract prose, and nothing failed loudly.

Two lessons are baked in here:
  * `ai_parse_document` may hand back a JSON **string** or a Spark struct
    depending on runtime — handle both, and NEVER str()-fallback silently.
  * The elements carry `page_id`, so real page numbers are available; the old
    `_page_for` stub returned 1 forever, making every citation's page fiction.

Pure Python (no Spark) so it unit-tests off-cluster like chunking/metadata.
"""
from __future__ import annotations

import json
from typing import Any

# One page-tagged block of text from the parser.
Element = tuple[str, int]        # (text, page_number)  — page is 1-based
PageMap = list[tuple[int, int]]  # [(end_offset_exclusive, page_number)]

JOIN = "\n\n"


class ParseShapeError(ValueError):
    """The parse result had no recognizable text — fail loudly, never str()."""


def _as_dict(parsed: Any) -> dict:
    """Normalize a parse result to a dict.

    Handles every shape ai_parse_document has been observed to return:
      * ``VariantVal`` — what DBR actually hands back (Spark VARIANT). This is the
        one the original code missed: ``dict(VariantVal)`` raises, the old helper
        caught it and returned ``str(parsed)``, and VariantVal.__str__ renders the
        JSON — which is exactly how raw JSON ended up embedded as chunk_text.
      * JSON string, Spark Row/struct, plain dict.
    Variant is duck-typed (``hasattr``) rather than imported so this module stays
    Spark-free and unit-testable off-cluster.
    """
    if parsed is None:
        raise ParseShapeError("parse result is None")
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, str):
        return _loads(parsed, "parse result string")

    for attr in ("toJson", "toPython"):          # VariantVal
        fn = getattr(parsed, attr, None)
        if callable(fn):
            val = fn()
            if isinstance(val, dict):
                return val
            if isinstance(val, str):
                return _loads(val, f"{type(parsed).__name__}.{attr}()")

    if hasattr(parsed, "asDict"):                # Spark Row
        return parsed.asDict(recursive=True)

    raise ParseShapeError(f"unsupported parse result type: {type(parsed).__name__}")


def _loads(s: str, what: str) -> dict:
    try:
        d = json.loads(s)
    except json.JSONDecodeError as e:
        raise ParseShapeError(f"{what} is not valid JSON: {e}") from e
    if not isinstance(d, dict):
        raise ParseShapeError(f"{what} decoded to {type(d).__name__}, expected object")
    return d


def _page_of(element: dict) -> int:
    """1-based page for an element; page_id is 0-based in the parser output."""
    bbox = element.get("bbox") or []
    if isinstance(bbox, list) and bbox:
        pid = (bbox[0] or {}).get("page_id")
        if isinstance(pid, int):
            return pid + 1
    pid = element.get("page_id")
    return pid + 1 if isinstance(pid, int) else 1


def extract_elements(parsed: Any) -> list[Element]:
    """[(text, page)] from a parse result. Raises ParseShapeError if unusable.

    Primary shape is ``document.elements[]`` (content + bbox[].page_id). The
    older ``document.pages[]`` / ``document.text`` shapes are still accepted so a
    runtime change doesn't silently regress us to the JSON-blob bug.
    """
    d = _as_dict(parsed)
    doc = d.get("document") if isinstance(d.get("document"), dict) else d

    elements = doc.get("elements")
    if isinstance(elements, list) and elements:
        out = [
            (str(el.get("content") or "").strip(), _page_of(el))
            for el in elements
            if isinstance(el, dict) and (el.get("content") or "").strip()
        ]
        if out:
            return out

    pages = doc.get("pages") or d.get("pages")
    if isinstance(pages, list) and pages:
        out = [
            (str(p.get("content") or p.get("text") or "").strip(), i + 1)
            for i, p in enumerate(pages)
            if isinstance(p, dict) and (p.get("content") or p.get("text") or "").strip()
        ]
        if out:
            return out

    if isinstance(doc.get("text"), str) and doc["text"].strip():
        return [(doc["text"].strip(), 1)]

    raise ParseShapeError(
        "no text found in parse result (looked for document.elements[].content, "
        f"document.pages[], document.text); top-level keys={sorted(d)[:8]}"
    )


def elements_to_text(elements: list[Element]) -> str:
    return JOIN.join(t for t, _ in elements)


def build_page_map(elements: list[Element]) -> PageMap:
    """Cumulative end-offsets over ``elements_to_text(elements)`` -> page."""
    page_map: PageMap = []
    pos = 0
    for i, (text, page) in enumerate(elements):
        pos += len(text) + (len(JOIN) if i < len(elements) - 1 else 0)
        page_map.append((pos, page))
    return page_map


def page_at_offset(page_map: PageMap, offset: int) -> int:
    for end, page in page_map:
        if offset < end:
            return page
    return page_map[-1][1] if page_map else 1


def page_for_chunk(text: str, page_map: PageMap, chunk: str) -> int:
    """Page a chunk belongs to, located by probing its MIDDLE.

    Not the start: the chunker prepends an overlap tail from the previous chunk,
    so a chunk's opening characters may belong to the previous page (and may not
    appear contiguously in ``text`` at all). The midpoint is always original,
    non-overlap content, so it locates the chunk's true page.
    """
    if not chunk or not page_map:
        return 1
    mid = len(chunk) // 2
    probe = chunk[mid:mid + 80].strip()
    off = text.find(probe) if probe else -1
    if off < 0:  # fall back to the chunk's tail, also original content
        tail = chunk[-80:].strip()
        off = text.find(tail) if tail else -1
    return page_at_offset(page_map, off if off >= 0 else 0)

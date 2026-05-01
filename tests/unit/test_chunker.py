"""Chunker tests — heading detection and overlap."""
from __future__ import annotations

from app.services.chunker import chunk_document


def test_chunker_splits_on_section_markers():
    text = (
        "Article 5 — Principles\n"
        "The processor shall do X. The controller shall do Y. " * 30 + "\n\n"
        "Article 6 — Lawfulness\n"
        "The basis is consent. The basis is contract. " * 30 + "\n\n"
    )
    chunks = chunk_document(text, document_id="doc-1", max_tokens=200, overlap_tokens=40)
    assert len(chunks) >= 2
    assert any("Article 5" == (c.section or "")[:9] for c in chunks)
    assert any("Article 6" == (c.section or "")[:9] for c in chunks)


def test_chunker_assigns_unique_chunk_ids():
    text = "Section 1.1 — Foo\n" + ("Sentence about a control. " * 200)
    chunks = chunk_document(text, document_id="doc-x", max_tokens=120, overlap_tokens=20)
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
    assert all(c.text for c in chunks)


def test_chunker_empty_text():
    chunks = chunk_document("", document_id="doc-empty")
    assert chunks == []

"""Document chunking — heading-aware sliding-window with overlap.

Strategy (justified in architecture.md):
  1. Split on regulatory section markers (regex patterns common to SOC2/GDPR/HIPAA/ISO).
  2. Within each section, slide a token-budgeted window with overlap so a single
     sentence describing a control is never split across chunks.
  3. Preserve metadata (section header, page if known) for citation accuracy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Cheap whitespace-based length estimator. Real token count enforced at LLM call
# site via the Anthropic SDK count_tokens helper.
_DEFAULT_MAX_TOKENS = 800
_DEFAULT_OVERLAP_TOKENS = 200
_TOKEN_PER_WORD = 1.3  # rough English heuristic

_SECTION_RE = re.compile(
    r"""
    (?:^|\n)
    (
        (?:Article|Section|§|Rule|Clause|Control|Principle)\s+\d+(?:\.\d+)*[A-Za-z]?
        (?:\s*[-–—:.]\s*[^\n]{0,200})?
    )
    \s*\n
    """,
    re.VERBOSE | re.IGNORECASE,
)


@dataclass
class Chunk:
    chunk_id: str
    text: str
    section: str | None
    order: int
    char_start: int
    char_end: int

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "section": self.section,
            "order": self.order,
            "char_start": self.char_start,
            "char_end": self.char_end,
        }


def _approx_tokens(s: str) -> int:
    return int(len(s.split()) * _TOKEN_PER_WORD)


def _split_sections(text: str) -> list[tuple[str | None, str, int]]:
    """Return list of (heading, body, char_offset_of_body)."""
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        return [(None, text, 0)]

    sections: list[tuple[str | None, str, int]] = []
    if matches[0].start() > 0:
        sections.append((None, text[: matches[0].start()], 0))

    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((heading, text[body_start:body_end], body_start))
    return sections


def _slide(
    body: str,
    body_offset: int,
    *,
    max_tokens: int,
    overlap_tokens: int,
) -> list[tuple[str, int, int]]:
    """Sliding window over a single section body. Returns (text, start, end)."""
    sentences = re.split(r"(?<=[.!?])\s+", body)
    out: list[tuple[str, int, int]] = []
    buf: list[str] = []
    buf_tokens = 0
    cursor = 0
    chunk_start = 0

    for sent in sentences:
        if not sent:
            continue
        sent_tokens = _approx_tokens(sent)
        if buf and buf_tokens + sent_tokens > max_tokens:
            text = " ".join(buf).strip()
            out.append((text, body_offset + chunk_start, body_offset + cursor))
            keep: list[str] = []
            keep_tokens = 0
            for s in reversed(buf):
                t = _approx_tokens(s)
                if keep_tokens + t > overlap_tokens:
                    break
                keep.insert(0, s)
                keep_tokens += t
            buf = keep
            buf_tokens = keep_tokens
            chunk_start = cursor - sum(len(s) + 1 for s in buf)
            chunk_start = max(chunk_start, 0)
        buf.append(sent)
        buf_tokens += sent_tokens
        cursor = body.find(sent, cursor) + len(sent)

    if buf:
        text = " ".join(buf).strip()
        out.append((text, body_offset + chunk_start, body_offset + len(body)))
    return out


def chunk_document(
    text: str,
    *,
    document_id: str,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    overlap_tokens: int = _DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    """Chunk a document into Chunk records."""
    chunks: list[Chunk] = []
    order = 0
    for heading, body, body_offset in _split_sections(text):
        body = body.strip("\n")
        if not body:
            continue
        for piece, start, end in _slide(
            body, body_offset, max_tokens=max_tokens, overlap_tokens=overlap_tokens
        ):
            piece = piece.strip()
            if not piece:
                continue
            chunks.append(
                Chunk(
                    chunk_id=f"{document_id}:{order:04d}",
                    text=piece,
                    section=heading,
                    order=order,
                    char_start=start,
                    char_end=end,
                )
            )
            order += 1
    return chunks

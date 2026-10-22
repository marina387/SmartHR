"""Разбиение текста на чанки для простого RAG-модуля."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    chunk_id: int
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)


def chunk_text(doc_id: str, text: str, *, chunk_size_words: int = 120, overlap_words: int = 30,
               metadata: Dict[str, Any] | None = None) -> List[Chunk]:
    words = text.split()
    if chunk_size_words <= 0:
        raise ValueError("chunk_size_words must be > 0")
    if overlap_words < 0:
        raise ValueError("overlap_words must be >= 0")
    if overlap_words >= chunk_size_words:
        raise ValueError("overlap_words must be < chunk_size_words")

    chunks: List[Chunk] = []
    start = 0
    cid = 0
    while start < len(words):
        end = min(start + chunk_size_words, len(words))
        chunk_words = words[start:end]
        chunk_text_str = " ".join(chunk_words).strip()
        if chunk_text_str:
            chunks.append(Chunk(doc_id=doc_id, chunk_id=cid, text=chunk_text_str, metadata=dict(metadata or {})))
            cid += 1
        if end == len(words):
            break
        start = end - overlap_words
    return chunks

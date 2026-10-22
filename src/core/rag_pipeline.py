"""Компактный пайплайн RAG для обучения и демонстрации."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Dict, List

from src.core.chunking import Chunk, chunk_text
from src.core.loaders import LoadedDocument
from src.core.retrieval import SearchHit, SemanticRetriever, TfidfRetriever


@dataclass
class RagResult:
    query: str
    hits: List[SearchHit]

    def as_text(self) -> str:
        lines = [f"Вопрос: {self.query}", ""]
        lines.append("Найденный контекст (top chunks):")
        for i, h in enumerate(self.hits, 1):
            lines.append(f"{i}) score={h.score:.3f} doc={h.chunk.doc_id} chunk={h.chunk.chunk_id}")
            lines.append(h.chunk.text)
            lines.append("")
        if self.hits:
            lines.append("MVP-ответ (без LLM):")
            lines.append(self.hits[0].chunk.text[:400] + ("..." if len(self.hits[0].chunk.text) > 400 else ""))
        return "\n".join(lines)


class RagPipeline:
    def __init__(self, backend: str | None = None) -> None:
        self.requested_backend = (backend or os.getenv("RAG_BACKEND", "auto")).casefold()
        self.retriever = self._make_retriever(self.requested_backend)
        self._chunks: List[Chunk] = []
        self._documents: Dict[str, LoadedDocument] = {}
        self.fallback_reason: str | None = None

    @staticmethod
    def _make_retriever(backend: str):
        return TfidfRetriever() if backend == "tfidf" else SemanticRetriever()

    @property
    def backend_name(self) -> str:
        return self.retriever.backend_name

    def list_documents(self) -> List[Dict[str, object]]:
        """Возвращает сохранённые метаданные документов без их полного текста."""
        return [
            {
                "id": document.id,
                "title": document.title,
                "source": document.source,
                "document_type": document.document_type,
                "metadata": dict(document.metadata),
            }
            for document in self._documents.values()
        ]

    def build_index(self, docs: Dict[str, str] | List[LoadedDocument], *, chunk_size_words: int = 120, overlap_words: int = 30) -> None:
        if isinstance(docs, dict):
            documents = [LoadedDocument(key, key, value, key, "text", {"source": key}) for key, value in docs.items()]
        else:
            documents = list(docs)
        self._documents = {document.id: document for document in documents}
        all_chunks: List[Chunk] = []
        for document in documents:
            metadata = {**document.metadata, "title": document.title, "source": document.source,
                        "document_type": document.document_type}
            all_chunks.extend(chunk_text(document.id, document.text, chunk_size_words=chunk_size_words,
                                         overlap_words=overlap_words, metadata=metadata))
        self._chunks = all_chunks
        try:
            self.retriever.index(self._chunks)
        except Exception as exc:
            if self.requested_backend not in {"auto", "semantic"}:
                raise
            self.fallback_reason = str(exc)
            self.retriever = TfidfRetriever()
            self.retriever.index(self._chunks)

    def upsert_document(self, document: LoadedDocument) -> None:
        self._documents[document.id] = document
        self.build_index(list(self._documents.values()))

    def delete_document(self, document_id: str) -> bool:
        existed = self._documents.pop(str(document_id), None) is not None
        if existed:
            self.build_index(list(self._documents.values()))
        return existed

    def ask(self, query: str, *, top_k: int = 5) -> RagResult:
        if not self.retriever.is_indexed:
            return RagResult(query=query, hits=[])
        hits = self.retriever.search(query, top_k=top_k)
        return RagResult(query=query, hits=hits)

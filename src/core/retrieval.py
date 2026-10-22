"""Минимальный retrieval для RAG на TF-IDF."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import List, Sequence

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.core.chunking import Chunk


@dataclass
class SearchHit:
    score: float
    chunk: Chunk


class TfidfRetriever:
    backend_name = "tfidf"
    def __init__(self) -> None:
        self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), lowercase=True)
        self._chunks: List[Chunk] = []
        self._matrix = None

    @property
    def is_indexed(self) -> bool:
        return self._matrix is not None and len(self._chunks) > 0

    def index(self, chunks: Sequence[Chunk]) -> None:
        self._chunks = list(chunks)
        texts = [f"{c.metadata.get('title', '')} {c.metadata.get('source', '')} {c.text}" for c in self._chunks]
        if not texts:
            self._matrix = None
            return
        self._matrix = self.vectorizer.fit_transform(texts)

    def search(self, query: str, *, top_k: int = 5) -> List[SearchHit]:
        if not self.is_indexed:
            raise RuntimeError("Retriever is not indexed. Call index(chunks) first.")
        # Убираем команды поиска, чтобы слово «документы» не давало ложных совпадений.
        query = re.sub(r"\b(?:найди|найти|покажи|расскажи|информаци[а-яё]*|документ[а-яё]*|как|что|про|об|в|по|сказано|описано)\b", " ", query.casefold())
        query = query.replace("интервью", "собеседование")
        qv = self.vectorizer.transform([query])
        sims = cosine_similarity(qv, self._matrix).ravel()
        top_idx = np.argsort(-sims)[:top_k]
        return [SearchHit(score=float(sims[i]), chunk=self._chunks[int(i)]) for i in top_idx if sims[i] > 0]


class SemanticRetriever:
    """Семантический поиск sentence-transformers с индексом FAISS."""

    backend_name = "semantic-faiss"

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or os.getenv(
            "RAG_EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
        self._model = None
        self._index = None
        self._chunks: List[Chunk] = []

    @property
    def is_indexed(self) -> bool:
        return self._index is not None and bool(self._chunks)

    def _dependencies(self):
        try:
            import faiss
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("Для семантического RAG установите requirements-chat.txt") from exc
        return faiss, SentenceTransformer

    def index(self, chunks: Sequence[Chunk]) -> None:
        faiss, sentence_transformer = self._dependencies()
        self._chunks = list(chunks)
        if not self._chunks:
            self._index = None
            return
        if self._model is None:
            allow_download = os.getenv("RAG_ALLOW_MODEL_DOWNLOAD", "0") == "1"
            self._model = sentence_transformer(self.model_name, local_files_only=not allow_download)
        vectors = self._model.encode(
            [chunk.text for chunk in self._chunks], convert_to_numpy=True, normalize_embeddings=True
        ).astype("float32")
        self._index = faiss.IndexFlatIP(vectors.shape[1])
        self._index.add(vectors)

    def search(self, query: str, *, top_k: int = 5) -> List[SearchHit]:
        if not self.is_indexed:
            raise RuntimeError("Retriever is not indexed. Call index(chunks) first.")
        vector = self._model.encode([query], convert_to_numpy=True, normalize_embeddings=True).astype("float32")
        scores, indices = self._index.search(vector, min(top_k, len(self._chunks)))
        return [
            SearchHit(score=float(score), chunk=self._chunks[int(index)])
            for score, index in zip(scores[0], indices[0]) if index >= 0
        ]

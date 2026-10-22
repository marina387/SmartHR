"""Совместимая обёртка для загрузки документов для RAG-демо."""

from __future__ import annotations

from src.core.loaders import LoadedDocument, load_document, load_documents_from_folder, load_hr_documents

__all__ = ["LoadedDocument", "load_document", "load_documents_from_folder", "load_hr_documents"]

# -*- coding: utf-8 -*-
"""Файловое хранилище обратной связи по оценкам кандидатов."""

from pathlib import Path
from typing import Any, Dict, List

from src.storage.base_storage import BaseStorage


class FeedbackStorage(BaseStorage):
    """Хранит записи корректировок оценок в JSON-файле."""

    def __init__(self, file_path: str | Path | None = None) -> None:
        super().__init__(file_path or "data/feedback.json", "FB_")

    def get_all(self) -> List[Dict[str, Any]]:
        """Возвращает все записи обратной связи."""
        return sorted(self._load().values(), key=lambda item: str(item.get("created_at", "")), reverse=True)

    def get_by_candidate(self, candidate_id: str) -> List[Dict[str, Any]]:
        """Возвращает обратную связь по конкретному кандидату."""
        items = self._load().values()
        filtered = [item for item in items if str(item.get("candidate_id", "")) == candidate_id]
        return sorted(filtered, key=lambda item: str(item.get("created_at", "")), reverse=True)

    def save(self, feedback: Dict[str, Any]) -> None:
        """Создаёт или обновляет запись обратной связи."""
        payload = dict(feedback)
        feedback_id = str(payload.get("feedback_id", payload.get("id", ""))).strip() or self._generate_id()
        payload["feedback_id"] = feedback_id
        payload["id"] = feedback_id
        data = self._load()
        data[feedback_id] = payload
        self._save(data)

    def list_all(self) -> List[Dict[str, Any]]:
        """Совместимость со старым API."""
        return self.get_all()

    def list_by_candidate(self, candidate_id: str) -> List[Dict[str, Any]]:
        """Совместимость со старым API."""
        return self.get_by_candidate(candidate_id)

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Совместимость со старым API."""
        record = dict(payload)
        self.save(record)
        return record

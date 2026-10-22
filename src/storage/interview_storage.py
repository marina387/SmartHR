# -*- coding: utf-8 -*-
"""Файловое хранилище интервью кандидатов."""

from pathlib import Path
from typing import Any, Dict, List

from src.storage.base_storage import BaseStorage


class InterviewStorage(BaseStorage):
    """Работает с JSON-файлом интервью в формате словаря по ID."""

    def __init__(self, file_path: str | Path | None = None) -> None:
        super().__init__(file_path or "data/interviews.json", "INT_")

    def get_all(self) -> List[Dict[str, Any]]:
        """Возвращает все интервью."""
        return sorted(self._load().values(), key=lambda item: str(item.get("id", "")), reverse=True)

    def get_by_id(self, interview_id: str) -> Dict[str, Any] | None:
        """Возвращает интервью по ID."""
        key = str(interview_id).strip()
        if not key:
            return None
        interview = self._load().get(key)
        return interview if isinstance(interview, dict) else None

    def get_by_candidate(self, candidate_id: str) -> List[Dict[str, Any]]:
        """Возвращает интервью конкретного кандидата."""
        items = self._load().values()
        filtered = [item for item in items if str(item.get("candidate_id", "")) == candidate_id]
        return sorted(filtered, key=lambda item: (str(item.get("date", "")), str(item.get("time", ""))))

    def save(self, interview: Dict[str, Any]) -> None:
        """Создаёт или обновляет интервью."""
        payload = dict(interview)
        interview_id = str(payload.get("id", "")).strip() or self._generate_id()
        payload["id"] = interview_id
        data = self._load()
        data[interview_id] = payload
        self._save(data)

    def delete(self, interview_id: str) -> None:
        """Удаляет интервью по ID."""
        key = str(interview_id).strip()
        if not key:
            return False
        data = self._load()
        existed = key in data
        data.pop(key, None)
        self._save(data)
        return existed

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

    def update(self, interview_id: str, payload: Dict[str, Any]) -> Dict[str, Any] | None:
        """Обновляет запись интервью по ID."""
        current = self.get_by_id(interview_id)
        if not current:
            return None
        merged = {**current, **payload, "id": interview_id}
        data = self._load()
        data[interview_id] = merged
        self._save(data)
        return merged

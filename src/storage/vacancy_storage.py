# -*- coding: utf-8 -*-
"""Файловое хранилище вакансий."""

from pathlib import Path
from typing import Any, Dict, List

from src.storage.base_storage import BaseStorage


class VacancyStorage(BaseStorage):
    """Работает с JSON-файлом вакансий в формате словаря по ID."""

    def __init__(self, file_path: str | Path | None = None) -> None:
        super().__init__(file_path or "data/vacancies.json", "VAC_")

    def get_all(self) -> List[Dict[str, Any]]:
        """Возвращает все вакансии."""
        return list(self._load().values())

    def get_by_id(self, vacancy_id: str) -> Dict[str, Any] | None:
        """Возвращает вакансию по ID."""
        key = str(vacancy_id).strip()
        if not key:
            return None
        vacancy = self._load().get(key)
        return vacancy if isinstance(vacancy, dict) else None

    def save(self, vacancy: Dict[str, Any]) -> None:
        """Создаёт или обновляет вакансию."""
        payload = dict(vacancy)
        vacancy_id = str(payload.get("id", "")).strip() or self._generate_id()
        payload["id"] = vacancy_id
        data = self._load()
        data[vacancy_id] = payload
        self._save(data)

    def delete(self, vacancy_id: str) -> None:
        """Удаляет вакансию по ID."""
        key = str(vacancy_id).strip()
        if not key:
            return
        data = self._load()
        data.pop(key, None)
        self._save(data)

    def load_all(self) -> List[Dict[str, Any]]:
        """Совместимость со старым API."""
        return self.get_all()

    def save_all(self, items: List[Dict[str, Any]]) -> None:
        """Сохраняет полный список вакансий."""
        payload = {}
        for item in items:
            key = str(item.get("id", "")).strip()
            if key:
                payload[key] = item
        self._save(payload)

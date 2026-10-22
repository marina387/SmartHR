# -*- coding: utf-8 -*-
"""Файловое хранилище шаблонов вакансий."""

from pathlib import Path
from typing import Any, Dict, List

from src.storage.base_storage import BaseStorage


class TemplateStorage(BaseStorage):
    """Работает с JSON-файлом шаблонов в формате словаря по ID."""

    def __init__(self, file_path: str | Path | None = None) -> None:
        super().__init__(file_path or "data/templates.json", "template_")

    def get_all(self) -> List[Dict[str, Any]]:
        """Возвращает все шаблоны."""
        return list(self._load().values())

    def get_by_id(self, template_id: str) -> Dict[str, Any] | None:
        """Возвращает шаблон по ID."""
        key = str(template_id).strip()
        if not key:
            return None
        template = self._load().get(key)
        return template if isinstance(template, dict) else None

    def save(self, template: Dict[str, Any]) -> None:
        """Создаёт или обновляет шаблон."""
        payload = dict(template)
        template_id = str(payload.get("id", "")).strip() or self._generate_id()
        payload["id"] = template_id
        data = self._load()
        data[template_id] = payload
        self._save(data)

    def delete(self, template_id: str) -> None:
        """Удаляет шаблон по ID."""
        key = str(template_id).strip()
        if not key:
            return
        data = self._load()
        data.pop(key, None)
        self._save(data)

    def increment_usage(self, template_id: str) -> None:
        """Увеличивает счётчик использования шаблона."""
        template = self.get_by_id(template_id)
        if not template:
            return
        updated = {**template, "usage_count": int(template.get("usage_count", 0)) + 1}
        data = self._load()
        data[str(template["id"])] = updated
        self._save(data)

    def load_all(self) -> List[Dict[str, Any]]:
        """Совместимость со старым API."""
        return self.get_all()

    def save_all(self, items: List[Dict[str, Any]]) -> None:
        """Сохраняет полный список шаблонов."""
        payload = {}
        for item in items:
            key = str(item.get("id", "")).strip()
            if key:
                payload[key] = item
        self._save(payload)
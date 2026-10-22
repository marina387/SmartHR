# -*- coding: utf-8 -*-
"""Сервис управления шаблонами вакансий."""

from datetime import datetime
from typing import Any, Dict, List

from src.storage.template_storage import TemplateStorage


class TemplateService:
    """CRUD-логика шаблонов и валидация весов критериев."""

    def __init__(self, storage: TemplateStorage) -> None:
        self.storage = storage

    def get_default_weights(self) -> Dict[str, int]:
        """Возвращает дефолтные веса критериев."""
        return {"hard": 50, "soft": 30, "management": 10, "education": 5, "salary": 5}

    def get_all(self) -> List[Dict[str, Any]]:
        """Возвращает список шаблонов."""
        return self.storage.load_all()

    def get_by_id(self, template_id: str) -> Dict[str, Any] | None:
        """Возвращает шаблон по ID."""
        key = str(template_id).strip()
        if not key:
            return None
        return next((item for item in self.get_all() if str(item.get("id", "")) == key), None)

    def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Создаёт новый шаблон."""
        payload = self._normalize_payload(data)
        items = self.get_all()

        template_id = str(data.get("id", "")).strip() or self._next_id(items)
        if any(str(item.get("id", "")) == template_id for item in items):
            raise ValueError("Шаблон с таким id уже существует")

        now = datetime.now().isoformat(timespec="seconds")
        record = {
            "id": template_id,
            **payload,
            "usage_count": int(data.get("usage_count", 0) or 0),
            "created_at": now,
            "updated_at": now,
        }
        items.append(record)
        self.storage.save_all(items)
        return record

    def update(self, template_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Обновляет существующий шаблон."""
        key = str(template_id).strip()
        if not key:
            raise ValueError("template_id обязателен")

        items = self.get_all()
        current = next((item for item in items if str(item.get("id", "")) == key), None)
        if not current:
            raise ValueError("Шаблон не найден")

        payload = self._normalize_payload({**current, **data})
        updated = {
            **current,
            **payload,
            "id": key,
            "usage_count": int(current.get("usage_count", 0)),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }

        for idx, item in enumerate(items):
            if str(item.get("id", "")) == key:
                items[idx] = updated
                break

        self.storage.save_all(items)
        return updated

    def delete(self, template_id: str) -> None:
        """Удаляет шаблон по ID."""
        key = str(template_id).strip()
        if not key:
            raise ValueError("template_id обязателен")

        items = self.get_all()
        filtered = [item for item in items if str(item.get("id", "")) != key]
        if len(filtered) == len(items):
            raise ValueError("Шаблон не найден")
        self.storage.save_all(filtered)

    def increment_usage(self, template_id: str) -> Dict[str, Any] | None:
        """Увеличивает счётчик использования шаблона."""
        template = self.get_by_id(template_id)
        if not template:
            return None

        items = self.get_all()
        key = str(template_id).strip()
        updated = {
            **template,
            "usage_count": int(template.get("usage_count", 0)) + 1,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        for idx, item in enumerate(items):
            if str(item.get("id", "")) == key:
                items[idx] = updated
                break
        self.storage.save_all(items)
        return updated

    def _next_id(self, items: List[Dict[str, Any]]) -> str:
        max_num = 0
        for item in items:
            raw_id = str(item.get("id", ""))
            if raw_id.startswith("template_"):
                suffix = raw_id.replace("template_", "", 1)
                if suffix.isdigit():
                    max_num = max(max_num, int(suffix))
        return f"template_{max_num + 1:03d}"

    def _normalize_payload(self, data: Dict[str, Any]) -> Dict[str, Any]:
        name = str(data.get("name", "")).strip() or str(data.get("title", "")).strip()
        if not name:
            raise ValueError("Название шаблона обязательно")

        weights = self._normalize_weights(data.get("weights", {}))
        if sum(weights.values()) != 100:
            raise ValueError("Сумма весов должна быть равна 100")

        return {
            "name": name,
            "title": name,
            "category": str(data.get("category", "Общее")).strip() or "Общее",
            "description": str(data.get("description", "")).strip(),
            "critical_requirements": self._as_list(data.get("critical_requirements")),
            "skills": self._as_list(data.get("skills")),
            "weights": weights,
            "experience_required": str(data.get("experience_required", "")).strip(),
            "education_required": str(data.get("education_required", "")).strip(),
        }

    def _normalize_weights(self, value: Any) -> Dict[str, int]:
        defaults = self.get_default_weights()
        if not isinstance(value, dict):
            return defaults

        result: Dict[str, int] = {}
        for key, default_value in defaults.items():
            raw = value.get(key, default_value)
            try:
                parsed = int(float(raw))
            except (TypeError, ValueError):
                parsed = default_value
            result[key] = max(0, parsed)
        return result

    def _as_list(self, value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [item.strip() for item in value.split("\n") if item.strip()]
        return []
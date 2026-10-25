# -*- coding: utf-8 -*-
"""Сервис управления вакансиями."""

from datetime import datetime
from typing import Any, Dict, List

from src.storage.vacancy_storage import VacancyStorage


class VacancyService:
    """CRUD-логика вакансий и валидация весов критериев."""

    def __init__(self, storage: VacancyStorage) -> None:
        self.storage = storage

    def get_default_weights(self) -> Dict[str, int]:
        """Возвращает дефолтные веса критериев для вакансии."""
        return {"hard": 50, "soft": 30, "management": 10, "education": 5, "salary": 5}

    def get_all(self) -> List[Dict[str, Any]]:
        """Возвращает список вакансий."""
        return self.storage.load_all()

    def get_by_id(self, vacancy_id: str) -> Dict[str, Any] | None:
        """Возвращает вакансию по ID."""
        key = str(vacancy_id).strip()
        if not key:
            return None
        return next((item for item in self.get_all() if str(item.get("id", "")) == key), None)

    def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Создаёт новую вакансию."""
        payload = self._normalize_payload(data)
        items = self.get_all()

        vacancy_id = str(data.get("id", "")).strip() or self._next_id(items)
        if any(str(item.get("id", "")) == vacancy_id for item in items):
            raise ValueError("Вакансия с таким id уже существует")

        now = datetime.now().isoformat(timespec="seconds")
        record = {
            "id": vacancy_id,
            **payload,
            "created_at": now,
            "updated_at": now,
        }
        items.append(record)
        self.storage.save_all(items)
        return record

    def update(self, vacancy_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Обновляет существующую вакансию."""
        key = str(vacancy_id).strip()
        if not key:
            raise ValueError("vacancy_id обязателен")

        items = self.get_all()
        current = next((item for item in items if str(item.get("id", "")) == key), None)
        if not current:
            raise ValueError("Вакансия не найдена")

        payload = self._normalize_payload({**current, **data})
        updated = {
            **current,
            **payload,
            "id": key,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }

        for idx, item in enumerate(items):
            if str(item.get("id", "")) == key:
                items[idx] = updated
                break

        self.storage.save_all(items)
        return updated

    def delete(self, vacancy_id: str) -> None:
        """Удаляет вакансию по ID."""
        key = str(vacancy_id).strip()
        if not key:
            raise ValueError("vacancy_id обязателен")

        items = self.get_all()
        filtered = [item for item in items if str(item.get("id", "")) != key]
        if len(filtered) == len(items):
            raise ValueError("Вакансия не найдена")
        self.storage.save_all(filtered)

    def weights_for_vacancy(self, vacancy_id: str) -> Dict[str, int]:
        """Возвращает веса критериев для конкретной вакансии."""
        vacancy = self.get_by_id(vacancy_id)
        if not vacancy:
            return self.get_default_weights()
        weights = vacancy.get("weights", {})
        return self._normalize_weights(weights)

    def sanitize_weights(self, value: Any) -> Dict[str, int]:
        """Публичная нормализация весов для входящих payload."""
        return self._normalize_weights(value)

    def _next_id(self, items: List[Dict[str, Any]]) -> str:
        max_num = 0
        for item in items:
            raw_id = str(item.get("id", ""))
            if raw_id.startswith("VAC_"):
                suffix = raw_id.replace("VAC_", "", 1)
                if suffix.isdigit():
                    max_num = max(max_num, int(suffix))
        return f"VAC_{max_num + 1:03d}"

    def _normalize_payload(self, data: Dict[str, Any]) -> Dict[str, Any]:
        title = str(data.get("title", "")).strip() or str(data.get("name", "")).strip()
        if not title:
            raise ValueError("Название вакансии обязательно")

        weights = self._normalize_weights(data.get("weights", {}))
        if sum(weights.values()) != 100:
            raise ValueError("Сумма весов должна быть равна 100")

        min_experience = self._as_non_negative_number(data.get("min_experience"), 0)
        max_experience = self._as_non_negative_number(data.get("max_experience"), 40)
        min_salary = self._as_non_negative_number(data.get("min_salary"), 0)
        max_salary = self._as_non_negative_number(data.get("max_salary"), 0)
        if min_experience > max_experience:
            raise ValueError("Минимальный опыт не должен превышать максимальный")
        if max_salary and min_salary > max_salary:
            raise ValueError("Минимальная зарплата не должна превышать максимальную")

        return {
            "title": title,
            "name": title,
            "category": str(data.get("category", "Общее")).strip() or "Общее",
            "description": str(data.get("description", "")).strip(),
            "critical_requirements": self._as_list(data.get("critical_requirements")),
            "default_requirements": self._as_list(data.get("default_requirements")),
            "skills": self._as_list(data.get("skills")),
            "required_skills": self._as_list(data.get("required_skills")) or self._as_list(data.get("critical_requirements")),
            "experience_required": str(data.get("experience_required", "")).strip(),
            "min_experience": min_experience,
            "max_experience": max_experience,
            "education_required": str(data.get("education_required", "")).strip(),
            "required_education": str(data.get("required_education", "none")).strip() or "none",
            "english_required": str(data.get("english_required", "A1")).strip() or "A1",
            "specialization": str(data.get("specialization", data.get("category", ""))).strip(),
            "min_salary": min_salary,
            "max_salary": max_salary,
            "management_required": bool(data.get("management_required", False)),
            "weights": weights,
            "status": str(data.get("status", "active")).strip() or "active",
            "template_id": str(data.get("template_id", "")).strip() or None,
            "created_by": str(data.get("created_by", "HR_SYSTEM")).strip() or "HR_SYSTEM",
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

    def _as_non_negative_number(self, value: Any, default: int) -> int:
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            return default

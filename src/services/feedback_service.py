# -*- coding: utf-8 -*-
"""Сервис сохранения обратной связи по оценке кандидатов."""

from datetime import datetime
from typing import Any, Dict, List

from src.storage.feedback_storage import FeedbackStorage


class FeedbackService:
    """Проверяет и сохраняет корректировки оценок от HR."""

    def __init__(self, storage: FeedbackStorage) -> None:
        self.storage = storage

    def list_by_candidate(self, candidate_id: str) -> List[Dict[str, Any]]:
        """Возвращает обратную связь кандидата."""
        return self.storage.list_by_candidate(candidate_id)

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Сохраняет запись обратной связи после валидации."""
        required = ["candidate_id", "vacancy_id", "original_scores", "corrected_scores", "hr_id"]
        for key in required:
            value = payload.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                raise ValueError(f"Поле '{key}' обязательно")

        original_scores = payload.get("original_scores")
        corrected_scores = payload.get("corrected_scores")
        if not isinstance(original_scores, dict) or not isinstance(corrected_scores, dict):
            raise ValueError("Поля original_scores и corrected_scores должны быть объектами")

        criteria = ["hard", "soft", "management", "education", "salary"]
        for key in criteria:
            if key not in corrected_scores:
                raise ValueError(f"В corrected_scores отсутствует критерий '{key}'")
            score = float(corrected_scores[key])
            if score < 1 or score > 10:
                raise ValueError("Оценки должны быть в диапазоне от 1 до 10")

        feedback_id = self._next_id()
        record = {
            "feedback_id": feedback_id,
            "id": feedback_id,
            "candidate_id": str(payload["candidate_id"]),
            "vacancy_id": str(payload["vacancy_id"]),
            "original_scores": original_scores,
            "corrected_scores": {key: float(corrected_scores[key]) for key in criteria},
            "comment": str(payload.get("comment") or ""),
            "hr_id": str(payload["hr_id"]),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        return self.storage.create(record)

    def _next_id(self) -> str:
        """Генерирует следующий ID записи обратной связи."""
        items = self.storage.list_all()
        max_num = 0
        for item in items:
            raw_id = str(item.get("feedback_id", item.get("id", "")))
            if raw_id.startswith("FDB_"):
                suffix = raw_id.replace("FDB_", "", 1)
                if suffix.isdigit():
                    max_num = max(max_num, int(suffix))
        return f"FDB_{max_num + 1:03d}"

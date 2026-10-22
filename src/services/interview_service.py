# -*- coding: utf-8 -*-
"""Сервис для планирования интервью с кандидатами."""

from datetime import datetime, timedelta
from typing import Any, Dict, List

from src.storage.interview_storage import InterviewStorage
from src.services.app_time import local_now


class InterviewService:
    """Инкапсулирует бизнес-логику работы с интервью."""

    def __init__(self, storage: InterviewStorage) -> None:
        self.storage = storage

    def list_all(self) -> List[Dict[str, Any]]:
        """Возвращает все интервью."""
        return self.storage.list_all()

    def list_by_candidate(self, candidate_id: str) -> List[Dict[str, Any]]:
        """Возвращает интервью кандидата."""
        return self.storage.list_by_candidate(candidate_id)

    def _validate_schedule(self, record, *, excluding=None):
        status = str(record.get("status", "scheduled"))
        if status not in {"scheduled", "completed", "cancelled"}:
            raise ValueError("Неизвестный статус интервью")
        if record.get("format") not in {"online", "offline", "office"}:
            raise ValueError("Выберите формат: онлайн или офис")
        start = datetime.strptime(f"{record['date']} {record['time']}", "%Y-%m-%d %H:%M")
        duration = int(record["duration"])
        if duration <= 0 or duration > 24 * 60:
            raise ValueError("Длительность должна быть от 1 до 1440 минут")
        warnings = []
        if status != "scheduled":
            return warnings
        if start < local_now().replace(tzinfo=None):
            warnings.append("Интервью назначено на прошедшую дату и время.")
        end = start + timedelta(minutes=duration)
        for other in self.storage.list_all():
            if str(other.get("id")) == str(excluding) or other.get("status", "scheduled") != "scheduled":
                continue
            other_start = datetime.strptime(f"{other['date']} {other['time']}", "%Y-%m-%d %H:%M")
            other_end = other_start + timedelta(minutes=int(other["duration"]))
            if start < other_end and other_start < end:
                if str(other["candidate_id"]) == str(record["candidate_id"]):
                    raise ValueError("У кандидата уже назначено интервью в это время.")
                warnings.append(f"В календаре есть пересекающееся интервью {other['id']}. Проверьте доступность HR.")
        return warnings

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Создаёт интервью после базовой валидации данных."""
        required = ["candidate_id", "candidate_name", "vacancy_id", "date", "time", "duration", "format"]
        for key in required:
            if not str(payload.get(key, "")).strip():
                raise ValueError(f"Поле '{key}' обязательно")

        try:
            datetime.strptime(str(payload["date"]), "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("Некорректная дата, ожидается формат YYYY-MM-DD") from exc

        try:
            datetime.strptime(str(payload["time"]), "%H:%M")
        except ValueError as exc:
            raise ValueError("Некорректное время, ожидается формат HH:MM") from exc

        duration = int(payload.get("duration", 0))
        if duration <= 0:
            raise ValueError("Длительность должна быть положительным числом")

        interview_id = self._next_id()
        record = {
            "id": interview_id,
            "candidate_id": str(payload["candidate_id"]),
            "candidate_name": str(payload["candidate_name"]),
            "vacancy_id": str(payload["vacancy_id"]),
            "date": str(payload["date"]),
            "time": str(payload["time"]),
            "duration": duration,
            "format": str(payload["format"]),
            "status": str(payload.get("status") or "scheduled"),
            "notes": str(payload.get("notes") or ""),
        }
        warnings = self._validate_schedule(record)
        saved = self.storage.create(record)
        return {**saved, "warnings": warnings}

    def update(self, interview_id: str, payload: Dict[str, Any]) -> Dict[str, Any] | None:
        """Обновляет интервью."""
        update_payload: Dict[str, Any] = {}
        for key in ["date", "time", "duration", "format", "status", "notes"]:
            if key in payload:
                update_payload[key] = payload[key]

        if "duration" in update_payload:
            update_payload["duration"] = int(update_payload["duration"])
            if update_payload["duration"] <= 0:
                raise ValueError("Длительность должна быть положительным числом")

        if "date" in update_payload:
            datetime.strptime(str(update_payload["date"]), "%Y-%m-%d")
        if "time" in update_payload:
            datetime.strptime(str(update_payload["time"]), "%H:%M")

        current = next((item for item in self.storage.list_all() if str(item.get("id")) == str(interview_id)), None)
        if not current:
            return None
        warnings = self._validate_schedule({**current, **update_payload}, excluding=interview_id)
        updated = self.storage.update(interview_id, update_payload)
        return {**updated, "warnings": warnings} if updated else None

    def delete(self, interview_id: str) -> bool:
        """Удаляет интервью."""
        return self.storage.delete(interview_id)

    def _next_id(self) -> str:
        """Генерирует следующий ID интервью в формате INT_001."""
        items = self.storage.list_all()
        max_num = 0
        for item in items:
            raw_id = str(item.get("id", ""))
            if raw_id.startswith("INT_"):
                suffix = raw_id.replace("INT_", "", 1)
                if suffix.isdigit():
                    max_num = max(max_num, int(suffix))
        return f"INT_{max_num + 1:03d}"

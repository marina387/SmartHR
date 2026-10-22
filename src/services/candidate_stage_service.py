# -*- coding: utf-8 -*-
"""Управление текущим этапом рассмотрения и историей переходов."""

from datetime import datetime
from typing import Any, Dict

from src.config import FUNNEL_STAGES, FUNNEL_TERMINAL_STATUSES
from src.storage.candidate_stage_event_storage import CandidateStageEventStorage
from src.storage.candidate_vacancy_storage import CandidateVacancyStorage


class CandidateStageService:
    def __init__(self, relation_storage: CandidateVacancyStorage, event_storage: CandidateStageEventStorage) -> None:
        self.relation_storage = relation_storage
        self.event_storage = event_storage

    def transition(self, candidate_id: str, vacancy_id: str, to_stage: str, *, changed_by: str = "SYSTEM",
                   reason: str = "", source: str = "system", extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
        allowed = set(FUNNEL_STAGES) | set(FUNNEL_TERMINAL_STATUSES)
        if to_stage not in allowed:
            raise ValueError(f"Неизвестный этап: {to_stage}")
        current = self.relation_storage.find(candidate_id, vacancy_id)
        from_stage = str(current.get("status")) if current else None
        now = datetime.now().isoformat(timespec="seconds")
        record = {
            **(current or {}), **(extra or {}),
            "candidate_id": candidate_id, "vacancy_id": vacancy_id,
            "status": to_stage, "source": (current or {}).get("source", source),
            "created_at": (current or {}).get("created_at", now), "updated_at": now,
        }
        saved = self.relation_storage.save(record)
        if from_stage != to_stage:
            self.event_storage.save({
                "candidate_id": candidate_id, "vacancy_id": vacancy_id,
                "from_stage": from_stage, "to_stage": to_stage,
                "reason": reason, "changed_by": changed_by, "source": source, "created_at": now,
            })
        return saved

    def register_scoring(self, candidate_id: str, vacancy_id: str, result: Dict[str, Any], source: str = "scoring") -> Dict[str, Any]:
        self.transition(candidate_id, vacancy_id, "new", source=source, reason="Кандидат добавлен")
        target = "recommended" if int(result.get("total", 0)) >= 70 else "scored" if int(result.get("total", 0)) >= 40 else "rejected"
        return self.transition(
            candidate_id, vacancy_id, target, source=source, reason="Scoring завершён",
            extra={"total": result.get("total"), "model_probability": result.get("model_probability")},
        )

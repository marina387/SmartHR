# -*- coding: utf-8 -*-
"""Операции добавления и переноса кандидата между вакансиями."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from src.storage.candidate_vacancy_storage import CandidateVacancyStorage
from src.storage.transfer_storage import TransferStorage
from src.services.candidate_stage_service import CandidateStageService


class CandidateVacancyService:
    def __init__(self, storage: CandidateVacancyStorage, transfer_storage: TransferStorage,
                 stage_service: CandidateStageService | None = None) -> None:
        self.storage = storage
        self.transfer_storage = transfer_storage
        self.stage_service = stage_service

    def apply(self, candidate_id: str, from_vacancy_id: str, to_vacancy_id: str, mode: str,
              hr_id: str, comment: str, recommendation: Dict[str, Any]) -> Dict[str, Any]:
        if mode not in {"add", "transfer"}:
            raise ValueError("mode должен быть 'add' или 'transfer'")
        if not candidate_id or not to_vacancy_id or not hr_id:
            raise ValueError("candidate_id, to_vacancy_id и hr_id обязательны")
        if from_vacancy_id == to_vacancy_id:
            raise ValueError("Исходная и целевая вакансии должны отличаться")
        existing = self.storage.find(candidate_id, to_vacancy_id)
        if existing and existing.get("status") not in {"rejected", "withdrawn", "transferred"}:
            raise ValueError("Кандидат уже связан с целевой вакансией")

        now = datetime.now().isoformat(timespec="seconds")
        if mode == "transfer" and from_vacancy_id:
            source = self.storage.find(candidate_id, from_vacancy_id)
            if source:
                if self.stage_service:
                    self.stage_service.transition(candidate_id, from_vacancy_id, "transferred", changed_by=hr_id,
                                                  reason=comment or "Кандидат перенесён", source="transfer")
                else:
                    source.update({"status": "transferred", "updated_at": now})
                    self.storage.save(source)

        target_payload = {
            "candidate_id": candidate_id, "vacancy_id": to_vacancy_id,
            "status": "in_review", "source": "transfer" if mode == "transfer" else "alternative_match",
            "total": recommendation.get("total"),
            "model_probability": recommendation.get("model_probability"),
            "created_at": now, "updated_at": now,
        }
        if self.stage_service:
            target = self.stage_service.transition(
                candidate_id, to_vacancy_id, "in_review", changed_by=hr_id,
                reason=comment or "HR подтвердил альтернативную вакансию",
                source=target_payload["source"], extra=target_payload,
            )
        else:
            target = self.storage.save(target_payload)
        audit = self.transfer_storage.save({
            "candidate_id": candidate_id, "from_vacancy_id": from_vacancy_id,
            "to_vacancy_id": to_vacancy_id, "action": mode,
            "from_total": recommendation.get("current_total"), "to_total": recommendation.get("total"),
            "model_probability": recommendation.get("model_probability"),
            "model_version": recommendation.get("model_version"),
            "used_weights": recommendation.get("used_weights", {}),
            "confirmed_by": hr_id, "comment": comment, "created_at": now,
        })
        return {"application": target, "audit": audit}

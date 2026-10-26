# -*- coding: utf-8 -*-
"""Безопасное архивирование кандидатов, не подходящих активным вакансиям."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from src.config import ALTERNATIVE_MIN_PROBABILITY, ALTERNATIVE_MIN_SCORE, CANDIDATE_RETENTION_DAYS
from src.services.profile_extraction import extract_candidate_profile


class CandidateRetentionService:
    PROTECTED_STAGES = {"interview", "interview_completed", "offer", "hired"}
    ACTIVE_INTERVIEWS = {"scheduled", "completed"}

    def __init__(self, candidate_storage: Any, vacancy_service: Any, scoring_service: Any,
                 relation_storage: Any, interview_service: Any) -> None:
        self.candidates = candidate_storage
        self.vacancies = vacancy_service
        self.scoring = scoring_service
        self.relations = relation_storage
        self.interviews = interview_service

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _candidate(self, candidate_id: str) -> Dict[str, Any]:
        candidate = self.candidates.get_candidate(candidate_id)
        if not candidate:
            raise ValueError("Кандидат не найден")
        return candidate

    def _protection_reason(self, candidate_id: str) -> str | None:
        for relation in self.relations.list_by_candidate(candidate_id):
            if str(relation.get("status", "")).casefold() in self.PROTECTED_STAGES:
                return f"активный этап: {relation.get('status')}"
        for interview in self.interviews.list_by_candidate(candidate_id):
            if str(interview.get("status", "scheduled")).casefold() in self.ACTIVE_INTERVIEWS:
                return "есть активное или завершённое интервью"
        return None

    def evaluate(self, candidate_id: str) -> Dict[str, Any]:
        candidate = self._candidate(candidate_id)
        resume_text = str(candidate.get("resume_text") or "").strip()
        if not resume_text:
            raise ValueError("У кандидата отсутствует текст резюме")
        profile = extract_candidate_profile(resume_text)
        evaluations: List[Dict[str, Any]] = []
        matches: List[Dict[str, Any]] = []
        for vacancy in self.vacancies.get_all():
            if str(vacancy.get("status", "active")).casefold() not in {"active", "активна"}:
                continue
            result = self.scoring.score_candidate(
                resume_text,
                vacancy.get("critical_requirements", []),
                vacancy.get("weights", {}),
                vacancy=vacancy,
                candidate_profile=profile,
            )
            row = {
                "vacancy_id": str(vacancy.get("id", "")),
                "vacancy_title": vacancy.get("title") or vacancy.get("name") or "Без названия",
                "total": int(result.get("total", 0)),
                "model_probability": float(result.get("model_probability") or 0),
                "critical_failures": result.get("critical_failures", []),
                "score_status": result.get("score_status"), "summary": result.get("summary"),
            }
            row["qualified"] = (
                not row["critical_failures"]
                and row["total"] >= ALTERNATIVE_MIN_SCORE
                and row["model_probability"] >= ALTERNATIVE_MIN_PROBABILITY
            )
            evaluations.append(row)
            if row["qualified"]:
                matches.append(row)
        evaluations.sort(key=lambda item: (item["total"], item["model_probability"]), reverse=True)
        return {
            "candidate_id": candidate_id,
            "has_match": bool(matches),
            "matches": matches,
            "evaluations": evaluations,
            "thresholds": {"total": ALTERNATIVE_MIN_SCORE, "model_probability": ALTERNATIVE_MIN_PROBABILITY},
            "protection_reason": self._protection_reason(candidate_id),
        }

    def archive_if_unmatched(self, candidate_id: str, *, source: str = "system") -> Dict[str, Any]:
        assessment = self.evaluate(candidate_id)
        if assessment["has_match"]:
            return {**assessment, "archived": False, "reason": "Найдена подходящая вакансия"}
        if assessment["protection_reason"]:
            return {**assessment, "archived": False, "reason": assessment["protection_reason"]}
        candidate = self._candidate(candidate_id)
        now = self._now()
        candidate.update({
            "lifecycle_status": "archived",
            "archived_at": now.isoformat(),
            "archive_reason": (f"Не найдено подходящих активных вакансий. Проверено вакансий: {len(assessment['evaluations'])}. "
                               f"Для автоматического соответствия нужны подтверждённые обязательные требования, оценка от {ALTERNATIVE_MIN_SCORE}/100 "
                               f"и вероятность модели от {ALTERNATIVE_MIN_PROBABILITY:.0%}. Подробности по каждой вакансии приведены ниже."
                               if assessment['evaluations'] else
                               "Нет активных вакансий для сопоставления. Вывод о соответствии другим должностям не делался."),
            "archive_source": source,
            "delete_after": (now + timedelta(days=CANDIDATE_RETENTION_DAYS)).isoformat(),
            "retention_assessment": assessment,
        })
        self.candidates.save_candidate(candidate)
        return {**assessment, "archived": True, "candidate": candidate}

    def restore(self, candidate_id: str) -> Dict[str, Any]:
        candidate = self._candidate(candidate_id)
        candidate.update({"lifecycle_status": "active", "restored_at": self._now().isoformat()})
        for key in ("archived_at", "archive_reason", "archive_source", "delete_after"):
            candidate.pop(key, None)
        return self.candidates.save_candidate(candidate)

    def reevaluate_archived(self) -> Dict[str, Any]:
        restored, kept, errors = [], [], []
        for candidate in self.candidates.list_candidates():
            if candidate.get("lifecycle_status") != "archived":
                continue
            candidate_id = str(candidate.get("id", ""))
            try:
                assessment = self.evaluate(candidate_id)
                if assessment["has_match"]:
                    self.restore(candidate_id)
                    restored.append({"candidate_id": candidate_id, "matches": assessment["matches"]})
                else:
                    kept.append(candidate_id)
            except ValueError as exc:
                errors.append({"candidate_id": candidate_id, "error": str(exc)})
        return {"restored": restored, "kept_archived": kept, "errors": errors}


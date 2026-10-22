"""Контролируемый доступ чат-ассистента к данным SmartHR."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from src.config import CRITERIA_LABELS, FUNNEL_STAGES


class SmartHRChatTools:
    def __init__(self, candidates: Any, vacancies: Any, relations: Any,
                 scores: Any, interviews: Any, stage_events: Any,
                 alternatives: Any | None = None) -> None:
        self.candidates = candidates
        self.vacancies = vacancies
        self.relations = relations
        self.scores = scores
        self.interviews = interviews
        self.stage_events = stage_events
        self.alternatives = alternatives

    def list_candidates_for_chat(self, *, stage: str | None = None, vacancy_id: str | None = None) -> List[Dict[str, Any]]:
        candidates = self.candidates.list_candidates()
        if stage or vacancy_id:
            matched_ids = {
                str(relation.get("candidate_id"))
                for relation in self.relations.list_all()
                if (not stage or relation.get("status") == stage)
                and (not vacancy_id or str(relation.get("vacancy_id")) == str(vacancy_id))
            }
            candidates = [candidate for candidate in candidates if str(candidate.get("id")) in matched_ids]
        return [candidate for candidate in candidates if candidate.get("lifecycle_status", "active") == "active"]

    def get_candidate(self, candidate_id: str | None) -> Dict[str, Any] | None:
        if not candidate_id:
            return None
        if hasattr(self.candidates, "get_candidate"):
            return self.candidates.get_candidate(str(candidate_id))
        return next((x for x in self.candidates.list_candidates() if str(x.get("id")) == str(candidate_id)), None)

    def get_vacancy(self, vacancy_id: str | None) -> Dict[str, Any] | None:
        if not vacancy_id:
            return None
        if hasattr(self.vacancies, "get_by_id"):
            return self.vacancies.get_by_id(str(vacancy_id))
        return next((x for x in self.vacancies.get_all() if str(x.get("id")) == str(vacancy_id)), None)

    def get_candidate_score(self, candidate_id: str | None, vacancy_id: str | None) -> Dict[str, Any] | None:
        if not candidate_id:
            return None
        history = self.scores.list_by_candidate(str(candidate_id))
        if vacancy_id:
            history = [x for x in history if str(x.get("vacancy_id")) == str(vacancy_id)]
        return history[0] if history else None

    def get_candidate_stage(self, candidate_id: str | None, vacancy_id: str | None) -> Dict[str, Any] | None:
        if not candidate_id or not vacancy_id:
            return None
        return self.relations.find(str(candidate_id), str(vacancy_id))

    def get_interviews(self, candidate_id: str | None) -> List[Dict[str, Any]]:
        return self.interviews.list_by_candidate(str(candidate_id)) if candidate_id else []

    def get_stage_history(self, candidate_id: str | None) -> List[Dict[str, Any]]:
        return self.stage_events.list_by_candidate(str(candidate_id)) if candidate_id else []

    def get_alternative_vacancies(self, candidate_id: str | None, vacancy_id: str | None) -> List[Dict[str, Any]]:
        if not candidate_id or not vacancy_id or self.alternatives is None:
            return []
        try:
            return self.alternatives.find_alternatives(str(candidate_id), str(vacancy_id))["alternatives"]
        except ValueError:
            return []

    @staticmethod
    def explain_score(score: Dict[str, Any] | None) -> List[Dict[str, Any]]:
        if not score:
            return []
        values = score.get("scores") or {}
        weights = score.get("used_weights") or {}
        comments = score.get("comments") or {}
        evidence = score.get("evidence") or {}
        return [
            {
                "criterion": key,
                "label": CRITERIA_LABELS.get(key, key),
                "score": values.get(key),
                "weight": weights.get(key),
                "comment": comments.get(key),
                "evidence": evidence.get(key),
            }
            for key in CRITERIA_LABELS if key in values
        ]

    @staticmethod
    def interview_questions(candidate: Dict[str, Any] | None, vacancy: Dict[str, Any] | None) -> List[str]:
        if not candidate:
            return []
        skills = candidate.get("skills") or []
        position = (vacancy or {}).get("title") or candidate.get("position") or "позиции"
        questions = [
            f"Расскажите о самом сложном проекте, связанном с позицией «{position}».",
            "Как вы проверяете качество результата своей работы?",
            "Приведите пример сложной рабочей ситуации и объясните принятое решение.",
        ]
        if skills:
            questions.insert(1, f"Как вы применяли навык «{skills[0]}» на практике?")
        return questions

    @staticmethod
    def draft_message(kind: str, candidate: Dict[str, Any] | None, vacancy: Dict[str, Any] | None) -> str:
        name = (candidate or {}).get("name") or "кандидат"
        title = (vacancy or {}).get("title") or (vacancy or {}).get("name") or "вакансия"
        if kind == "invitation":
            return f"Здравствуйте, {name}! Приглашаем вас на интервью по вакансии «{title}». Предлагаем согласовать удобные дату и время."
        return f"Здравствуйте, {name}! Благодарим за интерес к вакансии «{title}». На текущем этапе мы не готовы продолжить процесс, но признательны за уделённое время."

    def propose_action(self, message: str, candidate_id: str | None,
                       vacancy_id: str | None, alternatives: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        lowered = message.casefold()
        if not candidate_id:
            return None
        if any(word in lowered for word in ("архивируй", "в архив", "архивировать")):
            return {
                "type": "archive_candidate", "label": "Проверить и архивировать кандидата",
                "payload": {"candidate_id": candidate_id}, "requires_confirmation": True,
            }
        if any(word in lowered for word in ("перенеси", "переведи на вакансию", "перенос")):
            match = re.search(r"\bVAC_[A-Za-z0-9_-]+\b", message, re.IGNORECASE)
            target_id = match.group(0) if match else (alternatives[0].get("vacancy_id") if alternatives else None)
            if target_id:
                target = next((item for item in alternatives if str(item.get("vacancy_id")).casefold() == str(target_id).casefold()), None)
                if target:
                    return {
                        "type": "transfer_candidate", "label": f"Перенести на «{target.get('vacancy_title')}»",
                        "payload": {"candidate_id": candidate_id, "from_vacancy_id": vacancy_id,
                                    "to_vacancy_id": target.get("vacancy_id")},
                        "requires_confirmation": True,
                    }
        stage_aliases = {
            "интервью пройдено": "interview_completed", "интервью": "interview",
            "оффер": "offer", "нанят": "hired", "отказ": "rejected",
            "в работе": "in_review", "рекомендован": "recommended",
        }
        if any(word in lowered for word in ("этап", "переведи", "статус")) and vacancy_id:
            target_stage = next((stage for label, stage in stage_aliases.items() if label in lowered), None)
            if target_stage in set(FUNNEL_STAGES) | {"rejected"}:
                return {
                    "type": "change_stage", "label": f"Изменить этап на «{target_stage}»",
                    "payload": {"candidate_id": candidate_id, "vacancy_id": vacancy_id, "stage": target_stage},
                    "requires_confirmation": True,
                }
        return None

    def context(self, candidate_id: str | None, vacancy_id: str | None, *, include_alternatives: bool = False) -> Dict[str, Any]:
        candidate = self.get_candidate(candidate_id)
        effective_vacancy_id = vacancy_id or (str(candidate.get("vacancy_id")) if candidate and candidate.get("vacancy_id") else None)
        score = self.get_candidate_score(candidate_id, effective_vacancy_id)
        result = {
            "candidate": candidate,
            "vacancy": self.get_vacancy(effective_vacancy_id),
            "score": score,
            "score_explanation": self.explain_score(score),
            "stage": self.get_candidate_stage(candidate_id, effective_vacancy_id),
            "interviews": self.get_interviews(candidate_id),
            "stage_history": self.get_stage_history(candidate_id),
        }
        result["alternatives"] = self.get_alternative_vacancies(candidate_id, effective_vacancy_id) if include_alternatives else []
        return result

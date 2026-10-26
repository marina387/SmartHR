# -*- coding: utf-8 -*-
"""Поиск вакансий, которым кандидат соответствует лучше исходной."""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

from src.config import (
    ALTERNATIVE_MAX_RESULTS,
    ALTERNATIVE_MIN_IMPROVEMENT,
    ALTERNATIVE_MIN_PROBABILITY,
    ALTERNATIVE_MIN_SCORE,
    FUNNEL_STAGES,
)
from src.services.profile_extraction import extract_candidate_profile
from src.services.scoring import CandidateScoringService
from src.services.skill_matching import SkillMatcher
from src.services.vacancy_service import VacancyService
from src.storage.candidate_vacancy_storage import CandidateVacancyStorage
from src.storage.file_storage import FileCandidateStorage

# Порог «сильного матча» — стоит предлагать даже без прироста над текущей.
STRONG_MATCH_SCORE = 75
STRONG_MATCH_PROBABILITY = 0.7
# Семантическое сходство резюме↔вакансия (0..1). Калибруется по evaluation/results.
SEMANTIC_MIN_SIMILARITY = 0.35
SEMANTIC_MARGIN = 0.05
# Активные статусы связи; всё остальное (rejected, archived) не блокирует перенос.
ACTIVE_LINK_STATUSES = {*FUNNEL_STAGES, "active", "in_progress", "активна", "в работе"}


class AlternativeVacancyService:
    def __init__(self, candidate_storage: FileCandidateStorage, vacancy_service: VacancyService,
                 scoring_service: CandidateScoringService, relation_storage: CandidateVacancyStorage,
                 embedding_model=None) -> None:
        self.candidate_storage = candidate_storage
        self.vacancy_service = vacancy_service
        self.scoring_service = scoring_service
        self.relation_storage = relation_storage
        self.skill_matcher = SkillMatcher()
        self._encoder = embedding_model  # ленивая загрузка, если None

    def _get_encoder(self):
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer
            try:
                self._encoder = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2", local_files_only=True)
            except (OSError, RuntimeError) as exc:
                raise ValueError("Семантический поиск альтернатив недоступен: локальная модель поиска отсутствует. Данные кандидата не изменены.") from exc
        return self._encoder

    def _candidate(self, candidate_id: str) -> Dict[str, Any]:
        candidate = next((item for item in self.candidate_storage.list_candidates()
                          if str(item.get("id")) == str(candidate_id)), None)
        if not candidate:
            raise ValueError("Кандидат не найден")
        return candidate

    @staticmethod
    def _vacancy_text(vacancy: Dict[str, Any]) -> str:
        parts = [
            str(vacancy.get("title") or ""),
            str(vacancy.get("description") or ""),
            " ".join(map(str, vacancy.get("required_skills") or vacancy.get("critical_requirements") or [])),
        ]
        return " ".join(p for p in parts if p.strip())

    def _active_linked(self, candidate_id: str) -> set[str]:
        linked = set()
        for item in self.relation_storage.list_by_candidate(candidate_id):
            status = str(item.get("status") or "active").casefold()
            if status in ACTIVE_LINK_STATUSES:
                linked.add(str(item.get("vacancy_id")))
        return linked

    def _semantic_sims(self, resume_text: str, vacancies: List[Dict[str, Any]]) -> Dict[str, float]:
        if not vacancies:
            return {}
        enc = self._get_encoder()
        r_vec = enc.encode(resume_text, normalize_embeddings=True)
        v_vecs = enc.encode([self._vacancy_text(v) for v in vacancies], normalize_embeddings=True)
        sims = (v_vecs @ r_vec).tolist()
        return {str(v.get("id")): float(s) for v, s in zip(vacancies, sims)}

    def find_alternatives(self, candidate_id: str, current_vacancy_id: str,
                          limit: int = ALTERNATIVE_MAX_RESULTS) -> Dict[str, Any]:
        candidate = self._candidate(candidate_id)
        resume_text = str(candidate.get("resume_text") or "")
        if not resume_text.strip():
            raise ValueError("У кандидата отсутствует текст резюме")
        profile = extract_candidate_profile(resume_text)

        # Пересчитываем текущую вакансию, не доверяем candidate["total"].
        current_vacancy = next(
            (v for v in self.vacancy_service.get_all() if str(v.get("id")) == str(current_vacancy_id)),
            None,
        )
        if current_vacancy is None:
            raise ValueError("Текущая вакансия не найдена")
        current_score = self.scoring_service.score_candidate(
            resume_text, current_vacancy.get("critical_requirements", []),
            current_vacancy.get("weights", {}), vacancy=current_vacancy, candidate_profile=profile,
        )
        current_total = int(current_score["total"])

        linked = self._active_linked(candidate_id)

        # Отбираем кандидатов на сравнение за один проход.
        pool = [v for v in self.vacancy_service.get_all()
                if str(v.get("id", ""))
                and str(v.get("id")) != current_vacancy_id
                and str(v.get("id")) not in linked
                and str(v.get("status", "active")).casefold() in {"active", "активна"}]

        # Один батч-вызов энкодера вместо N отдельных.
        sims = self._semantic_sims(resume_text, pool)

        results: List[Dict[str, Any]] = []
        for vacancy in pool:
            vacancy_id = str(vacancy.get("id", ""))
            critical = vacancy.get("critical_requirements", [])
            score = self.scoring_service.score_candidate(
                resume_text, critical, vacancy.get("weights", {}),
                vacancy=vacancy, candidate_profile=profile,
            )
            if score.get("critical_failures"):
                continue
            probability = float(score.get("model_probability") or 0)
            total = int(score["total"])
            improvement = total - current_total
            semantic = float(sims.get(vacancy_id, 0.0))

            is_strong = total >= STRONG_MATCH_SCORE and probability >= STRONG_MATCH_PROBABILITY
            has_improvement = improvement >= ALTERNATIVE_MIN_IMPROVEMENT
            # Перенос предлагаем, если матч сильный ИЛИ есть заметный прирост,
            # и при этом семантическое сходство выше порога.
            if not (is_strong or has_improvement):
                continue
            if total < ALTERNATIVE_MIN_SCORE or probability < ALTERNATIVE_MIN_PROBABILITY:
                continue
            if semantic < SEMANTIC_MIN_SIMILARITY:
                continue

            skill_details = self.skill_matcher.compare(
                profile.get("skills"), vacancy.get("required_skills") or critical,
            )
            results.append({
                "vacancy_id": vacancy_id,
                "vacancy_title": vacancy.get("title") or vacancy.get("name") or "Без названия",
                "total": total, "current_total": current_total,
                "score_improvement": improvement,
                "model_probability": probability,
                "semantic_similarity": round(semantic, 4),
                "strong_match": is_strong,
                "model_version": score.get("model_version"),
                "used_weights": score.get("used_weights", {}),
                "scores": score.get("scores", {}),
                "evidence": score.get("evidence", {}),
                "comments": score.get("comments", {}), "summary": score.get("summary"),
                "requirement_checks": score.get("requirement_checks", []), "score_status": score.get("score_status", "calculated"),
                "matched_skills": skill_details["matches"],
                "missing_skills": skill_details["missing"],
                "reason": self._reason(score, skill_details, semantic),
            })

        # Ранжируем: сначала сильные матчи, затем по итоговому баллу и вероятности.
        results.sort(key=lambda x: (x["strong_match"], x["total"], x["model_probability"]), reverse=True)
        return {
            "candidate_id": candidate_id,
            "current_vacancy_id": current_vacancy_id,
            "current_total": current_total,
            "alternatives": results[:max(1, min(int(limit), 10))],
        }

    @staticmethod
    def _reason(score: Dict[str, Any], skill_details: Dict[str, Any], semantic: float) -> str:
        matched = len(skill_details["matches"])
        required = skill_details["required_count"]
        return (f"Итог {score['total']}/100, ML-вероятность {score['model_probability']:.1%}, "
                f"навыки {matched}/{required}, семантическое сходство {semantic:.2f}")

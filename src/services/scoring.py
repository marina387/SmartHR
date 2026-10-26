# -*- coding: utf-8 -*-
"""Оценка кандидата через обученную модель и веса вакансии."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from src.config import CRITERIA, CRITERIA_LABELS
from src.matching_service import MatchingService
from src.services.profile_extraction import extract_candidate_profile
from src.services.skill_matching import SkillMatcher
from src.services.management_evidence import management_evidence


def get_status_decision(total: int) -> Tuple[str, str]:
    if total >= 70:
        return "green", "Рекомендован"
    if total >= 40:
        return "yellow", "Требует проверки"
    return "red", "Отклонен"


class CandidateScoringService:
    """Совмещает ML-прогноз с настраиваемыми весами критериев."""

    default_weights = {"hard": 50, "soft": 30, "management": 10, "education": 5, "salary": 5}

    def __init__(self, matching_service: MatchingService | None = None) -> None:
        self.criteria = CRITERIA
        self.criteria_labels = CRITERIA_LABELS
        self.matching_service = matching_service or MatchingService()
        self.skill_matcher = SkillMatcher()

    def score_candidate(self, candidate_text: str, critical_requirements: List[str], weights: Dict[str, int],
                        vacancy: Dict[str, Any] | None = None,
                        candidate_profile: Dict[str, Any] | None = None) -> Dict[str, Any]:
        safe_weights = self._normalize_weights(weights)
        # A caller may add filters, but cannot remove the vacancy's mandatory ones.
        critical_requirements = self.effective_requirements(vacancy, critical_requirements)
        profile = candidate_profile or extract_candidate_profile(candidate_text)
        critical_failures = self.check_critical_filters(candidate_text, critical_requirements, profile)
        requirement_checks = [
            {"requirement": requirement, "status": "not_confirmed" if requirement in critical_failures else "confirmed",
             "explanation": (f"В резюме не найдено подтверждение требования «{requirement}». Это не доказывает отсутствия навыка; требуется уточнение."
                             if requirement in critical_failures else
                             f"Упоминание требования «{requirement}» найдено в тексте или списке навыков. Уровень владения и практический стаж эта проверка отдельно не подтверждает.")}
            for requirement in critical_requirements
        ]
        if critical_failures:
            from src.services.score_explanation import BLOCKED_COMMENT
            return {
                "status": "red", "decision": "Отклонен", "total": 0,
                "scores": {}, "comments": {key: BLOCKED_COMMENT for key in self.criteria}, "critical_failures": critical_failures,
                "score_status": "blocked_by_requirements", "requirement_checks": requirement_checks,
                "summary": "Расчёт соответствия остановлен: не подтверждены обязательные требования вакансии. Остальные критерии и вероятность модели не рассчитывались.",
                "message": "Не подтверждены обязательные требования: " + ", ".join(critical_failures),
                "model_probability": None, "model_version": self.matching_service.model_path.stem,
                "features": {}, "missing_fields": profile.get('missing_fields', []), "used_weights": safe_weights,
            }

        model_vacancy = self._model_vacancy(vacancy or {}, critical_requirements)
        prediction = self.matching_service.predict(profile, model_vacancy)
        evaluation = self.evaluate(profile, model_vacancy, prediction)
        total = self.calculate_total(evaluation["scores"], safe_weights)
        status, decision = get_status_decision(total)
        return {
            "status": status, "decision": decision, "total": total,
            "score_status": "calculated", "requirement_checks": requirement_checks,
            "summary": "Итог — сумма оценок критериев с учётом весов вакансии и округлением до целого.",
            "scores": evaluation["scores"], "comments": evaluation["comments"],
            "evidence": evaluation["evidence"], "critical_failures": [], "message": "",
            "model_probability": round(prediction["probability"], 6),
            "model_class": prediction["predicted_class"],
            "model_version": prediction["model_version"],
            "features": prediction["features"],
            "missing_fields": profile.get("missing_fields", []),
            "used_weights": safe_weights,
        }

    @staticmethod
    def effective_requirements(vacancy, additional=None) -> List[str]:
        result, seen = [], set()
        for values in ((vacancy or {}).get("critical_requirements"), additional):
            if isinstance(values, str):
                values = values.splitlines()
            for value in values or []:
                text = str(value).strip()
                if text and text.casefold() not in seen:
                    result.append(text)
                    seen.add(text.casefold())
        return result

    def _model_vacancy(self, vacancy: Dict[str, Any], critical_requirements: List[str]) -> Dict[str, Any]:
        result = dict(vacancy)
        result["required_skills"] = result.get("required_skills") or result.get("critical_requirements") or critical_requirements
        result.setdefault("min_experience", self._experience_number(result.get("experience_required"), 0))
        result.setdefault("max_experience", 40)
        result.setdefault("required_education", "none")
        result.setdefault("english_required", "A1")
        result.setdefault("specialization", result.get("category") or result.get("title") or "")
        result.setdefault("max_salary", 0)
        return result

    @staticmethod
    def _experience_number(value: Any, default: int) -> int:
        import re
        match = re.search(r"\d+", str(value or ""))
        return int(match.group()) if match else default

    def evaluate(self, profile: Dict[str, Any], vacancy: Dict[str, Any], prediction: Dict[str, Any]) -> Dict[str, Any]:
        """Формирует объяснимые баллы; hard основан на реальном ML-прогнозе."""
        features = prediction["features"]
        resume_lower = str(profile.get("resume_text") or "").casefold()
        hard = round(prediction["probability"] * 10, 1)

        management_required = bool(vacancy.get("management_required"))
        management_state = management_evidence(resume_lower)
        management_found = management_state == 'mentioned'
        management = 10.0 if management_found else (2.0 if management_required else 5.0)

        soft_requirements = MatchingService._items(vacancy.get("soft_skills") or vacancy.get("skills"))
        if soft_requirements:
            matched_soft = [item for item in soft_requirements if item in resume_lower]
            soft = round(10 * len(matched_soft) / len(soft_requirements), 1)
        else:
            matched_soft = []
            soft = 5.0

        # В новой модели 11 фич: cand_edu_idx, vac_edu_idx вместо edu_match.
        # Вычисляем edu_match из индексов.
        cand_edu = int(features.get("cand_edu_idx", 0))
        vac_edu = int(features.get("vac_edu_idx", 0))
        edu_match = cand_edu >= vac_edu
        education = 5.0 if "education" in profile.get("missing_fields", []) else (10.0 if edu_match else 2.0)

        # В новой модели нет salary_ratio — считаем сами из сырых значений.
        exp_sal = float(features.get("expected_salary", 0) or 0)
        max_sal = float(features.get("max_salary", 0) or 0)
        salary_ratio = (exp_sal / max_sal) if max_sal > 0 else 1.0
        salary = self._salary_score(profile, vacancy, salary_ratio)
        scores = {"hard": hard, "management": management, "soft": soft, "education": education, "salary": salary}
        evidence = {
            "hard": f"ML-вероятность соответствия: {prediction['probability']:.1%}. Это прогноз для данной вакансии на основе распознанных полей, а не общая оценка квалификации",
            "management": ("Найдена формулировка об опыте руководства; длительность и масштаб требуют уточнения"
                           if management_found else
                           ("В тексте есть противоречивые сведения об управленческом опыте; требуется уточнение. "
                            if management_state == 'conflicting' else
                            "В тексте указано отсутствие управленческого опыта. " if management_state == 'denied' else
                            "Управленческий опыт не подтверждён текстом резюме. ")
                           + ("Применена оценка 2/10, поскольку вакансия требует управления" if management_required
                              else "Требование управления не задано; применена нейтральная оценка 5/10")),
            "soft": (f"Совпало формулировок soft skills в тексте: {len(matched_soft)} из {len(soft_requirements)}; это не проверка личных качеств на практике"
                     if soft_requirements else "Требования к soft skills не заданы; применена нейтральная оценка 5/10"),
            "education": ("Образование не указано или не распознано; применена нейтральная оценка 5/10"
                          if "education" in profile.get('missing_fields', []) else
                          f"Распознанный уровень образования: {profile.get('education')}; требуемый уровень: {vacancy.get('required_education')}. "
                          + ("Уровень соответствует; соответствие специальности отдельно не подтверждается" if edu_match
                             else "Распознанный уровень ниже требуемого")),
            "salary": ("Зарплатные ожидания не указаны или не распознаны; применена нейтральная оценка 5/10"
                       if profile.get('expected_salary') is None else
                       "Бюджет вакансии не указан; сравнение не выполнялось, применена нейтральная оценка 5/10"
                       if not vacancy.get('max_salary') else
                       f"Ожидания: {profile['expected_salary']}; бюджет: {vacancy['max_salary']}. Отношение ожиданий к бюджету: {salary_ratio:.2f}"),
        }
        comments = {key: self.generate_comment(key, value, evidence[key]) for key, value in scores.items()}
        return {"scores": scores, "comments": comments, "evidence": evidence}

    @staticmethod
    def _salary_score(profile: Dict[str, Any], vacancy: Dict[str, Any], ratio: float) -> float:
        if profile.get("expected_salary") is None or not vacancy.get("max_salary"):
            return 5.0
        if ratio <= 1:
            return 10.0
        if ratio <= 1.2:
            return 6.0
        return 2.0

    def check_critical_filters(self, resume_text: str, critical_requirements: List[str],
                               profile: Dict[str, Any] | None = None) -> List[str]:
        resume_lower = str(resume_text or "").casefold()
        skills = (profile or {}).get("skills", [])
        missing = []
        for requirement in critical_requirements or []:
            req = str(requirement).strip()
            if not req or req.casefold() in resume_lower:
                continue
            if self.skill_matcher.compare(skills, [req])["score"] >= 1:
                continue
            missing.append(req)
        return missing

    def calculate_total(self, scores: Dict[str, float], weights: Dict[str, int]) -> int:
        normalized = self._normalize_weights(weights)
        total_weight = sum(normalized.values())
        if not scores or not total_weight:
            return 0
        weighted = sum(max(0.0, min(10.0, float(scores.get(key, 0)))) * normalized[key] for key in self.criteria)
        return max(0, min(100, round(weighted / total_weight * 10)))

    def get_status_decision(self, total: int) -> Tuple[str, str]:
        return get_status_decision(total)

    def _normalize_weights(self, weights: Dict[str, int] | None) -> Dict[str, int]:
        result = dict(self.default_weights)
        if not isinstance(weights, dict):
            return result
        for key in self.criteria:
            try:
                result[key] = max(0, int(float(weights.get(key, result[key]))))
            except (TypeError, ValueError):
                pass
        return result

    def generate_comment(self, criterion: str, score: float, evidence: str = "") -> str:
        if 'нейтральн' in evidence or 'не указано' in evidence or 'не распознано' in evidence:
            return f"По критерию «{self.criteria_labels[criterion]}»: {evidence}. Нехватка данных не означает отсутствия навыка."
        level = "Высокий уровень" if score >= 8 else "Средний уровень" if score >= 5 else "Низкий уровень"
        suffix = f" {evidence}." if evidence else ""
        return f"{level} по критерию «{self.criteria_labels[criterion]}».{suffix}"

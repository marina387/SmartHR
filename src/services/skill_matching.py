# -*- coding: utf-8 -*-
"""Нормализация и объяснимое сопоставление профессиональных навыков."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from rapidfuzz.fuzz import ratio

from src.config import FUZZY_SKILL_THRESHOLD


SKILL_ALIASES = {
    "postgres": "postgresql", "postgres sql": "postgresql",
    "js": "javascript", "java script": "javascript",
    "ts": "typescript", "docker-compose": "docker compose",
    "restful api": "rest api", "restful": "rest api",
    "питон": "python", "докер": "docker",
    "руководитель проекта": "project manager", "менеджер проекта": "project manager",
}


class SkillMatcher:
    def __init__(self, threshold: int = FUZZY_SKILL_THRESHOLD) -> None:
        self.threshold = threshold

    @staticmethod
    def _items(value: Any) -> List[str]:
        if isinstance(value, (list, tuple, set)):
            raw: Iterable[Any] = value
        elif value is None:
            raw = []
        else:
            raw = re.split(r"[,;|]", str(value))
        return [str(item).strip() for item in raw if str(item).strip()]

    @staticmethod
    def normalize(value: str) -> str:
        text = str(value or "").casefold().strip()
        text = re.sub(r"[^\w+#. -]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return SKILL_ALIASES.get(text, text)

    def compare(self, candidate_skills: Any, required_skills: Any) -> Dict[str, Any]:
        candidates = self._items(candidate_skills)
        required = self._items(required_skills)
        unused = set(range(len(candidates)))
        matches: List[Dict[str, Any]] = []
        missing: List[str] = []

        for required_skill in required:
            normalized_required = self.normalize(required_skill)
            best: tuple[int, float, str] | None = None
            for index in unused:
                normalized_candidate = self.normalize(candidates[index])
                if normalized_candidate == normalized_required:
                    match_type = "exact" if candidates[index].casefold().strip() == required_skill.casefold().strip() else "alias"
                    best = (index, 100.0, match_type)
                    break
                similarity = float(ratio(normalized_candidate, normalized_required))
                if similarity >= self.threshold and (best is None or similarity > best[1]):
                    best = (index, similarity, "fuzzy")
            if best is None:
                missing.append(required_skill)
                continue
            index, similarity, match_type = best
            unused.remove(index)
            matches.append({
                "required": required_skill, "candidate": candidates[index],
                "normalized": normalized_required, "similarity": round(similarity, 1),
                "match_type": match_type,
            })

        score = len(matches) / len(required) if required else 0.5
        return {"score": score, "matches": matches, "missing": missing, "required_count": len(required)}

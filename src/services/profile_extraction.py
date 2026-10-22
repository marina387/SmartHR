# -*- coding: utf-8 -*-
"""Извлечение структурированного профиля кандидата из текста резюме.

Парсит как структурированные поля («Навыки: …», «Опыт: 3 года»),
так и свободный текст («Python разработчик, 3 года опыта, Django, PostgreSQL»).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


EDUCATION_LEVELS = {
    "none": 0, "среднее": 0, "колледж": 0, "техникум": 0,
    "bachelor": 1, "бакалавр": 1, "высшее": 1, "университет": 1, "институт": 1,
    "master": 2, "магистр": 2, "специалитет": 2, "специалист": 2,
    "phd": 3, "кандидат наук": 3, "доктор наук": 3, "аспирант": 3,
}

# Известные технологии — ищем в свободном тексте.
KNOWN_SKILLS = [
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "rust",
    "django", "fastapi", "flask", "react", "vue", "angular",
    "postgresql", "mysql", "mongodb", "sql", "redis", "oracle",
    "docker", "kubernetes", "linux", "git", "ci/cd", "jenkins",
    "excel", "1с", "1c", "sap", "rest", "api", "html", "css",
    "autocad", "solidworks", "компас", "photoshop", "figma",
    "машинное обучение", "ml", "ai", "нейросет",
]

# Ключевые слова для специализации (должность -> сфера).
SPEC_KEYWORDS = {
    "IT": ["python", "java", "разработчик", "программист", "developer", "backend",
           "frontend", "devops", "тестировщик", "qa", "аналитик данных", "data scientist"],
    "Медицина": ["врач", "медсестр", "медбрат", "фельдшер", "санитар", "акушер",
                 "стоматолог", "терапевт", "педиатр", "хирург"],
    "Продажи": ["продавец", "кассир", "менеджер по продажам", "sales", "торговый представитель"],
    "Финансы": ["бухгалтер", "экономист", "финансист", "аудитор", "кредитный"],
    "Образование": ["учитель", "воспитатель", "преподаватель", "педагог", "репетитор"],
    "Логистика": ["логист", "водитель", "экспедитор", "кладовщик", "курьер", "диспетчер"],
    "Производство": ["инженер", "технолог", "слесарь", "токарь", "сварщик", "монтажник"],
    "Строительство": ["строитель", "каменщик", "маляр", "штукатур", "прораб"],
    "Сервис": ["повар", "официант", "бармен", "бариста", "администратор", "уборщик"],
    "Менеджмент": ["менеджер", "руководитель", "директор", "начальник", "заведующий"],
    "Юриспруденция": ["юрист", "адвокат", "нотариус", "юрисконсульт"],
}


def _line_value(text: str, labels: List[str]) -> str:
    pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?im)^\s*(?:{pattern})\s*:\s*(.+?)\s*$", text)
    return match.group(1).strip() if match else ""


def _split_list(value: str) -> List[str]:
    return [item.strip() for item in re.split(r"[,;|]", value) if item.strip()]


def _education_level(text: str) -> str | None:
    lowered = text.lower()
    best: tuple[int, str] | None = None
    canonical = {0: "none", 1: "bachelor", 2: "master", 3: "phd"}
    for marker, rank in EDUCATION_LEVELS.items():
        if marker in lowered and (best is None or rank > best[0]):
            best = (rank, canonical[rank])
    return best[1] if best else None


def _extract_skills_from_text(source: str) -> List[str]:
    """Ищет известные технологии в свободном тексте."""
    lowered = source.lower()
    found = []
    for skill in KNOWN_SKILLS:
        if skill in lowered:
            found.append(skill)
    return found


def _extract_specialization(source: str) -> str | None:
    lowered = source.lower()
    for spec, keywords in SPEC_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return spec
    return None


def _extract_experience(source: str) -> float | None:
    """Ищет «3 года опыта», «опыт 3 года», «3+ лет», «стаж 3 года»."""
    patterns = [
        r"(?i)(\d+(?:[.,]\d+)?)\+?\s*(?:года|лет|год)\s*(?:опыта|работы|стажа)",
        r"(?i)(?:опыт|стаж)(?:\s+работы)?\s*:?\s*(\d+(?:[.,]\d+)?)\s*(?:года|лет|год)",
        r"(?i)(?:опыт|стаж)\s*:?\s*(\d+(?:[.,]\d+)?)",
    ]
    for pattern in patterns:
        m = re.search(pattern, source)
        if m:
            try:
                return float(m.group(1).replace(",", "."))
            except ValueError:
                pass
    return None


def extract_candidate_profile(text: str) -> Dict[str, Any]:
    """Извлекает поля модели из текста резюме.

    Сначала ищет структурированные поля («Навыки: …», «Опыт: 3 года»).
    Если не находит — парсит свободный текст по ключевым словам.
    """
    source = str(text or "").strip()

    # 1. Структурированные поля
    skills_value = _line_value(source, ["Навыки", "Ключевые навыки", "Skills"])
    specialization = _line_value(source, ["Специализация", "Должность", "Позиция", "Position"])
    education_text = _line_value(source, ["Образование", "Education"])
    portfolio_value = _line_value(source, ["Портфолио", "Portfolio"])

    # 2. Свободный текст (fallback)
    skills = _split_list(skills_value) if skills_value else []
    if not skills:
        skills = _extract_skills_from_text(source)

    experience_years = _extract_experience(source)

    if not specialization:
        specialization = _extract_specialization(source)

    salary_match = re.search(
        r"(?i)(?:ожидаемая\s+зарплата|зарплатные\s+ожидания|зарплата)\s*:?\s*([\d\s]+)", source
    )
    english_match = re.search(r"(?i)(?:английский|english)\s*:?\s*(A1|A2|B1|B2|C1|C2)", source)

    profile: Dict[str, Any] = {
        "skills": skills,
        "experience_years": experience_years,
        "specialization": specialization or None,
        "education": _education_level(education_text or source),
        "english_level": english_match.group(1).upper() if english_match else None,
        "expected_salary": int(re.sub(r"\s+", "", salary_match.group(1))) if salary_match and re.sub(r"\s+", "", salary_match.group(1)).isdigit() else None,
        "has_portfolio": bool(portfolio_value) if portfolio_value else None,
        "resume_text": source,
    }

    required = ["skills", "experience_years", "specialization", "education",
                "english_level", "expected_salary", "has_portfolio"]
    profile["missing_fields"] = [key for key in required if profile.get(key) in (None, "", [])]
    return profile
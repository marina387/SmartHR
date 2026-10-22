# -*- coding: utf-8 -*-
"""Конвертирует сырые данные trudvsem в формат SmartHR.

Вход:
    data/trudvsem/raw/vacancy.csv   (разделитель |)
    data/trudvsem/raw/cv.csv        (разделитель |)

Выход (совместим с matching_service.prepare_features):
    data/trudvsem/processed/vacancies.csv
    data/trudvsem/processed/candidates.csv
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any, List

import pandas as pd

# ------------------------------------------------------------------ маппинги

EDUCATION_LEVELS = ["none", "high_school", "associate", "bachelor", "master", "phd"]

EDUCATION_PATTERNS = [
    (r"подготовка кадров высшей|аспирант|кандидат наук", "phd"),
    (r"магистратура|магистр", "master"),
    (r"специалитет|специалист", "master"),
    (r"бакалавриат|бакалавр", "bachelor"),
    (r"среднее профессиональное|среднее специальное|техникум|колледж", "associate"),
    (r"среднее общее|11 класс|полное среднее", "high_school"),
    (r"основное общее|9 класс", "high_school"),
    (r"не указано|не имеет значение|требования не предъявляются|не требуется", "none"),
]

SPEC_MAP = {
    "информационные технологии": "IT",
    "здравоохранение": "Медицина",
    "продажи": "Продажи",
    "финансы": "Финансы",
    "бухгалтерия": "Финансы",
    "строительство": "Строительство",
    "образование": "Образование",
    "транспорт": "Логистика",
    "производство": "Производство",
    "государственная служба": "Госсектор",
    "искусство": "Креатив",
    "туризм": "Сервис",
    "услуги населению": "Сервис",
    "рабочие специальности": "Рабочие",
    "жкх": "ЖКХ",
    "электроэнергетика": "Энергетика",
    "пищевая промышленность": "Производство",
    "легкая промышленность": "Производство",
}

ENGLISH_RE = re.compile(r"\b(A1|A2|B1|B2|C1|C2)\b", re.IGNORECASE)
DIGIT_RE = re.compile(r"(\d+(?:[.,]\d+)?)")


def map_education(text: str) -> str:
    if not text:
        return "none"
    low = str(text).lower()
    for pattern, level in EDUCATION_PATTERNS:
        if re.search(pattern, low):
            return level
    return "none"


def map_specialization(text: str) -> str:
    if not text:
        return "Прочее"
    low = str(text).lower()
    for key, mapped in SPEC_MAP.items():
        if key in low:
            return mapped
    return "Прочее"


def parse_years(text: Any) -> float:
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return 0.0
    try:
        return float(text)
    except (TypeError, ValueError):
        m = DIGIT_RE.search(str(text))
        return float(m.group(1).replace(",", ".")) if m else 0.0


def parse_english(text: Any) -> str:
    if not text:
        return "A1"
    m = ENGLISH_RE.search(str(text))
    return m.group(1).upper() if m else "A1"


def split_skills(*columns: Any) -> List[str]:
    """Объединяет skills/hardSkills/softSkills, нормализует."""
    result = set()
    for col in columns:
        if col is None or (isinstance(col, float) and pd.isna(col)):
            continue
        text = str(col).strip()
        if not text or text in {"[]", "{}", "None"}:
            continue
        # Может быть JSON-список, Python-список или строка через запятую/;
        parsed = None
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except Exception:
                try:
                    parsed = ast.literal_eval(text)
                except Exception:
                    parsed = None
        if isinstance(parsed, list):
            for item in parsed:
                s = str(item).strip().lower()
                if s and len(s) < 60:
                    result.add(s)
        else:
            for part in re.split(r"[,;]", text):
                s = part.strip().lower()
                if s and len(s) < 60:
                    result.add(s)
    return sorted(result)


def stable_id(prefix: str, *parts: str) -> str:
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:12]
    return f"{prefix}_{h}"


# ------------------------------------------------------------------ вакансии

def convert_vacancies(input_path: Path, output_path: Path) -> None:
    print(f"[vacancy] читаю {input_path} ...")
    df = pd.read_csv(input_path, sep="|", low_memory=False, on_bad_lines="skip")
    print(f"[vacancy] строк: {len(df):,}")

    out = pd.DataFrame()
    out["vacancy_id"] = df["id"].apply(lambda v: stable_id("VAC", str(v)))
    out["title"] = df["vacancyName"].fillna("Без названия")
    out["required_skills"] = df.apply(
        lambda r: split_skills(r.get("skills"), r.get("hardSkills"), r.get("softSkills")),
        axis=1,
    )
    out["min_experience"] = df["experienceRequirements"].apply(parse_years)
    out["max_experience"] = out["min_experience"] + 5
    out["min_salary"] = pd.to_numeric(df["salaryMin"], errors="coerce").fillna(0)
    out["max_salary"] = pd.to_numeric(df["salaryMax"], errors="coerce").fillna(0)
    out["required_education"] = df["educationRequirements"].apply(map_education)
    out["english_required"] = "A1"
    out["specialization"] = df["professionalSphereName"].apply(map_specialization)
    out["responsibilities"] = df["responsibilities"].fillna("")
    out["requirements_text"] = df["positionRequirements"].fillna("")
    out["company"] = df["company"].fillna("")
    out["region"] = df["regionName"].fillna("")
    out["status"] = "active"

    out.to_csv(output_path, index=False, encoding="utf-8")
    print(f"[vacancy] сохранено: {len(out):,} -> {output_path}")


# ------------------------------------------------------------------ резюме

def convert_resumes(input_path: Path, output_path: Path, chunksize: int = 50_000) -> None:
    print(f"[resume] читаю {input_path} чанками по {chunksize:,} ...")
    total = 0
    first = True
    for chunk in pd.read_csv(input_path, sep="|", chunksize=chunksize,
                             low_memory=False, on_bad_lines="skip"):
        out = pd.DataFrame()
        out["candidate_id"] = chunk["id"].apply(lambda v: stable_id("CV", str(v)))
        out["name"] = "Кандидат " + out["candidate_id"].str[-4:]
        out["experience_years"] = chunk["experience"].apply(parse_years)
        out["skills"] = chunk.apply(
            lambda r: split_skills(r.get("skills"), r.get("hardSkills"), r.get("softSkills")),
            axis=1,
        )
        out["education"] = chunk["education"].apply(map_education)
        out["specialization"] = chunk["typicalPosition"].apply(map_specialization)
        out["expected_salary"] = pd.to_numeric(chunk["salaryMin"], errors="coerce").fillna(0)
        out["last_position"] = chunk["positionName"].fillna("")
        out["english_level"] = chunk["languageKnowledge"].apply(parse_english)
        out["has_portfolio"] = False
        out["soft_skills"] = chunk["softSkills"].fillna("")
        out["certifications"] = chunk["otherCertificates"].fillna("")
        out["region"] = chunk["localityName"].fillna("")
        out["resume_text"] = (
            chunk["positionName"].fillna("").astype(str) + " | "
            + chunk["skills"].fillna("").astype(str) + " | "
            + chunk["experience"].fillna("").astype(str)
        )

        out.to_csv(output_path, mode="a", header=first, index=False, encoding="utf-8")
        first = False
        total += len(out)
        print(f"[resume] обработано: {total:,}")

    print(f"[resume] итого: {total:,} -> {output_path}")


# ------------------------------------------------------------------ main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=Path("data/trudvsem/raw"))
    ap.add_argument("--out", type=Path, default=Path("data/trudvsem/processed"))
    ap.add_argument("--max-resumes", type=int, default=0,
                    help="0 = все; иначе остановиться после N резюме")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    vac = args.raw / "vacancy.csv"
    cv = args.raw / "cv.csv"
    if vac.exists():
        convert_vacancies(vac, args.out / "vacancies.csv")
    if cv.exists():
        convert_resumes(cv, args.out / "candidates.csv")

    # Удаляем старый файл, если он есть — чтобы чанки не дописывались к прошлому запуску.
    print("Готово.")


if __name__ == "__main__":
    main()
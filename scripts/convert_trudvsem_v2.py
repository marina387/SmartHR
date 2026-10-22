# -*- coding: utf-8 -*-
"""Конвертер trudvsem v2.1.

Изменения относительно v2:
- split_skills возвращён из v1: парсит JSON-списки из skills/hardSkills/softSkills.
- extract_tech добавлен к split_skills: вытаскивает технологии из positionName/responsibilities.
- educationRequirements парсится как JSON (educationType), а не как строка.
- educationList в резюме парсится как JSON.
- Маппинг должностей POSITION_TO_SPEC расширен.
- Дедуп спам-компаний (Пятёрочка, Fix Price, Магнит, Ашан).
- Флаг --only-resumes: пересобрать только candidates.csv.
- Флаг --limit: ограничить число строк (для теста).
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

EDU_TYPE_MAP = {
    "подготовка кадров высшей квалификации": "phd",
    "магистратура": "master",
    "специалитет": "master",
    "бакалавриат": "bachelor",
    "среднее профессиональное": "associate",
    "среднее общее": "high_school",
    "основное общее": "high_school",
    "общее образование": "high_school",
    "требования не предъявляются": "none",
    "не указано": "none",
    "не имеет значение": "none",
}

# Должность -> сфера. Расширен по сравнению с v2.
POSITION_TO_SPEC = {
    # Медицина
    "врач": "Медицина", "медсестр": "Медицина", "медбрат": "Медицина",
    "фельдшер": "Медицина", "санитар": "Медицина", "акушер": "Медицина",
    "стоматолог": "Медицина", "хирург": "Медицина", "терапевт": "Медицина",
    "педиатр": "Медицина", "фармацевт": "Медицина", "провизор": "Медицина",
    "лаборант": "Медицина", "медтехник": "Медицина", "анестезиолог": "Медицина",
    # Продажи
    "продав": "Продажи", "кассир": "Продажи", "мерчендайзер": "Продажи",
    "товаровед": "Продажи", "закупщик": "Продажи", "снабжен": "Продажи",
    "торгов": "Продажи", "консультант": "Продажи", "коммерч": "Продажи",
    # IT
    "программист": "IT", "разработчик": "IT", "тестировщик": "IT",
    "системный администратор": "IT", "сисадмин": "IT", "аналитик данных": "IT",
    "devops": "IT", "data scientist": "IT", "backend": "IT", "frontend": "IT",
    "web": "IT", "верстальщик": "IT", "инженер-программист": "IT",
    # Финансы
    "бухгалтер": "Финансы", "экономист": "Финансы", "финансист": "Финансы",
    "аудитор": "Финансы", "кредитн": "Финансы", "банк": "Финансы",
    "казначей": "Финансы", "налогов": "Финансы",
    # Образование
    "учитель": "Образование", "воспитатель": "Образование",
    "преподаватель": "Образование", "педагог": "Образование",
    "методист": "Образование", "репетитор": "Образование", "тренер": "Образование",
    # Логистика
    "водитель": "Логистика", "логист": "Логистика", "экспедитор": "Логистика",
    "кладовщик": "Логистика", "курьер": "Логистика", "грузчик": "Логистика",
    "диспетчер": "Логистика", "комплектовщик": "Логистика",
    # Производство
    "инженер": "Производство", "технолог": "Производство", "слесарь": "Производство",
    "токарь": "Производство", "сварщик": "Производство", "монтажник": "Производство",
    "оператор станк": "Производство", "наладчик": "Производство",
    # Строительство
    "строитель": "Строительство", "каменщик": "Строительство", "маляр": "Строительство",
    "штукатур": "Строительство", "плотник": "Строительство", "прораб": "Строительство",
    "бетонщик": "Строительство", "арматурщик": "Строительство",
    # Энергетика
    "электрик": "Энергетика", "электромонтер": "Энергетика", "энергетик": "Энергетика",
    "электромонтажник": "Энергетика", "электротехник": "Энергетика",
    # Сервис
    "повар": "Сервис", "официант": "Сервис", "бармен": "Сервис", "бариста": "Сервис",
    "уборщ": "Сервис", "дворник": "Сервис", "администратор": "Сервис",
    "горничная": "Сервис", "хостес": "Сервис", "кондитер": "Сервис",
    # Юриспруденция
    "юрист": "Юриспруденция", "адвокат": "Юриспруденция", "нотариус": "Юриспруденция",
    "юрисконсульт": "Юриспруденция",
    # Креатив
    "дизайнер": "Креатив", "художник": "Креатив", "фотограф": "Креатив",
    "архитектор": "Креатив", "копирайтер": "Креатив", "журналист": "Креатив",
    # Менеджмент
    "менеджер": "Менеджмент", "руководитель": "Менеджмент", "директор": "Менеджмент",
    "начальник": "Менеджмент", "заведующ": "Менеджмент", "управляющ": "Менеджмент",
    "заместитель": "Менеджмент",
    # Госсектор
    "госслуж": "Госсектор", "инспектор": "Госсектор", "специалист по": "Госсектор",
    # Рабочие
    "рабочий": "Рабочие", "разнорабочий": "Рабочие", "подсобный": "Рабочие",
}

# Технологии для extract_tech. Расширен.
KNOWN_TECH = [
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "rust",
    "sql", "postgresql", "mysql", "mongodb", "oracle", "excel", "1с", "1c",
    "kubernetes", "docker", "react", "vue", "angular", "django", "flask",
    "fastapi", "linux", "git", "sap", "rest", "api", "html", "css",
    "autocad", "solidworks", "компас", "photoshop", "figma", "illustrator",
    "машинное обучение", "ml", "ai", "нейросет", "big data", "hadoop", "spark",
]

SPAM_COMPANIES = {"пятёрочка", "пятерочка", "fix price", "фикс прайс", "магнит", "ашан"}

DIGIT_RE = re.compile(r"(\d+(?:[.,]\d+)?)")


# ------------------------------------------------------------------ парсинг

def _parse_json(value: Any) -> Any:
    """Парсит JSON-строку в dict/list, если это возможно."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text in {"[]", "{}", "None", "nan", "NaN"}:
        return None
    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except Exception:
            try:
                return ast.literal_eval(text)
            except Exception:
                return None
    return text


def split_skills(*columns: Any) -> List[str]:
    """Парсит skills/hardSkills/softSkills из JSON-списков или строки."""
    result: set[str] = set()
    for col in columns:
        if col is None or (isinstance(col, float) and pd.isna(col)):
            continue
        text = str(col).strip()
        if not text or text in {"[]", "{}", "None", "nan", "NaN"}:
            continue
        parsed = _parse_json(text)
        if isinstance(parsed, list):
            for item in parsed:
                s = str(item).strip().lower()
                if s and 0 < len(s) < 80:
                    result.add(s)
        elif isinstance(parsed, str) and parsed:
            for part in re.split(r"[,;\n]", parsed):
                s = part.strip().lower()
                if s and 0 < len(s) < 80:
                    result.add(s)
    return sorted(result)


def extract_tech(text: str) -> List[str]:
    """Ищет известные технологии в тексте."""
    low = str(text or "").lower()
    return [t for t in KNOWN_TECH if t in low]


def parse_years(raw: Any) -> float:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        m = DIGIT_RE.search(str(raw))
        return float(m.group(1).replace(",", ".")) if m else 0.0


def map_education(raw: Any) -> str:
    """educationRequirements — JSON с полем educationType."""
    parsed = _parse_json(raw)
    text = ""
    if isinstance(parsed, dict):
        text = str(parsed.get("educationType") or "")
    elif isinstance(parsed, list) and parsed:
        first = parsed[0]
        text = str(first.get("educationType") if isinstance(first, dict) else first)
    elif isinstance(parsed, str):
        text = parsed
    low = text.lower()
    # Сначала точные совпадения из EDU_TYPE_MAP
    for key, level in EDU_TYPE_MAP.items():
        if key in low:
            return level
    return "none"


def map_spec_from_position(raw: Any) -> str:
    low = str(raw or "").lower()
    if not low:
        return "Прочее"
    for key, spec in POSITION_TO_SPEC.items():
        if key in low:
            return spec
    return "Прочее"


def map_spec_from_sphere(raw: Any) -> str:
    low = str(raw or "").lower()
    if "здравоохран" in low: return "Медицина"
    if "образован" in low: return "Образование"
    if "продаж" in low or "торговля" in low: return "Продажи"
    if "информационн" in low: return "IT"
    if "финанс" in low or "бухгалтер" in low: return "Финансы"
    if "строительств" in low: return "Строительство"
    if "транспорт" in low: return "Логистика"
    if "производств" in low or "промышленн" in low: return "Производство"
    if "электроэнерг" in low: return "Энергетика"
    if "жкх" in low: return "ЖКХ"
    if "государствен" in low: return "Госсектор"
    if "услуг" in low or "туризм" in low or "ресторан" in low: return "Сервис"
    if "юрид" in low: return "Юриспруденция"
    if "менеджмент" in low or "управлен" in low: return "Менеджмент"
    if "искусств" in low or "культур" in low: return "Креатив"
    return "Прочее"


def stable_id(prefix: str, *parts: str) -> str:
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:12]
    return f"{prefix}_{h}"


# ------------------------------------------------------------------ вакансии

def convert_vacancies(input_path: Path, output_path: Path, limit: int = 0) -> None:
    print(f"[vacancy] читаю {input_path} ...")
    df = pd.read_csv(input_path, sep="|", low_memory=False, on_bad_lines="skip",
                     nrows=limit if limit else None)
    print(f"[vacancy] строк: {len(df):,}")

    # Дедуп спам-компаний
    if "fullCompanyName" in df.columns:
        comp_col = df["fullCompanyName"].fillna(df["company"].astype(str))
    else:
        comp_col = df["company"].astype(str)
    comp_low = comp_col.astype(str).str.lower()
    spam_mask = comp_low.apply(lambda s: any(x in s for x in SPAM_COMPANIES))
    dedup_key = df["vacancyName"].astype(str) + "|" + df["regionName"].astype(str) + "|" + comp_low
    keep = ~spam_mask | ~dedup_key.duplicated()
    df = df[keep].copy()
    comp_col = comp_col[keep]
    print(f"[vacancy] после дедупа: {len(df):,}")

    out = pd.DataFrame()
    out["vacancy_id"] = df["id"].apply(lambda v: stable_id("VAC", str(v)))
    out["title"] = df["vacancyName"].fillna("Без названия")
    out["required_skills"] = df.apply(
        lambda r: split_skills(r.get("skills"), r.get("hardSkills"), r.get("softSkills"))
                  + extract_tech(
                      str(r.get("responsibilities", "")) + " "
                      + str(r.get("positionRequirements", "")) + " "
                      + str(r.get("additionalRequirements", ""))
                  ),
        axis=1,
    )
    out["min_experience"] = df["experienceRequirements"].apply(parse_years)
    out["max_experience"] = out["min_experience"] + 5
    out["min_salary"] = pd.to_numeric(df["salaryMin"], errors="coerce").fillna(0)
    out["max_salary"] = pd.to_numeric(df["salaryMax"], errors="coerce").fillna(0)
    out["required_education"] = df["educationRequirements"].apply(map_education)
    out["english_required"] = "A1"
    out["specialization"] = df["professionalSphereName"].apply(map_spec_from_sphere)
    out["responsibilities"] = df["responsibilities"].fillna("")
    out["requirements_text"] = df["positionRequirements"].fillna("")
    out["company"] = comp_col.fillna("")
    out["region"] = df["regionName"].fillna("")
    out["status"] = "active"

    out.to_csv(output_path, index=False, encoding="utf-8")
    print(f"[vacancy] сохранено: {len(out):,} -> {output_path}")
    print(f"[vacancy] skills непустых: {(out['required_skills'].astype(str).str.len() > 2).sum():,}")
    print(f"[vacancy] specialization:\n{out['specialization'].value_counts().head(10)}")


# ------------------------------------------------------------------ резюме

def convert_resumes(input_path: Path, output_path: Path, chunksize: int = 50_000,
                    limit: int = 0) -> None:
    print(f"[resume] читаю {input_path} чанками по {chunksize:,} ...")
    total = 0
    first = True
    skills_nonempty = 0

    for chunk in pd.read_csv(input_path, sep="|", chunksize=chunksize,
                             low_memory=False, on_bad_lines="skip"):
        if limit and total + len(chunk) > limit:
            chunk = chunk.head(limit - total)

        out = pd.DataFrame()
        out["candidate_id"] = chunk["id"].apply(lambda v: stable_id("CV", str(v)))
        out["name"] = "Кандидат " + out["candidate_id"].str[-4:]
        out["experience_years"] = chunk["experience"].apply(parse_years)

        # skills: JSON из skills/hardSkills/softSkills + технологии из positionName
        out["skills"] = chunk.apply(
            lambda r: split_skills(r.get("skills"), r.get("hardSkills"), r.get("softSkills"))
                      + extract_tech(str(r.get("positionName", ""))),
            axis=1,
        )
        out["education"] = chunk["education"].apply(map_education)
        out["specialization"] = chunk["positionName"].apply(map_spec_from_position)
        out["expected_salary"] = pd.to_numeric(chunk["salaryMin"], errors="coerce").fillna(0)
        out["last_position"] = chunk["positionName"].fillna("")
        out["english_level"] = "A1"
        out["has_portfolio"] = False
        out["soft_skills"] = chunk.get("softSkills", "").fillna("")
        out["certifications"] = chunk.get("otherCertificates", "").fillna("")
        out["region"] = chunk.get("localityName", "").fillna("")

        # resume_text: должность + навыки + опыт + образование
        edu_str = chunk["education"].fillna("").astype(str)
        out["resume_text"] = (
            chunk["positionName"].fillna("").astype(str) + " | "
            + out["skills"].astype(str) + " | опыт: "
            + chunk["experience"].fillna("").astype(str) + " лет | "
            + "образование: " + edu_str
        )

        out.to_csv(output_path, mode="a", header=first, index=False, encoding="utf-8")
        first = False
        total += len(out)
        skills_nonempty += (out["skills"].astype(str).str.len() > 2).sum()
        if total % 100_000 == 0:
            print(f"[resume] обработано: {total:,}")
        if limit and total >= limit:
            break

    print(f"[resume] итого: {total:,} -> {output_path}")
    print(f"[resume] skills непустых: {skills_nonempty:,} ({skills_nonempty / max(total, 1) * 100:.1f}%)")


# ------------------------------------------------------------------ main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=Path("data/trudvsem/raw"))
    ap.add_argument("--out", type=Path, default=Path("data/trudvsem/processed_v2"))
    ap.add_argument("--only-resumes", action="store_true",
                    help="Пересобрать только candidates.csv")
    ap.add_argument("--only-vacancies", action="store_true",
                    help="Пересобрать только vacancies.csv")
    ap.add_argument("--limit", type=int, default=0,
                    help="0 = все строки; иначе — только первые N (для теста)")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    vac = args.raw / "vacancy.csv"
    cv = args.raw / "cv.csv"

    do_vac = not args.only_resumes
    do_res = not args.only_vacancies

    if do_vac and vac.exists():
        convert_vacancies(vac, args.out / "vacancies.csv", limit=args.limit)

    if do_res and cv.exists():
        # Удаляем старый файл перед новой сборкой, чтобы не было дописывания
        out_path = args.out / "candidates.csv"
        if out_path.exists() and not args.limit:
            out_path.unlink()
            print(f"[resume] удалён старый {out_path}")
        convert_resumes(cv, out_path, limit=args.limit)

    print("Готово.")


if __name__ == "__main__":
    main()
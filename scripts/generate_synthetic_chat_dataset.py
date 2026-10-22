"""Generate synthetic HR-assistant answers from collected real-world records.

The generated answers are grounded in explicit text overlap only. They are useful
for pipeline experiments and initial fine-tuning, but are not expert HR labels.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.chat.dataset import read_jsonl, validate_records, write_jsonl


SYSTEM_PROMPT = (
    "Ты HR-ассистент SmartHR. Используй только переданные данные, "
    "не придумывай факты и не принимай решение вместо HR."
)

SKILLS = (
    "Python", "Django", "Flask", "FastAPI", "Java", "Kotlin", "JavaScript",
    "TypeScript", "React", "Angular", "Vue", "Node.js", ".NET", "C#", "C++",
    "PHP", "Laravel", "Ruby", "Rails", "Golang", "Swift", "Flutter", "Android",
    "iOS", "SQL", "PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch",
    "Docker", "Kubernetes", "AWS", "Azure", "GCP", "Git", "CI/CD", "Linux",
    "Terraform", "Ansible", "Jenkins", "REST API", "GraphQL", "RabbitMQ", "Kafka",
    "PyTorch", "TensorFlow", "Pandas", "NumPy", "Power BI", "Tableau", "Figma",
    "Photoshop", "Unity", "Unreal Engine", "Selenium", "Cypress", "Jira", "Scrum",
)


def load_records(path: Path) -> List[Dict[str, Any]]:
    return [record for _, record in read_jsonl(path)]


def contains_skill(text: str, skill: str) -> bool:
    normalized = text.casefold()
    escaped = re.escape(skill.casefold())
    return bool(re.search(rf"(?<![\w]){escaped}(?![\w])", normalized))


def extract_skills(text: str) -> List[str]:
    return [skill for skill in SKILLS if contains_skill(text, skill)]


def join_items(items: Sequence[str], empty: str = "не выявлены") -> str:
    return ", ".join(items) if items else empty


def evidence(candidate: Dict[str, Any], vacancy: Dict[str, Any]) -> Dict[str, Any]:
    candidate_text = " ".join(str(candidate.get(key) or "") for key in ("position", "profile", "highlights"))
    vacancy_text = " ".join(str(vacancy.get(key) or "") for key in ("position", "description"))
    candidate_skills = extract_skills(candidate_text)
    vacancy_skills = extract_skills(vacancy_text)
    common = [skill for skill in vacancy_skills if skill in candidate_skills]
    missing = [skill for skill in vacancy_skills if skill not in candidate_skills]
    return {
        "candidate_skills": candidate_skills,
        "vacancy_skills": vacancy_skills,
        "common_skills": common,
        "unconfirmed_skills": missing,
        "experience_years": candidate.get("experience_years"),
        "experience_required": vacancy.get("experience_required"),
    }


def assessment_answer(data: Dict[str, Any]) -> str:
    common = join_items(data["common_skills"])
    missing = join_items(data["unconfirmed_skills"])
    experience = data.get("experience_years")
    experience_note = (
        f"В профиле указано {experience:g} года опыта. "
        if isinstance(experience, (int, float)) else
        "Продолжительность опыта в структурированных данных не указана. "
    )
    return (
        f"В тексте профиля подтверждены совпадения с вакансией: {common}. "
        f"В профиле явно не подтверждены требования: {missing}. {experience_note}"
        "Окончательное решение должен принять HR после проверки опыта и обязательных требований."
    )


def gaps_answer(data: Dict[str, Any]) -> str:
    return (
        f"Подтверждённые общие навыки: {join_items(data['common_skills'])}. "
        f"Навыки из вакансии, которые не найдены в профиле: {join_items(data['unconfirmed_skills'])}. "
        "Отсутствие упоминания не доказывает отсутствие навыка, поэтому пробелы следует уточнить у кандидата."
    )


def interview_answer(data: Dict[str, Any]) -> str:
    missing = data["unconfirmed_skills"][:3]
    common = data["common_skills"][:2]
    questions = []
    if common:
        questions.append(f"Попросите привести пример практического применения {join_items(common)}.")
    for skill in missing:
        questions.append(f"Уточните, есть ли практический опыт с {skill}, и попросите описать выполненную задачу.")
    questions.extend([
        "Уточните личную роль кандидата и измеримый результат в последнем проекте.",
        "Проверьте ожидания кандидата и его готовность выполнять задачи этой вакансии.",
    ])
    return "Рекомендуемые вопросы: " + " ".join(f"{i}. {q}" for i, q in enumerate(questions, 1))


def safe_recommendation(data: Dict[str, Any]) -> str:
    if not data["vacancy_skills"]:
        return (
            "В тексте вакансии не удалось выделить достаточно проверяемых технологических требований. "
            "Автоматическая рекомендация невозможна: HR должен уточнить критерии вакансии."
        )
    if not data["common_skills"]:
        return (
            "В профиле не найдены явные совпадения с выделенными требованиями вакансии. "
            "Это не является основанием для автоматического отказа: проверьте полноту резюме и обязательные критерии вручную."
        )
    return (
        f"Для дальнейшей проверки есть основания: подтверждены {join_items(data['common_skills'])}. "
        f"Перед приглашением уточните {join_items(data['unconfirmed_skills'], 'остальные обязательные требования')}. "
        "Решение о следующем этапе остаётся за HR."
    )


SCENARIOS = (
    ("candidate_assessment", "Оцени соответствие кандидата вакансии.", assessment_answer),
    ("strengths_and_gaps", "Назови подтверждённые сильные стороны и пробелы кандидата.", gaps_answer),
    ("interview_questions", "Подготовь вопросы для интервью по этой вакансии.", interview_answer),
    ("next_step_recommendation", "Стоит ли переводить кандидата на следующий этап?", safe_recommendation),
)


def generate_records(candidates: Iterable[Dict[str, Any]], vacancies: Iterable[Dict[str, Any]],
                     pairs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidate_map = {item["id"]: item for item in candidates}
    vacancy_map = {item["id"]: item for item in vacancies}
    records = []
    for index, pair in enumerate(pairs):
        candidate = candidate_map[pair["candidate_id"]]
        vacancy = vacancy_map[pair["vacancy_id"]]
        scenario, question, answer_builder = SCENARIOS[index % len(SCENARIOS)]
        facts = evidence(candidate, vacancy)
        context = (
            f"Профиль кандидата: {candidate.get('profile', '')}\n"
            f"Вакансия: {vacancy.get('position', '')}. {vacancy.get('description', '')}\n"
            f"Вопрос: {question}"
        )
        records.append({
            "id": f"synthetic_{index + 1:05d}",
            "group_id": candidate["id"],
            "scenario": scenario,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": context},
                {"role": "assistant", "content": answer_builder(facts)},
            ],
            "source_ids": [candidate["id"], vacancy["id"]],
            "pair_id": pair["id"],
            "synthetic": True,
            "generation_method": "deterministic_template_v1",
            "approved_by_hr": False,
            "anonymized": True,
        })
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/chat/collected"))
    parser.add_argument("--output", type=Path, default=Path("data/chat/synthetic"))
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    candidates = load_records(args.input / "candidates.jsonl")
    vacancies = load_records(args.input / "vacancies.jsonl")
    pairs = load_records(args.input / "candidate_vacancy_pairs.jsonl")[:args.limit]
    records = generate_records(candidates, vacancies, pairs)
    args.output.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output / "synthetic_chat.jsonl", records)
    validation = validate_records(records, require_approved=False)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "records": len(records),
        "synthetic": True,
        "approved_by_hr": 0,
        "scenarios": dict(Counter(item["scenario"] for item in records)),
        "validation_errors": len(validation["errors"]),
        "warning": "Synthetic answers are not expert HR labels.",
    }
    (args.output / "generation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if validation["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Generate grounded synthetic RAG conversations for the SmartHR chat dataset."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.chat.dataset import read_jsonl, validate_records, write_jsonl
from src.core.loaders import load_hr_documents


SYSTEM = (
    "Ты HR-ассистент SmartHR. Для вопросов по документам отвечай только по найденным "
    "фрагментам, указывай источник и прямо сообщай, если сведений недостаточно."
)


def read_records(path: Path) -> List[Dict[str, Any]]:
    return [record for _, record in read_jsonl(path)]


def rag_record(index: int, scenario: str, user: str, tool: str, assistant: str,
               source_ids: Iterable[str], citations: Iterable[Dict[str, Any]],
               group_id: str | None = None) -> Dict[str, Any]:
    source_ids = list(source_ids)
    return {
        "id": f"synthetic_rag_{index:05d}",
        "group_id": group_id or f"rag_{source_ids[0] if source_ids else 'no_source'}",
        "scenario": scenario,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
            {"role": "tool", "content": tool},
            {"role": "assistant", "content": assistant},
        ],
        "source_ids": source_ids,
        "citations": list(citations),
        "synthetic": True,
        "generation_method": "grounded_rag_template_v1",
        "approved_by_hr": False,
        "anonymized": True,
    }


def onet_examples(occupations: List[Dict[str, Any]], limit: int, start: int = 1) -> List[Dict[str, Any]]:
    records = []
    for offset, occupation in enumerate(occupations[:limit]):
        index = start + offset
        code = occupation["code"]
        title = occupation["title"]
        description = occupation["description"]
        citation = {"source_id": occupation["id"], "title": "O*NET 31.0 Database", "section": code,
                    "url": occupation["source"]["source_url"]}
        if offset % 3 == 0:
            scenario = "document_search_by_title"
            user = f"Найди в O*NET описание профессии {title}."
            answer = f"Согласно O*NET, «{title}» описывается так: {description} Источник: O*NET 31.0, код {code}."
        elif offset % 3 == 1:
            scenario = "document_search_by_context"
            clue = " ".join(description.split()[:24])
            user = f"Не помню название профессии. Найди её по описанию деятельности: {clue}."
            answer = f"По смыслу запроса подходит профессия «{title}». {description} Источник: O*NET 31.0, код {code}."
        else:
            scenario = "document_information_extraction"
            user = f"Какие функции выполняет специалист {title}?"
            answer = f"В доступном описании указаны следующие функции: {description} Источник: O*NET 31.0, код {code}."
        tool = json.dumps({"status": "found", "document": "O*NET 31.0 Database", "section": code,
                           "text": description, "score": 0.93}, ensure_ascii=False)
        records.append(rag_record(index, scenario, user, tool, answer, [occupation["id"]], [citation]))
    return records


def document_sections(text: str) -> List[Dict[str, str]]:
    matches = list(re.finditer(r"(?m)^(\d+\.\s*[^\n]+)$", text))
    if not matches:
        return [{"section": "Документ", "text": text.strip()}]
    sections = []
    for position, match in enumerate(matches):
        end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
        sections.append({"section": match.group(1).strip(), "text": text[match.end():end].strip()})
    return sections


def internal_document_examples(folder: Path, start: int) -> List[Dict[str, Any]]:
    records = []
    index = start
    for document in load_hr_documents(folder):
        for section in document_sections(document.text):
            if not section["text"]:
                continue
            citation = {"source_id": document.id, "title": document.title,
                        "section": section["section"], "source": document.source}
            variants = [
                ("document_search_by_title", f"Покажи раздел «{section['section']}» документа «{document.title}»."),
                ("document_search_by_context", f"Не помню название документа. Где сказано про: {' '.join(section['text'].split()[:12])}?"),
            ]
            for scenario, user in variants:
                tool = json.dumps({"status": "found", "document": document.title,
                                   "section": section["section"], "text": section["text"], "score": 0.91},
                                  ensure_ascii=False)
                answer = (f"В документе «{document.title}», раздел «{section['section']}», указано: "
                          f"{section['text']} Источник: {document.title}, {section['section']}.")
                records.append(rag_record(index, scenario, user, tool, answer, [document.id], [citation]))
                index += 1
    return records


def boundary_examples(start: int) -> List[Dict[str, Any]]:
    cases = [
        ("document_not_found", "Покажи статью 5 Трудового кодекса.",
         {"status": "not_found", "query": "статья 5 Трудового кодекса"},
         "В доступной базе не найден текст статьи 5 Трудового кодекса. Я не буду воспроизводить её по памяти. Загрузите актуальную редакцию документа или подключите официальный источник."),
        ("document_not_found", "Что закон говорит об испытательном сроке?",
         {"status": "not_found", "query": "испытательный срок законодательство"},
         "В доступных документах нет подтверждённого фрагмента об испытательном сроке. Для ответа требуется актуальный нормативный источник."),
        ("ambiguous_document_query", "Найди положение об отпусках.",
         {"status": "ambiguous", "documents": ["Положение об отпусках 2024", "Положение об отпусках 2025"]},
         "Найдено две версии положения об отпусках: за 2024 и 2025 год. Уточните нужную редакцию или подтвердите использование самой новой версии."),
        ("outdated_document", "Как сейчас оформляется удалённая работа?",
         {"status": "outdated", "document": "Регламент удалённой работы", "revision": "2022-01-01"},
         "Найдена только редакция регламента от 2022 года, поэтому я не могу подтвердить, что порядок актуален. Требуется действующая версия документа."),
        ("conflicting_sources", "Кто согласовывает отпуск?",
         {"status": "conflict", "hits": ["Регламент A: руководитель", "Регламент B: руководитель и HR"]},
         "Найденные документы противоречат друг другу: в одном требуется согласование руководителя, в другом — руководителя и HR. Необходимо определить действующую редакцию."),
        ("access_denied", "Покажи служебное расследование по сотруднику.",
         {"status": "access_denied", "document": "Материалы служебного расследования"},
         "У вашей роли нет доступа к этому документу. Я не могу показать его содержимое. Обратитесь к владельцу документа или администратору доступа."),
        ("no_answer_in_source", "Какая компенсация положена при увольнении?",
         {"status": "found_without_answer", "document": "Справочник сотрудника", "text": "Общие рабочие стандарты и развитие сотрудников."},
         "Справочник сотрудника найден, но в доступном фрагменте нет сведений о компенсации при увольнении. Нужен другой документ или нормативный источник."),
    ]
    records = []
    for offset in range(70):
        scenario, user, tool_data, answer = cases[offset % len(cases)]
        variant = offset // len(cases) + 1
        varied_user = user if variant == 1 else f"{user} Вариант запроса {variant}."
        records.append(rag_record(start + offset, scenario, varied_user,
                                  json.dumps(tool_data, ensure_ascii=False), answer,
                                  [], [], group_id=f"rag_boundary_case_{offset % len(cases)}"))
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--occupations", type=Path, default=Path("data/chat/collected/occupations.jsonl"))
    parser.add_argument("--documents", type=Path, default=Path("docs/sample_docs"))
    parser.add_argument("--base", type=Path, default=Path("data/chat/synthetic/synthetic_chat.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/chat/synthetic"))
    parser.add_argument("--occupation-limit", type=int, default=600)
    args = parser.parse_args()
    occupations = read_records(args.occupations)
    records = onet_examples(occupations, args.occupation_limit)
    records.extend(internal_document_examples(args.documents, len(records) + 1))
    records.extend(boundary_examples(len(records) + 1))
    validation = validate_records(records, require_approved=False)
    if validation["errors"]:
        print(json.dumps(validation, ensure_ascii=False, indent=2))
        return 1
    args.output.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output / "synthetic_rag.jsonl", records)
    base_records = read_records(args.base) if args.base.exists() else []
    combined = base_records + records
    write_jsonl(args.output / "combined_chat.jsonl", combined)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_records": len(base_records), "rag_records": len(records), "combined_records": len(combined),
        "rag_scenarios": dict(Counter(item["scenario"] for item in records)),
        "synthetic": True, "approved_by_hr": 0, "validation_errors": 0,
    }
    (args.output / "rag_generation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

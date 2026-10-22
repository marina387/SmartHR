"""Collect a review-ready SmartHR dataset from public real-world sources.

The script streams anonymized candidate profiles and job descriptions from the
Djinni Recruitment Dataset on Hugging Face.  It does not create ground-truth
hiring decisions: candidate-vacancy pairs and chat answers remain unapproved
until an HR specialist reviews them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List

from datasets import load_dataset

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.chat.dataset import anonymize_text, read_jsonl, write_jsonl


CANDIDATE_DATASET = "lang-uk/recruitment-dataset-candidate-profiles-english"
VACANCY_DATASET = "lang-uk/recruitment-dataset-job-descriptions-english"
SOURCE_REPOSITORY = "https://github.com/Stereotypes-in-LLMs/recruitment-dataset"
SOURCE_PAPER = "https://aclanthology.org/2024.unlp-1.2/"
ONET_URL = "https://www.onetcenter.org/dl_files/database/db_31_0_json/occupation_data.json"
SYSTEM_PROMPT = (
    "Ты HR-ассистент SmartHR. Используй только переданные данные, "
    "не придумывай факты и не принимай решение вместо HR."
)


def compact_text(value: Any, limit: int = 6000) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return anonymize_text(text)[:limit]


def stable_id(prefix: str, source_id: str) -> str:
    digest = hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:16]
    # Separators also prevent hexadecimal identifiers from looking like phone or
    # passport numbers to downstream PII scanners.
    grouped = "-".join(digest[index:index + 4] for index in range(0, len(digest), 4))
    return f"{prefix}_{grouped}"


def normalize_keyword(value: Any) -> str:
    return compact_text(value, 120).casefold() or "other"


def source_meta(dataset: str, source_id: str) -> Dict[str, str]:
    return {
        "dataset": dataset,
        "source_record_id": source_id,
        "source_url": f"https://huggingface.co/datasets/{dataset}",
        "repository_url": SOURCE_REPOSITORY,
        "paper_url": SOURCE_PAPER,
        "license": "MIT",
    }


def candidate_record(row: Dict[str, Any]) -> Dict[str, Any]:
    source_id = str(row.get("id") or row.get("__index_level_0__") or "")
    return {
        "id": stable_id("candidate", source_id),
        "position": compact_text(row.get("Position"), 300),
        "profile": compact_text(row.get("CV"), 6000),
        "looking_for": compact_text(row.get("Looking For"), 1500),
        "highlights": compact_text(row.get("Highlights"), 1500),
        "primary_keyword": compact_text(row.get("Primary Keyword"), 120),
        "english_level": compact_text(row.get("English Level"), 50),
        "experience_years": row.get("Experience Years"),
        "language": compact_text(row.get("CV_lang"), 10),
        "anonymized": True,
        "source": source_meta(CANDIDATE_DATASET, source_id),
    }


def vacancy_record(row: Dict[str, Any]) -> Dict[str, Any]:
    source_id = str(row.get("id") or row.get("__index_level_0__") or "")
    return {
        "id": stable_id("vacancy", source_id),
        "position": compact_text(row.get("Position"), 300),
        "description": compact_text(row.get("Long Description"), 6000),
        # Company names are deliberately omitted: they are unnecessary for training.
        "experience_required": compact_text(row.get("Exp Years"), 50),
        "primary_keyword": compact_text(row.get("Primary Keyword"), 120),
        "english_level": compact_text(row.get("English Level"), 50),
        "published": compact_text(row.get("Published"), 80),
        "language": compact_text(row.get("Long Description_lang"), 10),
        "anonymized": True,
        "source": source_meta(VACANCY_DATASET, source_id),
    }


def onet_records(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{
        "id": f"onet_{str(row.get('onetsoc_code') or '').replace('.', '_')}",
        "code": str(row.get("onetsoc_code") or ""),
        "title": compact_text(row.get("title"), 300),
        "description": compact_text(row.get("description"), 1500),
        "language": "en",
        "source": {
            "dataset": "O*NET 31.0 Database",
            "source_record_id": str(row.get("onetsoc_code") or ""),
            "source_url": ONET_URL,
            "license": "CC BY 4.0",
            "attribution": "U.S. Department of Labor, Employment and Training Administration",
        },
    } for row in payload.get("row", [])]


def load_onet() -> List[Dict[str, Any]]:
    with urllib.request.urlopen(ONET_URL, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return onet_records(payload)


def stream_sample(dataset_name: str, count: int, seed: int,
                  shuffle_buffer: int = 100_000) -> Iterator[Dict[str, Any]]:
    dataset = load_dataset(dataset_name, split="train", streaming=True)
    # Source rows are ordered by position. A large reservoir-style shuffle buffer
    # prevents a small pilot from consisting only of alphabetically early roles.
    yield from dataset.shuffle(seed=seed, buffer_size=max(count, shuffle_buffer)).take(count)


def pair_records(candidates: List[Dict[str, Any]], vacancies: List[Dict[str, Any]],
                 count: int, seed: int) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    by_keyword: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for vacancy in vacancies:
        by_keyword[normalize_keyword(vacancy["primary_keyword"])].append(vacancy)
    all_vacancies = list(vacancies)
    pairs: List[Dict[str, Any]] = []
    seen = set()
    shuffled = list(candidates)
    rng.shuffle(shuffled)
    while len(pairs) < count and shuffled:
        candidate = shuffled[len(pairs) % len(shuffled)]
        keyword = normalize_keyword(candidate["primary_keyword"])
        matching = by_keyword.get(keyword) or all_vacancies
        vacancy = rng.choice(matching)
        key = (candidate["id"], vacancy["id"])
        if key in seen:
            vacancy = rng.choice(all_vacancies)
            key = (candidate["id"], vacancy["id"])
        if key in seen:
            continue
        seen.add(key)
        pairs.append({
            "id": stable_id("pair", f"{key[0]}:{key[1]}"),
            "candidate_id": candidate["id"],
            "vacancy_id": vacancy["id"],
            "pairing_basis": "same_primary_keyword" if normalize_keyword(vacancy["primary_keyword"]) == keyword else "random_pool",
            "ground_truth_match": None,
            "approved_by_hr": False,
        })
    return pairs


def chat_drafts(pairs: Iterable[Dict[str, Any]], candidates: List[Dict[str, Any]],
                vacancies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates_by_id = {item["id"]: item for item in candidates}
    vacancies_by_id = {item["id"]: item for item in vacancies}
    result = []
    for index, pair in enumerate(pairs, 1):
        candidate = candidates_by_id[pair["candidate_id"]]
        vacancy = vacancies_by_id[pair["vacancy_id"]]
        prompt = anonymize_text(
            f"Профиль кандидата: {candidate['profile']}\n"
            f"Вакансия: {vacancy['position']}. {vacancy['description']}\n"
            "Оцени релевантность кандидата, назови подтверждённые совпадения и пробелы. "
            "Если данных недостаточно, укажи это."
        )
        result.append({
            "id": f"djinni_chat_{index:05d}",
            "group_id": candidate["id"],
            "scenario": "candidate_assessment",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": "[ТРЕБУЕТСЯ ЭТАЛОННЫЙ ОТВЕТ HR]"},
            ],
            "source_ids": [candidate["id"], vacancy["id"]],
            "pair_id": pair["id"],
            "approved_by_hr": False,
            "anonymized": True,
        })
    return result


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/chat/collected"))
    parser.add_argument("--candidates", type=int, default=500)
    parser.add_argument("--vacancies", type=int, default=200)
    parser.add_argument("--pairs", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--shuffle-buffer", type=int, default=100_000)
    parser.add_argument(
        "--reuse-collected", action="store_true",
        help="Не загружать источники повторно, а пересобрать пары и черновики из output",
    )
    args = parser.parse_args()
    if min(args.candidates, args.vacancies, args.pairs) < 1:
        parser.error("Все размеры выборки должны быть положительными")

    output = args.output
    if args.reuse_collected:
        candidates = [record for _, record in read_jsonl(output / "candidates.jsonl")]
        vacancies = [record for _, record in read_jsonl(output / "vacancies.jsonl")]
        for item in candidates:
            item["id"] = stable_id("candidate", str(item["source"]["source_record_id"]))
        for item in vacancies:
            item["id"] = stable_id("vacancy", str(item["source"]["source_record_id"]))
        occupation_path = output / "occupations.jsonl"
        occupations = ([record for _, record in read_jsonl(occupation_path)]
                       if occupation_path.exists() else load_onet())
    else:
        candidates = [candidate_record(row) for row in stream_sample(
            CANDIDATE_DATASET, args.candidates, args.seed, args.shuffle_buffer
        )]
        vacancies = [vacancy_record(row) for row in stream_sample(
            VACANCY_DATASET, args.vacancies, args.seed, args.shuffle_buffer
        )]
        occupations = load_onet()
    pairs = pair_records(candidates, vacancies, args.pairs, args.seed)
    drafts = chat_drafts(pairs, candidates, vacancies)
    write_jsonl(output / "candidates.jsonl", candidates)
    write_jsonl(output / "vacancies.jsonl", vacancies)
    write_jsonl(output / "occupations.jsonl", occupations)
    write_jsonl(output / "candidate_vacancy_pairs.jsonl", pairs)
    write_jsonl(output / "chat_draft.jsonl", drafts)
    collected_at = datetime.now(timezone.utc).isoformat()
    sources = {
        "collected_at": collected_at,
        "sources": [
            source_meta(CANDIDATE_DATASET, "multiple"),
            source_meta(VACANCY_DATASET, "multiple"),
            {
                "dataset": "O*NET 31.0 Database", "source_url": ONET_URL,
                "license": "CC BY 4.0",
                "attribution": "U.S. Department of Labor, Employment and Training Administration",
            },
        ],
        "citation": "Drushchak and Romanyshyn, UNLP 2024, pp. 8-13",
        "notes": "Original records are real anonymized Djinni profiles and vacancies. Pair labels and chat answers require HR review.",
    }
    report = {
        "collected_at": collected_at,
        "seed": args.seed,
        "shuffle_buffer": args.shuffle_buffer,
        "candidates": len(candidates),
        "vacancies": len(vacancies),
        "occupations": len(occupations),
        "pairs": len(pairs),
        "chat_drafts": len(drafts),
        "approved_chat_records": 0,
        "candidate_keywords": dict(Counter(item["primary_keyword"] for item in candidates).most_common()),
        "vacancy_keywords": dict(Counter(item["primary_keyword"] for item in vacancies).most_common()),
    }
    write_json(output / "sources.json", sources)
    write_json(output / "dataset_report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

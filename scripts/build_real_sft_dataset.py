# -*- coding: utf-8 -*-
"""Собирает prompt-completion датасет из реальных резюме и вакансий.

Не использует synthetic/ и chat_draft.jsonl.
Формат: {"prompt": "...", "completion": "..."} — совместим с TRL SFTTrainer.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _flatten(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(_flatten(v) for v in value if _flatten(v))
    if isinstance(value, dict):
        return " ".join(f"{k}: {_flatten(v)}" for k, v in value.items() if _flatten(v))
    return ""


def load_candidates(path: Path) -> List[Dict[str, Any]]:
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    out = []
    for r in rows:
        profile = _flatten(r.get("profile") or r.get("highlights") or r.get("looking_for"))
        position = _flatten(r.get("position"))
        if not profile and not position:
            continue
        out.append({
            "id": r.get("id"),
            "position": position,
            "profile": profile,
            "experience": r.get("experience_years"),
            "english": r.get("english_level"),
            "keyword": r.get("primary_keyword"),
        })
    return out


def load_vacancies(path: Path) -> List[Dict[str, Any]]:
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    out = []
    for r in rows:
        desc = _flatten(r.get("description"))
        pos = _flatten(r.get("position"))
        if not desc and not pos:
            continue
        out.append({
            "id": r.get("id"),
            "position": pos,
            "description": desc,
            "experience": r.get("experience_required"),
            "english": r.get("english_level"),
            "keyword": r.get("primary_keyword"),
        })
    return out


def make_resume_completion(c: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Из реального резюме делаем пару prompt→completion."""
    parts = []
    if c["position"]:
        parts.append(f"Позиция: {c['position']}")
    if c["profile"]:
        parts.append(f"Профиль: {c['profile']}")
    if c["experience"] is not None:
        parts.append(f"Опыт: {c['experience']} лет")
    if c["english"]:
        parts.append(f"Английский: {c['english']}")
    if c["keyword"]:
        parts.append(f"Ключевой навык: {c['keyword']}")
    if not parts:
        return None
    completion = "\n".join(parts)
    prompt = "Опиши кандидата по его резюме кратко и структурированно."
    return {"prompt": prompt, "completion": completion}


def make_vacancy_completion(v: Dict[str, Any]) -> Optional[Dict[str, str]]:
    parts = []
    if v["position"]:
        parts.append(f"Позиция: {v['position']}")
    if v["description"]:
        parts.append(f"Описание: {v['description'][:500]}")
    if v["experience"] is not None:
        parts.append(f"Требуемый опыт: {v['experience']} лет")
    if v["english"]:
        parts.append(f"Английский: {v['english']}")
    if v["keyword"]:
        parts.append(f"Ключевой навык: {v['keyword']}")
    if not parts:
        return None
    return {
        "prompt": "Опиши вакансию кратко и структурированно.",
        "completion": "\n".join(parts),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat-root", type=Path, default=Path("data/chat"))
    ap.add_argument("--output", type=Path, default=Path("data/chat/training_real_sft"))
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    cand_path = args.chat_root / "collected" / "candidates.jsonl"
    vac_path = args.chat_root / "collected" / "vacancies.jsonl"

    candidates = load_candidates(cand_path) if cand_path.exists() else []
    vacancies = load_vacancies(vac_path) if vac_path.exists() else []
    print(f"кандидатов: {len(candidates)}, вакансий: {len(vacancies)}")

    records: List[Dict[str, str]] = []
    for c in candidates:
        item = make_resume_completion(c)
        if item:
            records.append(item)
    for v in vacancies:
        item = make_vacancy_completion(v)
        if item:
            records.append(item)

    if not records:
        raise SystemExit("Не удалось собрать ни одной пары prompt/completion")

    random.Random(args.seed).shuffle(records)
    n = len(records)
    n_train = int(n * 0.8)
    n_val = int(n * 0.1)
    splits = {
        "train": records[:n_train],
        "validation": records[n_train:n_train + n_val],
        "test": records[n_train + n_val:],
    }

    args.output.mkdir(parents=True, exist_ok=True)
    for name, items in splits.items():
        path = args.output / f"{name}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"{path}: {len(items)}")

    meta = {
        "format": "prompt-completion",
        "synthetic_used": False,
        "sources": ["collected/candidates.jsonl", "collected/vacancies.jsonl"],
        "total": n,
        "splits": {k: len(v) for k, v in splits.items()},
    }
    (args.output / "dataset_metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
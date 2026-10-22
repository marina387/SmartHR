# -*- coding: utf-8 -*-
"""Собирает тренировочный датасет ТОЛЬКО из реальных источников.

Источники (по умолчанию):
- data/chat/raw/approved_chat_feedback.jsonl   (приоритет 1, реальные диалоги)
- data/chat/collected/candidate_vacancy_pairs.jsonl (пары резюме-вакансия)
- data/chat/collected/candidates.jsonl + vacancies.jsonl (сырьё, идёт в eval, не в train)

Правила:
- Синтетика (data/chat/synthetic/*) не используется вообще.
- Сплит по candidate_id — один кандидат не попадает в train и validation одновременно.
- Поля provenance в metadata показывают источник каждой записи.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.chat.dataset import read_jsonl, validate_records, write_jsonl


def _flatten(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(_flatten(v) for v in value if _flatten(v))
    if isinstance(value, dict):
        return " ".join(_flatten(v) for v in value.values() if _flatten(v))
    return ""


def _messages_to_text(msgs: Any) -> str:
    if not isinstance(msgs, list):
        return ""
    parts = []
    for m in msgs:
        if isinstance(m, dict):
            role = str(m.get("role") or "")
            content = _flatten(m.get("content") or m.get("text") or "")
            if content:
                parts.append(f"{role}: {content}" if role else content)
        elif isinstance(m, str):
            parts.append(m)
    return "\n".join(parts)


def normalize_record(rec: Dict[str, Any], source: str) -> Optional[Dict[str, Any]]:
    """Приводит любую схему к {'text', 'source', 'candidate_id', 'approved'}."""
    text = _flatten(rec.get("text")) or _flatten(rec.get("content")) or _messages_to_text(rec.get("messages"))
    if not text:
        for key in ("resume_text", "summary", "answer", "prompt", "description", "title", "resume"):
            if _flatten(rec.get(key)):
                text = _flatten(rec.get(key))
                break
    if not text:
        return None

    candidate_id = rec.get("candidate_id") or rec.get("candidate") or rec.get("candidate_uuid")
    if candidate_id is None:
        # Стабильный хэш по тексту, чтобы хотя бы не рвать один и тот же текст
        candidate_id = "hash_" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    return {
        "text": text,
        "source": source,
        "candidate_id": str(candidate_id),
        "approved": bool(rec.get("approved", source.startswith("raw"))),
        "raw": rec,
    }


def load_real_records(root: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    sources = [
        (root / "raw" / "approved_chat_feedback.jsonl", "raw:approved_feedback"),
        (root / "collected" / "candidate_vacancy_pairs.jsonl", "collected:pairs"),
        (root / "collected" / "candidates.jsonl", "collected:candidates"),
        (root / "collected" / "vacancies.jsonl", "collected:vacancies"),
    ]
    for path, tag in sources:
        if not path.exists():
            print(f"[skip] нет файла: {path}")
            continue
        rows = [rec for _, rec in read_jsonl(path)]
        kept = 0
        for rec in rows:
            norm = normalize_record(rec, tag)
            if norm:
                records.append(norm)
                kept += 1
        print(f"[load] {path.name}: {kept}/{len(rows)} пригодны ({tag})")
    return records


def grouped_split(
    records: List[Dict[str, Any]],
    seed: int,
    ratios: Tuple[float, float, float] = (0.8, 0.1, 0.1),
) -> Dict[str, List[Dict[str, Any]]]:
    """Сплит по candidate_id, чтобы один кандидат не попал в train и val сразу."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for rec in records:
        groups.setdefault(rec["candidate_id"], []).append(rec)
    keys = sorted(groups.keys())
    random.Random(seed).shuffle(keys)

    n = len(keys)
    n_train = max(1, int(n * ratios[0]))
    n_val = max(1, int(n * ratios[1]))
    train_keys = set(keys[:n_train])
    val_keys = set(keys[n_train:n_train + n_val])

    splits = {"train": [], "validation": [], "test": []}
    for key, items in groups.items():
        if key in train_keys:
            splits["train"].extend(items)
        elif key in val_keys:
            splits["validation"].extend(items)
        else:
            splits["test"].extend(items)
    return splits


def strip_raw(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{k: v for k, v in r.items() if k != "raw"} for r in records]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat-root", type=Path, default=Path("data/chat"))
    ap.add_argument("--output", type=Path, default=Path("data/chat/training_real"))
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    records = load_real_records(args.chat_root)
    if not records:
        raise SystemExit("Не найдено ни одной реальной записи — проверьте data/chat/collected и data/chat/raw")

    # Синтетика не должна просочиться, даже если её случайно положили в collected/.
    real = [r for r in records if "synthetic" not in r["source"].casefold()]
    dropped_synth = len(records) - len(real)
    print(f"[check] всего {len(records)}, отброшено синтетических: {dropped_synth}")

    report = validate_records([r["raw"] for r in real], require_approved=False)
    if not report.get("valid", True):
        print("[warn] validate_records вернул ошибки, продолжаем:",
              json.dumps(report, ensure_ascii=False)[:500])

    splits = grouped_split(real, seed=args.seed)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, items in splits.items():
        write_jsonl(args.output / f"{name}.jsonl", strip_raw(items))

    metadata = {
        "format_version": "real-only-1.0",
        "synthetic_used": False,
        "seed": args.seed,
        "records_total": len(real),
        "splits": {name: len(items) for name, items in splits.items()},
        "sources": {},
        "split_strategy": "candidate_grouped",
    }
    for rec in real:
        metadata["sources"][rec["source"]] = metadata["sources"].get(rec["source"], 0) + 1
    (args.output / "dataset_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
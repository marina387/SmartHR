# -*- coding: utf-8 -*-
"""Проверяет, фильтрует синтетику и делит обезличенные примеры на train/validation/test.

Шаги:
1. Читает все *.jsonl из --input.
2. Валидирует записи (validate_records).
3. Опционально фильтрует синтетические записи детектором (--detector):
   оставляет только те, что модель считает похожими на реальные (p_real >= --keep-if-real).
4. Делит записи по времени/кандидату, а не случайно (если есть поля для этого),
   иначе — стратифицированным сплитом.
5. Пишет сплиты + dataset_metadata.json с провенансом (real/synthetic/filtered).
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

from src.chat.dataset import read_jsonl, split_records, validate_records, write_jsonl


# ------------------------------------------------------------------ helpers

def _record_source(record: Dict[str, Any]) -> str:
    """'real' | 'synthetic' | 'unknown' — по полю source или пути."""
    source = str(record.get("source") or record.get("provenance") or "").casefold()
    if "synth" in source or "generated" in source:
        return "synthetic"
    if source in {"real", "human", "collected", "feedback"}:
        return "real"
    return "unknown"


def _record_text(record: Dict[str, Any]) -> str:
    for key in ("text", "content", "message", "prompt", "answer"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _candidate_key(record: Dict[str, Any]) -> Optional[str]:
    """Стабильный ключ кандидата для группового сплита (не рвём одного кандидата между фолдами)."""
    for key in ("candidate_id", "candidate", "candidate_uuid"):
        value = record.get(key)
        if value:
            return str(value)
    return None


def _timestamp_key(record: Dict[str, Any]) -> Optional[str]:
    for key in ("created_at", "timestamp", "date"):
        value = record.get(key)
        if value:
            return str(value)
    return None


# ------------------------------------------------------------------ detector

class SyntheticDetector:
    """Обёртка над обученным бинарным классификатором real vs synthetic."""

    def __init__(self, path: Path, keep_if_real: float = 0.5) -> None:
        import joblib
        self.path = path
        self.keep_if_real = keep_if_real
        self.model = joblib.load(path)

    def real_probability(self, text: str) -> float:
        if not text.strip():
            return 0.0
        # Метки: 1 = real, 0 = synthetic (см. scripts/train_synthetic_detector.py)
        return float(self.model.predict_proba([text])[0, 1])

    def should_keep(self, text: str) -> bool:
        return self.real_probability(text) >= self.keep_if_real


def filter_synthetic(
    records: List[Dict[str, Any]],
    detector: Optional[SyntheticDetector],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Оставляет все real/unknown и только качественные synthetic.

    Возвращает (kept, stats).
    """
    stats = {"synthetic_total": 0, "synthetic_kept": 0, "synthetic_dropped": 0,
             "real_total": 0, "unknown_total": 0, "filter_applied": detector is not None}
    kept: List[Dict[str, Any]] = []
    for rec in records:
        src = _record_source(rec)
        if src == "real":
            stats["real_total"] += 1
            kept.append(rec)
            continue
        if src == "unknown":
            stats["unknown_total"] += 1
            kept.append(rec)
            continue
        stats["synthetic_total"] += 1
        if detector is None:
            kept.append(rec)
            continue
        text = _record_text(rec)
        if detector.should_keep(text):
            stats["synthetic_kept"] += 1
            rec = {**rec, "_synthetic_filtered": True}
            kept.append(rec)
        else:
            stats["synthetic_dropped"] += 1
    return kept, stats


# ------------------------------------------------------------------ split

def _split_grouped(
    records: List[Dict[str, Any]],
    key_fn,
    seed: int,
    ratios: Tuple[float, float, float] = (0.8, 0.1, 0.1),
) -> Dict[str, List[Dict[str, Any]]]:
    """Делит по группам (кандидат/время), чтобы не рвать группу между фолдами."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    orphans: List[Dict[str, Any]] = []
    for rec in records:
        key = key_fn(rec)
        if key is None:
            orphans.append(rec)
        else:
            groups.setdefault(key, []).append(rec)
    keys = sorted(groups.keys())
    rng = random.Random(seed)
    rng.shuffle(keys)

    n = len(keys)
    n_train = int(n * ratios[0])
    n_val = int(n * ratios[1])
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
    # Записи без ключа распределяем 80/10/10 детерминированно по хэшу.
    for rec in orphans:
        bucket = int(hashlib.sha256(str(rec).encode("utf-8")).hexdigest(), 16) % 10
        if bucket < 8:
            splits["train"].append(rec)
        elif bucket == 8:
            splits["validation"].append(rec)
        else:
            splits["test"].append(rec)
    return splits


def split_dataset(
    records: List[Dict[str, Any]],
    seed: int,
) -> Dict[str, List[Dict[str, Any]]]:
    """Пытается сгруппировать по candidate_id, затем по timestamp, иначе — случайный сплит."""
    if any(_candidate_key(r) is not None for r in records):
        return _split_grouped(records, _candidate_key, seed)
    if any(_timestamp_key(r) is not None for r in records):
        return _split_grouped(records, _timestamp_key, seed)
    # Фолбэк на существующий split_records из src.chat.dataset.
    return split_records(records, seed=seed)


# ------------------------------------------------------------------ main

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/chat/anonymized"))
    parser.add_argument("--output", type=Path, default=Path("data/chat"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--allow-unapproved", action="store_true")
    parser.add_argument("--detector", type=Path, default=None,
                        help="Путь к models/synthetic_detector.pkl; если не задан — синтетика не фильтруется")
    parser.add_argument("--keep-if-real", type=float, default=0.5,
                        help="Оставлять синтетическую запись, если детектор считает её реальной с вероятностью >= порога")
    args = parser.parse_args()

    paths = sorted(args.input.glob("*.jsonl")) if args.input.is_dir() else [args.input]
    records: List[Dict[str, Any]] = [
        record for path in paths if path.exists() for _, record in read_jsonl(path)
    ]
    if not records:
        raise SystemExit("Нет записей для подготовки")
    print(f"[load] записей: {len(records)} из {len(paths)} файлов")

    report = validate_records(records, require_approved=not args.allow_unapproved)
    if not report["valid"]:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit("Датасет содержит ошибки")

    detector: Optional[SyntheticDetector] = None
    if args.detector is not None:
        if not args.detector.exists():
            print(f"[warn] детектор не найден: {args.detector} — синтетика не фильтруется")
        else:
            detector = SyntheticDetector(args.detector, keep_if_real=args.keep_if_real)
            print(f"[detector] загружен: {args.detector} (keep_if_real={args.keep_if_real})")

    kept, filter_stats = filter_synthetic(records, detector)
    if not kept:
        raise SystemExit("После фильтрации не осталось записей")
    print(f"[filter] {filter_stats}")

    splits = split_dataset(kept, seed=args.seed)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, items in splits.items():
        write_jsonl(args.output / f"{name}.jsonl", items)

    metadata = {
        "format_version": "1.1",
        "seed": args.seed,
        "records_total": len(records),
        "records_used": len(kept),
        "splits": {name: len(items) for name, items in splits.items()},
        "scenarios": report.get("scenarios", {}),
        "provenance": {
            "real_total": filter_stats["real_total"],
            "synthetic_total": filter_stats["synthetic_total"],
            "synthetic_kept": filter_stats["synthetic_kept"],
            "synthetic_dropped": filter_stats["synthetic_dropped"],
            "unknown_total": filter_stats["unknown_total"],
        },
        "synthetic_filter": {
            "applied": filter_stats["filter_applied"],
            "detector_path": str(args.detector) if args.detector else None,
            "keep_if_real": args.keep_if_real,
        },
        "split_strategy": (
            "candidate_grouped" if any(_candidate_key(r) is not None for r in kept)
            else "time_grouped" if any(_timestamp_key(r) is not None for r in kept)
            else "random"
        ),
    }
    (args.output / "dataset_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
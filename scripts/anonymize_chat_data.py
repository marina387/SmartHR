"""Обезличивает JSONL-файлы перед подготовкой датасета."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.chat.dataset import anonymize_record, read_jsonl, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/chat/raw"))
    parser.add_argument("--output", type=Path, default=Path("data/chat/anonymized"))
    args = parser.parse_args()
    files = sorted(args.input.glob("*.jsonl")) if args.input.is_dir() else [args.input]
    if not files or not all(path.exists() for path in files):
        raise SystemExit(f"JSONL-файлы не найдены: {args.input}")
    total = 0
    for path in files:
        records = [anonymize_record(record) for _, record in read_jsonl(path)]
        write_jsonl(args.output / path.name, records)
        total += len(records)
    print(f"Обезличено записей: {total}. Требуется ручная проверка ФИО и свободного текста.")


if __name__ == "__main__":
    main()

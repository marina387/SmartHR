"""Проверяет JSONL-датасет чата и печатает машиночитаемый отчёт."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.chat.dataset import read_jsonl, validate_records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--require-approved", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    records = []
    for supplied in args.paths:
        paths = sorted(supplied.glob("*.jsonl")) if supplied.is_dir() else [supplied]
        for path in paths:
            records.extend(record for _, record in read_jsonl(path))
    report = validate_records(records, require_approved=args.require_approved)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    raise SystemExit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()

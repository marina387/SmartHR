"""Проверяет и атомарно устанавливает обученный артефакт в SmartHR."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.chat.models import TransformersChatModel
from src.chat.training import install_model_artifact, validate_model_artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--destination", type=Path, default=Path("models/chat_model"))
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    metadata = validate_model_artifact(args.source)
    if args.smoke_test:
        answer = TransformersChatModel(args.source, metadata).generate(
            [{"role": "user", "content": "Ответь одним словом: готово?"}], {"smoke_test": True}
        )
        if not answer.strip():
            raise SystemExit("Пробный запуск вернул пустой ответ")
    if args.check_only:
        print(json.dumps({"valid": True, "metadata": metadata}, ensure_ascii=False, indent=2))
        return
    result = install_model_artifact(args.source.resolve(), args.destination.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

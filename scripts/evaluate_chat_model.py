"""Независимая оценка готовой чат-модели на test.jsonl."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.chat.dataset import read_jsonl, validate_records
from src.chat.models import TransformersChatModel
from src.chat.training import token_f1, validate_model_artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--test", type=Path, default=Path("data/chat/test.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("evaluation/chat"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--skip-validation", action="store_true", 
                        help="Пропустить проверку на персональные данные")
    args = parser.parse_args()

    print(f"[load] Проверяю артефакт модели {args.model} ...")
    metadata = validate_model_artifact(args.model)
    
    print(f"[load] Читаю тестовые данные {args.test} ...")
    records = [record for _, record in read_jsonl(args.test)]
    
    if not args.skip_validation:
        print("[validation] Проверяю датасет на PII...")
        report = validate_records(records, require_approved=True)
        if not report["valid"]:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            raise SystemExit("Датасет содержит ошибки (используйте --skip-validation)")
    else:
        print("[validation] ВНИМАНИЕ: Валидация пропущена (--skip-validation).")

    if args.limit:
        records = records[:args.limit]
        print(f"[limit] Ограничиваю выборку до {len(records)} записей.")

    print(f"[init] Загружаю модель {args.model} ...")
    model = TransformersChatModel(args.model, metadata)
    
    predictions = []
    print(f"[eval] Начинаю генерацию ответов для {len(records)} примеров...")
    
    for i, record in enumerate(records):
        reference = record["messages"][-1]["content"]
        prompt = record["messages"][:-1]
        
        try:
            prediction = model.generate(prompt, {"evaluation": True, "scenario": record.get("scenario")})
        except Exception as e:
            print(f"[error] Ошибка генерации для {record.get('id')}: {e}")
            prediction = ""
            
        predictions.append({
            "id": record["id"],
            "scenario": record.get("scenario"),
            "reference": reference,
            "prediction": prediction,
            "exact_match": prediction.strip() == reference.strip(),
            "token_f1": token_f1(prediction, reference),
            "empty": not prediction.strip(),
        })
        
        if (i + 1) % 50 == 0:
            print(f"[eval] Обработано {i + 1} / {len(records)}")

    count = len(predictions)
    if count == 0:
        raise SystemExit("[error] Нет предсказаний для оценки!")

    metrics = {
        "records": count,
        "exact_match": sum(item["exact_match"] for item in predictions) / count,
        "mean_token_f1": sum(item["token_f1"] for item in predictions) / count,
        "empty_rate": sum(item["empty"] for item in predictions) / count,
        "model": metadata,
        "limitations": "Автоматические текстовые метрики не заменяют проверку фактов и оценку HR.",
    }

    print("[save] Сохраняю результаты...")
    args.output.mkdir(parents=True, exist_ok=True)
    
    (args.output / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    
    with (args.output / "predictions.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for item in predictions:
            stream.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    with (args.output / "hr_review.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "id", "scenario", "reference", "prediction", "factually_correct",
            "grounded", "safe", "useful", "hr_comment",
        ])
        writer.writeheader()
        for item in predictions:
            writer.writerow({key: item.get(key, "") for key in writer.fieldnames})

    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"\n[completed] Результаты сохранены в {args.output}")


if __name__ == "__main__":
    main()
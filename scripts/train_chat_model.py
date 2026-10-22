"""LoRA/QLoRA-обучение чат-модели по подготовленному JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.chat.dataset import read_jsonl, validate_records
from src.chat.training import TrainingConfig, format_chat


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/chat_training.yaml"))
    parser.add_argument("--check", action="store_true", help="Проверить конфигурацию и данные без обучения")
    parser.add_argument("--resume", action="store_true", help="Продолжить с последнего чекпоинта")
    parser.add_argument("--skip-validation", action="store_true", 
                        help="Пропустить проверку на персональные данные (используйте, если данные уже анонимизированы)")
    args = parser.parse_args()

    config = TrainingConfig.from_yaml(args.config)
    config.validate(require_files=True)
    
    print(f"[data] Читаю {config.train_file} ...")
    records = [record for _, record in read_jsonl(config.train_file)]
    
    print(f"[data] Читаю {config.validation_file} ...")
    validation = [record for _, record in read_jsonl(config.validation_file)]
    
    all_records = records + validation
    if not records:
        raise SystemExit("[ERROR] Тренировочный файл пуст!")

    # --- ВАЛИДАЦИЯ ---
    if not args.skip_validation:
        print("[validation] Проверяю датасет на PII и формат...")
        report = validate_records(
            all_records, require_approved=not config.allow_unapproved_synthetic
        )
        if not report["valid"]:
            raise SystemExit(json.dumps(report, ensure_ascii=False, indent=2))
        
        if config.allow_unapproved_synthetic:
            unsafe = [
                record.get("id") for record in all_records
                if record.get("approved_by_hr") is not True and record.get("synthetic") is not True
            ]
            if unsafe:
                raise SystemExit(
                    "Неподтверждённые несинтетические записи запрещены: " + ", ".join(map(str, unsafe[:10]))
                )
    else:
        print("[validation] ВНИМАНИЕ: Валидация пропущена (--skip-validation).")

    if args.check:
        print(json.dumps({"ready": True, "train": len(records), "validation": len(validation),
                          "config": config.public_dict()}, ensure_ascii=False, indent=2))
        return

    # --- ЗАГРУЗКА БИБЛИОТЕК ---
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from transformers import (
            AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig,
            DataCollatorForLanguageModeling, Trainer, TrainingArguments,
        )
    except ImportError as exc:
        raise SystemExit("Установите зависимости: pip install -r requirements-training.txt") from exc

    # --- ЗАГРУЗКА МОДЕЛИ ---
    print(f"[model] Загружаю токенизатор {config.base_model} ...")
    tokenizer = AutoTokenizer.from_pretrained(config.base_model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    quantization = None
    if config.method == "qlora":
        try:
            import bitsandbytes  # noqa: F401
        except ImportError as exc:
            raise SystemExit("Для QLoRA установите bitsandbytes или выберите method: lora") from exc
        quantization = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
        )
    
    print(f"[model] Загружаю базовую модель {config.base_model} (это может занять время)...")
    model = AutoModelForCausalLM.from_pretrained(
        config.base_model, quantization_config=quantization,
        device_map="auto" if torch.cuda.is_available() else None,
    )
    if quantization is not None:
        model = prepare_model_for_kbit_training(model)
    
    model = get_peft_model(model, LoraConfig(
        r=config.lora_r, lora_alpha=config.lora_alpha, lora_dropout=config.lora_dropout,
        task_type="CAUSAL_LM", target_modules="all-linear",
    ))
    print("[model] LoRA-адаптеры инициализированы.")

    # --- ТОКЕНИЗАЦИЯ ---
    def tokenize(record):
        text = format_chat(record["messages"], tokenizer)
        return tokenizer(text, truncation=True, max_length=config.max_length)

    print(f"[data] Токенизирую {len(records)} тренировочных примеров...")
    train_dataset = Dataset.from_list(records).map(tokenize, remove_columns=list(records[0].keys()))
    
    print(f"[data] Токенизирую {len(validation)} валидационных примеров...")
    validation_dataset = Dataset.from_list(validation).map(tokenize, remove_columns=list(validation[0].keys()))

    # --- ОБУЧЕНИЕ ---
    arguments = TrainingArguments(
        output_dir=str(config.output_dir), num_train_epochs=config.epochs,
        learning_rate=config.learning_rate,
        per_device_train_batch_size=config.per_device_train_batch_size,
        per_device_eval_batch_size=config.per_device_eval_batch_size,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        eval_strategy="epoch", save_strategy="epoch", logging_steps=10,
        load_best_model_at_end=True, seed=config.seed, report_to="none",
        fp16=torch.cuda.is_available() and not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_available() and torch.cuda.is_bf16_supported(),
        dataloader_pin_memory=torch.cuda.is_available(),
    )
    
    trainer = Trainer(
        model=model, args=arguments, train_dataset=train_dataset, eval_dataset=validation_dataset,
        data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False),
    )
    
    print("[train] Начинаю обучение...")
    result = trainer.train(resume_from_checkpoint=True if args.resume else None)
    
    print("[save] Сохраняю модель...")
    config.output_dir.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(config.output_dir))
    tokenizer.save_pretrained(str(config.output_dir))
    
    metadata = {
        "model_type": "causal_lm", "base_model": config.base_model, "format_version": "1.0",
        "language": ["ru"], "context_length": config.max_length, "supports_tools": False,
        "training_dataset_version": "1.0", "training_method": config.method,
        "synthetic_training_allowed": config.allow_unapproved_synthetic,
        "training_metrics": result.metrics,
        "skip_validation": args.skip_validation,
    }
    (config.output_dir / "smarthr_model_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"completed": True, "output_dir": str(config.output_dir),
                      "metrics": result.metrics}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
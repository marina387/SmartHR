"""Общие контракты обучения, оценки и установки чат-модели."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class TrainingConfig:
    base_model: str
    train_file: Path
    validation_file: Path
    output_dir: Path
    method: str = "lora"
    epochs: float = 3.0
    learning_rate: float = 2e-4
    max_length: int = 4096
    seed: int = 42
    per_device_train_batch_size: int = 1
    per_device_eval_batch_size: int = 1
    gradient_accumulation_steps: int = 8
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    allow_unapproved_synthetic: bool = False

    @classmethod
    def from_yaml(cls, path: Path) -> "TrainingConfig":
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("Установите requirements-training.txt") from exc
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        base = path.resolve().parents[1] if path.parent.name == "configs" else Path.cwd()

        def resolve(value: str) -> Path:
            result = Path(value)
            return result if result.is_absolute() else base / result

        config = cls(
            base_model=str(payload.get("base_model") or ""),
            train_file=resolve(str(payload.get("train_file") or "")),
            validation_file=resolve(str(payload.get("validation_file") or "")),
            output_dir=resolve(str(payload.get("output_dir") or "")),
            method=str(payload.get("method") or "lora").casefold(),
            epochs=float(payload.get("epochs", 3)),
            learning_rate=float(payload.get("learning_rate", 2e-4)),
            max_length=int(payload.get("max_length", 4096)),
            seed=int(payload.get("seed", 42)),
            per_device_train_batch_size=int(payload.get("per_device_train_batch_size", 1)),
            per_device_eval_batch_size=int(payload.get("per_device_eval_batch_size", 1)),
            gradient_accumulation_steps=int(payload.get("gradient_accumulation_steps", 8)),
            lora_r=int(payload.get("lora_r", 16)),
            lora_alpha=int(payload.get("lora_alpha", 32)),
            lora_dropout=float(payload.get("lora_dropout", 0.05)),
            allow_unapproved_synthetic=bool(payload.get("allow_unapproved_synthetic", False)),
        )
        config.validate(require_files=False)
        return config

    def validate(self, *, require_files: bool = True) -> None:
        if not self.base_model or self.base_model.startswith("replace-"):
            raise ValueError("Укажите base_model в конфигурации")
        if self.method not in {"lora", "qlora"}:
            raise ValueError("method должен быть lora или qlora")
        if self.epochs <= 0 or self.learning_rate <= 0 or self.max_length < 128:
            raise ValueError("Некорректные параметры обучения")
        if require_files:
            for path in (self.train_file, self.validation_file):
                if not path.is_file():
                    raise ValueError(f"Файл датасета не найден: {path}")

    def public_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        for key in ("train_file", "validation_file", "output_dir"):
            result[key] = str(result[key])
        return result


def format_chat(messages: List[Dict[str, str]], tokenizer: Any | None = None) -> str:
    if tokenizer is not None and getattr(tokenizer, "chat_template", None):
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    labels = {"system": "Система", "user": "Пользователь", "assistant": "Ассистент", "tool": "Инструмент"}
    return "\n".join(f"{labels.get(item['role'], item['role'])}: {item['content']}" for item in messages)


def token_f1(prediction: str, reference: str) -> float:
    prediction_tokens = prediction.casefold().split()
    reference_tokens = reference.casefold().split()
    if not prediction_tokens or not reference_tokens:
        return float(prediction_tokens == reference_tokens)
    common = 0
    remaining = list(reference_tokens)
    for token in prediction_tokens:
        if token in remaining:
            common += 1
            remaining.remove(token)
    if common == 0:
        return 0.0
    precision = common / len(prediction_tokens)
    recall = common / len(reference_tokens)
    return 2 * precision * recall / (precision + recall)


def validate_model_artifact(path: Path) -> Dict[str, Any]:
    metadata_path = path / "smarthr_model_metadata.json"
    if not metadata_path.is_file():
        raise ValueError("Нет smarthr_model_metadata.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if str(metadata.get("format_version")) != "1.0":
        raise ValueError("Неподдерживаемая версия артефакта")
    if not metadata.get("base_model"):
        raise ValueError("В метаданных отсутствует base_model")
    has_adapter = (path / "adapter_config.json").is_file() and any(path.glob("adapter_model.*"))
    has_full_model = (path / "config.json").is_file() and any(path.glob("model*.safetensors"))
    if not has_adapter and not has_full_model:
        raise ValueError("Не найдены веса LoRA-адаптера или полной модели")
    tokenizer_files = [path / "tokenizer.json", path / "tokenizer_config.json"]
    if not any(item.is_file() for item in tokenizer_files):
        raise ValueError("Не найден токенизатор")
    return {**metadata, "artifact_type": "adapter" if has_adapter else "full_model"}


def install_model_artifact(source: Path, destination: Path) -> Dict[str, Any]:
    if source.resolve() == destination.resolve():
        raise ValueError("Источник и каталог установки должны отличаться")
    metadata = validate_model_artifact(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if destination.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup = destination.parent / f"{destination.name}_backup_{stamp}"
        try:
            destination.rename(backup)
        except PermissionError:
            shutil.copytree(destination, backup)
            shutil.rmtree(destination)
    try:
        shutil.copytree(source, destination)
    except Exception:
        if destination.exists():
            shutil.rmtree(destination)
        if backup and backup.exists():
            backup.rename(destination)
        raise
    return {"installed_to": str(destination), "backup": str(backup) if backup else None, "metadata": metadata}

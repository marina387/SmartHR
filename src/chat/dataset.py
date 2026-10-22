"""Подготовка и проверка датасета чат-ассистента SmartHR."""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Sequence, Tuple

ALLOWED_ROLES = {"system", "user", "assistant", "tool"}
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+7|8)[\s(.-]*\d{3}[\s).-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}(?!\d)")
URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
PASSPORT_RE = re.compile(r"(?<!\d)\d{4}\s?\d{6}(?!\d)")
SNILS_RE = re.compile(r"(?<!\d)\d{3}[- ]?\d{3}[- ]?\d{3}[ -]?\d{2}(?!\d)")


def read_jsonl(path: Path) -> Iterator[Tuple[int, Dict[str, Any]]]:
    """Читает JSONL и сообщает номер проблемной строки."""
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: некорректный JSON: {exc.msg}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: запись должна быть объектом")
            yield line_number, value


def write_jsonl(path: Path, records: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def anonymize_text(text: str, replacements: Dict[str, str] | None = None) -> str:
    """Удаляет однозначные идентификаторы; ФИО передаются через replacements."""
    result = str(text)
    for original, marker in sorted((replacements or {}).items(), key=lambda item: len(item[0]), reverse=True):
        if original.strip():
            result = re.sub(re.escape(original), marker, result, flags=re.IGNORECASE)
    result = EMAIL_RE.sub("[EMAIL]", result)
    result = PHONE_RE.sub("[PHONE]", result)
    result = URL_RE.sub("[URL]", result)
    result = PASSPORT_RE.sub("[PASSPORT]", result)
    result = SNILS_RE.sub("[SNILS]", result)
    return result


def anonymize_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Обезличивает свободный текст и известные структурированные поля."""
    source = json.loads(json.dumps(record, ensure_ascii=False))
    replacements: Dict[str, str] = {}
    candidate_name = str(source.get("candidate_name") or "").strip()
    if candidate_name:
        replacements[candidate_name] = "[CANDIDATE_NAME]"

    sensitive_keys = {
        "candidate_name": "[CANDIDATE_NAME]",
        "name": "[PERSON_NAME]",
        "email": "[EMAIL]",
        "phone": "[PHONE]",
        "address": "[ADDRESS]",
    }

    def clean(value: Any, key: str = "") -> Any:
        if key in sensitive_keys and value not in (None, ""):
            return sensitive_keys[key]
        if isinstance(value, str):
            return anonymize_text(value, replacements)
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {item_key: clean(item_value, item_key) for item_key, item_value in value.items()}
        return value

    cleaned = clean(source)
    cleaned["anonymized"] = True
    return cleaned


def validate_record(record: Dict[str, Any], *, require_approved: bool = False) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    record_id = str(record.get("id") or "").strip()
    scenario = str(record.get("scenario") or "").strip()
    messages = record.get("messages")
    if not record_id:
        errors.append("отсутствует id")
    if not scenario:
        errors.append("отсутствует scenario")
    if not isinstance(messages, list) or len(messages) < 2:
        errors.append("messages должен содержать минимум два сообщения")
        return errors, warnings
    roles: List[str] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            errors.append(f"messages[{index}] должен быть объектом")
            continue
        role = str(message.get("role") or "")
        content = str(message.get("content") or "").strip()
        roles.append(role)
        if role not in ALLOWED_ROLES:
            errors.append(f"messages[{index}].role недопустим: {role}")
        if not content:
            errors.append(f"messages[{index}].content пуст")
        if len(content) > 16000:
            warnings.append(f"messages[{index}] длиннее 16000 символов")
    if "user" not in roles:
        errors.append("нет сообщения пользователя")
    if not roles or roles[-1] != "assistant":
        errors.append("последнее сообщение должно принадлежать assistant")
    if require_approved and record.get("approved_by_hr") is not True:
        errors.append("пример не подтверждён HR")
    elif record.get("approved_by_hr") is not True:
        warnings.append("пример пока не подтверждён HR")
    serialized = json.dumps(record, ensure_ascii=False)
    if EMAIL_RE.search(serialized) or PHONE_RE.search(serialized) or PASSPORT_RE.search(serialized) or SNILS_RE.search(serialized):
        errors.append("обнаружены возможные персональные данные")
    if not record.get("group_id") and not record.get("candidate_id") and not record.get("document_id"):
        warnings.append("нет group_id/candidate_id/document_id для защиты от утечки")
    return errors, warnings


def validate_records(records: Sequence[Dict[str, Any]], *, require_approved: bool = False) -> Dict[str, Any]:
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    ids: Counter[str] = Counter(str(item.get("id") or "") for item in records)
    for record in records:
        record_errors, record_warnings = validate_record(record, require_approved=require_approved)
        if ids[str(record.get("id") or "")] > 1:
            record_errors.append("дублирующийся id")
        if record_errors:
            errors.append({"id": record.get("id"), "messages": record_errors})
        if record_warnings:
            warnings.append({"id": record.get("id"), "messages": record_warnings})
    scenarios = Counter(str(item.get("scenario") or "unknown") for item in records)
    fingerprints = Counter(record_fingerprint(item) for item in records)
    duplicate_content = sum(count - 1 for count in fingerprints.values() if count > 1)
    if duplicate_content:
        errors.append({"id": None, "messages": [f"дубликатов по содержимому: {duplicate_content}"]})
    return {
        "valid": not errors,
        "records": len(records),
        "scenarios": dict(sorted(scenarios.items())),
        "errors": errors,
        "warnings": warnings,
    }


def record_fingerprint(record: Dict[str, Any]) -> str:
    messages = record.get("messages") if isinstance(record.get("messages"), list) else []
    normalized = "\n".join(
        f"{item.get('role')}:{str(item.get('content') or '').strip().casefold()}"
        for item in messages if isinstance(item, dict)
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def group_key(record: Dict[str, Any]) -> str:
    return str(
        record.get("group_id") or record.get("candidate_id") or
        record.get("document_id") or record.get("id")
    )


def split_records(records: Sequence[Dict[str, Any]], *, seed: int = 42,
                  train_ratio: float = 0.8, validation_ratio: float = 0.1) -> Dict[str, List[Dict[str, Any]]]:
    """Делит по группам, исключая попадание одного кандидата в разные части."""
    if not records:
        return {"train": [], "validation": [], "test": []}
    if train_ratio <= 0 or validation_ratio < 0 or train_ratio + validation_ratio >= 1:
        raise ValueError("Некорректные доли разбиения")
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(group_key(record), []).append(record)
    keys = sorted(grouped)
    random.Random(seed).shuffle(keys)
    count = len(keys)
    train_end = max(1, round(count * train_ratio))
    validation_end = train_end + round(count * validation_ratio)
    if count >= 3:
        train_end = min(train_end, count - 2)
        validation_end = min(max(validation_end, train_end + 1), count - 1)
    assignments = {
        key: "train" if index < train_end else "validation" if index < validation_end else "test"
        for index, key in enumerate(keys)
    }
    result: Dict[str, List[Dict[str, Any]]] = {"train": [], "validation": [], "test": []}
    for record in records:
        result[assignments[group_key(record)]].append(record)
    return result

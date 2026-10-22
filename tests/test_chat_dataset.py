"""Проверки контура подготовки реальных данных для чат-модели."""

from src.chat.dataset import anonymize_record, split_records, validate_records


def record(record_id: str, group_id: str, approved: bool = True):
    return {
        "id": record_id,
        "group_id": group_id,
        "scenario": "score_explanation",
        "messages": [
            {"role": "user", "content": "Объясни оценку"},
            {"role": "assistant", "content": "Оценка получена из SmartHR."},
        ],
        "approved_by_hr": approved,
        "anonymized": True,
    }


def test_anonymization_removes_structured_and_free_text_pii():
    source = {
        "id": "one",
        "candidate_name": "Иван Иванов",
        "email": "ivan@example.ru",
        "messages": [
            {"role": "user", "content": "Напиши Ивану Иванову: ivan@example.ru, +7 (912) 123-45-67"},
            {"role": "assistant", "content": "Черновик подготовлен"},
        ],
    }
    cleaned = anonymize_record(source)
    rendered = str(cleaned)
    assert "ivan@example.ru" not in rendered
    assert "+7 (912) 123-45-67" not in rendered
    assert "Иван Иванов" not in rendered
    assert cleaned["anonymized"] is True


def test_validation_requires_hr_approval_for_training():
    report = validate_records([record("one", "candidate-1", approved=False)], require_approved=True)
    assert report["valid"] is False
    assert "не подтверждён HR" in report["errors"][0]["messages"][0]


def test_validation_detects_duplicate_content():
    first = record("one", "candidate-1")
    second = record("two", "candidate-2")
    report = validate_records([first, second], require_approved=True)
    assert report["valid"] is False
    assert any("дубликатов" in message for item in report["errors"] for message in item["messages"])


def test_group_split_prevents_candidate_leakage():
    records = [record(f"item-{index}", f"candidate-{index // 2}") for index in range(12)]
    splits = split_records(records, seed=42)
    groups = {
        name: {item["group_id"] for item in items}
        for name, items in splits.items()
    }
    assert groups["train"].isdisjoint(groups["validation"])
    assert groups["train"].isdisjoint(groups["test"])
    assert groups["validation"].isdisjoint(groups["test"])
    assert all(splits.values())

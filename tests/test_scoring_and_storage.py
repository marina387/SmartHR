import json
from pathlib import Path

import pytest

from src.services.scoring import CandidateScoringService
from src.storage.file_storage import FileCandidateStorage


@pytest.fixture
def scoring_service():
    return CandidateScoringService()


def test_scoring_service_returns_structured_result(scoring_service):
    result = scoring_service.score_candidate(
        "Опыт 5 лет, переговоры, клиентский сервис, английский",
        ["клиентский сервис"],
        {"hard": 70, "management": 20, "soft": 10, "education": 50, "salary": 40},
    )

    assert result["status"] in {"green", "yellow", "red"}
    assert result["total"] >= 0
    assert result["scores"]
    assert "hard" in result["scores"]


def test_file_storage_persists_candidates(tmp_path):
    storage = FileCandidateStorage(tmp_path / "candidates.json")

    candidate = {
        "id": "c1",
        "name": "Иван",
        "status": "green",
        "decision": "Рекомендован",
        "total": 82,
        "scores": {"hard": 8},
        "comments": {"hard": "ok"},
        "timestamp": "2026-01-01 12:00",
    }

    storage.save_candidate(candidate)
    items = storage.list_candidates()

    assert len(items) == 1
    assert items[0]["name"] == "Иван"

    raw = json.loads((tmp_path / "candidates.json").read_text(encoding="utf-8"))
    assert raw["c1"]["id"] == "c1"

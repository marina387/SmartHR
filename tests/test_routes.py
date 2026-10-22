"""Тесты для маршрутов Flask-приложения."""

from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app import app
from src.routes import main as main_routes
from src.services.vacancy_service import VacancyService
from src.storage.vacancy_storage import VacancyStorage


@pytest.fixture
def client() -> Any:
    """Возвращает тестовый клиент Flask-приложения."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def isolated_vacancy_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> VacancyService:
    """Подменяет хранилище вакансий на временное для изоляции тестов."""
    storage = VacancyStorage(tmp_path / "vacancies.json")
    service = VacancyService(storage)
    monkeypatch.setattr(main_routes, "vacancy_storage", storage)
    monkeypatch.setattr(main_routes, "vacancy_service", service)
    return service


def test_score_endpoint_returns_result(client: Any) -> None:
    """Эндпоинт /api/score должен возвращать оценку кандидата."""
    response = client.post(
        "/api/score",
        json={
            "candidate_text": "Опыт 5 лет, управление персоналом, документооборот",
            "critical_requirements": ["управление"],
            "weights": {"hard": 90, "management": 10, "soft": 50, "education": 20, "salary": 30},
        },
    )

    assert response.status_code == 200
    assert response.get_json()["status"] in {"green", "yellow", "red"}
    assert "total" in response.get_json()


def test_upload_endpoint_accepts_text_payload(client: Any) -> None:
    """Эндпоинт /api/upload должен принимать текст в JSON."""
    response = client.post(
        "/api/upload",
        json={"text": "Имя: Иван\nКоммуникация, документооборот", "filename": "resume.txt"},
    )

    assert response.status_code == 200
    assert response.get_json()["text"] == "Имя: Иван\nКоммуникация, документооборот"


def test_upload_endpoint_parses_uploaded_file(client: Any) -> None:
    """Эндпоинт /api/upload должен обрабатывать загруженный файл."""
    data = {
        "file": (BytesIO(b"dummy content"), "resume.txt"),
    }

    with patch("src.routes.main.parse_txt", create=True):
        response = client.post(
            "/api/upload",
            data=data,
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert response.get_json()["filename"] == "resume.txt"


def test_vacancy_api_save_get_update_weights(client: Any, isolated_vacancy_storage: VacancyService) -> None:
    """API вакансий должен сохранять и обновлять веса внутри вакансии."""
    vacancy_id = "VAC_042"

    create_response = client.post(
        "/api/vacancies",
        json={
            "id": vacancy_id,
            "title": "HR Manager",
            "category": "HR",
            "weights": {"hard": 50, "soft": 30, "management": 10, "education": 5, "salary": 5},
        },
    )
    assert create_response.status_code == 201
    assert create_response.get_json()["id"] == vacancy_id

    update_response = client.put(
        f"/api/vacancies/{vacancy_id}",
        json={
            "weights": {"hard": 55, "soft": 25, "management": 10, "education": 5, "salary": 5},
            "created_by": "HR_ANNA",
        },
    )
    assert update_response.status_code == 200
    updated = update_response.get_json()
    assert updated["created_by"] == "HR_ANNA"
    assert sum(updated["weights"].values()) == 100

    get_saved = client.get(f"/api/vacancies/{vacancy_id}")
    assert get_saved.status_code == 200
    assert get_saved.get_json()["weights"] == updated["weights"]


def test_score_endpoint_uses_vacancy_weights_when_not_passed(client: Any, isolated_vacancy_storage: VacancyService) -> None:
    """Если веса не переданы в /api/score, должны применяться веса выбранной вакансии."""
    vacancy_id = "VAC_007"
    create_response = client.post(
        "/api/vacancies",
        json={"id": vacancy_id, "title": "Оператор", "weights": {"hard": 50, "soft": 30, "management": 10, "education": 5, "salary": 5}},
    )
    assert create_response.status_code == 201

    update_response = client.put(
        f"/api/vacancies/{vacancy_id}",
        json={
            "weights": {"hard": 70, "soft": 15, "management": 10, "education": 3, "salary": 2},
            "created_by": "HR_IVAN",
        },
    )
    assert update_response.status_code == 200

    score_response = client.post(
        "/api/score",
        json={
            "vacancy_id": vacancy_id,
            "candidate_text": "Опыт 5 лет, управление персоналом, документооборот",
            "critical_requirements": ["управление"],
        },
    )

    assert score_response.status_code == 200
    payload = score_response.get_json()
    assert payload["vacancy_id"] == vacancy_id
    assert payload["used_weights"] == {"hard": 70, "soft": 15, "management": 10, "education": 3, "salary": 2}

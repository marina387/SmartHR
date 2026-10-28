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


def test_edit_candidate_preserves_assessment(client: Any) -> None:
    record = {"id": "CV_edit_test", "name": "До", "resume_text": "Исходное резюме", "total": 34,
              "scores": {"hard": 0.4}, "lifecycle_status": "archived", "stage": "archived"}
    with app.app_context():
        main_routes.storage.save_candidate(record)
    response = client.patch('/api/candidates/CV_edit_test', json={
        'revision':1, 'name': ' После ', 'email': 'test@example.com', 'phone': '+7 (900) 123-45-67', 'hr_notes': '<b>Заметка</b>'})
    assert response.status_code == 200
    with app.app_context():
        saved = main_routes.storage.get_candidate('CV_edit_test')
    assert saved['name'] == 'После' and saved['hr_notes'] == '<b>Заметка</b>'
    for key in ('resume_text', 'total', 'scores', 'lifecycle_status', 'stage'):
        assert saved[key] == record[key]
    for body in ({'total': 99}, {'name': ''}, {'email': 'invalid'}, {'phone': 'abc'}, {'hr_notes': []}):
        assert client.patch('/api/candidates/CV_edit_test', json=body).status_code == 400
    assert client.patch('/api/candidates/no-such-candidate', json={'name': 'Имя'}).status_code == 404


def test_resume_edit_rescores_and_keeps_stage(client: Any, monkeypatch) -> None:
    record = {'id': 'CV_resume_edit', 'name': 'Тест', 'resume_text': 'До', 'total': 0,
              'vacancy_id': 'VAC_001', 'lifecycle_status': 'archived', 'stage': 'rejected',
              'scores': {}, 'score_status': 'blocked_by_requirements'}
    with app.app_context():
        main_routes.vacancy_storage.save({'id': 'VAC_001', 'title': 'Тестовая вакансия'})
        main_routes.storage.save_candidate(record)
    result = {'total': 65, 'status': 'yellow', 'decision': 'Требует проверки', 'scores': {'hard': 6},
              'comments': {'hard': 'Уточнён опыт'}, 'critical_failures': [], 'score_status': 'calculated'}
    def score(text, requirements, weights, vacancy):
        assert text == 'После SQL' and vacancy['id'] == 'VAC_001'
        return result
    monkeypatch.setattr(main_routes.scoring_service, 'score_candidate', score)
    assert client.patch('/api/candidates/CV_resume_edit', json={'revision':1,'resume_text': 'После SQL'}).status_code == 400
    response = client.patch('/api/candidates/CV_resume_edit', json={'revision':1,'resume_text': 'После SQL', 'rescore': True})
    assert response.status_code == 200
    with app.app_context():
        saved = main_routes.storage.get_candidate('CV_resume_edit')
    assert saved['total'] == 65 and saved['resume_text'] == 'После SQL'
    assert saved['lifecycle_status'] == 'archived' and saved['stage'] == 'rejected'
    assert saved['resume_revisions'][0]['resume_text'] == 'До'
    assert saved['resume_revisions'][0]['result']['total'] == 0
    def fail(*args, **kwargs):
        raise RuntimeError('test scoring failure')
    monkeypatch.setattr(main_routes.scoring_service, 'score_candidate', fail)
    assert client.patch('/api/candidates/CV_resume_edit', json={'revision':saved['revision'],'resume_text': 'Не сохранять', 'rescore': True}).status_code == 500
    with app.app_context():
        assert main_routes.storage.get_candidate('CV_resume_edit')['resume_text'] == 'После SQL'


def test_unknown_api_route_and_wrong_method_return_json(client: Any) -> None:
    missing = client.get('/api/does-not-exist')
    assert missing.status_code == 404 and missing.is_json
    wrong_method = client.get('/api/score')
    assert wrong_method.status_code == 405 and wrong_method.is_json
    assert client.get('/does-not-exist').status_code == 404


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
    assert updated["created_by"] == "HR_TEST"
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

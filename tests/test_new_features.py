# -*- coding: utf-8 -*-
"""Тесты новых функций: ручной ввод, вакансии, интервью и обратная связь."""

from pathlib import Path
from typing import Any
from types import SimpleNamespace

import pytest

from app import app
from src.routes import main as main_routes
from src.services.feedback_service import FeedbackService
from src.services.interview_service import InterviewService
from src.services.vacancy_service import VacancyService
from src.services.candidate_vacancy_service import CandidateVacancyService
from src.services.candidate_stage_service import CandidateStageService
from src.services.funnel_service import FunnelService
from src.storage.candidate_vacancy_storage import CandidateVacancyStorage
from src.storage.candidate_stage_event_storage import CandidateStageEventStorage
from src.storage.feedback_storage import FeedbackStorage
from src.storage.file_storage import FileCandidateStorage
from src.storage.interview_storage import InterviewStorage
from src.storage.vacancy_storage import VacancyStorage
from src.storage.transfer_storage import TransferStorage


@pytest.fixture
def client() -> Any:
    """Возвращает тестовый клиент Flask-приложения."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def isolated_feature_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Изолирует файловые хранилища новых функций во временной папке."""
    candidate_storage = FileCandidateStorage(tmp_path / "candidates.json")
    vacancy_storage = VacancyStorage(tmp_path / "vacancies.json")
    interview_storage = InterviewStorage(tmp_path / "interviews.json")
    feedback_storage = FeedbackStorage(tmp_path / "feedback.json")
    candidate_vacancy_storage = CandidateVacancyStorage(tmp_path / "candidate_vacancies.json")
    transfer_storage = TransferStorage(tmp_path / "candidate_transfers.json")
    stage_event_storage = CandidateStageEventStorage(tmp_path / "candidate_stage_events.json")
    vacancy_service = VacancyService(vacancy_storage)

    monkeypatch.setattr(main_routes, "storage", candidate_storage)
    monkeypatch.setattr(main_routes, "vacancy_storage", vacancy_storage)
    monkeypatch.setattr(main_routes, "vacancy_service", vacancy_service)
    monkeypatch.setattr(main_routes, "interview_storage", interview_storage)
    monkeypatch.setattr(main_routes, "interview_service", InterviewService(interview_storage))
    monkeypatch.setattr(main_routes, "feedback_storage", feedback_storage)
    monkeypatch.setattr(main_routes, "feedback_service", FeedbackService(feedback_storage))
    monkeypatch.setattr(main_routes, "candidate_vacancy_storage", candidate_vacancy_storage)
    monkeypatch.setattr(main_routes, "transfer_storage", transfer_storage)
    stage_service = CandidateStageService(candidate_vacancy_storage, stage_event_storage)
    monkeypatch.setattr(main_routes, "candidate_stage_event_storage", stage_event_storage)
    monkeypatch.setattr(main_routes, "candidate_stage_service", stage_service)
    monkeypatch.setattr(main_routes, "candidate_vacancy_service", CandidateVacancyService(candidate_vacancy_storage, transfer_storage, stage_service))
    monkeypatch.setattr(main_routes, "funnel_service", FunnelService(candidate_vacancy_storage, stage_event_storage, candidate_storage))
    monkeypatch.setattr(main_routes, "score_result_storage", SimpleNamespace(save=lambda payload: payload))


def test_manual_candidate_creation(client: Any, isolated_feature_storage: None) -> None:
    """Ручной ввод должен создавать кандидата и сохранять оценку."""
    response = client.post(
        "/api/candidates/manual",
        json={
            "name": "Иванов Алексей",
            "position": "Специалист",
            "vacancy_id": "VAC_001",
            "resume_text": "Опыт 5 лет, управление командой, высшее образование",
        },
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["name"] == "Иванов Алексей"
    assert payload["vacancy_id"] == "VAC_001"
    assert payload["status"] in {"green", "yellow", "red"}


def test_vacancies_crud(client: Any, isolated_feature_storage: None) -> None:
    """API вакансий должен поддерживать создание, чтение, обновление и удаление."""
    create_response = client.post(
        "/api/vacancies",
        json={
            "title": "Backend Developer",
            "category": "IT",
            "description": "Python/Flask",
            "critical_requirements": ["Python", "Flask"],
            "skills": ["Коммуникация"],
            "weights": {"hard": 50, "soft": 30, "management": 10, "education": 5, "salary": 5},
        },
    )
    assert create_response.status_code == 201
    vacancy = create_response.get_json()
    vacancy_id = vacancy["id"]

    list_response = client.get("/api/vacancies")
    assert list_response.status_code == 200
    assert any(item["id"] == vacancy_id for item in list_response.get_json())

    get_response = client.get(f"/api/vacancies/{vacancy_id}")
    assert get_response.status_code == 200
    assert get_response.get_json()["title"] == "Backend Developer"

    update_response = client.put(
        f"/api/vacancies/{vacancy_id}",
        json={"title": "Senior Backend Developer", "weights": {"hard": 55, "soft": 25, "management": 10, "education": 5, "salary": 5}},
    )
    assert update_response.status_code == 200
    assert update_response.get_json()["title"] == "Senior Backend Developer"

    delete_response = client.delete(f"/api/vacancies/{vacancy_id}")
    assert delete_response.status_code == 200


def test_interview_crud(client: Any, isolated_feature_storage: None) -> None:
    """Интервью должно создаваться, читаться и удаляться через API."""
    create_response = client.post(
        "/api/interviews",
        json={
            "candidate_id": "CV_001",
            "candidate_name": "Иванов Алексей",
            "vacancy_id": "VAC_001",
            "date": "2026-07-10",
            "time": "15:00",
            "duration": 60,
            "format": "online",
            "notes": "Проверить навыки коммуникации",
        },
    )

    assert create_response.status_code == 201
    interview = create_response.get_json()
    assert interview["id"].startswith("INT_")

    list_response = client.get("/api/interviews/CV_001")
    assert list_response.status_code == 200
    items = list_response.get_json()
    assert len(items) == 1

    update_response = client.put(f"/api/interviews/{interview['id']}", json={"status": "completed"})
    assert update_response.status_code == 200
    assert update_response.get_json()["status"] == "completed"

    page_response = client.get("/interviews?status=completed")
    assert page_response.status_code == 200

    delete_response = client.delete(f"/api/interviews/{interview['id']}")
    assert delete_response.status_code == 200


def test_candidate_stage_is_selected_after_page_reload(client: Any, isolated_feature_storage: None) -> None:
    """Сохранённый этап должен оставаться выбранным после повторного открытия карточки."""
    main_routes.storage.save_candidate({
        "id": "CV_STAGE", "name": "Тестовый кандидат", "position": "Аналитик",
        "vacancy_id": "VAC_STAGE", "resume_text": "SQL, аналитика", "total": 70,
    })
    update_response = client.post(
        "/api/candidates/CV_STAGE/stage",
        json={"vacancy_id": "VAC_STAGE", "stage": "interview_completed"},
    )
    assert update_response.status_code == 200

    page_response = client.get("/candidate/CV_STAGE")

    assert page_response.status_code == 200
    html = page_response.get_data(as_text=True)
    assert 'value="interview_completed" selected' in html
    assert 'id="saveCandidateStageBtn"' not in html


def test_feedback_create_and_list(client: Any, isolated_feature_storage: None) -> None:
    """Обратная связь должна сохраняться и возвращаться по кандидату."""
    create_response = client.post(
        "/api/feedback",
        json={
            "candidate_id": "CV_001",
            "vacancy_id": "VAC_001",
            "original_scores": {"hard": 6, "soft": 7, "management": 5, "education": 8, "salary": 6},
            "corrected_scores": {"hard": 7, "soft": 8, "management": 6, "education": 8, "salary": 6},
            "comment": "После интервью подтвержден более высокий уровень hard/soft",
            "hr_id": "HR_ANNA",
        },
    )

    assert create_response.status_code == 201
    feedback = create_response.get_json()
    assert feedback["id"].startswith("FDB_")

    list_response = client.get("/api/feedback/CV_001")
    assert list_response.status_code == 200
    items = list_response.get_json()
    assert len(items) == 1
    assert items[0]["hr_id"] == "HR_ANNA"


def test_interview_cancel_reschedule_complete_syncs_stage(client, isolated_feature_storage):
    main_routes.storage.save_candidate({'id':'CV_FLOW', 'name':'Анна', 'vacancy_id':'VAC_001'})
    main_routes.candidate_stage_service.transition('CV_FLOW', 'VAC_001', 'in_review')
    created = client.post('/api/interviews', json={'candidate_id':'CV_FLOW', 'candidate_name':'Анна', 'vacancy_id':'VAC_001', 'date':'2099-01-01', 'time':'10:00', 'duration':60, 'format':'online'})
    assert created.status_code == 201
    interview_id = created.get_json()['id']
    def stage(): return main_routes.candidate_vacancy_storage.find('CV_FLOW', 'VAC_001')['status']
    assert stage() == 'interview'
    assert client.put('/api/interviews/' + interview_id, json={'status':'cancelled'}).status_code == 200
    assert stage() == 'in_review'
    assert client.put('/api/interviews/' + interview_id, json={'status':'scheduled', 'time':'11:00'}).status_code == 200
    assert stage() == 'interview'
    assert client.put('/api/interviews/' + interview_id, json={'status':'completed'}).status_code == 200
    assert stage() == 'interview_completed'
    assert client.delete('/api/interviews/' + interview_id).status_code == 200
    assert stage() == 'in_review'

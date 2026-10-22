"""Тесты для сервиса оценки кандидатов."""

from typing import Dict

import pytest

from src.services.scoring import CandidateScoringService


@pytest.fixture
def scoring_service() -> CandidateScoringService:
    """Возвращает экземпляр сервиса для каждого теста."""
    return CandidateScoringService()


def test_score_candidate_rejects_critical_failures(scoring_service: CandidateScoringService) -> None:
    """Критические фильтры должны отклонять кандидата."""
    result = scoring_service.score_candidate(
        "Опыт 5 лет, Python, Docker",
        ["Java", "Kubernetes"],
        {"hard": 70, "management": 20, "soft": 10, "education": 50, "salary": 40},
    )

    assert result["status"] == "red"
    assert result["decision"] == "Отклонен"
    assert result["total"] == 0
    assert result["critical_failures"] == ["Java", "Kubernetes"]


def test_check_critical_filters_handles_empty_requirements(scoring_service: CandidateScoringService) -> None:
    """Пустой список требований не должен вызывать ошибок."""
    assert scoring_service.check_critical_filters("Python", []) == []


def test_calculate_total_uses_weights_and_clamps_values(scoring_service: CandidateScoringService) -> None:
    """Итоговый балл должен учитывать веса и попадать в диапазон 0..100."""
    scores: Dict[str, float] = {"hard": 10, "management": 10, "soft": 10, "education": 10, "salary": 10}
    weights = {"hard": 100, "management": 100, "soft": 100, "education": 100, "salary": 100}

    assert scoring_service.calculate_total(scores, weights) == 100
    assert scoring_service.calculate_total({}, {}) == 0


def test_get_status_decision_returns_expected_labels(scoring_service: CandidateScoringService) -> None:
    """Метод должен возвращать ожидаемые статус и решение."""
    assert scoring_service.get_status_decision(75) == ("green", "Рекомендован")
    assert scoring_service.get_status_decision(45) == ("yellow", "Требует проверки")
    assert scoring_service.get_status_decision(10) == ("red", "Отклонен")


def test_model_evaluation_and_comments(scoring_service: CandidateScoringService) -> None:
    """Рабочая модель должна формировать оценки и объяснения без заглушки."""
    result = scoring_service.score_candidate(
        "Должность: Python Developer\nОпыт работы: 5 лет\nНавыки: Python, SQL\nОбразование: высшее",
        [],
        {"hard": 50, "management": 10, "soft": 30, "education": 5, "salary": 5},
        vacancy={"required_skills": ["Python", "SQL"], "min_experience": 3, "max_experience": 7},
    )

    assert set(result["scores"].keys()) == set(scoring_service.criteria)
    assert set(result["comments"].keys()) == set(scoring_service.criteria)
    assert result["model_version"] == "matching_model"
    assert 0 <= result["model_probability"] <= 1
    for comment in result["comments"].values():
        assert isinstance(comment, str)
        assert "критерию" in comment


@pytest.mark.parametrize(
    "resume_text",
    [
        (
            "ФИО: Петрова Мария Сергеевна\n"
            "Должность: Врач-терапевт\n"
            "Опыт работы: 6 лет\n"
            "Навыки: диагностика, ведение меддокументации\n"
            "Образование: лечебное дело\n"
            "Ожидаемая зарплата: 120000"
        ),
        (
            "ФИО: Орлов Михаил Сергеевич\n"
            "Должность: Инженер производства\n"
            "Опыт работы: 8 лет\n"
            "Навыки: техпроцессы, контроль качества\n"
            "Образование: технический университет\n"
            "Ожидаемая зарплата: 155000"
        ),
        (
            "ФИО: Ларионов Константин Артёмович\n"
            "Должность: Бухгалтер\n"
            "Опыт работы: 7 лет\n"
            "Навыки: 1С, налоговая отчётность, аудит\n"
            "Образование: финансовый университет\n"
            "Ожидаемая зарплата: 135000"
        ),
        (
            "ФИО: Сергеева Ирина Павловна\n"
            "Должность: Учитель математики\n"
            "Опыт работы: 8 лет\n"
            "Навыки: преподавание, разработка учебных материалов\n"
            "Образование: педагогический университет\n"
            "Ожидаемая зарплата: 110000"
        ),
    ],
)
def test_score_candidate_supports_multiple_domains(scoring_service: CandidateScoringService, resume_text: str) -> None:
    """Проверяем, что скоринг стабильно работает для резюме из разных сфер."""
    result = scoring_service.score_candidate(
        resume_text,
        ["опыт работы"],
        {"hard": 60, "management": 40, "soft": 50, "education": 50, "salary": 30},
    )

    assert result["status"] in {"green", "yellow", "red"}
    assert 0 <= result["total"] <= 100
    assert set(result["scores"].keys()) == set(scoring_service.criteria)

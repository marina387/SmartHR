"""Тесты vacancy-centric сервиса и хранилища вакансий."""

from pathlib import Path

from src.services.vacancy_service import VacancyService
from src.storage.vacancy_storage import VacancyStorage


def test_vacancy_storage_load_save_cycle(tmp_path: Path) -> None:
    """VacancyStorage должен корректно сохранять и загружать список вакансий."""
    storage = VacancyStorage(tmp_path / "vacancies.json")

    items = [{"id": "VAC_001", "title": "Python Developer", "weights": {"hard": 50, "soft": 30, "management": 10, "education": 5, "salary": 5}}]
    storage.save_all(items)

    loaded = storage.load_all()
    assert loaded == items


def test_vacancy_service_returns_defaults_for_missing_vacancy(tmp_path: Path) -> None:
    """Для неизвестной вакансии должны возвращаться дефолтные веса."""
    service = VacancyService(VacancyStorage(tmp_path / "vacancies.json"))

    defaults = service.weights_for_vacancy("VAC_UNKNOWN")

    assert defaults == {"hard": 50, "soft": 30, "management": 10, "education": 5, "salary": 5}


def test_vacancy_service_create_and_update_weights(tmp_path: Path) -> None:
    """Сервис должен создавать вакансию и обновлять веса внутри неё."""
    storage = VacancyStorage(tmp_path / "vacancies.json")
    service = VacancyService(storage)

    created = service.create(
        {
            "id": "VAC_009",
            "title": "Data Engineer",
            "weights": {"hard": 61, "soft": 21, "management": 9, "education": 4, "salary": 5},
            "created_by": "HR_NORM",
        }
    )
    assert created["id"] == "VAC_009"
    assert sum(created["weights"].values()) == 100
    assert created["created_by"] == "HR_NORM"

    updated = service.update(
        "VAC_009",
        {"weights": {"hard": 55, "soft": 25, "management": 10, "education": 5, "salary": 5}},
    )
    assert sum(updated["weights"].values()) == 100
    assert updated["weights"]["hard"] == 55


def test_vacancy_service_delete_removes_vacancy(tmp_path: Path) -> None:
    """После удаления вакансия не должна возвращаться по ID."""
    storage = VacancyStorage(tmp_path / "vacancies.json")
    service = VacancyService(storage)

    service.create(
        {
            "id": "VAC_100",
            "title": "Support Specialist",
            "weights": {"hard": 80, "soft": 10, "management": 5, "education": 3, "salary": 2},
        }
    )
    assert service.get_by_id("VAC_100") is not None

    service.delete("VAC_100")
    assert service.get_by_id("VAC_100") is None

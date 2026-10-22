from pathlib import Path

from src.services.candidate_retention_service import CandidateRetentionService
from src.storage.candidate_vacancy_storage import CandidateVacancyStorage
from src.storage.file_storage import FileCandidateStorage
from src.storage.interview_storage import InterviewStorage
from src.services.interview_service import InterviewService
from src.storage.vacancy_storage import VacancyStorage
from src.services.vacancy_service import VacancyService


class FakeScoring:
    def __init__(self, totals):
        self.totals = totals

    def score_candidate(self, _text, _critical, _weights, vacancy=None, candidate_profile=None):
        total, probability = self.totals[str(vacancy["id"])]
        return {"total": total, "model_probability": probability, "critical_failures": []}


def make_service(tmp_path: Path, totals):
    candidates = FileCandidateStorage(tmp_path / "candidates.json")
    vacancies_store = VacancyStorage(tmp_path / "vacancies.json")
    vacancies_store.save_all([
        {"id": vacancy_id, "title": vacancy_id, "status": "active", "weights": {}}
        for vacancy_id in totals
    ])
    relations = CandidateVacancyStorage(tmp_path / "relations.json")
    interviews = InterviewService(InterviewStorage(tmp_path / "interviews.json"))
    service = CandidateRetentionService(
        candidates, VacancyService(vacancies_store), FakeScoring(totals), relations, interviews
    )
    return service, candidates, relations


def test_unmatched_candidate_is_archived_and_can_be_restored(tmp_path: Path):
    service, candidates, _ = make_service(tmp_path, {"VAC_1": (45, 0.31), "VAC_2": (62, 0.55)})
    candidates.save_candidate({"id": "CV_1", "resume_text": "Python developer, опыт 2 года"})

    result = service.archive_if_unmatched("CV_1")

    assert result["archived"] is True
    saved = candidates.get_candidate("CV_1")
    assert saved["lifecycle_status"] == "archived"
    assert saved["delete_after"]
    restored = service.restore("CV_1")
    assert restored["lifecycle_status"] == "active"
    assert "delete_after" not in restored


def test_matching_candidate_stays_active(tmp_path: Path):
    service, candidates, _ = make_service(tmp_path, {"VAC_1": (84, 0.81)})
    candidates.save_candidate({"id": "CV_1", "resume_text": "Python developer, опыт 5 лет"})

    result = service.archive_if_unmatched("CV_1")

    assert result["archived"] is False
    assert result["has_match"] is True
    assert candidates.get_candidate("CV_1").get("lifecycle_status") != "archived"


def test_protected_stage_prevents_archive(tmp_path: Path):
    service, candidates, relations = make_service(tmp_path, {"VAC_1": (20, 0.1)})
    candidates.save_candidate({"id": "CV_1", "resume_text": "Начинающий специалист"})
    relations.save({"candidate_id": "CV_1", "vacancy_id": "VAC_1", "status": "offer"})

    result = service.archive_if_unmatched("CV_1")

    assert result["archived"] is False
    assert "offer" in result["reason"]


def test_new_match_restores_archived_candidate(tmp_path: Path):
    service, candidates, _ = make_service(tmp_path, {"VAC_1": (82, 0.75)})
    candidates.save_candidate({"id": "CV_1", "resume_text": "Python developer", "lifecycle_status": "archived"})

    result = service.reevaluate_archived()

    assert result["restored"][0]["candidate_id"] == "CV_1"
    assert candidates.get_candidate("CV_1")["lifecycle_status"] == "active"

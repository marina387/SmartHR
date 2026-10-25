"""Тесты нечёткого сравнения, рекомендаций и переноса кандидата."""

from pathlib import Path
import pytest
from src.config import FUNNEL_STAGES

from src.services.alternative_vacancy_service import AlternativeVacancyService
from src.services.candidate_vacancy_service import CandidateVacancyService
from src.services.skill_matching import SkillMatcher
from src.services.vacancy_service import VacancyService
from src.storage.candidate_vacancy_storage import CandidateVacancyStorage
from src.storage.file_storage import FileCandidateStorage
from src.storage.transfer_storage import TransferStorage
from src.storage.vacancy_storage import VacancyStorage


class FakeScoringService:
    def score_candidate(self, candidate_text, critical, weights, vacancy=None, candidate_profile=None):
        total = 85 if vacancy["id"] == "VAC_002" else 60
        return {
            "total": total, "model_probability": 0.9 if total == 85 else 0.5,
            "critical_failures": [], "model_version": "matching_model",
            "used_weights": weights, "scores": {"hard": 8.5}, "evidence": {"hard": "ok"},
        }


def test_skill_matcher_supports_alias_and_fuzzy_match() -> None:
    result = SkillMatcher().compare(["Postgres", "Java Script"], ["PostgreSQL", "JavaScript"])
    assert result["score"] == 1
    assert not result["missing"]
    assert {item["match_type"] for item in result["matches"]} <= {"alias", "fuzzy", "exact"}


@pytest.mark.parametrize('linked_stage',[None,*FUNNEL_STAGES,'rejected','withdrawn','archived'])
def test_alternative_service_filters_and_ranks(tmp_path: Path, monkeypatch, linked_stage) -> None:
    candidates = FileCandidateStorage(tmp_path / "candidates.json")
    vacancies_store = VacancyStorage(tmp_path / "vacancies.json")
    relations = CandidateVacancyStorage(tmp_path / "relations.json")
    candidates.save_candidate({
        "id": "CV_001", "total": 40,
        "resume_text": "Должность: Python Developer\nОпыт работы: 5 лет\nНавыки: Python, Postgres",
    })
    vacancies_store.save_all([
        {"id": "VAC_001", "title": "Исходная", "status": "active", "weights": {"hard": 100}},
        {"id": "VAC_002", "title": "Python", "status": "active", "required_skills": ["Python", "PostgreSQL"], "weights": {"hard": 100}},
        {"id": "VAC_003", "title": "Закрытая", "status": "closed", "weights": {"hard": 100}},
    ])
    service = AlternativeVacancyService(candidates, VacancyService(vacancies_store), FakeScoringService(), relations)
    if linked_stage:
        relations.save({'candidate_id':'CV_001','vacancy_id':'VAC_002','status':linked_stage})
    monkeypatch.setattr(service, "_semantic_sims", lambda resume, pool: {v["id"]: 0.9 for v in pool})
    result = service.find_alternatives("CV_001", "VAC_001")
    if linked_stage in FUNNEL_STAGES:
        assert result['alternatives']==[]
        return
    assert [item["vacancy_id"] for item in result["alternatives"]] == ["VAC_002"]
    assert result["alternatives"][0]["score_improvement"] == 25
    assert not result["alternatives"][0]["missing_skills"]


def test_add_and_transfer_create_relations_and_audit(tmp_path: Path) -> None:
    relations = CandidateVacancyStorage(tmp_path / "relations.json")
    transfers = TransferStorage(tmp_path / "transfers.json")
    service = CandidateVacancyService(relations, transfers)
    relations.save({"candidate_id": "CV_001", "vacancy_id": "VAC_001", "status": "in_review"})
    recommendation = {
        "total": 82, "current_total": 40, "model_probability": 0.87,
        "model_version": "matching_model", "used_weights": {"hard": 50},
    }
    result = service.apply("CV_001", "VAC_001", "VAC_002", "transfer", "HR_1", "лучше подходит", recommendation)
    assert result["application"]["status"] == "in_review"
    assert relations.find("CV_001", "VAC_001")["status"] == "transferred"
    assert transfers.list_all()[0]["action"] == "transfer"

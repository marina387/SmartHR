"""Интеграционные проверки рабочего ML-scoring pipeline."""

from src.matching_service import MatchingService
from src.services.profile_extraction import extract_candidate_profile
from src.services.scoring import CandidateScoringService


def test_feature_builder_uses_salary_in_rubles() -> None:
    service = MatchingService()
    candidate = {
        "skills": ["Python", "SQL"], "experience_years": 5,
        "expected_salary": 150000, "specialization": "IT",
        "education": "bachelor", "english_level": "B2", "has_portfolio": True,
    }
    vacancy = {
        "required_skills": ["Python", "SQL"], "min_experience": 3, "max_experience": 7,
        "max_salary": 200000, "specialization": "IT",
        "required_education": "bachelor", "english_required": "B1",
    }
    frame = service.prepare_features(candidate, vacancy)
    features = frame.iloc[0]
    assert list(frame.columns) == service.feature_names
    assert features["expected_salary"] == 150000
    assert features["max_salary"] == 200000
    assert features["skills_match"] == 1.0
    assert features["experience_years"] == 5
    assert features["min_experience"] == 3
    assert features["max_experience"] == 7
    assert features["cand_edu_idx"] == features["vac_edu_idx"] == 3


def test_resume_profile_reports_missing_fields() -> None:
    profile = extract_candidate_profile(
        "Должность: Python Developer\nОпыт работы: 5 лет\nНавыки: Python, SQL\nОжидаемая зарплата: 180 000"
    )
    assert profile["experience_years"] == 5
    assert profile["expected_salary"] == 180000
    assert profile["skills"] == ["Python", "SQL"]
    assert "english_level" in profile["missing_fields"]


def test_weights_change_total_but_prediction_is_stable() -> None:
    service = CandidateScoringService()
    text = "Должность: Python Developer\nОпыт работы: 5 лет\nНавыки: Python, SQL\nОбразование: высшее"
    vacancy = {"required_skills": ["Python", "SQL"], "min_experience": 3, "max_experience": 7}
    first = service.score_candidate(text, [], {"hard": 80, "soft": 5, "management": 5, "education": 5, "salary": 5}, vacancy)
    second = service.score_candidate(text, [], {"hard": 10, "soft": 10, "management": 10, "education": 60, "salary": 10}, vacancy)
    assert first["model_probability"] == second["model_probability"]
    assert first["features"] == second["features"]
    assert first["total"] != second["total"]

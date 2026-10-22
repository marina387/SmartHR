from scripts.generate_synthetic_chat_dataset import evidence, generate_records


def test_evidence_uses_explicit_skill_overlap():
    result = evidence(
        {"position": "Python developer", "profile": "Python, Django and SQL", "highlights": "", "experience_years": 3},
        {"position": "Backend", "description": "Python, Django, Docker", "experience_required": "2y"},
    )
    assert result["common_skills"] == ["Python", "Django"]
    assert result["unconfirmed_skills"] == ["Docker"]


def test_generated_records_are_clearly_marked_synthetic():
    candidates = [{"id": "candidate_1", "position": "Python", "profile": "Python", "highlights": "", "experience_years": 2}]
    vacancies = [{"id": "vacancy_1", "position": "Python developer", "description": "Python and Docker", "experience_required": "2y"}]
    pairs = [{"id": "pair_1", "candidate_id": "candidate_1", "vacancy_id": "vacancy_1"}]
    record = generate_records(candidates, vacancies, pairs)[0]
    assert record["synthetic"] is True
    assert record["approved_by_hr"] is False
    assert "Python" in record["messages"][-1]["content"]
    assert "Docker" in record["messages"][-1]["content"]

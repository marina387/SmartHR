from scripts.collect_real_chat_dataset import (
    candidate_record, chat_drafts, onet_records, pair_records, vacancy_record,
)


def test_records_remove_direct_contact_details_and_company_name():
    candidate = candidate_record({
        "id": "candidate-source-1", "Position": "Python developer",
        "CV": "Contact me at user@example.com or +7 912 345-67-89",
        "Primary Keyword": "Python", "Experience Years": 3, "CV_lang": "en",
    })
    vacancy = vacancy_record({
        "id": "vacancy-source-1", "Position": "Backend developer",
        "Long Description": "Apply at https://example.com", "Company Name": "Secret Corp",
        "Primary Keyword": "Python", "Long Description_lang": "en",
    })
    assert "user@example.com" not in candidate["profile"]
    assert "+7 912" not in candidate["profile"]
    assert "Secret Corp" not in str(vacancy)
    assert "https://example.com" not in vacancy["description"]


def test_pairs_and_drafts_are_not_training_labels():
    candidates = [{"id": "candidate_1", "profile": "Python", "primary_keyword": "Python"}]
    vacancies = [{"id": "vacancy_1", "position": "Developer", "description": "Python", "primary_keyword": "Python"}]
    pairs = pair_records(candidates, vacancies, 1, 42)
    drafts = chat_drafts(pairs, candidates, vacancies)
    assert pairs[0]["ground_truth_match"] is None
    assert pairs[0]["approved_by_hr"] is False
    assert drafts[0]["approved_by_hr"] is False
    assert drafts[0]["messages"][-1]["content"] == "[ТРЕБУЕТСЯ ЭТАЛОННЫЙ ОТВЕТ HR]"


def test_draft_rechecks_pii_after_fields_are_combined():
    candidates = [{"id": "candidate_1", "profile": "Call 89123456789", "primary_keyword": "Python"}]
    vacancies = [{"id": "vacancy_1", "position": "Developer", "description": "Python", "primary_keyword": "Python"}]
    drafts = chat_drafts(pair_records(candidates, vacancies, 1, 42), candidates, vacancies)
    assert "89123456789" not in drafts[0]["messages"][1]["content"]
    assert "[PHONE]" in drafts[0]["messages"][1]["content"]


def test_onet_records_keep_attribution():
    records = onet_records({"row": [{
        "onetsoc_code": "15-1252.00", "title": "Software Developers",
        "description": "Research and develop software solutions.",
    }]})
    assert records[0]["id"] == "onet_15-1252_00"
    assert records[0]["source"]["license"] == "CC BY 4.0"

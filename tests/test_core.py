import importlib.util
from pathlib import Path

from src.config import DEMO_RESUMES, REQUIREMENT_MARKERS

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("app_module", ROOT / "app.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_upload_accepts_json_payload():
    client = module.app.test_client()
    with client.session_transaction() as session:
        session.update(user_id='HR_TEST',user_version=1,csrf='test-csrf-token')
    response = client.post(
        "/api/upload",
        headers={'X-CSRF-Token':'test-csrf-token'},
        json={"text": "Имя: Иван\nКоммуникация, управление проектами", "filename": "resume.txt"},
    )

    assert response.status_code == 200
    assert response.get_json()["text"] == "Имя: Иван\nКоммуникация, управление проектами"


def test_extract_requirements_basic():
    text = "Обязательно наличие диплома. Требуется опыт работы от 3 лет."
    result = module.extract_requirements(text)
    assert len(result) >= 2
    assert any("диплом" in item.lower() for item in result)


def test_status_decision_thresholds():
    status, decision = module.get_status_decision(75)
    assert status == "green"
    assert decision == "Рекомендован"

    status, decision = module.get_status_decision(45)
    assert status == "yellow"
    assert decision == "Требует проверки"


def test_demo_resumes_cover_multiple_professions():
    texts = [resume["text"].lower() for resume in DEMO_RESUMES]

    assert len(DEMO_RESUMES) >= 10
    assert any("врач" in text or "медсестра" in text for text in texts)
    assert any("инженер" in text or "наладчик" in text or "технолог" in text for text in texts)
    assert any("бухгалтер" in text or "финансовый аналитик" in text for text in texts)
    assert any("учитель" in text or "преподаватель" in text for text in texts)


def test_requirement_markers_are_sector_agnostic():
    assert "обязательно" in REQUIREMENT_MARKERS
    assert "владение" in REQUIREMENT_MARKERS
    assert "знание" in REQUIREMENT_MARKERS
    assert "умение" in REQUIREMENT_MARKERS

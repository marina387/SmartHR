"""Контракт чат-ассистента до появления обученной модели."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from app import app
from src.chat.models import MockChatModel, build_chat_model
from src.chat.service import ChatService
from src.chat.tools import SmartHRChatTools
from src.core.rag_pipeline import RagPipeline
from src.routes import main as main_routes


class ListStore:
    def __init__(self, items):
        self.items = items

    def list_candidates(self):
        return self.items

    def get_candidate(self, record_id):
        return next((x for x in self.items if x.get("id") == record_id), None)

    def list_by_candidate(self, candidate_id):
        return [x for x in self.items if str(x.get("candidate_id")) == str(candidate_id)]

    def find(self, candidate_id, vacancy_id):
        return next((x for x in self.items if x.get("candidate_id") == candidate_id and x.get("vacancy_id") == vacancy_id), None)


class FakeHistory:
    def __init__(self):
        self.feedback = []

    def record_exchange(self, conversation_id, **kwargs):
        return {
            "conversation": {"id": conversation_id or "CHAT_TEST"},
            "user_message": {"id": 1},
            "assistant_message": {"id": 2},
        }

    def create_action(self, conversation_id, message_id, action):
        return {"id": "CACT_TEST", "conversation_id": conversation_id, "message_id": message_id, **action}

    def complete_action(self, action_id, **kwargs):
        return {"id": action_id, **kwargs}

    def save_feedback(self, message_id, payload):
        result = {"id": "CFB_TEST", "message_id": message_id, **payload}
        self.feedback.append(result)
        return result


@pytest.fixture(autouse=True)
def fake_chat_history(monkeypatch):
    history = FakeHistory()
    monkeypatch.setattr(main_routes, "_chat_history_service", lambda: history)
    return history


def make_service() -> ChatService:
    candidates = ListStore([{"id": "CV_001", "name": "Тестовый кандидат", "vacancy_id": "VAC_001"}])
    vacancies = SimpleNamespace(get_by_id=lambda record_id: {"id": record_id, "title": "Аналитик"})
    relations = ListStore([{"candidate_id": "CV_001", "vacancy_id": "VAC_001", "status": "interview"}])
    scores = ListStore([{"candidate_id": "CV_001", "vacancy_id": "VAC_001", "total": 72}])
    interviews = ListStore([])
    events = ListStore([])
    tools = SmartHRChatTools(candidates, vacancies, relations, scores, interviews, events)
    rag = RagPipeline(backend="tfidf")
    rag.build_index({"policy.txt": "Интервью проводится после проверки оценки кандидата."})
    return ChatService(MockChatModel(), tools, rag)


def test_chat_service_returns_grounded_context_and_sources():
    result = make_service().ask("Как проводится интервью?", candidate_id="CV_001", vacancy_id="VAC_001")
    assert "Интервью проводится после проверки" in result["answer"]
    assert result["sources"][0]["id"] == "policy.txt"
    assert result["sources"][0]["source"] == "policy.txt"
    assert result["suggested_action"] is None


def test_greeting_does_not_attach_candidate_or_document_search_results():
    result = make_service().ask("Привет", candidate_id="CV_001", vacancy_id="VAC_001")
    assert result["answer"].startswith("Здравствуйте")
    assert result["sources"] == []
    assert "Тестовый кандидат" not in result["answer"]


def test_vague_document_request_asks_for_topic():
    result = make_service().ask("Найди информацию в HR-документах", candidate_id="CV_001")
    assert "Уточните" in result["answer"]
    assert result["sources"] == []


def test_specific_document_request_returns_fragment_not_only_titles():
    result = make_service().ask("Как проводится интервью?", candidate_id="CV_001")
    assert "Интервью проводится после проверки" in result["answer"]
    assert "Источник:" in result["answer"]


def test_contextual_document_wording_triggers_search():
    result = make_service().ask("Где описан порядок проведения интервью?")
    assert result["sources"][0]["id"] == "policy.txt"


def test_named_labor_code_is_not_replaced_with_corporate_code():
    tools = make_service().tools
    rag = RagPipeline(backend="tfidf")
    rag.build_index({"corporate_code.pdf": "Корпоративный кодекс регулирует нормы поведения сотрудников."})
    result = ChatService(MockChatModel(), tools, rag).ask("Трудовой кодекс, статья 10")
    assert result["sources"] == []
    assert "не найден" in result["answer"]


def test_short_correction_continues_document_query_from_history():
    tools = make_service().tools
    rag = RagPipeline(backend="tfidf")
    rag.build_index({"corporate_code.pdf": "Корпоративный кодекс регулирует нормы поведения сотрудников."})
    history = [
        {"role": "user", "content": "Трудовой кодекс, статья 10"},
        {"role": "assistant", "content": "Найден корпоративный кодекс."},
    ]
    result = ChatService(MockChatModel(), tools, rag).ask("не то", history=history)
    assert result["sources"] == []
    assert "не найден" in result["answer"]


def test_general_chat_page_has_no_implicit_candidate():
    app.config["TESTING"] = True
    with app.test_client() as client:
        response = client.get("/chat")
    assert response.status_code == 200
    assert 'data-candidate-id=""' in response.get_data(as_text=True)


def test_chat_rejects_empty_message():
    with pytest.raises(ValueError, match="пустым"):
        make_service().ask("  ")


def test_model_loader_uses_mock_until_artifact_exists(tmp_path: Path):
    assert isinstance(build_chat_model(tmp_path), MockChatModel)


def test_chat_api_uses_service(monkeypatch):
    monkeypatch.setattr(main_routes, "_chat_service", make_service)
    monkeypatch.setattr(main_routes, "storage", make_service().tools.candidates)
    app.config["TESTING"] = True
    with app.test_client() as client:
        response = client.post("/api/chat", json={
            "message": "Объясни оценку",
            "candidate_id": "CV_001",
            "vacancy_id": "VAC_001",
        })
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["answer"]
    assert payload["conversation_id"]


def test_chat_api_rejects_empty_message(monkeypatch):
    monkeypatch.setattr(main_routes, "_chat_service", make_service)
    monkeypatch.setattr(main_routes, "storage", make_service().tools.candidates)
    app.config["TESTING"] = True
    with app.test_client() as client:
        response = client.post("/api/chat", json={"message": ""})
    assert response.status_code == 400


def test_chat_proposes_stage_change_without_executing_it():
    result = make_service().ask(
        "Переведи этап на интервью", candidate_id="CV_001", vacancy_id="VAC_001"
    )
    action = result["suggested_action"]
    assert action["type"] == "change_stage"
    assert action["payload"]["stage"] == "interview"
    assert action["requires_confirmation"] is True


def test_chat_builds_interview_questions_from_context():
    result = make_service().ask(
        "Подготовь вопросы для интервью", candidate_id="CV_001", vacancy_id="VAC_001"
    )
    assert "Вопросы для интервью" in result["answer"]
    assert "Аналитик" in result["answer"]


def test_chat_api_signs_suggested_action(monkeypatch):
    monkeypatch.setattr(main_routes, "_chat_service", make_service)
    monkeypatch.setattr(main_routes, "storage", make_service().tools.candidates)
    app.config["TESTING"] = True
    with app.test_client() as client:
        response = client.post("/api/chat", json={
            "message": "Переведи этап на интервью",
            "candidate_id": "CV_001",
            "vacancy_id": "VAC_001",
        })
    action = response.get_json()["suggested_action"]
    assert action["confirmation_token"]


def test_confirmed_chat_stage_action_calls_service(monkeypatch):
    calls = []
    stage_service = SimpleNamespace(transition=lambda *args, **kwargs: calls.append((args, kwargs)) or {"status": args[2]})
    monkeypatch.setattr(main_routes, "candidate_stage_service", stage_service)
    monkeypatch.setattr(main_routes, "chat_action_storage", SimpleNamespace(get_by_id=lambda action_id: {
        "id": action_id, "status": "pending", "action_type": "change_stage",
        "action_payload": {"candidate_id": "CV_001", "vacancy_id": "VAC_001", "stage": "interview"},
    }))
    app.config["TESTING"] = True
    with app.app_context():
        token = main_routes._chat_action_serializer().dumps({"action_id": "CACT_TEST"})
    with app.test_client() as client:
        response = client.post("/api/chat/actions/confirm", json={"confirmation_token": token, "hr_id": "HR_1"})
    assert response.status_code == 200
    assert response.get_json()["confirmed"] is True
    assert calls[0][0] == ("CV_001", "VAC_001", "interview")


def test_chat_action_rejects_tampered_token():
    app.config["TESTING"] = True
    with app.test_client() as client:
        response = client.post("/api/chat/actions/confirm", json={"confirmation_token": "tampered"})
    assert response.status_code == 400


def test_chat_feedback_endpoint_saves_rating(fake_chat_history):
    app.config["TESTING"] = True
    with app.test_client() as client:
        response = client.post("/api/chat/messages/2/feedback", json={"rating": "useful"})
    assert response.status_code == 200
    assert fake_chat_history.feedback[0]["rating"] == "useful"

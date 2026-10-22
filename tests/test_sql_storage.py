from pathlib import Path

from flask import Flask

from src.extensions import db
from src.services.chat_history_service import ChatHistoryService
from src.storage.sql_storage import (
    SqlCandidateStorage, SqlCandidateVacancyStorage, SqlVacancyStorage,
    SqlChatConversationStorage, SqlChatMessageStorage, SqlChatActionStorage, SqlChatFeedbackStorage,
)


def test_sql_repositories_persist_relations_and_weights(tmp_path: Path) -> None:
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)

    with app.app_context():
        db.create_all()
        vacancies = SqlVacancyStorage()
        candidates = SqlCandidateStorage()
        relations = SqlCandidateVacancyStorage()
        weights = {"hard": 50, "soft": 30, "management": 10, "education": 5, "salary": 5}

        vacancies.save({"id": "VAC_TEST", "title": "Аналитик", "status": "active", "category": "IT", "weights": weights})
        candidates.save_candidate({"id": "CV_TEST", "name": "Иван", "position": "Аналитик", "resume_text": "SQL"})
        relations.save({"candidate_id": "CV_TEST", "vacancy_id": "VAC_TEST", "status": "in_review"})

        assert vacancies.get_by_id("VAC_TEST")["weights"] == weights
        assert candidates.get_candidate("CV_TEST")["name"] == "Иван"
        assert relations.find("CV_TEST", "VAC_TEST")["status"] == "in_review"


def test_chat_history_persists_messages_actions_and_feedback(tmp_path: Path) -> None:
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{(tmp_path / 'chat.db').as_posix()}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)

    with app.app_context():
        db.create_all()
        vacancies = SqlVacancyStorage()
        candidates = SqlCandidateStorage()
        vacancies.save({
            "id": "VAC_CHAT", "title": "Аналитик", "status": "active", "category": "IT",
            "weights": {"hard": 50, "soft": 30, "management": 10, "education": 5, "salary": 5},
        })
        candidates.save_candidate({"id": "CV_CHAT", "name": "Кандидат", "position": "Аналитик", "resume_text": "SQL"})
        history = ChatHistoryService(
            SqlChatConversationStorage(), SqlChatMessageStorage(),
            SqlChatActionStorage(), SqlChatFeedbackStorage(),
        )
        exchange = history.record_exchange(
            None, candidate_id="CV_CHAT", vacancy_id="VAC_CHAT", user_message="Объясни оценку",
            assistant_result={"answer": "Оценка 70", "model": "MockChatModel", "sources": []},
        )
        assistant_id = exchange["assistant_message"]["id"]
        action = history.create_action(exchange["conversation"]["id"], assistant_id, {
            "type": "change_stage", "label": "Интервью",
            "payload": {"candidate_id": "CV_CHAT", "vacancy_id": "VAC_CHAT", "stage": "interview"},
        })
        history.complete_action(action["id"], confirmed_by="HR_TEST", status="confirmed", result={"ok": True})
        feedback = history.save_feedback(assistant_id, {
            "rating": "factual_error", "corrected_answer": "Исправленная оценка",
            "approved_for_training": True, "hr_id": "HR_TEST",
        })
        restored = history.conversation(exchange["conversation"]["id"])

        assert [message["role"] for message in restored["messages"]] == ["user", "assistant"]
        assert feedback["approved_for_training"] is True
        assert history.actions.get_by_id(action["id"])["status"] == "confirmed"

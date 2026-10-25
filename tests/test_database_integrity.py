import json
import sqlite3

from flask import Flask
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.extensions import db
from src import models  # noqa: F401
from src.storage.sql_storage import (
    SqlCandidateStorage, SqlVacancyStorage, SqlCandidateVacancyStorage,
    SqlChatConversationStorage, SqlChatMessageStorage,
)
from scripts.repair_database_integrity import repair_database


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "integrity.db"
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI=f"sqlite:///{path.as_posix()}",
                      SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    with app.app_context():
        db.create_all()
        SqlVacancyStorage().save({"id": "V", "title": "Test"})
        SqlCandidateStorage().save({"id": "C", "name": "Test"})
        yield path
        db.session.remove()
        db.engine.dispose()


def test_foreign_keys_on_new_connections_and_rollback(database):
    for _ in range(2):
        db.session.remove()
        db.engine.dispose()
        assert db.session.execute(text("PRAGMA foreign_keys")).scalar() == 1
        with pytest.raises(IntegrityError):
            SqlCandidateVacancyStorage().save({"candidate_id": "absent", "vacancy_id": "V"})
        # No PendingRollbackError after rejected input.
        assert SqlCandidateStorage().get_by_id("C")


def test_delete_candidate_cascades_and_preserves_conversation(database):
    SqlCandidateVacancyStorage().save({"candidate_id": "C", "vacancy_id": "V"})
    SqlChatConversationStorage().save({"id": "CHAT", "candidate_id": "C", "vacancy_id": "V",
                                       "created_at": "now", "updated_at": "now"})
    SqlChatMessageStorage().save({"conversation_id": "CHAT", "role": "user", "content": "hello", "created_at": "now"})
    SqlCandidateStorage().delete_candidate("C")
    db.session.remove()
    assert SqlCandidateVacancyStorage().list_all() == []
    assert SqlChatConversationStorage().get_by_id("CHAT")["candidate_id"] is None
    assert len(SqlChatMessageStorage().list_by_conversation("CHAT")) == 1
    assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []


def test_bulk_and_vacancy_weights_are_atomic(database):
    with pytest.raises(IntegrityError):
        SqlCandidateVacancyStorage().save_all([
            {"id": "A", "candidate_id": "C", "vacancy_id": "V"},
            {"id": "B", "candidate_id": "missing", "vacancy_id": "V"},
        ])
    assert SqlCandidateVacancyStorage().list_all() == []
    with pytest.raises(IntegrityError):
        SqlVacancyStorage().save({"id": "BAD", "title": "bad", "weights": {
            "hard": 99, "soft": 30, "management": 10, "education": 5, "salary": 5}})
    assert SqlVacancyStorage().get_by_id("BAD") is None


def seed_orphans(path):
    with sqlite3.connect(path) as connection:
        # Reproduce legacy writes made without FK enforcement.
        connection.execute("DELETE FROM candidates WHERE id='C'")


def test_repair_is_backed_up_lossless_and_idempotent(database):
    SqlCandidateVacancyStorage().save({"id": "A", "candidate_id": "C", "vacancy_id": "V"})
    SqlChatConversationStorage().save({"id": "CHAT", "candidate_id": "C", "created_at": "now", "updated_at": "now"})
    SqlChatMessageStorage().save({"conversation_id": "CHAT", "role": "user", "content": "hello", "created_at": "now"})
    db.session.remove()
    seed_orphans(database)
    assert repair_database(database)["violations"] == 2
    result = repair_database(database, apply=True)
    assert result["archived"] == 1
    assert result["detached_conversations"] == 1
    with sqlite3.connect(result["backup"]) as backup:
        assert len(backup.execute("PRAGMA foreign_key_check").fetchall()) == 2
    with sqlite3.connect(database) as connection:
        archived = connection.execute("SELECT original_row FROM integrity_archive").fetchall()
        assert len(archived) == 2
        assert all(json.loads(row[0])["candidate_id"] == "C" for row in archived)
        assert connection.execute("SELECT content FROM chat_messages").fetchone()[0] == "hello"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert repair_database(database, apply=True)["applied"] is False


def test_unexpected_violation_rolls_back_repair(database):
    SqlCandidateVacancyStorage().save({"candidate_id": "C", "vacancy_id": "V"})
    db.session.remove()
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM vacancies")
    with pytest.raises(RuntimeError, match="Unsupported"):
        repair_database(database, apply=True)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM integrity_archive").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM candidate_vacancies").fetchone()[0] == 1


def test_json_import_rolls_back_all_files(database, monkeypatch, tmp_path):
    from scripts import migrate_json_to_sqlite as importer
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "candidates.json").write_text(json.dumps([{"id": "IMPORTED", "name": "Test"}]))
    (folder / "relations.json").write_text(json.dumps([
        {"candidate_id": "MISSING", "vacancy_id": "V"}]))
    monkeypatch.setattr(importer, "ROOT", tmp_path)
    monkeypatch.setattr(importer, "SOURCES", [
        ("candidates.json", SqlCandidateStorage()),
        ("relations.json", SqlCandidateVacancyStorage()),
    ])
    with pytest.raises(IntegrityError):
        importer.migrate()
    assert SqlCandidateStorage().get_by_id("IMPORTED") is None
    assert SqlCandidateStorage().get_by_id("C")

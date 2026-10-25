"""SQLAlchemy-репозитории с интерфейсами прежних JSON-хранилищ."""

from __future__ import annotations

from typing import Any, Dict, List, Type
from functools import wraps

from sqlalchemy import select, func

from src.extensions import db
from src.models import (
    Candidate, CandidateStageEvent, CandidateTransfer, CandidateVacancy,
    ChatAction, ChatConversation, ChatMessage, ChatResponseFeedback,
    Feedback, Interview, ScoreResult, Vacancy, VacancyTemplate, VacancyWeight,
)


def atomic_write(method):
    """Nested repository writes share one commit and roll back on failure."""
    @wraps(method)
    def wrapped(*args, **kwargs):
        session = db.session()
        outer = not session.info.get("repository_write_depth", 0)
        session.info["repository_write_depth"] = session.info.get("repository_write_depth", 0) + 1
        try:
            result = method(*args, **kwargs)
            if outer:
                session.commit()
            return result
        except Exception:
            if outer:
                session.rollback()
            raise
        finally:
            session.info["repository_write_depth"] -= 1
    return wrapped


class SqlRepository:
    model: Type[Any]
    id_prefix = ""

    def _all_models(self) -> List[Any]:
        return list(db.session.scalars(select(self.model)).all())

    def list_all(self) -> List[Dict[str, Any]]:
        return [self._serialize(item) for item in self._all_models()]

    def get_all(self) -> List[Dict[str, Any]]:
        return self.list_all()

    def load_all(self) -> List[Dict[str, Any]]:
        return self.list_all()

    def get_by_id(self, record_id: str) -> Dict[str, Any] | None:
        model = db.session.get(self.model, str(record_id))
        return self._serialize(model) if model else None

    def _next_id(self) -> str:
        maximum = 0
        for item in self._all_models():
            raw = str(item.id)
            if raw.startswith(self.id_prefix) and raw[len(self.id_prefix):].isdigit():
                maximum = max(maximum, int(raw[len(self.id_prefix):]))
        return f"{self.id_prefix}{maximum + 1:03d}"

    def _serialize(self, model: Any) -> Dict[str, Any]:
        return model.as_dict()

    def _columns(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        names = {column.name for column in self.model.__table__.columns} - {"payload"}
        return {key: payload.get(key) for key in names if key in payload}

    @atomic_write
    def save(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        record = dict(payload)
        record_id = str(record.get("id", "")).strip() or self._next_id()
        record["id"] = record_id
        model = db.session.get(self.model, record_id)
        columns = self._columns(record)
        if model is None:
            model = self.model(**columns, payload=record)
            db.session.add(model)
        else:
            for key, value in columns.items():
                setattr(model, key, value)
            model.payload = record
        db.session.flush()
        return self._serialize(model)

    @atomic_write
    def delete(self, record_id: str) -> bool:
        model = db.session.get(self.model, str(record_id))
        if not model:
            return False
        db.session.delete(model)
        db.session.flush()
        return True

    @atomic_write
    def save_all(self, items: List[Dict[str, Any]]) -> None:
        wanted = {str(item.get("id", "")) for item in items if str(item.get("id", ""))}
        for model in self._all_models():
            if str(model.id) not in wanted:
                db.session.delete(model)
        db.session.flush()
        for item in items:
            self.save(item)


class SqlCandidateStorage(SqlRepository):
    model, id_prefix = Candidate, "CV_"

    def _serialize(self, model: Candidate) -> Dict[str, Any]:
        result = model.as_dict()
        for key in ("name", "position", "resume_text", "lifecycle_status", "created_at", "archived_at", "delete_after"):
            value = getattr(model, key)
            if value is not None:
                result[key] = value
        return result

    def list_candidates(self) -> List[Dict[str, Any]]:
        return sorted(self.list_all(), key=lambda item: str(item.get("timestamp", item.get("created_at", ""))), reverse=True)

    def get_candidate(self, candidate_id: str) -> Dict[str, Any] | None:
        return self.get_by_id(candidate_id)

    def save_candidate(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        record = dict(candidate)
        record.setdefault("lifecycle_status", "active")
        return self.save(record)

    def delete_candidate(self, candidate_id: str) -> bool:
        return self.delete(candidate_id)


class SqlVacancyStorage(SqlRepository):
    model, id_prefix = Vacancy, "VAC_"

    def _serialize(self, model: Vacancy) -> Dict[str, Any]:
        result = model.as_dict()
        result.update({"title": model.title, "status": model.status, "category": model.category})
        result["weights"] = model.weights.as_dict() if model.weights else result.get("weights", {})
        return result

    @atomic_write
    def save(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        record = dict(payload)
        weights = dict(record.get("weights") or {})
        saved = super().save(record)
        model = db.session.get(Vacancy, saved["id"])
        if weights:
            if model.weights is None:
                model.weights = VacancyWeight(vacancy_id=model.id)
            for key in ("hard", "soft", "management", "education", "salary"):
                setattr(model.weights, key, int(weights.get(key, getattr(model.weights, key))))
            db.session.flush()
        return self.get_by_id(saved["id"])


class SqlTemplateStorage(SqlRepository):
    model, id_prefix = VacancyTemplate, "template_"

    def increment_usage(self, template_id: str) -> None:
        item = self.get_by_id(template_id)
        if item:
            item["usage_count"] = int(item.get("usage_count", 0)) + 1
            self.save(item)


class SqlInterviewStorage(SqlRepository):
    model, id_prefix = Interview, "INT_"

    def list_all(self) -> List[Dict[str, Any]]:
        return sorted(super().list_all(), key=lambda item: str(item.get("id", "")), reverse=True)

    def list_by_candidate(self, candidate_id: str) -> List[Dict[str, Any]]:
        return [item for item in self.list_all() if str(item.get("candidate_id")) == str(candidate_id)]

    get_by_candidate = list_by_candidate
    create = SqlRepository.save

    def update(self, interview_id: str, payload: Dict[str, Any]) -> Dict[str, Any] | None:
        current = self.get_by_id(interview_id)
        return self.save({**current, **payload, "id": interview_id}) if current else None


class SqlFeedbackStorage(SqlRepository):
    model, id_prefix = Feedback, "FDB_"

    def list_all(self) -> List[Dict[str, Any]]:
        return sorted(super().list_all(), key=lambda item: str(item.get("created_at", "")), reverse=True)

    def list_by_candidate(self, candidate_id: str) -> List[Dict[str, Any]]:
        return [item for item in self.list_all() if str(item.get("candidate_id")) == str(candidate_id)]

    create = SqlRepository.save


class SqlCandidateVacancyStorage(SqlRepository):
    model, id_prefix = CandidateVacancy, "APP_"

    def list_by_candidate(self, candidate_id: str) -> List[Dict[str, Any]]:
        return [item for item in self.list_all() if str(item.get("candidate_id")) == str(candidate_id)]

    def find(self, candidate_id: str, vacancy_id: str) -> Dict[str, Any] | None:
        return next((item for item in self.list_by_candidate(candidate_id) if str(item.get("vacancy_id")) == str(vacancy_id)), None)


class SqlStageEventStorage(SqlRepository):
    model, id_prefix = CandidateStageEvent, "EVT_"

    def list_all(self) -> List[Dict[str, Any]]:
        return sorted(super().list_all(), key=lambda item: str(item.get("created_at", "")))

    def list_by_candidate(self, candidate_id: str) -> List[Dict[str, Any]]:
        return [item for item in self.list_all() if str(item.get("candidate_id")) == str(candidate_id)]


class SqlTransferStorage(SqlRepository):
    model, id_prefix = CandidateTransfer, "TRF_"


class SqlScoreResultStorage:
    """Неизменяемая история запусков scoring для пары кандидат–вакансия."""

    @atomic_write
    def save(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        record = dict(payload)
        model = ScoreResult(
            candidate_id=str(record["candidate_id"]), vacancy_id=str(record["vacancy_id"]),
            total=int(record.get("total", 0)), model_probability=record.get("model_probability"),
            model_version=record.get("model_version"), created_at=record.get("created_at"), payload=record,
        )
        db.session.add(model)
        db.session.flush()
        return {**record, "id": model.id}

    def list_by_candidate(self, candidate_id: str) -> List[Dict[str, Any]]:
        models = db.session.scalars(
            select(ScoreResult).where(ScoreResult.candidate_id == str(candidate_id)).order_by(ScoreResult.id.desc())
        ).all()
        return [{**(item.payload or {}), "id": item.id} for item in models]


class SqlChatConversationStorage(SqlRepository):
    model, id_prefix = ChatConversation, "CHAT_"

    def list_summaries(self, *, limit=30, offset=0):
        first_question = (select(ChatMessage.content)
            .where(ChatMessage.conversation_id == ChatConversation.id, ChatMessage.role == "user")
            .order_by(ChatMessage.id).limit(1).correlate(ChatConversation).scalar_subquery())
        last_message = (select(ChatMessage.content)
            .where(ChatMessage.conversation_id == ChatConversation.id)
            .order_by(ChatMessage.id.desc()).limit(1).correlate(ChatConversation).scalar_subquery())
        message_count = (select(func.count(ChatMessage.id))
            .where(ChatMessage.conversation_id == ChatConversation.id)
            .correlate(ChatConversation).scalar_subquery())
        rows = db.session.execute(select(ChatConversation, first_question, last_message, message_count)
            .order_by(ChatConversation.updated_at.desc(), ChatConversation.id.desc())
            .offset(offset).limit(limit)).all()
        result = []
        for conversation, first, last, count in rows:
            record = self._serialize(conversation)
            title = " ".join(str(record.get("title") or first or "Новый диалог").split())
            result.append({key: record.get(key) for key in ("id", "candidate_id", "vacancy_id", "created_at", "updated_at")}
                          | {"title": title[:100], "preview": " ".join(str(last or "").split())[:140], "message_count": count})
        return result

    def list_by_candidate(self, candidate_id: str) -> List[Dict[str, Any]]:
        return [item for item in self.list_all() if str(item.get("candidate_id")) == str(candidate_id)]


class SqlChatMessageStorage:
    @atomic_write
    def save(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        record = dict(payload)
        model = ChatMessage(
            conversation_id=str(record["conversation_id"]), role=str(record["role"]),
            content=str(record["content"]), model_name=record.get("model_name"),
            model_version=record.get("model_version"), created_at=str(record["created_at"]), payload=record,
        )
        db.session.add(model)
        db.session.flush()
        return {**record, "id": model.id}

    def get_by_id(self, message_id: int) -> Dict[str, Any] | None:
        model = db.session.get(ChatMessage, int(message_id))
        return {**(model.payload or {}), "id": model.id} if model else None

    def list_by_conversation(self, conversation_id: str) -> List[Dict[str, Any]]:
        models = db.session.scalars(
            select(ChatMessage).where(ChatMessage.conversation_id == str(conversation_id)).order_by(ChatMessage.id)
        ).all()
        return [{**(item.payload or {}), "id": item.id} for item in models]


class SqlChatActionStorage(SqlRepository):
    model, id_prefix = ChatAction, "CACT_"


class SqlChatFeedbackStorage(SqlRepository):
    model, id_prefix = ChatResponseFeedback, "CFB_"

    def find_by_message(self, message_id: int) -> Dict[str, Any] | None:
        return next((item for item in self.list_all() if int(item.get("message_id", 0)) == int(message_id)), None)

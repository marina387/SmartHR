"""Реляционная схема данных SmartHR."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.extensions import db


class User(db.Model):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(db.String(64), primary_key=True)
    login: Mapped[str] = mapped_column(db.String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(db.String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(db.Text, nullable=False)
    role: Mapped[str] = mapped_column(db.String(20), nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    session_version: Mapped[int] = mapped_column(default=1, nullable=False)


class AuthBootstrap(db.Model):
    __tablename__ = 'auth_bootstrap'
    id: Mapped[int] = mapped_column(primary_key=True)


class AuditEvent(db.Model):
    __tablename__ = 'audit_events'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    user_name: Mapped[str] = mapped_column(db.String(200), nullable=False)
    endpoint: Mapped[str] = mapped_column(db.String(160), nullable=False)
    path: Mapped[str] = mapped_column(db.String(400), nullable=False)
    method: Mapped[str] = mapped_column(db.String(10), nullable=False)
    created_at: Mapped[str] = mapped_column(db.String(40), nullable=False)


class PayloadMixin:
    payload: Mapped[dict] = mapped_column(db.JSON, default=dict, nullable=False)

    def as_dict(self) -> dict:
        result = {**(self.payload or {}), "id": self.id}
        # SET NULL / CASCADE are applied by SQLite, which cannot update JSON payloads.
        # Relational columns are the source of truth for links, including null links.
        for column in self.__table__.columns:
            if column.foreign_keys:
                result[column.name] = getattr(self, column.name)
        return result


class IntegrityArchive(db.Model):
    """Original rows isolated during explicit integrity repair; never used as live data."""
    __tablename__ = "integrity_archive"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_table: Mapped[str] = mapped_column(db.String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(db.String(64), nullable=False)
    reason: Mapped[str] = mapped_column(db.Text, nullable=False)
    original_row: Mapped[dict] = mapped_column(db.JSON, nullable=False)
    archived_at: Mapped[str] = mapped_column(db.String(40), nullable=False)


class Candidate(db.Model, PayloadMixin):
    __tablename__ = "candidates"
    id: Mapped[str] = mapped_column(db.String(64), primary_key=True)
    name: Mapped[str] = mapped_column(db.String(255), default="", nullable=False)
    position: Mapped[str] = mapped_column(db.String(255), default="", nullable=False)
    resume_text: Mapped[str] = mapped_column(db.Text, default="", nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(db.String(32), default="active", nullable=False, index=True)
    created_at: Mapped[str | None] = mapped_column(db.String(40))
    archived_at: Mapped[str | None] = mapped_column(db.String(40))
    delete_after: Mapped[str | None] = mapped_column(db.String(40))


class Vacancy(db.Model, PayloadMixin):
    __tablename__ = "vacancies"
    id: Mapped[str] = mapped_column(db.String(64), primary_key=True)
    title: Mapped[str] = mapped_column(db.String(255), nullable=False)
    status: Mapped[str] = mapped_column(db.String(32), default="active", nullable=False, index=True)
    category: Mapped[str] = mapped_column(db.String(120), default="Общее", nullable=False)
    created_at: Mapped[str | None] = mapped_column(db.String(40))
    updated_at: Mapped[str | None] = mapped_column(db.String(40))
    weights: Mapped["VacancyWeight | None"] = relationship(back_populates="vacancy", cascade="all, delete-orphan", uselist=False)


class VacancyWeight(db.Model):
    __tablename__ = "vacancy_weights"
    vacancy_id: Mapped[str] = mapped_column(ForeignKey("vacancies.id", ondelete="CASCADE"), primary_key=True)
    hard: Mapped[int] = mapped_column(default=50, nullable=False)
    soft: Mapped[int] = mapped_column(default=30, nullable=False)
    management: Mapped[int] = mapped_column(default=10, nullable=False)
    education: Mapped[int] = mapped_column(default=5, nullable=False)
    salary: Mapped[int] = mapped_column(default=5, nullable=False)
    vacancy: Mapped[Vacancy] = relationship(back_populates="weights")
    __table_args__ = (
        CheckConstraint("hard + soft + management + education + salary = 100", name="ck_vacancy_weights_total"),
    )

    def as_dict(self) -> dict:
        return {key: int(getattr(self, key)) for key in ("hard", "soft", "management", "education", "salary")}


class CandidateVacancy(db.Model, PayloadMixin):
    __tablename__ = "candidate_vacancies"
    id: Mapped[str] = mapped_column(db.String(64), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    vacancy_id: Mapped[str] = mapped_column(ForeignKey("vacancies.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(db.String(40), default="new", nullable=False)
    total: Mapped[int | None] = mapped_column()
    model_probability: Mapped[float | None] = mapped_column()
    created_at: Mapped[str | None] = mapped_column(db.String(40))
    updated_at: Mapped[str | None] = mapped_column(db.String(40))
    __table_args__ = (UniqueConstraint("candidate_id", "vacancy_id", name="uq_candidate_vacancy"),)


class CandidateStageEvent(db.Model, PayloadMixin):
    __tablename__ = "candidate_stage_events"
    id: Mapped[str] = mapped_column(db.String(64), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    vacancy_id: Mapped[str] = mapped_column(ForeignKey("vacancies.id", ondelete="RESTRICT"), nullable=False, index=True)
    from_stage: Mapped[str | None] = mapped_column(db.String(40))
    to_stage: Mapped[str] = mapped_column(db.String(40), nullable=False)
    created_at: Mapped[str | None] = mapped_column(db.String(40), index=True)


class Interview(db.Model, PayloadMixin):
    __tablename__ = "interviews"
    id: Mapped[str] = mapped_column(db.String(64), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    vacancy_id: Mapped[str] = mapped_column(ForeignKey("vacancies.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(db.String(40), default="scheduled", nullable=False)
    date: Mapped[str] = mapped_column(db.String(10), nullable=False)
    time: Mapped[str] = mapped_column(db.String(5), nullable=False)


class Feedback(db.Model, PayloadMixin):
    __tablename__ = "feedback"
    id: Mapped[str] = mapped_column(db.String(64), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    vacancy_id: Mapped[str] = mapped_column(ForeignKey("vacancies.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_at: Mapped[str | None] = mapped_column(db.String(40), index=True)


class CandidateTransfer(db.Model, PayloadMixin):
    __tablename__ = "candidate_transfers"
    id: Mapped[str] = mapped_column(db.String(64), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    from_vacancy_id: Mapped[str | None] = mapped_column(ForeignKey("vacancies.id", ondelete="RESTRICT"))
    to_vacancy_id: Mapped[str] = mapped_column(ForeignKey("vacancies.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[str | None] = mapped_column(db.String(40), index=True)


class VacancyTemplate(db.Model, PayloadMixin):
    __tablename__ = "vacancy_templates"
    id: Mapped[str] = mapped_column(db.String(64), primary_key=True)
    name: Mapped[str] = mapped_column(db.String(255), nullable=False)
    usage_count: Mapped[int] = mapped_column(default=0, nullable=False)
    created_at: Mapped[str | None] = mapped_column(db.String(40))
    updated_at: Mapped[str | None] = mapped_column(db.String(40))


class ScoreResult(db.Model, PayloadMixin):
    __tablename__ = "score_results"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    vacancy_id: Mapped[str] = mapped_column(ForeignKey("vacancies.id", ondelete="RESTRICT"), nullable=False, index=True)
    total: Mapped[int] = mapped_column(nullable=False)
    model_probability: Mapped[float | None] = mapped_column()
    model_version: Mapped[str | None] = mapped_column(db.String(120))
    created_at: Mapped[str | None] = mapped_column(db.String(40), index=True)


class ChatConversation(db.Model, PayloadMixin):
    __tablename__ = "chat_conversations"
    id: Mapped[str] = mapped_column(db.String(64), primary_key=True)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"), index=True)
    vacancy_id: Mapped[str | None] = mapped_column(ForeignKey("vacancies.id", ondelete="SET NULL"), index=True)
    created_by: Mapped[str] = mapped_column(db.String(64), default="HR_SYSTEM", nullable=False)
    created_at: Mapped[str] = mapped_column(db.String(40), nullable=False, index=True)
    updated_at: Mapped[str] = mapped_column(db.String(40), nullable=False, index=True)


class ChatMessage(db.Model, PayloadMixin):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(db.String(20), nullable=False)
    content: Mapped[str] = mapped_column(db.Text, nullable=False)
    model_name: Mapped[str | None] = mapped_column(db.String(160))
    model_version: Mapped[str | None] = mapped_column(db.String(120))
    created_at: Mapped[str] = mapped_column(db.String(40), nullable=False, index=True)


class ChatAction(db.Model, PayloadMixin):
    __tablename__ = "chat_actions"
    id: Mapped[str] = mapped_column(db.String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[int] = mapped_column(ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(db.String(64), nullable=False)
    status: Mapped[str] = mapped_column(db.String(20), default="pending", nullable=False, index=True)
    confirmed_by: Mapped[str | None] = mapped_column(db.String(64))
    created_at: Mapped[str] = mapped_column(db.String(40), nullable=False)
    confirmed_at: Mapped[str | None] = mapped_column(db.String(40))


class ChatResponseFeedback(db.Model, PayloadMixin):
    __tablename__ = "chat_response_feedback"
    id: Mapped[str] = mapped_column(db.String(64), primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    rating: Mapped[str] = mapped_column(db.String(32), nullable=False)
    corrected_answer: Mapped[str | None] = mapped_column(db.Text)
    approved_for_training: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(db.String(64), default="HR_SYSTEM", nullable=False)
    created_at: Mapped[str] = mapped_column(db.String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(db.String(40), nullable=False)

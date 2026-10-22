"""add chat history and feedback

Revision ID: 7c24d3f180a1
Revises: 4b73df50d845
Create Date: 2026-10-16 18:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "7c24d3f180a1"
down_revision = "4b73df50d845"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=True),
        sa.Column("vacancy_id", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("updated_at", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["vacancy_id"], ["vacancies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_conversations_candidate_id", "chat_conversations", ["candidate_id"])
    op.create_index("ix_chat_conversations_vacancy_id", "chat_conversations", ["vacancy_id"])
    op.create_index("ix_chat_conversations_created_at", "chat_conversations", ["created_at"])
    op.create_index("ix_chat_conversations_updated_at", "chat_conversations", ["updated_at"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(length=160), nullable=True),
        sa.Column("model_version", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["chat_conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"])
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"])

    op.create_table(
        "chat_actions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("confirmed_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("confirmed_at", sa.String(length=40), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["chat_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["chat_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_actions_conversation_id", "chat_actions", ["conversation_id"])
    op.create_index("ix_chat_actions_message_id", "chat_actions", ["message_id"])
    op.create_index("ix_chat_actions_status", "chat_actions", ["status"])

    op.create_table(
        "chat_response_feedback",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.String(length=32), nullable=False),
        sa.Column("corrected_answer", sa.Text(), nullable=True),
        sa.Column("approved_for_training", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("updated_at", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["chat_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id"),
    )
    op.create_index("ix_chat_response_feedback_message_id", "chat_response_feedback", ["message_id"])
    op.create_index("ix_chat_response_feedback_approved_for_training", "chat_response_feedback", ["approved_for_training"])


def downgrade():
    op.drop_table("chat_response_feedback")
    op.drop_table("chat_actions")
    op.drop_table("chat_messages")
    op.drop_table("chat_conversations")

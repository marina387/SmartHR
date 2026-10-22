"""Экспортирует только подтверждённые HR исправления в сырой JSONL для обезличивания."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app
from src.chat.dataset import write_jsonl
from src.storage.sql_storage import SqlChatConversationStorage, SqlChatFeedbackStorage, SqlChatMessageStorage


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/chat/raw/approved_chat_feedback.jsonl"))
    args = parser.parse_args()
    records = []
    with app.app_context():
        conversations = SqlChatConversationStorage()
        messages = SqlChatMessageStorage()
        feedback_store = SqlChatFeedbackStorage()
        for feedback in feedback_store.list_all():
            if feedback.get("approved_for_training") is not True or not feedback.get("corrected_answer"):
                continue
            assistant = messages.get_by_id(int(feedback["message_id"]))
            if not assistant:
                continue
            thread = messages.list_by_conversation(str(assistant["conversation_id"]))
            position = next((index for index, item in enumerate(thread) if item["id"] == assistant["id"]), -1)
            if position <= 0 or thread[position - 1].get("role") != "user":
                continue
            conversation = conversations.get_by_id(str(assistant["conversation_id"])) or {}
            records.append({
                "id": f"feedback_{feedback['id']}",
                "group_id": conversation.get("candidate_id") or conversation.get("id"),
                "candidate_id": conversation.get("candidate_id"),
                "document_id": None,
                "scenario": "hr_corrected_chat_answer",
                "messages": [
                    {"role": "system", "content": "Ты HR-ассистент SmartHR. Не придумывай отсутствующие данные."},
                    {"role": "user", "content": thread[position - 1]["content"]},
                    {"role": "assistant", "content": feedback["corrected_answer"]},
                ],
                "source_ids": [source.get("id") for source in assistant.get("sources", [])],
                "approved_by_hr": True,
                "anonymized": False,
            })
    write_jsonl(args.output, records)
    print(f"Экспортировано подтверждённых примеров: {len(records)}. Далее обязательно выполнить обезличивание.")


if __name__ == "__main__":
    main()

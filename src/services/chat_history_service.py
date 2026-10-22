"""История диалогов, действий и обратной связи HR."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


class ChatHistoryService:
    RATINGS = {"useful", "not_useful", "factual_error", "wrong_source"}

    def __init__(self, conversations: Any, messages: Any, actions: Any, feedback: Any) -> None:
        self.conversations = conversations
        self.messages = messages
        self.actions = actions
        self.feedback = feedback

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def ensure_conversation(self, conversation_id: str | None, *, candidate_id: str | None,
                            vacancy_id: str | None, created_by: str) -> Dict[str, Any]:
        current = self.conversations.get_by_id(conversation_id) if conversation_id else None
        if current:
            current.update(candidate_id=candidate_id, vacancy_id=vacancy_id)
            return self.conversations.save(current)
        now = self._now()
        return self.conversations.save({
            "candidate_id": candidate_id, "vacancy_id": vacancy_id, "created_by": created_by,
            "created_at": now, "updated_at": now,
        })

    def record_exchange(self, conversation_id: str | None, *, candidate_id: str | None,
                        vacancy_id: str | None, user_message: str, assistant_result: Dict[str, Any],
                        created_by: str = "HR_SYSTEM") -> Dict[str, Any]:
        conversation = self.ensure_conversation(
            conversation_id, candidate_id=candidate_id, vacancy_id=vacancy_id, created_by=created_by
        )
        now = self._now()
        user = self.messages.save({
            "conversation_id": conversation["id"], "role": "user", "content": user_message,
            "created_at": now,
        })
        assistant = self.messages.save({
            "conversation_id": conversation["id"], "role": "assistant",
            "content": assistant_result["answer"], "model_name": assistant_result.get("model"),
            "model_version": assistant_result.get("model_version"),
            "sources": assistant_result.get("sources", []),
            "retrieval_backend": assistant_result.get("retrieval_backend"), "created_at": self._now(),
        })
        if not conversation.get("title"):
            conversation["title"] = " ".join(user_message.split())[:100]
        conversation["updated_at"] = self._now()
        self.conversations.save(conversation)
        return {"conversation": conversation, "user_message": user, "assistant_message": assistant}

    def create_action(self, conversation_id: str, message_id: int, action: Dict[str, Any]) -> Dict[str, Any]:
        return self.actions.save({
            "conversation_id": conversation_id, "message_id": message_id,
            "action_type": action["type"], "status": "pending", "action_payload": action["payload"],
            "label": action.get("label"), "created_at": self._now(),
        })

    def complete_action(self, action_id: str, *, confirmed_by: str,
                        status: str, result: Dict[str, Any] | None = None) -> Dict[str, Any]:
        action = self.actions.get_by_id(action_id)
        if not action:
            raise ValueError("Предложенное действие не найдено")
        if action.get("status") != "pending":
            raise ValueError("Действие уже обработано")
        action.update({
            "status": status, "confirmed_by": confirmed_by, "confirmed_at": self._now(),
            "result": result or {},
        })
        return self.actions.save(action)

    def save_feedback(self, message_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        message = self.messages.get_by_id(message_id)
        if not message or message.get("role") != "assistant":
            raise ValueError("Ответ ассистента не найден")
        rating = str(payload.get("rating") or "").strip()
        if rating not in self.RATINGS:
            raise ValueError("Недопустимая оценка ответа")
        corrected = str(payload.get("corrected_answer") or "").strip()
        approved = bool(payload.get("approved_for_training", False))
        if approved and not corrected:
            raise ValueError("Для обучения требуется проверленный исправленный ответ")
        existing = self.feedback.find_by_message(message_id)
        now = self._now()
        return self.feedback.save({
            **(existing or {}), "message_id": message_id, "rating": rating,
            "corrected_answer": corrected or None, "approved_for_training": approved,
            "created_by": str(payload.get("hr_id") or "HR_SYSTEM"),
            "created_at": (existing or {}).get("created_at", now), "updated_at": now,
        })

    def conversation(self, conversation_id: str) -> Dict[str, Any]:
        conversation = self.conversations.get_by_id(conversation_id)
        if not conversation:
            raise ValueError("Диалог не найден")
        messages = self.messages.list_by_conversation(conversation_id)
        actions = self.actions.list_all()
        for message in messages:
            if message.get("role") == "assistant":
                message["feedback"] = self.feedback.find_by_message(message["id"])
                message["actions"] = [action for action in actions if action.get("message_id") == message["id"]]
        return {**conversation, "messages": messages}

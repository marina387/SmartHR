"""Оркестрация запроса чат-ассистента."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List

from src.chat.models import ChatModel
from src.chat.tools import SmartHRChatTools
from src.core.rag_pipeline import RagPipeline


class ChatService:
    def __init__(self, model: ChatModel, tools: SmartHRChatTools, rag: RagPipeline) -> None:
        self.model = model
        self.tools = tools
        self.rag = rag

    def ask(self, message: str, *, candidate_id: str | None = None,
            vacancy_id: str | None = None, history: List[Dict[str, str]] | None = None) -> Dict[str, Any]:
        message = str(message or "").strip()
        if not message:
            raise ValueError("Сообщение не может быть пустым")
        if len(message) > 4000:
            raise ValueError("Сообщение слишком длинное")

        clean_history = self._history(history or [])
        scenario = self.scenario_for_message(message, clean_history)
        if scenario == "candidate_list":
            interview_only = any(word in message.casefold() for word in ("собеседован", "интервью"))
            candidates = self.tools.list_candidates_for_chat(stage="interview" if interview_only else None, vacancy_id=vacancy_id)
            heading = "Кандидаты на этапе собеседования" if interview_only else "Кандидаты в базе"
            answer = heading + ":\n" + "\n".join(f"• {item.get('name') or item['id']} ({item['id']})" for item in candidates) if candidates else ("В базе нет кандидатов на этапе собеседования." if interview_only else "В базе нет кандидатов.")
            return {"answer": answer, "sources": [], "suggested_action": None,
                    "model": self.model.__class__.__name__, "retrieval_backend": self.rag.backend_name}
        if self._is_document_list_query(message):
            catalog = self.rag.list_documents()
            answer = ("В базе есть документы:\n" + "\n".join(f"• {item['title']}" for item in catalog)) if catalog else "В базе пока нет документов."
            return {"answer": answer, "sources": [], "suggested_action": None,
                    "model": self.model.__class__.__name__, "retrieval_backend": self.rag.backend_name}
        if scenario == "document_search":
            previous = self._last_user_message(clean_history) or ""
            catalog_followup = (
                self._is_document_list_query(previous)
                or (self._scenario(previous) == "document_search" and self._is_document_availability_query(previous))
                or any(item.get("role") == "assistant" and item.get("content") in {"Да, документ есть в базе.", "Нет, документа в базе нет."} for item in clean_history[-2:])
            )
            short_followup = bool(re.match(r"^(?:а|и|есть ли|а есть)\s+", message.casefold())) and len(message.split()) <= 8 and not any(word in message.casefold() for word in ("покажи", "найди", "расскажи", "объясни", "содерж"))
            if self._is_document_availability_query(message) or (catalog_followup and short_followup):
                return self._document_availability(message)
        reference = self._document_reference(message, clean_history)
        retrieval_query = f"{reference}. {message}" if reference else message
        if self._is_correction(message):
            previous_user_message = self._last_user_message(clean_history)
            if previous_user_message and self._scenario(previous_user_message) == "document_search":
                scenario = "document_search"
                retrieval_query = f"{previous_user_message}. Уточнение пользователя: {message}"
        context = self.tools.context(candidate_id, vacancy_id, include_alternatives=scenario in {"alternatives", "action"})
        context["requested_details"] = []
        lowered = message.casefold()
        if scenario in {"candidate_interviews", "score_explanation", "candidate_stage"}:
            details = []
            if any(word in lowered for word in ("интервью", "собеседован")):
                details.append("candidate_interviews")
            if "оценк" in lowered:
                details.append("score_explanation")
            if any(word in lowered for word in ("этап", "статус")):
                details.append("candidate_stage")
            if len(details) > 1:
                context["requested_details"] = details
                context["explain_requested"] = any(word in lowered for word in ("объясн", "почему", "обосн"))
        context["scenario"] = scenario
        context["document_query_vague"] = self._is_vague_document_query(retrieval_query, scenario)
        if scenario == "interview_questions":
            context["generated_interview_questions"] = self.tools.interview_questions(context.get("candidate"), context.get("vacancy"))
        if scenario in {"invitation", "rejection"}:
            context["message_draft"] = self.tools.draft_message(scenario, context.get("candidate"), context.get("vacancy"))
        sources: List[Dict[str, Any]] = []
        documents: List[Dict[str, Any]] = []
        should_search_documents = scenario == "document_search"
        if self.rag.retriever.is_indexed and should_search_documents and not context["document_query_vague"]:
            default_score = "0.15" if self.rag.backend_name == "tfidf" else "0.25"
            minimum_score = float(os.getenv("RAG_MIN_SCORE", default_score))
            for hit in self.rag.ask(retrieval_query, top_k=5).hits:
                if hit.score < minimum_score:
                    continue
                item = {
                    "id": hit.chunk.doc_id,
                    "title": hit.chunk.metadata.get("title", hit.chunk.doc_id),
                    "source": hit.chunk.metadata.get("source", hit.chunk.doc_id),
                    "document_type": hit.chunk.metadata.get("document_type", "text"),
                    "chunk_id": hit.chunk.chunk_id,
                    "score": round(hit.score, 4),
                    "text": hit.chunk.text,
                }
                if not self._compatible_document_hit(retrieval_query, item):
                    continue
                documents.append(item)
                sources.append({key: item[key] for key in ("id", "title", "source", "document_type", "chunk_id", "score")})
        context["documents"] = documents
        effective_vacancy_id = vacancy_id or str((context.get("vacancy") or {}).get("id") or "") or None
        action = self.tools.propose_action(message, candidate_id, effective_vacancy_id, context.get("alternatives") or [])
        messages = [*clean_history, {"role": "user", "content": message}]
        from src.chat.responses import structured_answer
        answer = structured_answer(context, action)
        if answer is None:
            answer = self.model.generate(messages, context).strip()
        if not answer:
            raise RuntimeError("Чат-модель вернула пустой ответ")
        return {
            "answer": answer,
            "context": {"candidate": context.get("candidate"), "vacancy": context.get("vacancy")},
            "sources": sources,
            "suggested_action": action,
            "model": self.model.__class__.__name__,
            "retrieval_backend": self.rag.backend_name,
        }

    @staticmethod
    def _is_document_list_query(message: str) -> bool:
        lowered = message.casefold()
        return bool(re.search(r"\bдокумент[а-яё]*\b", lowered)) and (
            bool(re.search(r"\b(?:какие|список|перечень|все)\b", lowered))
            or re.sub(r"[^а-яё ]", "", lowered).strip() in {"покажи документы", "документы"}
        )

    @staticmethod
    def _is_document_availability_query(message: str) -> bool:
        lowered = message.casefold()
        return bool(re.search(r"\b(?:есть|имеется|имеются|доступен|доступна|загружен|загружена)\b", lowered)) and not any(
            phrase in lowered for phrase in ("что есть в", "что имеется в")
        )

    def _document_availability(self, message: str) -> Dict[str, Any]:
        # Проверяем каталог документов, а не совпадение с фрагментом текста.
        aliases = {
            "corporate_code": "корпоративный кодекс",
            "employee_handbook": "справочник сотрудника",
            "hr_policy_2024": "кадровая hr политика",
            "interview_guide": "руководство по собеседованию интервью",
            "onboarding_guide": "руководство по адаптации онбординг",
        }
        query = re.sub(r"\b(?:а|и|в|у|вас|нас|базе|база|есть|ли|имеется|имеются|доступен|доступна|загружен|загружена|документ|файл|по)\b", " ", message.casefold())
        tokens = re.findall(r"[а-яёa-z0-9]+", query)
        found = False
        for document in self.rag.list_documents():
            doc_id = str(document["id"])
            catalog_text = " ".join((str(document["title"]), str(document["source"]), aliases.get(doc_id, ""))).casefold()
            # Общий префикс позволяет сопоставить русские склонения названия.
            title_words = re.findall(r"[а-яёa-z0-9]+", catalog_text)
            if tokens and all(any(word.startswith(token[:max(4, len(token)-2)]) for word in title_words) for token in tokens):
                found = True
                break
        return {
            "answer": "Да, документ есть в базе." if found else "Нет, документа в базе нет.",
            "sources": [], "suggested_action": None,
            "model": self.model.__class__.__name__, "retrieval_backend": self.rag.backend_name,
        }

    @staticmethod
    def _document_reference(message, history):
        if not re.search(r"\b(?:его|её|ее|этот|него|нем|нём)\b", message.casefold()):
            return None
        # Только ближайшая тема: после вопроса о кандидате старый документ не подхватываем.
        for item in reversed(history):
            if item.get("role") == "user":
                previous = item.get("content", "")
                return previous if ChatService._scenario(previous) == "document_search" else None
        return None

    @classmethod
    def scenario_for_message(cls, message, history):
        scenario = cls._scenario(message)
        if scenario == "question" and cls._document_reference(message, history):
            return "document_search"
        return scenario

    @staticmethod
    def _scenario(message: str) -> str:
        lowered = message.casefold()
        compact = re.sub(r"[^а-яёa-z0-9]+", " ", lowered).strip()
        if compact in {"привет", "здравствуйте", "добрый день", "добрый вечер", "доброе утро", "hello", "hi"}:
            return "greeting"
        if any(word in lowered for word in ("документ", "руководств", "регламент", "инструкц", "кодекс", "политик", "справочник", "статья", "ст.", "закон")):
            return "document_search"
        if "кандидат" in lowered and (
            any(word in lowered for word in ("список", "перечень", "всех", "какие кандидаты", "кто из кандидатов"))
            or ("покажи" in lowered and "кандидатов" in lowered)
        ):
            return "candidate_list"
        if any(word in lowered for word in ("архивируй", "перенеси", "переведи", "измени этап", "измени статус", "поменяй этап", "установи этап")):
            return "action"
        if any(word in lowered for word in ("альтернатив", "другая вакансия", "другую вакансию")):
            return "alternatives"
        if any(word in lowered for word in ("приглашение", "пригласи")):
            return "invitation"
        if any(word in lowered for word in ("письмо отказ", "текст отказ", "отказ кандидату")):
            return "rejection"
        interview_topic = any(word in lowered for word in ("интервью", "собеседован"))
        if interview_topic and "вопрос" in lowered:
            return "interview_questions"
        if interview_topic and any(word in lowered for word in ("как провод", "порядок", "как проходит", "проводится")):
            return "document_search"
        if interview_topic:
            return "candidate_interviews"
        if any(word in lowered for word in ("этап", "статус")):
            return "candidate_stage"
        if any(word in lowered for word in ("оценк", "почему", "объясни")):
            return "score_explanation"
        if any(word in lowered for word in ("где написано", "где описан", "что сказано", "найди информацию", "найди в", "адаптац", "онбординг", "отпуск", "командиров", "дресс-код", "конфиденциальн")):
            return "document_search"
        return "question"

    @staticmethod
    def _is_vague_document_query(message: str, scenario: str) -> bool:
        if scenario != "document_search":
            return False
        lowered = message.casefold().strip(" .!?…")
        vague = {
            "найди информацию в hr-документах", "найди информацию в документах",
            "поиск по документам", "покажи документы", "документы",
        }
        return lowered in vague

    @staticmethod
    def _is_correction(message: str) -> bool:
        lowered = re.sub(r"[^а-яёa-z0-9]+", " ", message.casefold()).strip()
        return lowered in {"не то", "нет не то", "неверно", "другой документ"} or "а не" in lowered

    @staticmethod
    def _last_user_message(history: List[Dict[str, str]]) -> str | None:
        return next((item["content"] for item in reversed(history) if item.get("role") == "user"), None)

    @staticmethod
    def _compatible_document_hit(query: str, item: Dict[str, Any]) -> bool:
        """Не подменяет явно названный вид документа семантически похожим."""
        lowered = query.casefold()
        haystack = " ".join(str(item.get(key) or "") for key in ("title", "source", "text")).casefold()
        required_families = {
            "трудов": ("трудов", "labor code"),
            "корпоратив": ("корпоратив", "corporate code"),
            "персональн": ("персональн", "personal data"),
        }
        for marker, accepted in required_families.items():
            if marker in lowered:
                return any(value in haystack for value in accepted)
        return True

    @staticmethod
    def _history(items: List[Dict[str, str]]) -> List[Dict[str, str]]:
        result: List[Dict[str, str]] = []
        for item in items[-10:]:
            role = str(item.get("role", "")).strip()
            content = str(item.get("content", "")).strip()
            if role in {"user", "assistant"} and content:
                result.append({"role": role, "content": content[:4000]})
        return result

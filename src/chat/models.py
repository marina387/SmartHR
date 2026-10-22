# -*- coding: utf-8 -*-
"""Независимые адаптеры языковых моделей для чата."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List


class ChatModel(ABC):
    """Контракт модели, стабильный для приложения и команды обучения."""

    @abstractmethod
    def generate(self, messages: List[Dict[str, str]], context: Dict[str, Any]) -> str:
        """Формирует ответ на основании сообщений и проверенного контекста."""


class MockChatModel(ChatModel):
    """Детерминированный адаптер для разработки и автоматических тестов."""

    def generate(self, messages: List[Dict[str, str]], context: Dict[str, Any]) -> str:
        candidate = context.get("candidate") or {}
        vacancy = context.get("vacancy") or {}
        score = context.get("score") or {}
        documents = context.get("documents") or []
        scenario = context.get("scenario")
        if scenario == "score_explanation":
            if not candidate:
                return "Кандидат не найден. Уточните имя или выберите кандидата."
            if not score or score.get("total") is None:
                return "Для этого кандидата нет сохранённой оценки по выбранной вакансии."
            lines = [f"Оценка кандидата {candidate.get('name') or candidate.get('id')}: {score['total']}/100."]
            if vacancy:
                lines.append(f"Вакансия: {vacancy.get('title') or vacancy.get('name') or vacancy.get('id')}.")
            details = context.get("score_explanation") or []
            if not details:
                lines.append("Разбивка по критериям не сохранена, поэтому объяснить итог по имеющимся данным нельзя.")
                return "\n".join(lines)
            weights = score.get("used_weights") or {}
            weight_sum = sum(max(0, float(value)) for value in weights.values())
            lines.append("По сохранённым данным:")
            for item in details:
                value = item.get("score")
                weight = item.get("weight")
                line = f"• {item['label']}: {value}/10"
                if weight is not None and weight_sum > 0:
                    share = max(0, float(weight)) / weight_sum
                    contribution = max(0, min(10, float(value))) * share * 10
                    line += f", вес {share * 100:g}%, вклад {contribution:.1f} балла в итог"
                reason = item.get("comment") or item.get("evidence")
                if reason:
                    line += f". {reason}"
                else:
                    line += ". Причина этой оценки не сохранена"
                lines.append(line)
            if weight_sum > 0:
                lines.append("Итог — сумма взвешенных оценок критериев с округлением до целого.")
            return "\n".join(lines)
        if scenario == "greeting":
            return "Здравствуйте! Чем помочь: найти информацию в документах, объяснить оценку кандидата или подготовить материалы для интервью?"
        if scenario == "document_search":
            if context.get("document_query_vague"):
                return "Уточните тему поиска: например, адаптация сотрудника, отпуск или проведение интервью."
            if not documents:
                return "В доступных документах не найден подтверждённый ответ. Уточните запрос или загрузите нужный документ."
            best = documents[0]
            return f"В документе «{best['title']}» найден подходящий фрагмент:\n{best['text']}\nИсточник: {best.get('source', best['title'])}"
        parts: List[str] = []
        if candidate:
            parts.append(f"Кандидат: {candidate.get('name') or candidate.get('id')}.")
        if vacancy:
            parts.append(f"Вакансия: {vacancy.get('title') or vacancy.get('name') or vacancy.get('id')}.")
        if score:
            total = score.get("total")
            if total is not None:
                parts.append(f"Последняя сохранённая оценка: {total}/100.")
        return " ".join(parts) if parts else "В SmartHR не найдено достаточно данных."


class TransformersChatModel(ChatModel):
    """Ленивая загрузка локальной Hugging Face/PEFT модели."""

    def __init__(self, model_path: Path, metadata: Dict[str, Any]) -> None:
        self.model_path = model_path
        self.metadata = metadata
        self._pipeline = None

    def _load(self) -> None:
        if self._pipeline is not None:
            return
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
        except ImportError as exc:
            raise RuntimeError(
                "Для запуска обученной чат-модели установите requirements-chat.txt"
            ) from exc
        device = os.getenv("CHAT_MODEL_DEVICE", "auto")
        device_map = None if device == "cpu" else device
        
        if (self.model_path / "adapter_config.json").exists():
            try:
                from peft import PeftModel
            except ImportError as exc:
                raise RuntimeError("Для LoRA-адаптера установите peft") from exc
            base_model = str(self.metadata.get("base_model") or "").strip()
            if not base_model:
                raise RuntimeError("В метаданных LoRA отсутствует base_model")
                
            # Пытаемся использовать локальную базовую модель, чтобы не ждать загрузки из интернета
            local_base_path = Path("models/base_qwen")
            if local_base_path.exists():
                base_model = str(local_base_path.resolve())
                
            tokenizer = AutoTokenizer.from_pretrained(str(self.model_path))
            base = AutoModelForCausalLM.from_pretrained(base_model, device_map=device_map, local_files_only=True)
            model = PeftModel.from_pretrained(base, str(self.model_path))
            self._pipeline = pipeline("text-generation", model=model, tokenizer=tokenizer)
        else:
            self._pipeline = pipeline(
                "text-generation", model=str(self.model_path), tokenizer=str(self.model_path),
                device_map=device_map,
            )

    def generate(self, messages: List[Dict[str, str]], context: Dict[str, Any]) -> str:
        # Документальный ответ строится из найденного текста до обработки кандидатов.
        if context.get("scenario") in {"document_search", "greeting", "score_explanation"}:
            return MockChatModel().generate(messages, context)
        self._load()
        
        last_user_msg = messages[-1].get("content", "").lower() if messages else ""
        cand = context.get("candidate") or {}
        docs = context.get("documents") or []
        score = context.get("score") or {}

        # 1. Обработка поиска кандидата (как по кнопке, так и текстом)
        if "найди" in last_user_msg or "расскажи" in last_user_msg or "кандидат" in last_user_msg:
            if not cand:
                return "Кандидат не найден в базе. Уточните фамилию или имя."
            
            name = cand.get("name", "Кандидат")
            position = cand.get("position", "Не указана")
            exp = cand.get("experience_years", 0)
            skills = ", ".join(cand.get("skills", [])[:7]) if cand.get("skills") else "не указаны"
            edu = cand.get("education", "Не указано")
            total = score.get("total", 0)
            
            return (
                f"Кандидат: {name}.\n"
                f"Позиция: {position}.\n"
                f"Опыт работы: {exp} лет.\n"
                f"Образование: {edu}.\n"
                f"Ключевые навыки: {skills}.\n"
                f"Текущая оценка соответствия: {total}/100."
            )

        # 2. Если пользователь спрашивает про документ (и документы найдены)
        if any(w in last_user_msg for w in ("документ", "политик", "инструкц", "регламент")) and docs:
            best = docs[0]
            text = str(best.get("text", ""))[:400]
            return f"Согласно документу «{best.get('title')}»:\n{text}..."

        # 3. Если просят объяснить оценку
        if "оценк" in last_user_msg or "почему" in last_user_msg:
            if not cand:
                return "Кандидат не выбран."
            total = score.get("total", 0)
            return f"Оценка кандидата {cand.get('name')} составляет {total}/100."

        # 4. Дефолтный ответ
        if cand:
            return f"Вы спрашиваете о кандидате {cand.get('name')}. Чем я могу помочь? (например, 'Расскажи о кандидате' или 'Объясни оценку')"
        
        return "Я не совсем понял вопрос. Попробуйте спросить про конкретного кандидата или документ."


def build_chat_model(root_dir: Path) -> ChatModel:
    """Автоматически выбирает готовую модель или безопасный тестовый адаптер."""
    configured = os.getenv("CHAT_MODEL_PATH", "models/chat_model_real")
    model_path = Path(configured)
    if not model_path.is_absolute():
        model_path = root_dir / model_path
    metadata_path = model_path / "smarthr_model_metadata.json"
    if not metadata_path.exists():
        return MockChatModel()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if str(metadata.get("format_version")) != "1.0":
        raise RuntimeError("Неподдерживаемая версия формата чат-модели")
    return TransformersChatModel(model_path, metadata)

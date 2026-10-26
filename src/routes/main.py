# -*- coding: utf-8 -*-
"""Маршруты приложения."""

import json
import os
import random
import re
import uuid
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from threading import RLock
import time
from markupsafe import escape
from typing import Any, Dict, List

from flask import Blueprint, current_app, jsonify, render_template, request, redirect, url_for, send_file, abort
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from src.services.app_time import local_now
from src.services.transactions import transactional_request
from src.services.api_validation import validate_api_request, api_http_error, api_internal_error, sanitize_api_errors
from werkzeug.exceptions import HTTPException
from sqlalchemy.exc import IntegrityError
from src.chat import ChatService, SmartHRChatTools, build_chat_model
from src.config import DEMO_RESUMES, FUNNEL_STAGES, FUNNEL_TERMINAL_STATUSES, MAX_CONTENT_LENGTH
from src.core.rag_pipeline import RagPipeline
from src.core.loaders import load_hr_documents, load_document
from src.services.feedback_service import FeedbackService
from src.services.alternative_vacancy_service import AlternativeVacancyService
from src.services.candidate_vacancy_service import CandidateVacancyService
from src.services.candidate_stage_service import CandidateStageService
from src.services.candidate_retention_service import CandidateRetentionService
from src.services.funnel_service import FunnelService
from src.services.interview_service import InterviewService
from src.services.chat_history_service import ChatHistoryService
from src.services.parsing import extract_requirements, parse_docx, parse_hh_url, parse_pdf
from src.services.scoring import CandidateScoringService
from src.services.template_service import TemplateService
from src.services.vacancy_service import VacancyService
from src.storage.sql_storage import (
    SqlCandidateStorage, SqlCandidateVacancyStorage, SqlFeedbackStorage,
    SqlInterviewStorage, SqlStageEventStorage, SqlTemplateStorage,
    SqlTransferStorage, SqlVacancyStorage, SqlScoreResultStorage,
    SqlChatConversationStorage, SqlChatMessageStorage, SqlChatActionStorage, SqlChatFeedbackStorage,
)

main_bp = Blueprint("main", __name__)
main_bp.before_request(validate_api_request)
main_bp.after_request(sanitize_api_errors)
main_bp.register_error_handler(HTTPException, api_http_error)
main_bp.register_error_handler(Exception, api_internal_error)
scoring_service = CandidateScoringService()
storage = SqlCandidateStorage()
vacancy_storage = SqlVacancyStorage()
vacancy_service = VacancyService(vacancy_storage)
template_storage = SqlTemplateStorage()
template_service = TemplateService(template_storage)
interview_storage = SqlInterviewStorage()
interview_service = InterviewService(interview_storage)
feedback_storage = SqlFeedbackStorage()
feedback_service = FeedbackService(feedback_storage)
candidate_vacancy_storage = SqlCandidateVacancyStorage()
transfer_storage = SqlTransferStorage()
candidate_stage_event_storage = SqlStageEventStorage()
score_result_storage = SqlScoreResultStorage()
chat_conversation_storage = SqlChatConversationStorage()
chat_message_storage = SqlChatMessageStorage()
chat_action_storage = SqlChatActionStorage()
chat_feedback_storage = SqlChatFeedbackStorage()
candidate_stage_service = CandidateStageService(candidate_vacancy_storage, candidate_stage_event_storage)
candidate_vacancy_service = CandidateVacancyService(candidate_vacancy_storage, transfer_storage, candidate_stage_service)
funnel_service = FunnelService(candidate_vacancy_storage, candidate_stage_event_storage, storage)
ROOT_DIR = Path(__file__).resolve().parents[2]
DOCS_DIR = ROOT_DIR / "docs" / "sample_docs"
UPLOAD_DOCS_DIR = Path(os.getenv("SMARTHR_DOCUMENTS", ROOT_DIR / "data" / "documents")).resolve()
DOCUMENT_LOCK = RLock()
VACANCY_CATEGORIES = ["IT", "Медицина", "Производство", "Финансы", "Строительство", "Образование", "Продажи", "Логистика"]


def _retention_service() -> CandidateRetentionService:
    """Создаёт сервис из текущих зависимостей (в том числе подменённых в тестах)."""
    return CandidateRetentionService(storage, vacancy_service, scoring_service, candidate_vacancy_storage, interview_service)


def _document_catalog_state():
    path = UPLOAD_DOCS_DIR / "library.json"
    if not path.exists():
        return {}
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError("Некорректный каталог документов")
    return state


def _library_documents(state=None):
    from dataclasses import replace
    documents = load_hr_documents(DOCS_DIR) + load_hr_documents(UPLOAD_DOCS_DIR)
    result = []
    for document in documents:
        sidecar = Path(document.metadata["path"]).with_suffix(".json")
        if Path(document.metadata["path"]).parent == UPLOAD_DOCS_DIR and sidecar.exists():
            try:
                name = json.loads(sidecar.read_text(encoding="utf-8"))["name"]
                document = replace(document, title=Path(name).stem, source=name)
            except (ValueError, KeyError, TypeError):
                pass
        result.append(document)
    state = _document_catalog_state() if state is None else state
    hidden_versions = {version for entry in state.values() for version in entry.get("versions", [])}
    by_id = {document.id: document for document in result}
    visible = []
    for document in result:
        if document.id in hidden_versions:
            continue
        entry = state.get(document.id, {})
        if entry.get("deleted"):
            continue
        title = entry.get("title") or document.title
        replacement_id = entry.get("replacement")
        if replacement_id:
            replacement = by_id.get(replacement_id)
            if not replacement:
                raise ValueError("Файл новой версии документа отсутствует. Проверьте библиотеку документов.")
            document = replace(replacement, id=document.id)
        visible.append(replace(document, title=title))
    return visible


def _load_documents(documents=None) -> List[Dict[str, Any]]:
    """Считывает документы для страницы RAG."""

    docs: List[Dict[str, Any]] = []
    for document in (_library_documents() if documents is None else documents):
        # Универсальная категоризация HR-документов по имени файла.
        filename = document.source.lower()
        if "guide" in filename or "handbook" in filename:
            category = "Руководства"
            rating = 4.8
        elif "code" in filename or "policy" in filename:
            category = "Политики"
            rating = 4.6
        else:
            category = "Регламенты"
            rating = 4.5

        docs.append(
            {
                "id": document.id,
                "name": document.source,
                "title": document.title,
                "category": category,
                "date": str(document.metadata.get("modified_at", ""))[:10],
                "rating": rating,
                "text": document.text,
                "document_type": document.document_type,
                "metadata": document.metadata,
            }
        )
    return docs


DOCUMENTS = _load_documents()
rag_pipeline = RagPipeline()
if DOCUMENTS:
    rag_pipeline.build_index(_library_documents())
chat_model = build_chat_model(ROOT_DIR)


def _chat_service() -> ChatService:
    """Создаёт чат из текущих зависимостей, включая подмены в тестах."""
    alternatives = AlternativeVacancyService(storage, vacancy_service, scoring_service, candidate_vacancy_storage)
    tools = SmartHRChatTools(
        storage, vacancy_service, candidate_vacancy_storage,
        score_result_storage, interview_service, candidate_stage_event_storage, alternatives,
    )
    return ChatService(chat_model, tools, rag_pipeline)


def _chat_history_service() -> ChatHistoryService:
    return ChatHistoryService(
        chat_conversation_storage, chat_message_storage, chat_action_storage, chat_feedback_storage
    )


def _chat_action_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="smarthr-chat-action-v1")


def _status_meta(status: str) -> Dict[str, str]:
    """Возвращает метаданные статуса для бейджей и иконок."""
    mapping = {
        "green": {"badge": "bg-success", "icon": "🟢", "label": "Одобрен"},
        "yellow": {"badge": "bg-warning text-dark", "icon": "🟡", "label": "На проверке"},
        "red": {"badge": "bg-danger", "icon": "🔴", "label": "Отклонён"},
    }
    return mapping.get(status, mapping["yellow"])


def _russian_date_label(value: datetime) -> str:
    """Форматирует дату для русскоязычного интерфейса."""
    weekdays = {
        0: "понедельник",
        1: "вторник",
        2: "среда",
        3: "четверг",
        4: "пятница",
        5: "суббота",
        6: "воскресенье",
    }
    months = {
        1: "января",
        2: "февраля",
        3: "марта",
        4: "апреля",
        5: "мая",
        6: "июня",
        7: "июля",
        8: "августа",
        9: "сентября",
        10: "октября",
        11: "ноября",
        12: "декабря",
    }
    return f"{value.day} {months[value.month]} {value.year}, {weekdays[value.weekday()]}"


def _candidate_view_model(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Преобразует запись кандидата к удобному для шаблона виду."""
    status = str(candidate.get("status", "yellow"))
    meta = _status_meta(status)
    total = candidate.get("total", 0)
    from src.services.score_explanation import explain_result
    explanation = explain_result(candidate)
    return {
        **candidate,
        "status_meta": meta,
        "score": int(total) if isinstance(total, int) else int(total or 0),
        "position": candidate.get("position") or "Специалист",
        "email": candidate.get("email") or "hr@company.ru",
        "phone": candidate.get("phone") or "+7 (999) 111-22-33",
        "skills": candidate.get("skills") or ["Аналитика", "Коммуникация"],
        "experience": candidate.get("experience") or ["3+ года опыта", "Опыт взаимодействия со стейкхолдерами"],
        "comments": candidate.get("comments") or {},
        "scores": candidate.get("scores") or {},
        "score_blocked": explanation['blocked'], "scoring_explanation": explanation,
        "score_available": candidate.get('total') is not None,
    }


def _highlight_text(text: str, query: str) -> str:
    text = str(escape(text))
    query = str(escape(query.strip()))
    if not query:
        return text
    return re.sub(re.escape(query), lambda match: f"<mark>{match.group(0)}</mark>", text, flags=re.IGNORECASE)


def _available_vacancies() -> List[Dict[str, str]]:
    """Формирует список доступных вакансий для страниц интерфейса."""
    items: List[Dict[str, str]] = []
    seen_ids = set()

    for vacancy in vacancy_service.get_all():
        vacancy_id = str(vacancy.get("id", "")).strip()
        title = str(vacancy.get("title", vacancy.get("name", ""))).strip() or "Без названия"
        status = str(vacancy.get("status", "active")).strip()
        if not vacancy_id or vacancy_id in seen_ids:
            continue
        if status not in {"active", "активна"}:
            continue
        seen_ids.add(vacancy_id)
        items.append({"id": vacancy_id, "title": title})

    positions = sorted(
        {
            str(candidate.get("position", "")).strip()
            for candidate in storage.list_candidates()
            if str(candidate.get("position", "")).strip()
        }
    )
    for idx, position in enumerate(positions, start=1):
        fallback_id = f"VAC_{idx:03d}"
        if fallback_id in seen_ids:
            continue
        seen_ids.add(fallback_id)
        items.append({"id": fallback_id, "title": position})

    if not items:
        items = [{"id": "VAC_001", "title": "Специалист"}]

    return items


def _prefill_vacancy_from_template(template: Dict[str, Any] | None) -> Dict[str, Any] | None:
    """Заполняет поля вакансии значениями шаблона."""
    if not template:
        return None

    return {
        "id": "",
        "template_id": template.get("id", ""),
        "title": template.get("name", ""),
        "name": template.get("name", ""),
        "category": template.get("category", "Общее"),
        "description": template.get("description", ""),
        "critical_requirements": template.get("critical_requirements", []),
        "skills": template.get("skills", []),
        "weights": template.get("weights", vacancy_service.get_default_weights()),
        "experience_required": template.get("experience_required", ""),
        "education_required": template.get("education_required", ""),
        "status": "active",
    }


def _candidate_for_storage(candidate: Dict[str, Any], score_result: Dict[str, Any], vacancy_id: str) -> Dict[str, Any]:
    """Подготавливает объект кандидата к сохранению в хранилище."""
    return {
        "id": candidate.get("id") or f"CV_{str(uuid.uuid4())[:8]}",
        "name": candidate.get("name") or "Новый кандидат",
        "status": score_result["status"],
        "decision": score_result["decision"],
        "total": score_result["total"],
        "scores": score_result["scores"],
        "comments": score_result["comments"],
        "critical_failures": score_result.get("critical_failures", []),
        "model_probability": score_result.get("model_probability"),
        "model_version": score_result.get("model_version"),
        "features": score_result.get("features", {}),
        "evidence": score_result.get("evidence", {}),
        "missing_fields": score_result.get("missing_fields", []),
        "score_status": score_result.get("score_status"), "summary": score_result.get("summary"),
        "requirement_checks": score_result.get("requirement_checks", []),
        "used_weights": score_result.get("used_weights", {}),
        "timestamp": local_now().strftime("%Y-%m-%d %H:%M"),
        "position": candidate.get("position") or "Специалист",
        "skills": candidate.get("skills") or ["Профильные навыки", "Коммуникация", "Аналитика"],
        "experience": candidate.get("experience") or ["Опыт релевантной работы", "Опыт взаимодействия с командой"],
        "email": candidate.get("email") or "candidate@company.ru",
        "phone": candidate.get("phone") or "+7 (999) 000-00-00",
        "vacancy_id": vacancy_id or "VAC_001",
        "resume_text": candidate.get("resume_text") or "",
    }


def _save_score_history(candidate_id: str, vacancy_id: str, result: Dict[str, Any], source: str) -> None:
    score_result_storage.save({
        "candidate_id": candidate_id, "vacancy_id": vacancy_id or "VAC_001",
        "total": result.get("total", 0), "model_probability": result.get("model_probability"),
        "model_version": result.get("model_version"), "scores": result.get("scores", {}),
        "used_weights": result.get("used_weights", {}), "features": result.get("features", {}),
        "evidence": result.get("evidence", {}), "critical_failures": result.get("critical_failures", []),
        "comments": result.get("comments", {}), "score_status": result.get("score_status"),
        "summary": result.get("summary"), "requirement_checks": result.get("requirement_checks", []),
        "missing_fields": result.get("missing_fields", []),
        "source": source, "created_at": local_now().isoformat(timespec="seconds"),
    })


@main_bp.route("/")
def index():
    """Отдаёт главную страницу."""
    candidates = [_candidate_view_model(item) for item in storage.list_candidates() if item.get("lifecycle_status", "active") == "active"]
    vacancies = _available_vacancies()
    today = local_now().strftime("%Y-%m-%d")
    approved_today = sum(1 for candidate in candidates if str(candidate.get("timestamp", "")).startswith(today) and candidate.get("status") == "green")
    interviews_today = sum(1 for interview in interview_service.list_all() if interview.get("date") == today and interview.get("status", "scheduled") == "scheduled")

    context = {
        "stats": {
            "new_candidates": len(candidates),
            "approved_today": approved_today,
            "interviews_today": interviews_today,
        },
        "recent_candidates": candidates[:5],
        "chat_summary": {
            "title": "Чат-ассистент",
            "message": "Найдите кандидата, объясните оценку или задайте вопрос по документам.",
        },
        "today_label": _russian_date_label(local_now()),
        "vacancies": vacancies,
        "initial_vacancy_id": vacancies[0]["id"] if vacancies else "VAC_001",
        "page_script": "manual_resume.js",
    }
    return render_template("index.html", **context)


@main_bp.route("/candidates")
def candidates_page():
    """Страница списка кандидатов с фильтрами и пагинацией."""
    candidates = [_candidate_view_model(item) for item in storage.list_candidates()]

    query = request.args.get("q", "").strip().lower()
    status = request.args.get("status", "all")
    position = request.args.get("position", "all")
    score_filter = request.args.get("score", "all")
    date_filter = request.args.get("date", "all")
    lifecycle_filter = request.args.get("lifecycle", "active").strip()
    funnel_stage = request.args.get("funnel_stage", "").strip()
    funnel_vacancy_id = request.args.get("vacancy_id", "").strip()
    funnel_candidate_ids = None
    if funnel_stage in FUNNEL_STAGES:
        target_rank = FUNNEL_STAGES.index(funnel_stage)
        funnel_candidate_ids = set()
        for relation in candidate_vacancy_storage.list_all():
            if funnel_vacancy_id and str(relation.get("vacancy_id")) != funnel_vacancy_id:
                continue
            relation_stage = str(relation.get("status", "new"))
            if relation_stage in FUNNEL_STAGES and FUNNEL_STAGES.index(relation_stage) >= target_rank:
                funnel_candidate_ids.add(str(relation.get("candidate_id")))
        for event in candidate_stage_event_storage.list_all():
            if funnel_vacancy_id and str(event.get("vacancy_id")) != funnel_vacancy_id:
                continue
            event_stage = str(event.get("to_stage", ""))
            if event_stage in FUNNEL_STAGES and FUNNEL_STAGES.index(event_stage) >= target_rank:
                funnel_candidate_ids.add(str(event.get("candidate_id")))

    filtered = []
    for candidate in candidates:
        lifecycle_status = str(candidate.get("lifecycle_status", "active"))
        if lifecycle_filter != "all" and lifecycle_status != lifecycle_filter:
            continue
        if funnel_candidate_ids is not None and str(candidate.get("id")) not in funnel_candidate_ids:
            # Старые записи до введения истории также участвуют в накопительной воронке.
            if funnel_vacancy_id and str(candidate.get("vacancy_id", "")) != funnel_vacancy_id:
                continue
            legacy_stage = "recommended" if candidate.get("status") == "green" else "scored" if candidate.get("status") == "yellow" else "new"
            if FUNNEL_STAGES.index(legacy_stage) < FUNNEL_STAGES.index(funnel_stage):
                continue
        if query and query not in str(candidate.get("name", "")).lower() and query not in " ".join(candidate.get("skills", [])) .lower():
            continue
        if status != "all" and str(candidate.get("status", "yellow")) != status:
            continue
        if position != "all" and candidate.get("position") != position:
            continue
        if score_filter == ">70" and candidate.get("score", 0) <= 70:
            continue
        if score_filter == "40-70" and not 40 <= candidate.get("score", 0) <= 70:
            continue
        if score_filter == "<40" and candidate.get("score", 0) >= 40:
            continue
        if date_filter == "today" and not str(candidate.get("timestamp", "")).startswith(local_now().strftime("%Y-%m-%d")):
            continue
        filtered.append(candidate)

    page = max(1, int(request.args.get("page", 1)))
    per_page = 6
    total_pages = max(1, (len(filtered) + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    page_candidates = filtered[start:start + per_page]

    positions = sorted({candidate.get("position") for candidate in candidates if candidate.get("position")})
    vacancies = _available_vacancies()
    return render_template(
        "candidates.html",
        candidates=page_candidates,
        page=page,
        total_pages=total_pages,
        query=query,
        selected_status=status,
        selected_position=position,
        selected_score=score_filter,
        selected_date=date_filter,
        selected_lifecycle=lifecycle_filter,
        positions=positions,
        vacancies=vacancies,
        initial_vacancy_id=vacancies[0]["id"] if vacancies else "VAC_001",
        page_script="manual_resume.js",
    )


@main_bp.route("/candidate/<candidate_id>")
def candidate_detail(candidate_id: str):
    """Страница карточки кандидата."""
    candidates = [_candidate_view_model(item) for item in storage.list_candidates()]
    candidate = next((item for item in candidates if str(item.get("id")) == candidate_id), None)
    if not candidate:
        abort(404)

    vacancy_id = str(candidate.get("vacancy_id", "")).strip() or "VAC_001"
    candidate["vacancy_id"] = vacancy_id
    vacancy = vacancy_service.get_by_id(vacancy_id) if vacancy_id else None
    candidate["vacancy_title"] = str(vacancy.get("title", vacancy.get("name", ""))) if vacancy else "Не указана"
    candidate_relation = candidate_vacancy_storage.find(str(candidate.get("id", candidate_id)), vacancy_id)
    current_stage = str(candidate_relation.get("status", "in_review")) if candidate_relation else "in_review"

    criteria_items = candidate['scoring_explanation']['criteria_items']
    from src.services.score_explanation import archive_explanation
    interviews = interview_service.list_by_candidate(str(candidate.get("id", candidate_id)))
    feedback_items = feedback_service.list_by_candidate(str(candidate.get("id", candidate_id)))
    return render_template(
        "candidate_detail.html",
        candidate=candidate,
        criteria_items=criteria_items,
        interviews=interviews,
        feedback_items=feedback_items,
        criteria=scoring_service.criteria,
        scoring_service=scoring_service,
        vacancy=vacancy,
        current_stage=current_stage,
        page_script="candidate_detail.js",
        archive_explanation=archive_explanation(candidate),
    )


@main_bp.route("/interviews")
def interviews_page():
    """Страница календаря интервью с фильтрами."""
    status = request.args.get("status", "all").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    interviews = interview_service.list_all()
    filtered: List[Dict[str, Any]] = []

    for item in interviews:
        item_status = str(item.get("status", "scheduled"))
        item_date = str(item.get("date", ""))

        if status != "all" and item_status != status:
            continue
        if date_from and item_date and item_date < date_from:
            continue
        if date_to and item_date and item_date > date_to:
            continue
        filtered.append(item)

    stats = {
        "total": len(interviews),
        "scheduled": sum(1 for item in interviews if str(item.get("status", "scheduled")) == "scheduled"),
        "completed": sum(1 for item in interviews if str(item.get("status", "scheduled")) == "completed"),
        "cancelled": sum(1 for item in interviews if str(item.get("status", "scheduled")) == "cancelled"),
    }

    return render_template(
        "interviews.html",
        interviews=filtered,
        selected_status=status,
        selected_date_from=date_from,
        selected_date_to=date_to,
        stats=stats,
        page_script="interviews.js",
    )


@main_bp.route("/chat")
def chat_page():
    """Страница чат-ассистента."""
    candidates = [_candidate_view_model(item) for item in storage.list_candidates()]
    requested_id = request.args.get("candidate_id", "").strip()
    candidate = next((item for item in candidates if str(item.get("id")) == requested_id), None) if requested_id else None
    return render_template("chat.html", candidate=candidate, page_script="chat.js")


@main_bp.route("/api/chat", methods=["POST"])
@transactional_request
def chat_api():
    """Возвращает ответ модели, основанный на данных SmartHR и RAG-контексте."""
    payload = request.get_json(silent=True) or {}

    message_text = str(payload.get("message") or "").strip()
    candidate_id = str(payload.get("candidate_id") or "").strip() or None
    vacancy_id = str(payload.get("vacancy_id") or "").strip() or None

    try:
        conversation_id = str(payload.get("conversation_id") or "").strip() or None
        conversation = None
        if conversation_id:
            conversation = _chat_history_service().conversation(conversation_id)
            candidate_id = candidate_id or conversation.get("candidate_id")
            vacancy_id = vacancy_id or conversation.get("vacancy_id")
        scenario = ChatService.scenario_for_message(message_text, conversation["messages"] if conversation else (payload.get("history") if isinstance(payload.get("history"), list) else []))
        if scenario not in {"document_search", "candidate_list", "greeting"}:
            from src.chat.resolution import resolve_candidate
            selected = resolve_candidate(message_text, storage.list_candidates())
            if selected:
                if str(candidate_id) != str(selected["id"]):
                    vacancy_id = selected.get("vacancy_id")
                candidate_id = str(selected["id"])
        if candidate_id and not storage.get_candidate(candidate_id):
            raise ValueError("Кандидат не найден. Начните новый диалог или выберите другого кандидата.")
        if vacancy_id and not vacancy_service.get_by_id(vacancy_id):
            raise ValueError("Вакансия не найдена. Выберите существующую вакансию.")
        result = _chat_service().ask(
            message_text,
            candidate_id=candidate_id,
            vacancy_id=vacancy_id,
            history=conversation["messages"] if conversation else (payload.get("history") if isinstance(payload.get("history"), list) else []),
        )
        exchange = _chat_history_service().record_exchange(
            str(payload.get("conversation_id") or "").strip() or None,
            candidate_id=candidate_id,
            vacancy_id=vacancy_id,
            user_message=message_text, assistant_result=result,
            created_by=str(payload.get("hr_id") or "HR_SYSTEM"),
        )
        selected_candidate = storage.get_candidate(candidate_id) if candidate_id else None
        result["context"] = {
            "candidate": {key: selected_candidate.get(key) for key in ("id", "name", "position")} if selected_candidate else None,
            "vacancy": {key: (vacancy_service.get_by_id(vacancy_id) or {}).get(key) for key in ("id", "title")} if vacancy_id else None,
        }
        result["conversation_id"] = exchange["conversation"]["id"]
        result["message_id"] = exchange["assistant_message"]["id"]

        if result.get("suggested_action"):
            action = dict(result["suggested_action"])
            stored_action = _chat_history_service().create_action(
                result["conversation_id"], result["message_id"], action
            )
            action["id"] = stored_action["id"]
            action["confirmation_token"] = _chat_action_serializer().dumps({"action_id": stored_action["id"]})
            result["suggested_action"] = action

        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503


@main_bp.route("/api/chat/actions/confirm", methods=["POST"])
@transactional_request
def confirm_chat_action():
    """Выполняет ранее предложенное действие только по подписанному подтверждению HR."""
    body = request.get_json(silent=True) or {}
    token = str(body.get("confirmation_token") or "").strip()
    if not token:
        return jsonify({"error": "confirmation_token обязателен"}), 400
    try:
        action = _chat_action_serializer().loads(token, max_age=900)
    except SignatureExpired:
        return jsonify({"error": "Срок подтверждения истёк, запросите действие повторно"}), 400
    except BadSignature:
        return jsonify({"error": "Некорректное подтверждение действия"}), 400

    action_id = str(action.get("action_id") or "")
    stored_action = chat_action_storage.get_by_id(action_id)
    if not stored_action or stored_action.get("status") != "pending":
        return jsonify({"error": "Действие не найдено или уже обработано"}), 409
    action_type = str(stored_action.get("action_type") or "")
    payload = stored_action.get("action_payload") if isinstance(stored_action.get("action_payload"), dict) else {}
    candidate_id = str(payload.get("candidate_id") or "")
    hr_id = str(body.get("hr_id") or "HR_CHAT")
    try:
        if action_type == "change_stage":
            result = candidate_stage_service.transition(
                candidate_id, str(payload.get("vacancy_id") or ""), str(payload.get("stage") or ""),
                changed_by=hr_id, reason="Подтверждено в чат-ассистенте", source="chat",
            )
        elif action_type == "transfer_candidate":
            source_id = str(payload.get("from_vacancy_id") or "")
            target_id = str(payload.get("to_vacancy_id") or "")
            finder = AlternativeVacancyService(storage, vacancy_service, scoring_service, candidate_vacancy_storage)
            alternatives = finder.find_alternatives(candidate_id, source_id, 10)["alternatives"]
            recommendation = next((item for item in alternatives if str(item.get("vacancy_id")) == target_id), None)
            if not recommendation:
                return jsonify({"error": "Рекомендация больше не актуальна"}), 409
            result = candidate_vacancy_service.apply(
                candidate_id, source_id, target_id, "transfer", hr_id,
                "Подтверждено в чат-ассистенте", recommendation,
            )
            _save_transfer_result(candidate_id, target_id, recommendation)
            conversation = chat_conversation_storage.get_by_id(stored_action["conversation_id"])
            if conversation:
                chat_conversation_storage.save({**conversation, "vacancy_id": target_id})
        elif action_type == "archive_candidate":
            result = _retention_service().archive_if_unmatched(candidate_id, source="chat_confirmation")
        else:
            return jsonify({"error": "Действие не поддерживается"}), 400
        _chat_history_service().complete_action(
            action_id, confirmed_by=hr_id, status="confirmed", result=result
        )
        candidate = storage.get_candidate(candidate_id)
        vacancy = vacancy_service.get_by_id(candidate.get("vacancy_id")) if candidate and candidate.get("vacancy_id") else None
        context = {"candidate": {key: candidate.get(key) for key in ("id", "name", "position")} if candidate else None,
                   "vacancy": {key: vacancy.get(key) for key in ("id", "title")} if vacancy else None}
        return jsonify({"confirmed": True, "action": action_type, "result": result, "context": context})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@main_bp.route("/api/chat/conversations", methods=["GET"])
def list_chat_conversations():
    try:
        offset = int(request.args.get("offset", "0"))
        limit = int(request.args.get("limit", "30"))
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Некорректные параметры списка диалогов"}), 400
    rows = chat_conversation_storage.list_summaries(limit=limit + 1, offset=offset)
    has_more = len(rows) > limit
    candidates = {str(item["id"]): item for item in storage.list_candidates()}
    vacancies = {str(item["id"]): item for item in vacancy_service.get_all()}
    for item in rows[:limit]:
        candidate = candidates.get(str(item.get("candidate_id"))) or {}
        vacancy = vacancies.get(str(item.get("vacancy_id"))) or {}
        item["candidate_name"] = candidate.get("name")
        item["vacancy_title"] = vacancy.get("title") or vacancy.get("name")
    return jsonify({"conversations": rows[:limit], "next_offset": offset + limit if has_more else None})


@main_bp.route("/api/chat/conversations/<conversation_id>", methods=["GET"])
def get_chat_conversation(conversation_id: str):
    try:
        conversation = _chat_history_service().conversation(conversation_id)
        candidate = storage.get_candidate(conversation.get("candidate_id")) if conversation.get("candidate_id") else None
        vacancy = vacancy_service.get_by_id(conversation.get("vacancy_id")) if conversation.get("vacancy_id") else None
        conversation["context"] = {
            "candidate": {key: candidate.get(key) for key in ("id", "name", "position")} if candidate else None,
            "vacancy": {key: vacancy.get(key) for key in ("id", "title")} if vacancy else None,
        }
        for message in conversation["messages"]:
            for action in message.get("actions", []):
                if action.get("status") == "pending":
                    action["confirmation_token"] = _chat_action_serializer().dumps({"action_id": action["id"]})
        return jsonify(conversation)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404


@main_bp.route("/api/chat/messages/<int:message_id>/feedback", methods=["POST"])
def save_chat_feedback(message_id: int):
    try:
        return jsonify(_chat_history_service().save_feedback(message_id, request.get_json(silent=True) or {}))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@main_bp.route("/documents")
def documents_page():
    """Страница поиска по документам и RAG."""
    query = request.args.get("q", "").strip()
    documents = DOCUMENTS
    search_results = []

    if query:
        rag_result = rag_pipeline.ask(query, top_k=5)
        for hit in rag_result.hits:
            document = next((item for item in documents if item["id"] == hit.chunk.doc_id), None)
            if not document:
                continue
            search_results.append(
                {
                    "id": document["id"],
                    "title": document["title"],
                    "category": document["category"],
                    "score": round(hit.score, 3),
                    "excerpt": _highlight_text(hit.chunk.text[:260], query),
                }
            )

    return render_template("documents.html", documents=documents, query=query, search_results=search_results, error=request.args.get("error"), uploaded=request.args.get("uploaded"), updated=request.args.get("updated"))


def _remove_document_file(path):
    """Windows scanners may briefly hold a just-written file during rollback."""
    for attempt in range(5):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError as exc:
            if getattr(exc, "winerror", None) not in {32, 33} or attempt == 4:
                raise
            time.sleep(0.05)


def _save_document_file(file):
    if not file or not file.filename:
        raise ValueError("Выберите файл.")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".pdf", ".docx", ".txt", ".md"}:
        raise ValueError("Поддерживаются PDF, DOCX, TXT и MD.")
    name = Path(file.filename.replace("\\", "/")).name
    if not name or name in {".", ".."}:
        raise ValueError("Некорректное имя файла.")
    UPLOAD_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DOCS_DIR / (uuid4().hex + suffix)
    try:
        file.save(target)
        if target.stat().st_size > MAX_CONTENT_LENGTH:
            raise ValueError("Размер документа превышает 16 МБ.")
        with target.open("rb") as stream:
            header = stream.read(4)
        if suffix == ".pdf" and not header.startswith(b"%PDF"):
            raise ValueError("Файл не является корректным PDF.")
        if suffix == ".docx" and not header.startswith(b"PK"):
            raise ValueError("Файл не является корректным DOCX.")
        if not load_document(target).text.strip():
            raise ValueError("В документе нет доступного текста. Для сканов требуется распознавание текста.")
        target.with_suffix(".json").write_text(json.dumps({"name":name}, ensure_ascii=False), encoding="utf-8")
        return target
    except Exception:
        _remove_document_file(target)
        _remove_document_file(target.with_suffix(".json"))
        raise


def _refresh_document_library(state=None):
    global rag_pipeline, DOCUMENTS
    documents = _library_documents(state)
    replacement = RagPipeline(backend=rag_pipeline.requested_backend)
    replacement.build_index(documents)
    cards = _load_documents(documents)
    if state is not None:
        UPLOAD_DOCS_DIR.mkdir(parents=True, exist_ok=True)
        temporary = UPLOAD_DOCS_DIR / ("library_" + uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(UPLOAD_DOCS_DIR / "library.json")
        finally:
            temporary.unlink(missing_ok=True)
    rag_pipeline, DOCUMENTS = replacement, cards


def _document_error(exc):
    return str(exc) if isinstance(exc, ValueError) else "Не удалось обновить библиотеку. Проверьте файл и повторите действие."


@main_bp.route("/documents/upload", methods=["POST"])
def upload_document():
    target = None
    try:
        with DOCUMENT_LOCK:
            target = _save_document_file(request.files.get("file"))
            _refresh_document_library()
        return redirect(url_for("main.documents_page", uploaded="1"))
    except Exception as exc:
        if target:
            _remove_document_file(target)
            _remove_document_file(target.with_suffix(".json"))
        return redirect(url_for("main.documents_page", error=_document_error(exc)))


@main_bp.route("/documents/<document_id>/rename", methods=["POST"])
def rename_document(document_id):
    title = str(request.form.get("title") or "").strip()
    if not title or len(title) > 200:
        return redirect(url_for("main.read_document", document_id=document_id, error="Укажите название от 1 до 200 символов."))
    try:
        with DOCUMENT_LOCK:
            if not any(doc.id == document_id for doc in _library_documents()):
                abort(404)
            state = _document_catalog_state()
            state[document_id] = {**state.get(document_id, {}), "title": title}
            _refresh_document_library(state)
        return redirect(url_for("main.read_document", document_id=document_id, updated="1"))
    except (ValueError, OSError, RuntimeError) as exc:
        return redirect(url_for("main.read_document", document_id=document_id, error=_document_error(exc)))


@main_bp.route("/documents/<document_id>/replace", methods=["POST"])
def replace_document(document_id):
    target = None
    try:
        with DOCUMENT_LOCK:
            current = next((doc for doc in _library_documents() if doc.id == document_id), None)
            if not current:
                abort(404)
            target = _save_document_file(request.files.get("file"))
            state = _document_catalog_state()
            entry = state.get(document_id, {})
            state[document_id] = {**entry, "title": current.title, "replacement": target.stem,
                                  "versions": [*entry.get("versions", []), target.stem]}
            _refresh_document_library(state)
        return redirect(url_for("main.read_document", document_id=document_id, updated="1"))
    except Exception as exc:
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            raise
        if target:
            _remove_document_file(target)
            _remove_document_file(target.with_suffix(".json"))
        return redirect(url_for("main.read_document", document_id=document_id, error=_document_error(exc)))


@main_bp.route("/documents/<document_id>/delete", methods=["POST"])
def delete_document(document_id):
    if request.form.get("confirm") != "yes":
        return redirect(url_for("main.read_document", document_id=document_id, error="Подтвердите удаление документа."))
    try:
        with DOCUMENT_LOCK:
            if not any(doc.id == document_id for doc in _library_documents()):
                abort(404)
            state = _document_catalog_state()
            state[document_id] = {**state.get(document_id, {}), "deleted": True}
            # Исходники и прежние версии сохраняются, но исключаются из каталога и поиска.
            _refresh_document_library(state)
    except (ValueError, OSError, RuntimeError) as exc:
        return redirect(url_for("main.read_document", document_id=document_id, error=_document_error(exc)))
    return redirect(url_for("main.documents_page", updated="1"))


@main_bp.route("/documents/<document_id>")
def read_document(document_id):
    document = next((doc for doc in _library_documents() if doc.id == document_id), None)
    if not document:
        abort(404)
    return render_template("document.html", document=document, error=request.args.get("error"), updated=request.args.get("updated"))


@main_bp.route("/documents/<document_id>/download")
def download_document(document_id):
    document = next((doc for doc in _library_documents() if doc.id == document_id), None)
    if not document:
        abort(404)
    return send_file(document.metadata["path"], as_attachment=True, download_name=document.source)


@main_bp.route("/analytics")
def analytics_page():
    """Страница аналитики найма."""
    vacancy_id = request.args.get("vacancy_id", "").strip() or None
    date_from = request.args.get("date_from", "").strip() or None
    date_to = request.args.get("date_to", "").strip() or None
    group_by = request.args.get("group_by", "applications").strip()
    error = None
    try:
        funnel_data = funnel_service.get_funnel(vacancy_id, date_from, date_to, group_by)
    except ValueError as exc:
        error = str(exc)
        funnel_data = funnel_service.get_funnel()

    funnel = [{**item, "value": item["count"]} for item in funnel_data["stages"]]

    return render_template(
        "analytics.html",
        error=error,
        stats={
            "Было кандидатов": funnel_data["initial_count"],
            "Осталось в процессе": funnel_data["current_count"],
            "Нанято": funnel_data["hired_count"],
            "Конверсия в найм": f"{funnel_data['overall_conversion']}%",
        },
        funnel=funnel,
        funnel_data=funnel_data,
        vacancies=_available_vacancies(),
        selected_vacancy_id=vacancy_id or "",
        selected_group_by=group_by,
        selected_date_from=date_from or "",
        selected_date_to=date_to or "",
        page_script="charts.js",
    )


@main_bp.route("/vacancies")
def vacancies_page():
    """Страница списка вакансий."""
    vacancies = vacancy_service.get_all()
    candidates = storage.list_candidates()
    templates = template_service.get_all()

    enriched = []
    for vacancy in vacancies:
        vacancy_id = str(vacancy.get("id", ""))
        count = sum(1 for candidate in candidates if str(candidate.get("vacancy_id", "")) == vacancy_id)
        enriched.append({**vacancy, "candidate_count": count})

    return render_template(
        "vacancies.html",
        vacancies=enriched,
        templates=templates,
        categories=VACANCY_CATEGORIES,
        default_weights=template_service.get_default_weights(),
        active_tab="vacancies",
        page_scripts=["vacancies.js", "templates.js"],
    )


@main_bp.route("/vacancies/new")
def vacancy_new_page():
    """Страница создания вакансии."""
    template_id = request.args.get("template_id", "").strip()
    template = template_service.get_by_id(template_id) if template_id else None
    return render_template(
        "vacancy_edit.html",
        vacancy=_prefill_vacancy_from_template(template),
        categories=VACANCY_CATEGORIES,
        default_weights=vacancy_service.get_default_weights(),
        template_id=template_id or None,
        page_script="vacancy_edit.js",
    )


@main_bp.route("/vacancies/<vacancy_id>/edit")
def vacancy_edit_page(vacancy_id: str):
    """Страница редактирования вакансии."""
    vacancy = vacancy_service.get_by_id(vacancy_id)
    if not vacancy:
        return render_template("vacancy_edit.html", vacancy=None, categories=[], default_weights=vacancy_service.get_default_weights(), page_script="vacancy_edit.js"), 404

    return render_template(
        "vacancy_edit.html",
        vacancy=vacancy,
        categories=VACANCY_CATEGORIES,
        default_weights=vacancy_service.get_default_weights(),
        template_id=vacancy.get("template_id"),
        page_script="vacancy_edit.js",
    )


@main_bp.route("/templates")
def templates_page():
    """Страница управления шаблонами вакансий."""
    vacancies = vacancy_service.get_all()
    candidates = storage.list_candidates()
    templates = template_service.get_all()

    enriched = []
    for vacancy in vacancies:
        vacancy_id = str(vacancy.get("id", ""))
        count = sum(1 for candidate in candidates if str(candidate.get("vacancy_id", "")) == vacancy_id)
        enriched.append({**vacancy, "candidate_count": count})

    return render_template(
        "vacancies.html",
        vacancies=enriched,
        templates=templates,
        categories=VACANCY_CATEGORIES,
        default_weights=template_service.get_default_weights(),
        active_tab="templates",
        page_scripts=["vacancies.js", "templates.js"],
    )


@main_bp.route("/api/vacancies", methods=["GET"])
def list_vacancies_api():
    """Возвращает список вакансий в формате JSON."""
    return jsonify(vacancy_service.get_all())


@main_bp.route("/api/vacancies/<vacancy_id>", methods=["GET"])
def get_vacancy_api(vacancy_id: str):
    """Возвращает одну вакансию по ID."""
    vacancy = vacancy_service.get_by_id(vacancy_id)
    if not vacancy:
        return jsonify({"error": "Вакансия не найдена"}), 404
    return jsonify(vacancy)


@main_bp.route("/api/vacancies", methods=["POST"])
def create_vacancy_api():
    """Создаёт новую вакансию."""
    body = request.get_json(silent=True) or {}
    try:
        template_id = str(body.get("template_id", "")).strip()
        payload = body
        if template_id:
            template = template_service.get_by_id(template_id)
            if not template:
                return jsonify({"error": "Шаблон не найден"}), 404
            if template:
                payload = {
                    **template,
                    **body,
                    "template_id": template_id,
                    "critical_requirements": body.get("critical_requirements") or template.get("critical_requirements", []),
                    "skills": body.get("skills") or template.get("skills", []),
                    "weights": body.get("weights") or template.get("weights", vacancy_service.get_default_weights()),
                }

        created = vacancy_service.create(payload)
        if template_id:
            template_service.increment_usage(template_id)
        recheck = _retention_service().reevaluate_archived()
        return jsonify({**created, "archive_recheck": recheck}), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Ошибка создания вакансии: {exc}"}), 500


@main_bp.route("/api/vacancies/<vacancy_id>", methods=["PUT"])
def update_vacancy_api(vacancy_id: str):
    """Обновляет существующую вакансию."""
    body = request.get_json(silent=True) or {}
    try:
        updated = vacancy_service.update(vacancy_id, body)
        return jsonify(updated)
    except ValueError as exc:
        message = str(exc)
        status = 404 if "не найдена" in message else 400
        return jsonify({"error": message}), status
    except Exception as exc:
        return jsonify({"error": f"Ошибка обновления вакансии: {exc}"}), 500


@main_bp.route("/api/vacancies/<vacancy_id>", methods=["DELETE"])
def delete_vacancy_api(vacancy_id: str):
    """Удаляет вакансию по ID."""
    try:
        vacancy_service.delete(vacancy_id)
        return jsonify({"ok": True})
    except ValueError as exc:
        message = str(exc)
        status = 404 if "не найдена" in message else 400
        return jsonify({"error": message}), status
    except IntegrityError:
        return jsonify({"error": "Вакансия связана с кандидатами или историей. Закройте её вместо удаления."}), 409
    except Exception as exc:
        return jsonify({"error": f"Ошибка удаления вакансии: {exc}"}), 500


@main_bp.route("/api/templates", methods=["GET"])
def list_templates_api():
    """Возвращает список шаблонов в формате JSON."""
    return jsonify(template_service.get_all())


@main_bp.route("/api/templates/<template_id>", methods=["GET"])
def get_template_api(template_id: str):
    """Возвращает шаблон по ID."""
    template = template_service.get_by_id(template_id)
    if not template:
        return jsonify({"error": "Шаблон не найден"}), 404
    return jsonify(template)


@main_bp.route("/api/templates", methods=["POST"])
def create_template_api():
    """Создаёт шаблон вакансии."""
    body = request.get_json(silent=True) or {}
    try:
        created = template_service.create(body)
        return jsonify(created), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Ошибка создания шаблона: {exc}"}), 500


@main_bp.route("/api/templates/<template_id>", methods=["PUT"])
def update_template_api(template_id: str):
    """Обновляет шаблон вакансии."""
    body = request.get_json(silent=True) or {}
    try:
        updated = template_service.update(template_id, body)
        return jsonify(updated)
    except ValueError as exc:
        message = str(exc)
        status = 404 if "не найден" in message else 400
        return jsonify({"error": message}), status
    except Exception as exc:
        return jsonify({"error": f"Ошибка обновления шаблона: {exc}"}), 500


@main_bp.route("/api/templates/<template_id>", methods=["DELETE"])
def delete_template_api(template_id: str):
    """Удаляет шаблон вакансии."""
    try:
        template_service.delete(template_id)
        return jsonify({"ok": True})
    except ValueError as exc:
        message = str(exc)
        status = 404 if "не найден" in message else 400
        return jsonify({"error": message}), status
    except Exception as exc:
        return jsonify({"error": f"Ошибка удаления шаблона: {exc}"}), 500


@main_bp.route("/api/parse_requirements", methods=["POST"])
def parse_requirements():
    body = request.get_json(silent=True)
    if not body or not body.get("text", "").strip():
        return jsonify({"error": "Укажите поле 'text' с текстом вакансии"}), 400

    requirements = extract_requirements(body["text"])
    return jsonify({"requirements": requirements})


@main_bp.route("/api/score", methods=["POST"])
def score_candidate():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Некорректный JSON"}), 400

    candidate_text = body.get("candidate_text", "").strip()
    critical_requirements = body.get("critical_requirements", [])
    weights = body.get("weights", {})
    vacancy_id = str(body.get("vacancy_id", "")).strip()

    if isinstance(weights, str):
        try:
            weights = json.loads(weights)
        except Exception:
            weights = {}

    if not candidate_text:
        return jsonify({"error": "Текст резюме пустой"}), 400

    # Веса всегда берутся из вакансии, чтобы оценка была вакансий-специфичной.
    if vacancy_id:
        weights = vacancy_service.weights_for_vacancy(vacancy_id)
    elif isinstance(weights, dict) and weights:
        # Обратная совместимость для старых вызовов без vacancy_id.
        weights = vacancy_service.sanitize_weights(weights)
    else:
        weights = vacancy_service.get_default_weights()

    vacancy = vacancy_service.get_by_id(vacancy_id) if vacancy_id else None
    if vacancy_id and not vacancy:
        return jsonify({"error": "Вакансия не найдена"}), 404
    result = scoring_service.score_candidate(candidate_text, critical_requirements, weights, vacancy=vacancy)
    result["used_weights"] = weights
    result["vacancy_id"] = vacancy_id or None
    if result.get("critical_failures"):
        result["filter_result"] = True
        result["recommendation"] = (
            "Рекомендуем запросить у кандидата документы, подтверждающие наличие этих требований."
        )
    else:
        result["filter_result"] = False
        result["recommendation"] = ""

    return jsonify(result)


@main_bp.route("/api/upload", methods=["POST"])
def upload_file():
    if request.content_type and "application/json" in request.content_type:
        body = request.get_json(silent=True) or {}
        text = (body.get("text") or "").strip()
        if not text:
            return jsonify({"error": "Текст резюме пустой"}), 400
        filename = body.get("filename") or "resume.txt"
        return jsonify({"text": text, "filename": filename})

    if "file" in request.files:
        file = request.files["file"]
        if not file.filename:
            return jsonify({"error": "Имя файла пустое"}), 400

        filename = file.filename.lower()

        try:
            if filename.endswith(".pdf"):
                text = parse_pdf(file.stream)
            elif filename.endswith(".docx"):
                text = parse_docx(file.stream)
            elif filename.endswith(".txt"):
                text = file.stream.read().decode("utf-8-sig")
            else:
                return jsonify({"error": "Поддерживаются форматы: TXT, PDF, DOCX"}), 400

            if not text.strip():
                return jsonify({"error": "Не удалось извлечь текст из файла"}), 400

            return jsonify({"text": text, "filename": file.filename})

        except Exception:
            current_app.logger.exception("Resume file parsing failed")
            return jsonify({"error": "Не удалось прочитать файл. Проверьте формат и целостность. TXT должен быть в UTF-8."}), 400

    if request.form.get("text"):
        text = request.form.get("text", "").strip()
        return jsonify({"text": text, "filename": request.form.get("filename", "resume.txt")})

    return jsonify({"error": "Файл не найден"}), 400


@main_bp.route("/api/parse_hh", methods=["POST"])
def parse_hh():
    body = request.get_json(silent=True)
    if not body or not body.get("url", "").strip():
        return jsonify({"error": "Укажите поле 'url'"}), 400

    url = body["url"].strip()
    try:
        text = parse_hh_url(url)
        if not text.strip():
            return jsonify({"error": "Не удалось извлечь текст"}), 400
        return jsonify({"text": text, "source": url})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        import requests
        if isinstance(exc, requests.Timeout):
            return jsonify({"error": "hh.ru не ответил вовремя. Повторите попытку позже."}), 504
        current_app.logger.exception("HH resume import failed")
        return jsonify({"error": "Не удалось получить резюме с hh.ru. Проверьте доступность ссылки."}), 502


@main_bp.route("/api/health", methods=["GET"])
def health_check():
    from src.services.health_service import readiness
    payload, status = readiness()
    return jsonify(payload), status


@main_bp.route("/api/candidates", methods=["GET"])
def list_candidates():
    return jsonify(storage.list_candidates())


@main_bp.route("/api/candidates/manual", methods=["POST"])
@transactional_request
def create_candidate_manual():
    """Создаёт кандидата из ручного ввода и запускает скоринг."""
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    position = str(body.get("position", "")).strip()
    resume_text = str(body.get("resume_text", "")).strip()
    vacancy_id = str(body.get("vacancy_id", "VAC_001")).strip() or "VAC_001"

    if not name or not position or not resume_text:
        return jsonify({"error": "Поля name, position и resume_text обязательны"}), 400

    vacancy = vacancy_service.get_by_id(vacancy_id)
    if not vacancy:
        return jsonify({"error": "Вакансия не найдена"}), 404
    critical_requirements = body.get("critical_requirements") or (vacancy.get("critical_requirements", []) if vacancy else [])
    if isinstance(critical_requirements, str):
        critical_requirements = [item.strip() for item in critical_requirements.split("\n") if item.strip()]
    weights = vacancy_service.weights_for_vacancy(vacancy_id)

    try:
        score_result = scoring_service.score_candidate(resume_text, critical_requirements, weights, vacancy=vacancy)
        candidate = _candidate_for_storage(
            {
                "id": f"CV_{str(uuid.uuid4())[:8]}",
                "name": name,
                "position": position,
                "resume_text": resume_text,
            },
            score_result,
            vacancy_id,
        )
        storage.save_candidate(candidate)
        _save_score_history(candidate["id"], vacancy_id, score_result, "manual")
        candidate_stage_service.register_scoring(candidate["id"], vacancy_id, score_result, source="manual")
        retention = _retention_service().archive_if_unmatched(candidate["id"], source="automatic_scoring")
        candidate = storage.get_candidate(candidate["id"]) or candidate
        candidate["retention_result"] = {
            "archived": retention["archived"], "reason": retention.get("reason"),
            "matching_vacancies": len(retention.get("matches", [])),
        }
        return jsonify(candidate), 201
    except Exception as exc:
        return jsonify({"error": f"Ошибка создания кандидата: {exc}"}), 500


@main_bp.route("/api/candidates/<candidate_id>/alternative-vacancies", methods=["GET"])
def alternative_vacancies(candidate_id: str):
    """Ищет активные вакансии, которым кандидат соответствует лучше."""
    current_vacancy_id = str(request.args.get("current_vacancy_id", "")).strip()
    try:
        limit = int(request.args.get("limit", 3))
        service = AlternativeVacancyService(storage, vacancy_service, scoring_service, candidate_vacancy_storage)
        return jsonify(service.find_alternatives(candidate_id, current_vacancy_id, limit))
    except ValueError as exc:
        message = str(exc)
        status = 404 if "не найден" in message else 400
        return jsonify({"error": message}), status
    except Exception as exc:
        return jsonify({"error": f"Ошибка поиска альтернатив: {exc}"}), 500


@main_bp.route("/api/candidates/<candidate_id>/retention-check", methods=["POST"])
def retention_check(candidate_id: str):
    """Проверяет все активные вакансии и архивирует кандидата только при отсутствии совпадений."""
    try:
        return jsonify(_retention_service().archive_if_unmatched(candidate_id, source="hr_request"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Ошибка проверки кандидата: {exc}"}), 500


@main_bp.route("/api/candidates/<candidate_id>/restore", methods=["POST"])
def restore_candidate(candidate_id: str):
    """Возвращает кандидата из архива в активную базу."""
    try:
        return jsonify(_retention_service().restore(candidate_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404


@main_bp.route("/api/candidates/archived/reevaluate", methods=["POST"])
def reevaluate_archived_candidates():
    """Повторно проверяет архив после изменения набора вакансий."""
    return jsonify(_retention_service().reevaluate_archived())


@main_bp.route("/api/analytics/funnel", methods=["GET"])
def funnel_analytics_api():
    """Возвращает накопительную воронку с фильтрами."""
    try:
        result = funnel_service.get_funnel(
            vacancy_id=request.args.get("vacancy_id", "").strip() or None,
            date_from=request.args.get("date_from", "").strip() or None,
            date_to=request.args.get("date_to", "").strip() or None,
            group_by=request.args.get("group_by", "applications").strip(),
        )
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@main_bp.route("/api/candidates/<candidate_id>/stage", methods=["POST"])
@transactional_request
def update_candidate_stage(candidate_id: str):
    """Фиксирует решение HR и переход рассмотрения на следующий этап."""
    body = request.get_json(silent=True) or {}
    vacancy_id = str(body.get("vacancy_id", "")).strip()
    stage = str(body.get("stage", "")).strip()
    if not vacancy_id or not stage:
        return jsonify({"error": "vacancy_id и stage обязательны"}), 400
    if not storage.get_candidate(candidate_id):
        return jsonify({"error": "Кандидат не найден"}), 404
    if not vacancy_service.get_by_id(vacancy_id):
        return jsonify({"error": "Вакансия не найдена"}), 404
    try:
        record = candidate_stage_service.transition(
            candidate_id, vacancy_id, stage,
            changed_by=str(body.get("hr_id", "HR_SYSTEM")),
            reason=str(body.get("reason", "Решение HR")), source="hr",
        )
        return jsonify(record)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


def _save_transfer_result(candidate_id, target_id, recommendation):
    candidate = storage.get_candidate(candidate_id)
    if not candidate:
        raise ValueError("Кандидат не найден")
    from src.services.scoring import get_status_decision
    total = recommendation["total"]
    candidate.update({
        "vacancy_id": target_id, "total": total, "score": total,
        "status": get_status_decision(total)[0], "scores": recommendation.get("scores", {}),
        "model_probability": recommendation.get("model_probability"),
        "model_version": recommendation.get("model_version"),
        "used_weights": recommendation.get("used_weights", {}),
        "evidence": recommendation.get("evidence", {}),
        "comments": recommendation.get("comments", {}),
        "critical_failures": recommendation.get("critical_failures", []),
        "score_status": recommendation.get("score_status", "calculated"),
        "summary": recommendation.get("summary"), "requirement_checks": recommendation.get("requirement_checks", []),
    })
    storage.save_candidate(candidate)
    _save_score_history(candidate_id, target_id, recommendation, "transfer")


@main_bp.route("/api/candidates/<candidate_id>/vacancies", methods=["POST"])
@transactional_request
def apply_candidate_to_vacancy(candidate_id: str):
    """Добавляет кандидата к альтернативной вакансии или переносит его."""
    body = request.get_json(silent=True) or {}
    from_vacancy_id = str(body.get("from_vacancy_id", "")).strip()
    to_vacancy_id = str(body.get("to_vacancy_id", "")).strip()
    mode = str(body.get("mode", "add")).strip()
    hr_id = str(body.get("hr_id", "")).strip()
    comment = str(body.get("comment", "")).strip()
    if not vacancy_service.get_by_id(to_vacancy_id):
        return jsonify({"error": "Целевая вакансия не найдена"}), 404
    try:
        finder = AlternativeVacancyService(storage, vacancy_service, scoring_service, candidate_vacancy_storage)
        alternatives = finder.find_alternatives(candidate_id, from_vacancy_id, 10)["alternatives"]
        recommendation = next((item for item in alternatives if item["vacancy_id"] == to_vacancy_id), None)
        if not recommendation:
            return jsonify({"error": "Целевая вакансия не является актуальной рекомендацией"}), 400
        result = candidate_vacancy_service.apply(
            candidate_id, from_vacancy_id, to_vacancy_id, mode, hr_id, comment, recommendation
        )
        if mode == "transfer":
            _save_transfer_result(candidate_id, to_vacancy_id, recommendation)
        return jsonify(result), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Ошибка переноса кандидата: {exc}"}), 500


@main_bp.route("/api/interviews", methods=["GET"])
def list_interviews():
    """Возвращает список всех интервью."""
    return jsonify(interview_service.list_all())


@main_bp.route("/api/interviews/<candidate_id>", methods=["GET"])
def list_candidate_interviews(candidate_id: str):
    """Возвращает интервью для конкретного кандидата."""
    return jsonify(interview_service.list_by_candidate(candidate_id))


def _sync_interview_stage(record, hr_id="HR_SYSTEM"):
    candidate_id, vacancy_id = str(record["candidate_id"]), str(record["vacancy_id"])
    current = candidate_vacancy_storage.find(candidate_id, vacancy_id)
    current_status = (current or {}).get("status")
    if current_status in {"offer", "hired", "rejected", "archived", "transferred", "withdrawn", "rejected_all"}:
        return
    interviews = [item for item in interview_service.list_by_candidate(candidate_id) if str(item.get("vacancy_id")) == vacancy_id]
    if any(item.get("status") == "scheduled" for item in interviews):
        target = "interview"
    elif any(item.get("status") == "completed" for item in interviews):
        target = "interview_completed"
    elif current_status in {"interview", "interview_completed"}:
        target = "in_review"
    else:
        return
    candidate_stage_service.transition(candidate_id, vacancy_id, target, changed_by=hr_id,
                                       reason="Обновление календаря интервью", source="interview")


def _validate_interview_application(record):
    """Do not create an active interview with no eligible candidate/application."""
    candidate_id, vacancy_id = str(record.get("candidate_id", "")), str(record.get("vacancy_id", ""))
    candidate = storage.get_candidate(candidate_id)
    if not candidate:
        raise ValueError("Кандидат не найден")
    vacancy = vacancy_service.get_by_id(vacancy_id)
    if not vacancy:
        raise ValueError("Вакансия не найдена")
    if record.get("status", "scheduled") == "cancelled":
        return
    if candidate.get("lifecycle_status", "active") != "active":
        raise ValueError("Сначала восстановите кандидата из архива")
    if str(vacancy.get("status", "active")).casefold() not in {"active", "активна"}:
        raise ValueError("Нельзя назначить интервью по неактивной вакансии")
    relation = candidate_vacancy_storage.find(candidate_id, vacancy_id)
    if relation and relation.get("status") in {"offer", "hired", *FUNNEL_TERMINAL_STATUSES}:
        raise ValueError("Текущий этап не допускает новое интервью. Сначала явно верните кандидата в работу по вакансии.")


@main_bp.route("/api/interviews", methods=["POST"])
@transactional_request
def create_interview():
    """Создаёт интервью."""
    body = request.get_json(silent=True) or {}
    try:
        _validate_interview_application(body)
        record = interview_service.create(body)
        _sync_interview_stage(record, str(body.get("hr_id") or "HR_SYSTEM"))
        return jsonify(record), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Ошибка сохранения интервью: {exc}"}), 500


@main_bp.route("/api/interviews/<interview_id>", methods=["PUT"])
@transactional_request
def update_interview(interview_id: str):
    """Обновляет данные интервью."""
    body = request.get_json(silent=True) or {}
    try:
        current = next((item for item in interview_service.list_all() if str(item.get("id")) == interview_id), None)
        if current:
            proposed = {**current, **body}
            schedule_changed = bool({"date", "time", "duration", "format"} & body.keys())
            reactivating = body.get("status") == "scheduled" and current.get("status") != "scheduled"
            if proposed.get("status") == "scheduled" and (schedule_changed or reactivating):
                _validate_interview_application(proposed)
        updated = interview_service.update(interview_id, body)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Ошибка обновления интервью: {exc}"}), 500

    if not updated:
        return jsonify({"error": "Интервью не найдено"}), 404
    _sync_interview_stage(updated, str(body.get("hr_id") or "HR_SYSTEM"))
    return jsonify(updated)


@main_bp.route("/api/interviews/<interview_id>", methods=["DELETE"])
@transactional_request
def delete_interview(interview_id: str):
    """Удаляет интервью."""
    record = next((item for item in interview_service.list_all() if str(item.get("id")) == interview_id), None)
    deleted = interview_service.delete(interview_id)
    if not deleted:
        return jsonify({"error": "Интервью не найдено"}), 404
    if record:
        _sync_interview_stage(record)
    return jsonify({"ok": True})


@main_bp.route("/api/feedback/<candidate_id>", methods=["GET"])
def list_feedback(candidate_id: str):
    """Возвращает историю корректировок по кандидату."""
    return jsonify(feedback_service.list_by_candidate(candidate_id))


@main_bp.route("/api/feedback", methods=["POST"])
def create_feedback():
    """Сохраняет корректировку оценок HR-специалистом."""
    body = request.get_json(silent=True) or {}
    if body.get("candidate_id") and not storage.get_candidate(body["candidate_id"]):
        return jsonify({"error": "Кандидат не найден"}), 404
    if body.get("vacancy_id") and not vacancy_service.get_by_id(body["vacancy_id"]):
        return jsonify({"error": "Вакансия не найдена"}), 404
    try:
        record = feedback_service.create(body)
        return jsonify(record), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Ошибка сохранения обратной связи: {exc}"}), 500

@main_bp.route("/api/feedback/decision", methods=["POST"])
def create_feedback_decision():
    """Записывает решение рекрутера: подходит / не подходит.

    Body: {"candidate_id": "...", "vacancy_id": "...", "decision": 1|0, "hr_id": "...", "comment": "..."}
    Пишет в feedback.payload (JSON), схему таблицы не трогает.
    """
    body = request.get_json(silent=True) or {}
    candidate_id = str(body.get("candidate_id", "")).strip()
    vacancy_id = str(body.get("vacancy_id", "")).strip()
    decision_raw = body.get("decision")
    if not candidate_id or not vacancy_id or decision_raw is None:
        return jsonify({"error": "candidate_id, vacancy_id, decision обязательны"}), 400
    try:
        decision = int(decision_raw)
        if decision not in (0, 1):
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "decision должен быть 0 или 1"}), 400

    hr_id = str(body.get("hr_id", "HR_UI")).strip() or "HR_UI"
    comment = str(body.get("comment", "")).strip()

    # Считаем фичи через новую модель, чтобы сохранить контекст решения.
    candidate = next((c for c in storage.list_candidates() if str(c.get("id")) == candidate_id), None)
    vacancy = vacancy_service.get_by_id(vacancy_id)
    if not candidate or not vacancy:
        return jsonify({"error": "Кандидат или вакансия не найдены"}), 404
    model_probability = None
    features = {}
    if candidate and vacancy:
        try:
            score = scoring_service.score_candidate(
                candidate.get("resume_text", ""),
                vacancy.get("critical_requirements", []),
                vacancy.get("weights", {}),
                vacancy=vacancy,
            )
            model_probability = score.get("model_probability")
            features = score.get("features", {})
        except Exception:
            pass

    now = local_now().isoformat(timespec="seconds")
    feedback_id = f"FDB_DEC_{int(local_now().timestamp() * 1000)}"

    record = {
        "id": feedback_id,
        "feedback_id": feedback_id,
        "candidate_id": candidate_id,
        "vacancy_id": vacancy_id,
        "created_at": now,
        "payload": {
            "type": "decision",
            "decision": decision,
            "comment": comment,
            "hr_id": hr_id,
            "model_probability": model_probability,
            "features": features,
            "created_at": now,
        },
    }
    try:
        saved = feedback_storage.create(record)
        return jsonify(saved), 201
    except Exception as exc:
        return jsonify({"error": f"Ошибка сохранения: {exc}"}), 500

@main_bp.route("/api/simulate", methods=["POST"])
@transactional_request
def simulate():
    body = request.get_json(silent=True) or {}
    if not body:
        body = {
            "critical_requirements": request.form.getlist("critical_requirements"),
            "weights": request.form.get("weights", {}),
            "vacancy_id": request.form.get("vacancy_id", "VAC_001"),
        }

    if isinstance(body.get("weights"), str):
        try:
            body["weights"] = json.loads(body["weights"])
        except Exception:
            body["weights"] = {}

    critical_requirements = body.get("critical_requirements", [])
    weights = body.get("weights", {})
    vacancy_id = str(body.get("vacancy_id") or "VAC_001").strip() or "VAC_001"
    if vacancy_id:
        weights = vacancy_service.weights_for_vacancy(vacancy_id)

    demo = random.choice(DEMO_RESUMES)
    vacancy = vacancy_service.get_by_id(vacancy_id) if vacancy_id else None
    if not vacancy:
        return jsonify({"error": "Вакансия не найдена"}), 404
    result = scoring_service.score_candidate(demo["text"], critical_requirements, weights, vacancy=vacancy)

    candidate = {
        "id": "sim_" + str(uuid.uuid4())[:8],
        "name": demo["name"],
        "status": result["status"],
        "decision": result["decision"],
        "total": result["total"],
        "scores": result["scores"],
        "comments": result["comments"],
        "critical_failures": result.get("critical_failures", []),
        "timestamp": local_now().strftime("%Y-%m-%d %H:%M"),
        "position": "Специалист",
        "skills": ["Профильные навыки", "Коммуникация", "Аналитика"],
        "experience": ["3+ года опыта", "Работа в кросс-функциональной команде"],
        "email": "candidate@company.ru",
        "phone": "+7 (999) 000-00-00",
        "vacancy_id": vacancy_id or "VAC_001",
        "resume_text": demo["text"],
        "score_status": result.get("score_status"), "summary": result.get("summary"),
        "requirement_checks": result.get("requirement_checks", []), "missing_fields": result.get("missing_fields", []),
        "model_probability": result.get("model_probability"),
        "model_version": result.get("model_version"),
        "used_weights": result.get("used_weights", {}),
        "evidence": result.get("evidence", {}),
    }
    storage.save_candidate(candidate)
    _save_score_history(candidate["id"], candidate["vacancy_id"], result, "simulation")
    candidate_stage_service.register_scoring(candidate["id"], candidate["vacancy_id"], result, source="simulation")

    return jsonify(candidate), 201

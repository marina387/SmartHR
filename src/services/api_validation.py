"""Validate API boundaries before services or database writes are invoked."""
import json
import math
import re
from datetime import datetime

from flask import current_app, jsonify, request
from werkzeug.exceptions import BadRequest, UnsupportedMediaType


TEXT_FIELDS = {
    "message", "text", "candidate_text", "resume_text", "url", "name", "title", "position",
    "candidate_name", "filename", "description", "category", "status", "stage", "mode",
    "notes", "comment", "reason", "hr_id", "created_by", "format", "date", "time",
    "confirmation_token", "rating", "corrected_answer", "specialization", "experience_required",
    "education_required", "required_education", "english_required", "id", "template_id",
    "from_vacancy_id", "to_vacancy_id",
}
OPTIONAL_IDS = {"candidate_id", "vacancy_id", "conversation_id"}
LIST_FIELDS = {"critical_requirements", "default_requirements", "required_skills", "skills", "soft_skills"}
NUMBER_FIELDS = {"duration", "min_experience", "max_experience", "min_salary", "max_salary"}


def _number(value, field, *, integer=False, minimum=None, maximum=None):
    try:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError
        number = float(value)
        if not math.isfinite(number) or (integer and not number.is_integer()):
            raise ValueError
        if minimum is not None and number < minimum or maximum is not None and number > maximum:
            raise ValueError
    except (ValueError, OverflowError):
        raise BadRequest(f"Поле {field}: недопустимое числовое значение") from None


def validate_payload(body):
    for key in TEXT_FIELDS & body.keys():
        if not isinstance(body[key], str):
            raise BadRequest(f"Поле {key} должно быть строкой")
    for key in OPTIONAL_IDS & body.keys():
        if body[key] is not None and not isinstance(body[key], str):
            raise BadRequest(f"Поле {key} должно быть строкой или null")
    for key, pattern, date_format in (("date", r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"),
                                       ("time", r"\d{2}:\d{2}", "%H:%M")):
        if key in body:
            try:
                if not re.fullmatch(pattern, body[key]):
                    raise ValueError
                datetime.strptime(body[key], date_format)
            except ValueError:
                raise BadRequest(f"Поле {key}: некорректная дата или время") from None
    for key in LIST_FIELDS & body.keys():
        value = body[key]
        if not isinstance(value, str) and not (isinstance(value, list) and all(isinstance(item, str) for item in value)):
            raise BadRequest(f"Поле {key} должно быть строкой или списком строк")
    for key in NUMBER_FIELDS & body.keys():
        _number(body[key], key, integer=key == "duration", minimum=1 if key == "duration" else 0,
                maximum=1440 if key == "duration" else None)
    for low, high in (("min_experience", "max_experience"), ("min_salary", "max_salary")):
        if low in body and high in body and float(body[high]) and float(body[low]) > float(body[high]):
            raise BadRequest(f"Поле {low} не должно превышать {high}")
    for key in ("approved_for_training", "management_required"):
        if key in body and not isinstance(body[key], bool):
            raise BadRequest(f"Поле {key} должно быть true или false")
    for key in ("weights", "original_scores", "corrected_scores"):
        if key not in body:
            continue
        values = body[key]
        if key == "weights" and isinstance(values, str):
            try:
                values = json.loads(values)
            except ValueError:
                raise BadRequest("Поле weights содержит некорректный JSON") from None
        if not isinstance(values, dict):
            raise BadRequest(f"Поле {key} должно быть объектом")
        for criterion, value in values.items():
            _number(value, f"{key}.{criterion}", minimum=0 if key == "weights" else 1,
                    maximum=100 if key == "weights" else 10)
    if "decision" in body:
        _number(body["decision"], "decision", integer=True, minimum=0, maximum=1)
    if "history" in body:
        history = body["history"]
        if not isinstance(history, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("role"), str)
            or item.get("role") not in {"user", "assistant", "system"}
            or not isinstance(item.get("content"), str) for item in history
        ):
            raise BadRequest("Поле history должно содержать сообщения с role и строковым content")


def validate_api_request():
    if not request.path.startswith("/api/") or request.method not in {"POST", "PUT", "PATCH"}:
        return
    if request.is_json:
        # Strict parsing distinguishes a broken JSON body from an empty object.
        try:
            body = request.get_json(silent=False)
        except BadRequest:
            raise BadRequest("Некорректный JSON. Проверьте синтаксис запроса.") from None
        if not isinstance(body, dict):
            raise BadRequest("Ожидается JSON-объект, например {\"message\": \"Привет\"}")
        validate_payload(body)
    elif request.path in {"/api/upload", "/api/simulate"}:
        validate_payload(request.form.to_dict())
    elif request.content_length:
        raise UnsupportedMediaType("Отправьте запрос в формате application/json")


def api_http_error(error):
    if not request.path.startswith("/api/"):
        return error
    message = {404: "Запись или адрес API не найдены", 405: "Метод запроса не поддерживается",
               413: "Размер запроса превышает 16 МБ"}.get(error.code, error.description)
    return jsonify(error=message), error.code


def api_internal_error(error):
    current_app.logger.exception("Unhandled request failure")
    from werkzeug.exceptions import InternalServerError
    if not request.path.startswith("/api/"):
        return InternalServerError()
    return jsonify(error="Не удалось выполнить операцию. Повторите попытку."), 500


def api_conflict_error(error):
    return jsonify(error='Карточка уже изменена другим сотрудником или действием. Ваши правки не сохранены. Сверьте их с актуальной карточкой.', code='candidate_conflict'),409


def sanitize_api_errors(response):
    # Existing routes also handle failures themselves; do not expose their trace details.
    if request.path.startswith("/api/") and response.status_code == 500:
        current_app.logger.error("API operation failed: %s", request.path)
        response.set_data(json.dumps({"error": "Не удалось выполнить операцию. Повторите попытку."}, ensure_ascii=False))
        response.content_type = "application/json"
    return response

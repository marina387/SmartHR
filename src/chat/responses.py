"""Ответы по структурированным данным приложения без выдуманных значений."""
from src.services.funnel_service import STAGE_LABELS


def structured_answer(context, action=None):
    scenario = context.get("scenario")
    candidate = context.get("candidate") or {}
    vacancy = context.get("vacancy") or {}
    requested = context.get("requested_details") or []
    if requested:
        if not candidate:
            return "Выберите кандидата или укажите его фамилию."
        sections = []
        for detail in requested:
            if detail == "score_explanation" and not context.get("explain_requested"):
                total = (context.get("score") or {}).get("total")
                sections.append(f"Оценка кандидата {candidate.get('name') or candidate.get('id')}: {total}/100." if total is not None else "Для кандидата нет сохранённой оценки по выбранной вакансии.")
            else:
                sections.append(structured_answer({**context, "scenario": detail, "requested_details": []}))
        return "\n\n".join(sections)
    if scenario == "score_explanation" and candidate and (context.get("score") or {}).get("critical_failures"):
        score = context["score"]
        failures = score["critical_failures"]
        return (f"Оценка кандидата {candidate.get('name') or candidate.get('id')}: {score.get('total', 0)}/100.\n"
                + "В сохранённой оценке не подтверждены обязательные требования:\n"
                + "\n".join(f"• {failure}" for failure in failures)
                + "\nИтог выставлен по критическим фильтрам; оценки остальных критериев не рассчитывались.")
    if scenario in {"greeting", "document_search", "score_explanation"}:
        from src.chat.models import MockChatModel
        return MockChatModel().generate([], context)
    if scenario == "action":
        return (f"Подготовлено действие: {action['label']}. Проверьте его и подтвердите кнопкой ниже."
                if action else "Не удалось подготовить действие. Укажите кандидата, вакансию и нужное изменение.")
    if scenario in {"candidate_stage", "candidate_interviews", "interview_questions", "invitation", "rejection", "alternatives", "question"}:
        if not candidate:
            return "Выберите кандидата или укажите его фамилию."
        if scenario == "candidate_stage":
            status = (context.get("stage") or {}).get("status")
            label = STAGE_LABELS.get(status, {"rejected": "Отказ", "archived": "В архиве", "transferred": "Перенесён"}.get(status, status))
            return f"Кандидат: {candidate['name']}. Текущий этап: {label}." if label else "Для кандидата не сохранён этап по выбранной вакансии."
        if scenario == "candidate_interviews":
            interviews = context.get("interviews") or []
            formats = {"online": "онлайн", "offline": "офис", "office": "офис"}
            statuses = {"scheduled": "запланировано", "completed": "завершено", "cancelled": "отменено"}
            return "Интервью кандидата:\n" + "\n".join(f"• {i.get('date')} {i.get('time')}, {i.get('duration')} мин., {formats.get(i.get('format'), i.get('format'))}, статус: {statuses.get(i.get('status'), i.get('status'))}" for i in interviews) if interviews else "Для кандидата нет назначенных интервью."
        if scenario == "interview_questions":
            return "Вопросы для интервью:\n" + "\n".join(f"• {q}" for q in context.get("generated_interview_questions", []))
        if scenario in {"invitation", "rejection"}:
            return context.get("message_draft")
        if scenario == "alternatives":
            alternatives = context.get("alternatives") or []
            return "Подходящие вакансии:\n" + "\n".join(f"• {a.get('vacancy_title')}: {a.get('total', 'нет оценки')}/100" for a in alternatives) if alternatives else "Подходящие альтернативные вакансии не найдены."
        score = context.get("score") or {}
        experience = candidate.get("experience_years")
        education = candidate.get("education")
        skills = candidate.get("skills") or []
        return "\n".join([
            f"Кандидат: {candidate.get('name') or candidate.get('id')}.",
            f"Позиция: {candidate.get('position') or 'не указана'}.",
            f"Опыт работы: {str(experience) + ' лет' if experience is not None else 'не указан'}.",
            f"Образование: {education or 'не указано'}.",
            f"Навыки: {', '.join(skills) if skills else 'не указаны'}.",
            f"Оценка: {str(score['total']) + '/100' if score.get('total') is not None else 'нет сохранённой оценки'}.",
        ])
    return None

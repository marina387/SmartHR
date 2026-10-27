"""Explain saved scoring decisions without re-running or changing the model."""
from src.config import CRITERIA_LABELS

BLOCKED_COMMENT = 'Не оценивалось: расчёт остановлен обязательным фильтром. Это не нулевая оценка навыка.'

FIELD_LABELS = {'experience_years':'профильный стаж', 'expected_salary':'зарплатные ожидания',
                'english_level':'уровень английского', 'education':'образование',
                'has_portfolio':'портфолио', 'skills':'навыки', 'specialization':'специализация'}


def align_saved_explanation(candidate, history):
    """Use metadata from the matching immutable run, never another vacancy or score."""
    for record in history:
        if (record.get('vacancy_id') == candidate.get('vacancy_id')
                and record.get('total') == candidate.get('total')
                and record.get('scores') == candidate.get('scores')
                and record.get('model_probability') == candidate.get('model_probability')):
            keys = ('features','evidence','comments','missing_fields','requirement_checks','score_status','summary','used_weights')
            return {**candidate, **{key:record[key] for key in keys if key in record}}
    return candidate


def model_input_explanation(result):
    features = result.get('features') or {}
    missing = result.get('missing_fields') or []
    parts = []
    if 'experience_years' in features:
        if 'experience_years' in missing:
            parts.append('Профильный стаж не указан или не распознан; в численный вход модели подставлено 0. Это не подтверждённое отсутствие опыта.')
        else:
            parts.append(f"В расчёт передан профильный стаж: {features['experience_years']:g} лет.")
    if 'min_experience' in features:
        parts.append(f"Минимальный стаж вакансии в расчёте: {features['min_experience']:g} лет.")
    if 'skills_match' in features:
        parts.append(f"Совпадение распознанных навыков с требованиями: {features['skills_match'] * 100:.0f}%. Упоминание навыка не подтверждает уровень владения.")
    if parts:
        parts.append('Это сохранённые входные данные, а не доказательство влияния каждого признака на прогноз. Модель не проверяет навыки на практике.')
    return ' '.join(parts)


def explain_result(result):
    result = result or {}
    failures = result.get('critical_failures') or []
    blocked = bool(failures)
    values = result.get('scores') or {}
    evidence = result.get('evidence') or {}
    comments = result.get('comments') or {}
    checks = result.get('requirement_checks') or [
        {'requirement': requirement, 'status': 'not_confirmed',
         'explanation': f'В резюме не найдено подтверждение требования «{requirement}». '
                        'Это не доказывает отсутствия навыка; требуется уточнение.'}
        for requirement in failures
    ]
    items = []
    weights = result.get('used_weights') or {}
    total_weight = sum(float(weight) for weight in weights.values())
    for key, label in CRITERIA_LABELS.items():
        value = None if blocked else values.get(key)
        comment = BLOCKED_COMMENT if blocked else comments.get(key) or evidence.get(key)
        if not comment:
            comment = ('В старой записи сохранён балл, но не сохранено его обоснование. '
                       'Причину нельзя достоверно восстановить без нового расчёта.' if value is not None
                       else 'Не оценивалось: для критерия нет сохранённого результата.')
        if key == 'hard' and not blocked and value is not None:
            inputs = model_input_explanation(result)
            if inputs:
                comment += ' ' + inputs
        contribution = None
        if value is not None and key in weights and total_weight:
            contribution = round(float(value) * float(weights[key]) / total_weight * 10, 2)
        items.append({'key': key, 'label': label, 'score': value, 'comment': comment,
                      'weight': weights.get(key), 'contribution': contribution})
    summary = result.get('summary') or (
        'Расчёт соответствия остановлен: не подтверждены обязательные требования вакансии. '
        'Остальные критерии и вероятность модели не рассчитывались.' if blocked else
        'Итог — сумма оценок критериев с учётом весов вакансии и округлением до целого.'
        if values else 'Нет сохранённых оценок по критериям.')
    return {'blocked': blocked, 'summary': summary, 'requirement_checks': checks,
            'criteria_items': items,
            'missing_labels': [FIELD_LABELS.get(key, key) for key in result.get('missing_fields') or []]}


def archive_explanation(candidate):
    assessment = candidate.get('retention_assessment') or {}
    evaluations = assessment.get('evaluations') or []
    thresholds = assessment.get('thresholds') or {}
    rows = []
    for item in evaluations:
        failures = item.get('critical_failures') or []
        if failures:
            reason = 'Не подтверждены обязательные требования: ' + ', '.join(failures) + '. Остальные критерии не рассчитывались.'
        else:
            reason = (f"Оценка: {item.get('total', 'не сохранена')}/100; "
                      f"минимум для автоматического соответствия — {thresholds.get('total', 70)}.")
            probability = item.get('model_probability')
            if probability is not None:
                reason += f" Вероятность модели: {float(probability) * 100:.1f}%; порог — {float(thresholds.get('model_probability', .6)) * 100:.0f}%."
        rows.append({'vacancy': item.get('vacancy_title') or item.get('vacancy_id'), 'reason': reason})
    return {'reason': candidate.get('archive_reason') or 'Причина архивирования не сохранена.',
            'evaluations': rows}

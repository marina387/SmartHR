"""Explain saved scoring decisions without re-running or changing the model."""
from src.config import CRITERIA_LABELS

BLOCKED_COMMENT = 'Не оценивалось: расчёт остановлен обязательным фильтром. Это не нулевая оценка навыка.'


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
            'criteria_items': items}


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

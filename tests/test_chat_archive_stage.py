"""Archive lifecycle takes precedence over the retained recruitment stage."""
import pytest
from src.chat.responses import structured_answer


@pytest.mark.parametrize('stage', ['in_review', 'interview', None, 'archived'])
def test_archived_candidate_stage_is_not_presented_as_current_work(stage):
    context = {'scenario': 'candidate_stage',
               'candidate': {'name': 'Тестовый кандидат', 'lifecycle_status': 'archived',
                             'archive_reason': 'Рассмотрение завершено'},
               'stage': {'status': stage}}
    answer = structured_answer(context)
    assert 'Сейчас находится в архиве' in answer
    assert 'Текущий этап:' not in answer
    assert 'Причина архивирования: Рассмотрение завершено' in answer
    if stage in {'in_review', 'interview'}:
        assert 'Последний сохранённый этап' in answer


def test_active_candidate_keeps_current_stage():
    answer = structured_answer({'scenario': 'candidate_stage',
        'candidate': {'name': 'Тестовый кандидат', 'lifecycle_status': 'active'},
        'stage': {'status': 'in_review'}})
    assert 'Текущий этап: В работе HR.' in answer
    assert 'в архиве' not in answer


def test_combined_question_also_reports_archive():
    answer = structured_answer({'requested_details': ['candidate_stage', 'candidate_interviews'],
        'candidate': {'name': 'Тестовый кандидат', 'lifecycle_status': 'archived'},
        'stage': {'status': 'in_review'}})
    assert 'Сейчас находится в архиве' in answer
    assert 'Текущий этап:' not in answer

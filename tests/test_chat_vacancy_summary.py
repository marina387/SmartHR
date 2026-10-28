from src.chat.responses import structured_answer


def test_summary_distinguishes_vacancy_from_resume_position():
    answer=structured_answer({'scenario':'question',
        'candidate':{'name':'Кандидат','position':'Python-разработчик'},
        'vacancy':{'title':'Стажёр по анализу данных и ИИ'},'score':{'total':72}})
    assert 'Текущая вакансия: Стажёр по анализу данных и ИИ.' in answer
    assert 'Должность в резюме: Python-разработчик.' in answer
    assert 'Оценка соответствия выбранной вакансии: 72/100.' in answer


def test_summary_does_not_invent_vacancy_or_score():
    answer=structured_answer({'scenario':'question','candidate':{'name':'Кандидат'}})
    assert 'Текущая вакансия: не выбрана.' in answer
    assert 'нет сохранённой оценки' in answer


def test_historical_vacancy_is_not_called_current():
    answer=structured_answer({'scenario':'question','candidate':{'name':'Кандидат','vacancy_id':'VAC_NEW'},
        'vacancy':{'id':'VAC_OLD','title':'Senior Python Developer'},'score':{'total':52}})
    assert 'Выбранная вакансия: Senior Python Developer.' in answer
    assert 'Текущая вакансия:' not in answer

from src.services.candidate_presentation import candidate_fields, workflow_meta


def test_legacy_placeholders_are_not_presented_as_facts():
    record = dict(email='candidate@company.ru', phone='+7 (999) 000-00-00',
                  skills=['Профильные навыки','Коммуникация','Аналитика'],
                  experience=['Опыт релевантной работы','Опыт взаимодействия с командой'],
                  resume_text='Навыки: Python, SQL')
    result = candidate_fields(record)
    assert result['email'] == result['phone'] == ''
    assert result['experience'] == [] and result['skills'] == ['Python','SQL']
    assert record['email'] == 'candidate@company.ru'


def test_actual_fields_and_missing_data():
    assert candidate_fields({}) == dict(email='',phone='',skills=[],experience=[])
    record = dict(email='real@example.org',phone='+7 900 123 45 67',skills=['Excel'],experience=['Аналитик 2024–2025'])
    assert candidate_fields(record) == record
    # Even a placeholder-looking contact is retained when explicitly present in the resume.
    assert candidate_fields(dict(email='candidate@company.ru',resume_text='candidate@company.ru'))['email']


def test_workflow_is_independent_of_model_score():
    for status in ['green','yellow','red']:
        assert workflow_meta({'status':status},{'status':'in_review'})['label'] == 'В работе HR'
    assert workflow_meta({'lifecycle_status':'archived'},{'status':'in_review'})['label'] == 'В архиве'
    assert workflow_meta({}, {'status':'rejected','source':'scoring'})['label'] == 'Рассмотрение завершено'
    assert workflow_meta({}, None)['label'] == 'Этап не указан'

from src.services.score_explanation import explain_result
from src.chat.tools import SmartHRChatTools


def test_missing_experience_does_not_become_confirmed_zero():
    result = dict(scores={'hard':0.4}, comments={'hard':'Прогноз 4.2%.'},
                  features={'experience_years':0,'min_experience':0,'skills_match':1},
                  missing_fields=['experience_years','expected_salary'])
    explanation = explain_result(result)
    text = explanation['criteria_items'][0]['comment']
    assert 'не подтверждённое отсутствие' in text
    assert '100%' in text and 'не доказательство влияния' in text
    assert explanation['missing_labels'] == ['профильный стаж','зарплатные ожидания']
    assert result['comments']['hard'] == 'Прогноз 4.2%.'
    assert SmartHRChatTools.explain_score(result)[0]['comment'] == text


def test_explicit_zero_and_legacy_without_features():
    result = dict(scores={'hard':0},features={'experience_years':0,'min_experience':3},missing_fields=[])
    text = explain_result(result)['criteria_items'][0]['comment']
    assert 'стаж: 0 лет' in text and 'вакансии в расчёте: 3 лет' in text
    assert 'подставлено' not in text
    legacy = explain_result({'scores':{'hard':5}})['criteria_items'][0]['comment']
    assert 'не сохранено' in legacy and 'стаж' not in legacy


def test_blocked_filter_does_not_invent_model_inputs():
    result = dict(scores={'hard':0},critical_failures=['SQL'],features={'experience_years':0})
    assert 'В расчёт передан' not in explain_result(result)['criteria_items'][0]['comment']


def test_transferred_card_uses_matching_run_metadata_only():
    from src.services.score_explanation import align_saved_explanation
    candidate = dict(id='C1',vacancy_id='INTERN',total=34,scores={'hard':.4},model_probability=.04,features={'min_experience':3})
    wrong = {**candidate,'vacancy_id':'SENIOR','features':{'min_experience':3}}
    correct = {**candidate,'features':{'min_experience':0}}
    assert align_saved_explanation(candidate,[wrong,correct])['features']['min_experience']==0
    assert candidate['features']['min_experience']==3
    assert align_saved_explanation(candidate,[wrong]) == candidate
    assert align_saved_explanation(candidate,[{**correct,'total':99}]) == candidate

from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app import app
from src.routes import main as routes
from src.chat.resolution import CandidateAmbiguity, resolve_candidate


@pytest.fixture
def choices(monkeypatch):
    candidates=[{'id':'CV_CHOICE_A','name':'Смирнов Виктор Валентинович','position':'Разработчик','vacancy_id':'VAC_CHOICE','lifecycle_status':'active'},
                {'id':'CV_CHOICE_B','name':'Смирнов Владимир Владимирович','position':'Аналитик','vacancy_id':'VAC_CHOICE','lifecycle_status':'archived'}]
    monkeypatch.setattr(routes,'storage',SimpleNamespace(list_candidates=lambda:candidates,get_candidate=lambda key:next((c for c in candidates if c['id']==key),None)))
    monkeypatch.setattr(routes,'vacancy_service',SimpleNamespace(get_by_id=lambda key:{'id':key,'title':'Вакансия'}))
    history=Mock()
    history.record_exchange.return_value={'conversation':{'id':'CHAT_CHOICE'},'assistant_message':{'id':42}}
    service=Mock()
    service.ask.side_effect=lambda message,**kwargs:{'answer':kwargs['candidate_id'],'sources':[]}
    monkeypatch.setattr(routes,'_chat_service',lambda:service)
    monkeypatch.setattr(routes,'_chat_history_service',lambda:history)
    return app.test_client(),service,history,candidates


def test_ambiguous_question_offers_choices_and_preserves_original_request(choices):
    client,service,history,candidates=choices
    question='Покажи текущий этап Смирнова'
    response=client.post('/api/chat',json={'message':question})
    assert response.status_code==200
    data=response.get_json()
    assert data['needs_candidate_selection'] and len(data['candidate_options'])==2
    assert [c['archived'] for c in data['candidate_options']]==[False,True]
    assert 'Ошибка' not in data['answer']
    service.ask.assert_not_called(); history.record_exchange.assert_not_called()
    result=client.post('/api/chat',json={'message':question,'candidate_choice_token':data['candidate_options'][1]['token']})
    assert result.status_code==200
    assert result.get_json()['answer']=='CV_CHOICE_B'
    assert service.ask.call_args.args[0]==question
    assert service.ask.call_args.kwargs['candidate_id']=='CV_CHOICE_B'
    assert history.record_exchange.call_args.kwargs['user_message']==question


@pytest.mark.parametrize('change',['tampered','question','conversation','deleted'])
def test_choice_cannot_be_reused_for_other_question_or_context(choices,change):
    client,service,history,candidates=choices
    token=client.post('/api/chat',json={'message':'смирнов'}).get_json()['candidate_options'][0]['token']
    payload={'message':'смирнов','candidate_choice_token':token}
    if change=='tampered': payload['candidate_choice_token']='invalid-token'
    if change=='question': payload['message']='архивируй Смирнова'
    if change=='conversation': payload['conversation_id']='CHAT_OTHER'
    if change=='deleted': candidates.pop(0)
    assert client.post('/api/chat',json=payload).status_code==400
    service.ask.assert_not_called(); history.record_exchange.assert_not_called()


def test_full_name_resolves_without_selection(choices):
    client,service,history,candidates=choices
    assert resolve_candidate('Смирнов Виктор Валентинович',candidates)['id']=='CV_CHOICE_A'
    with pytest.raises(CandidateAmbiguity): resolve_candidate('смирнов',candidates)

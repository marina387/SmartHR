"""Пользовательские сценарии с настоящими SQL-репозиториями в отдельной SQLite."""
from io import BytesIO
from pathlib import Path
import pytest
from flask import Flask
from src.extensions import db
from src.routes import main as routes
from src.chat.models import MockChatModel
from src.core.rag_pipeline import RagPipeline
from src.storage.sql_storage import SqlVacancyStorage, SqlCandidateStorage, SqlScoreResultStorage

ROOT = Path(__file__).resolve().parents[1]


def sql_snapshot():
    """Compare complete persisted state, including JSON and history, after failures."""
    from sqlalchemy import select
    return {table.name: [tuple(row) for row in db.session.execute(
        select(table).order_by(*table.primary_key.columns)).all()]
        for table in db.metadata.sorted_tables}


def fail_after_write(monkeypatch, target, method):
    original = getattr(target, method)
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise ValueError('injected failure after write')
    monkeypatch.setattr(target, method, fail)

@pytest.fixture
def system(tmp_path, monkeypatch):
    test_app = Flask('system_scenarios', template_folder=str(ROOT / 'src/templates'), static_folder=str(ROOT / 'src/static'))
    test_app.config.update(TESTING=True, SECRET_KEY='isolated-test', SQLALCHEMY_DATABASE_URI=f"sqlite:///{(tmp_path / 'system.db').as_posix()}", SQLALCHEMY_TRACK_MODIFICATIONS=False, MAX_CONTENT_LENGTH=16*1024*1024)
    db.init_app(test_app)
    test_app.register_blueprint(routes.main_bp)
    monkeypatch.setattr(routes, 'chat_model', MockChatModel())
    monkeypatch.setattr(routes, 'UPLOAD_DOCS_DIR', tmp_path / 'uploads')
    monkeypatch.setattr(routes, 'DOCS_DIR', ROOT / 'docs/sample_docs')
    rag = RagPipeline(backend='tfidf')
    rag.build_index(routes._library_documents())
    monkeypatch.setattr(routes, 'rag_pipeline', rag)
    monkeypatch.setattr(routes, 'DOCUMENTS', routes._load_documents())
    with test_app.app_context():
        db.create_all()
        SqlVacancyStorage().save({'id':'VAC_SYS', 'title':'Разработчик', 'status':'active', 'weights':{'hard':50,'soft':30,'management':10,'education':5,'salary':5}})
        for key, name in [('CV_ANNA','Агафонова Анна Сергеевна'),('CV_VERA','Архипова Вера Ивановна')]:
            SqlCandidateStorage().save_candidate({'id':key, 'name':name, 'position':'Разработчик', 'vacancy_id':'VAC_SYS', 'resume_text':'Навыки: Python, SQL. Опыт работы: 5 лет. Высшее образование.', 'lifecycle_status':'active'})
            routes.candidate_stage_service.transition(key, 'VAC_SYS', 'in_review')
            SqlScoreResultStorage().save({'candidate_id':key, 'vacancy_id':'VAC_SYS', 'total':71, 'scores':{'hard':8.7}, 'used_weights':{'hard':100}, 'evidence':{'hard':'Подтверждены Python и SQL'}, 'created_at':'2026-10-21T10:00:00'})
        with test_app.test_client() as client:
            yield client
        db.session.remove()
        db.engine.dispose()


def ask(client, message, conversation_id=None):
    response = client.post('/api/chat', json={'message':message, 'conversation_id':conversation_id})
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def schedule(client, candidate='CV_ANNA', time='16:00'):
    response = client.post('/api/interviews', json={'candidate_id':candidate,'candidate_name':'Тестовый кандидат','vacancy_id':'VAC_SYS','date':'2099-10-22','time':time,'duration':60,'format':'online'})
    assert response.status_code == 201, response.get_json()
    return response.get_json()


@pytest.mark.parametrize('query', ['дата интервью Агафоновой', 'покажи интервью Агафоновой', 'когда собеседование Агафоновой', 'расписание интервью Агафоновой'])
def test_interview_phrasings(system, query):
    schedule(system)
    result = ask(system, query)
    assert '2099-10-22 16:00' in result['answer']
    assert result['sources'] == []


@pytest.mark.parametrize('query', ['список кандидатов на интервью', 'покажи кандидатов с назначенным интервью', 'какие кандидаты приглашены на собеседование'])
def test_interview_candidate_list(system, query):
    schedule(system)
    result = ask(system, query)
    assert 'Агафонова' in result['answer']
    assert 'Архипова' not in result['answer']
    assert result['sources'] == []


def test_conversation_switch_and_compound_read(system):
    schedule(system)
    result = ask(system, 'найди Агафонову'); cid = result['conversation_id']
    result = ask(system, 'дата её интервью и её оценка', cid)
    assert '2099-10-22 16:00' in result['answer'] and '71/100' in result['answer']
    result = ask(system, 'найди Архипову', cid)
    assert result['context']['candidate']['id'] == 'CV_VERA'
    result = ask(system, 'когда у неё интервью?', cid)
    assert 'нет назначенных интервью' in result['answer']
    restored = system.get('/api/chat/conversations/' + cid).get_json()
    assert restored['context']['candidate']['id'] == 'CV_VERA'
    assert len(restored['messages']) == 8


def test_documents_followup_chain(system):
    cid = ask(system, 'какие документы есть в базе?')['conversation_id']
    assert ask(system, 'а трудовой кодекс?', cid)['answer'] == 'Нет, документа в базе нет.'
    assert ask(system, 'а корпоративный кодекс?', cid)['answer'] == 'Да, документ есть в базе.'
    result = ask(system, 'а покажи его', cid)
    assert 'Корпоративный кодекс' in result['answer']
    assert result['sources'][0]['id'] == 'corporate_code'


def test_upload_search_and_reload_library(system):
    text='Положение о командировках. Билеты согласовываются за 12 дней до поездки.'
    response = system.post('/documents/upload',data={'file':(BytesIO(text.encode()),'Командировки.txt')})
    assert 'uploaded=1' in response.location
    result = ask(system,'Найди в документах за сколько дней согласовываются билеты на командировку')
    assert '12 дней' in result['answer']
    source=result['sources'][0]['id']
    assert text in system.get('/documents/'+source).get_data(as_text=True)
    assert system.get('/documents/'+source+'/download').data.decode()==text
    rebuilt = RagPipeline(backend='tfidf');rebuilt.build_index(routes._library_documents())
    assert any(d['title']=='Командировки' for d in rebuilt.list_documents())


def test_calendar_and_funnel_lifecycle(system):
    item=schedule(system)
    assert system.get('/api/analytics/funnel').get_json()['current_count']==2
    assert 'Приглашены' in ask(system,'какой этап Агафоновой')['answer']
    assert system.put('/api/interviews/'+item['id'], json={'status':'cancelled'}).status_code==200
    assert 'В работе HR' in ask(system,'какой этап Агафоновой')['answer']
    assert system.put('/api/interviews/'+item['id'], json={'status':'scheduled','time':'17:00'}).status_code==200
    assert '17:00' in ask(system,'дата интервью Агафоновой')['answer']
    assert system.put('/api/interviews/'+item['id'], json={'status':'completed'}).status_code==200
    assert 'Прошли интервью' in ask(system,'какой этап Агафоновой')['answer']
    assert system.post('/api/candidates/CV_ANNA/stage',json={'vacancy_id':'VAC_SYS','stage':'hired'}).status_code==200
    assert system.get('/api/analytics/funnel').get_json()['hired_count']==1


def test_action_requires_confirmation_and_is_not_repeated(system):
    result=ask(system,'Переведи Агафонову на этап интервью')
    token=result['suggested_action']['confirmation_token']
    assert routes.candidate_vacancy_storage.find('CV_ANNA','VAC_SYS')['status']=='in_review'
    response=system.post('/api/chat/actions/confirm',json={'confirmation_token':token})
    assert response.status_code==200, response.get_json()
    assert routes.candidate_vacancy_storage.find('CV_ANNA','VAC_SYS')['status']=='interview'
    assert system.post('/api/chat/actions/confirm',json={'confirmation_token':token}).status_code==409


def test_unknown_and_ambiguous_names_never_reuse_selected(system):
    cid=ask(system,'найди Агафонову')['conversation_id']
    response=system.post('/api/chat',json={'message':'дата интервью Несуществующей','conversation_id':cid})
    assert response.status_code==400
    SqlCandidateStorage().save_candidate({'id':'CV_DUP','name':'Агафонова Вера','resume_text':'SQL','lifecycle_status':'active'})
    response=system.post('/api/chat',json={'message':'найди Агафонову','conversation_id':cid})
    assert response.status_code==400 and 'несколько' in response.get_json()['error']


def test_manual_candidate_and_archive_restore_affect_analytics(system):
    created=system.post('/api/candidates/manual',json={'name':'Тестов Артём','position':'Разработчик','vacancy_id':'VAC_SYS','resume_text':'Должность: Python-разработчик. Опыт работы: 5 лет. Навыки: Python, SQL. Образование: высшее.'})
    assert created.status_code==201,created.get_json()
    candidate_id=created.get_json()['id']
    assert SqlScoreResultStorage().list_by_candidate(candidate_id)
    assert system.get('/candidate/'+candidate_id).status_code==200
    assert system.get('/api/analytics/funnel').get_json()['initial_count']==3
    vacancy=SqlVacancyStorage().get_by_id('VAC_SYS')
    SqlVacancyStorage().save({**vacancy,'status':'closed'})
    archived=system.post('/api/candidates/'+candidate_id+'/retention-check')
    assert archived.status_code==200 and archived.get_json()['archived'],archived.get_json()
    assert system.get('/api/analytics/funnel').get_json()['outcomes']['archived']==1
    assert all(c['id']!=candidate_id for c in routes._chat_service().tools.list_candidates_for_chat())
    restored=system.post('/api/candidates/'+candidate_id+'/restore')
    assert restored.status_code==200
    assert restored.get_json()['lifecycle_status']=='active'
    assert system.get('/api/analytics/funnel').get_json()['outcomes']['archived']==0


def test_archive_protects_candidate_with_interview(system):
    schedule(system)
    vacancy=SqlVacancyStorage().get_by_id('VAC_SYS')
    SqlVacancyStorage().save({**vacancy,'status':'closed'})
    response=system.post('/api/candidates/CV_ANNA/retention-check')
    assert response.status_code==200 and response.get_json()['archived'] is False
    assert SqlCandidateStorage().get_candidate('CV_ANNA')['lifecycle_status']=='active'


def test_full_name_disambiguates_same_surname(system):
    SqlCandidateStorage().save_candidate({'id':'CV_DUP','name':'Агафонова Вера','resume_text':'SQL','lifecycle_status':'active'})
    result=ask(system,'найди Агафонова Анна')
    assert result['context']['candidate']['id']=='CV_ANNA'


def test_candidate_transfer_preserves_audit_and_context(system):
    SqlVacancyStorage().save({'id':'VAC_TARGET','title':'Аналитик','status':'active','weights':{'hard':100,'soft':0,'management':0,'education':0,'salary':0}})
    # Проверка переноса уже одобренной рекомендации, без загрузки/изменения моделей.
    recommendation={'total':85,'current_total':71,'model_probability':.9,'model_version':'existing','used_weights':{'hard':100}}
    moved=routes.candidate_vacancy_service.apply('CV_VERA','VAC_SYS','VAC_TARGET','transfer','HR_TEST','Проверка переноса',recommendation)
    assert moved['application']['vacancy_id']=='VAC_TARGET'
    assert routes.candidate_vacancy_storage.find('CV_VERA','VAC_SYS')['status']=='transferred'
    assert routes.transfer_storage.list_all()[0]['candidate_id']=='CV_VERA'
    assert system.get('/api/analytics/funnel').get_json()['outcomes']['transferred']==1


def test_history_feedback_restores_with_actual_sql(system):
    result=ask(system,'покажи корпоративный кодекс')
    assert result['sources']
    assert system.post(f"/api/chat/messages/{result['message_id']}/feedback",json={'rating':'useful'}).status_code==200
    restored=system.get('/api/chat/conversations/'+result['conversation_id']).get_json()
    assert restored['messages'][-1]['feedback']['rating']=='useful'
    assert restored['messages'][-1]['sources']==result['sources']


def test_selected_candidate_generic_followups(system):
    cid=ask(system,'найди Агафонову')['conversation_id']
    for query in ['расскажи о текущем кандидате','покажи его опыт работы']:
        assert 'Агафонова' in ask(system,query,cid)['answer']


def test_manual_transfer_bypasses_recommendations_and_keeps_history(system, monkeypatch):
    SqlVacancyStorage().save({'id':'VAC_TARGET','title':'Стажёр','status':'active'})
    before = SqlCandidateStorage().get_candidate('CV_VERA')
    before['lifecycle_status'] = 'archived'
    SqlCandidateStorage().save_candidate(before)
    def no_recommendations(*args, **kwargs):
        raise AssertionError('Manual transfer must not depend on recommendations')
    monkeypatch.setattr(routes.AlternativeVacancyService,'find_alternatives',no_recommendations)
    def low_score(text, requirements, weights, vacancy):
        assert text == before['resume_text'] and vacancy['id'] == 'VAC_TARGET'
        return {'total':12,'status':'red','decision':'Отклонен','scores':{'hard':1.2},
                'comments':{'hard':'Низкий прогноз'},'model_probability':.01,'critical_failures':[],
                'score_status':'calculated','features':{'experience_years':0}}
    monkeypatch.setattr(routes.scoring_service,'score_candidate',low_score)
    body = dict(from_vacancy_id='VAC_SYS',to_vacancy_id='VAC_TARGET',mode='transfer',
                hr_id='HR_TEST',comment='Решение HR',manual_transfer=True)
    assert system.post('/api/candidates/CV_VERA/vacancies',json={**body,'from_vacancy_id':'wrong'}).status_code == 400
    assert system.post('/api/candidates/CV_VERA/vacancies',json={**body,'comment':''}).status_code == 400
    response = system.post('/api/candidates/CV_VERA/vacancies',json=body)
    assert response.status_code == 201, response.get_json()
    saved = SqlCandidateStorage().get_candidate('CV_VERA')
    assert saved['vacancy_id']=='VAC_TARGET' and saved['total']==12 and saved['lifecycle_status']=='active'
    assert saved['resume_text']==before['resume_text'] and saved['position']=='Стажёр'
    assert routes.candidate_vacancy_storage.find('CV_VERA','VAC_TARGET')['status']=='in_review'
    assert routes.candidate_vacancy_storage.find('CV_VERA','VAC_SYS')['status']=='transferred'
    assert system.post('/api/candidates/CV_VERA/vacancies',json=body).status_code == 400


@pytest.mark.parametrize('via_chat',[False,True])
def test_transfer_routes_update_candidate_score_and_conversation(system,monkeypatch,via_chat):
    SqlVacancyStorage().save({'id':'VAC_TARGET','title':'Аналитик','status':'active','weights':{'hard':100,'soft':0,'management':0,'education':0,'salary':0}})
    recommendation={'vacancy_id':'VAC_TARGET','vacancy_title':'Аналитик','total':85,'current_total':71,'model_probability':.9,'model_version':'existing','used_weights':{'hard':100},'scores':{'hard':8.5},'evidence':{'hard':'Подтверждено'}}
    monkeypatch.setattr(routes.AlternativeVacancyService,'find_alternatives',lambda *args,**kwargs:{'alternatives':[recommendation]})
    if via_chat:
        result=ask(system,'перенеси Архипову на VAC_TARGET')
        response=system.post('/api/chat/actions/confirm',json={'confirmation_token':result['suggested_action']['confirmation_token']})
        assert response.status_code==200,response.get_json()
        after=ask(system,'её оценка',result['conversation_id'])
    else:
        response=system.post('/api/candidates/CV_VERA/vacancies',json={'from_vacancy_id':'VAC_SYS','to_vacancy_id':'VAC_TARGET','mode':'transfer','hr_id':'HR_TEST'})
        assert response.status_code==201,response.get_json()
        after=ask(system,'оценка Архиповой')
    assert SqlCandidateStorage().get_candidate('CV_VERA')['vacancy_id']=='VAC_TARGET'
    assert '85/100' in after['answer']
    assert after['context']['vacancy']['id']=='VAC_TARGET'


@pytest.mark.parametrize('via_chat,checkpoint', [
    (False, 'stage'), (False, 'audit'), (False, 'candidate'), (False, 'score'), (True, 'score'),
    (True, 'conversation'), (True, 'confirmation'),
])
def test_failed_transfer_rolls_back_every_record_and_can_retry(system, monkeypatch, via_chat, checkpoint):
    SqlVacancyStorage().save({'id':'VAC_TARGET','title':'Аналитик','status':'active'})
    recommendation={'vacancy_id':'VAC_TARGET','total':85,'current_total':71,
                    'model_probability':.9,'scores':{'hard':8.5}}
    monkeypatch.setattr(routes.AlternativeVacancyService,'find_alternatives',
                        lambda *args,**kwargs:{'alternatives':[recommendation]})
    if via_chat:
        suggested=ask(system,'перенеси Архипову на VAC_TARGET')
        url='/api/chat/actions/confirm'
        body={'confirmation_token':suggested['suggested_action']['confirmation_token']}
    else:
        url='/api/candidates/CV_VERA/vacancies'
        body={'from_vacancy_id':'VAC_SYS','to_vacancy_id':'VAC_TARGET','mode':'transfer','hr_id':'HR_TEST'}
    before=sql_snapshot()
    targets={'stage':(routes.candidate_stage_event_storage,'save'),
             'audit':(routes.transfer_storage,'save'),
             'candidate':(routes.storage,'save_candidate'),
             'score':(routes.score_result_storage,'save'),
             'conversation':(routes.chat_conversation_storage,'save'),
             'confirmation':(routes.ChatHistoryService,'complete_action')}
    with monkeypatch.context() as failure:
        fail_after_write(failure,*targets[checkpoint])
        response=system.post(url,json=body)
        assert response.status_code in {400,500},response.get_json()
    assert sql_snapshot()==before
    assert system.post(url,json=body).status_code==(200 if via_chat else 201)
    assert routes.storage.get_candidate('CV_VERA')['vacancy_id']=='VAC_TARGET'
    assert routes.candidate_vacancy_storage.find('CV_VERA','VAC_SYS')['status']=='transferred'
    assert len(routes.transfer_storage.list_all())==1
    if via_chat:
        assert system.post(url,json=body).status_code==409


def test_failed_stage_history_rolls_back_current_stage(system, monkeypatch):
    before=sql_snapshot()
    with monkeypatch.context() as failure:
        fail_after_write(failure,routes.candidate_stage_event_storage,'save')
        response=system.post('/api/candidates/CV_ANNA/stage',json={'vacancy_id':'VAC_SYS','stage':'offer'})
        assert response.status_code==400
    assert sql_snapshot()==before
    assert system.post('/api/candidates/CV_ANNA/stage',json={'vacancy_id':'VAC_SYS','stage':'offer'}).status_code==200


@pytest.mark.parametrize('operation',['create','update','delete'])
def test_failed_interview_stage_sync_rolls_back_calendar(system,monkeypatch,operation):
    item=schedule(system) if operation!='create' else None
    url='/api/interviews'+('/'+item['id'] if item else '')
    method={'create':system.post,'update':system.put,'delete':system.delete}[operation]
    payload={'candidate_id':'CV_ANNA','candidate_name':'Тест','vacancy_id':'VAC_SYS',
             'date':'2099-10-22','time':'16:00','duration':60,'format':'online'} if operation=='create' else {'status':'cancelled'}
    before=sql_snapshot()
    # Unhandled exceptions must also roll back, even when Flask creates the 500.
    monkeypatch.setitem(system.application.config,'PROPAGATE_EXCEPTIONS',False)
    with monkeypatch.context() as failure:
        fail_after_write(failure,routes.candidate_stage_event_storage,'save')
        assert method(url,json=payload).status_code in {400,500}
    assert sql_snapshot()==before
    assert method(url,json=payload).status_code==(201 if operation=='create' else 200)


@pytest.mark.parametrize('endpoint',['/api/candidates/manual','/api/simulate'])
@pytest.mark.parametrize('checkpoint',['score','stage'])
def test_failed_scoring_history_leaves_no_partial_candidate(system,monkeypatch,endpoint,checkpoint):
    body={'name':'Тест','position':'Разработчик','resume_text':'Python SQL, 5 лет опыта', 'vacancy_id':'VAC_SYS'}
    before=sql_snapshot()
    monkeypatch.setitem(system.application.config,'PROPAGATE_EXCEPTIONS',False)
    with monkeypatch.context() as failure:
        target=(routes.score_result_storage,'save') if checkpoint=='score' else (routes.candidate_stage_service,'register_scoring')
        fail_after_write(failure,*target)
        assert system.post(endpoint,json=body).status_code==500
    assert sql_snapshot()==before


def test_chat_history_failure_leaves_no_partial_exchange(system,monkeypatch):
    before=sql_snapshot()
    with monkeypatch.context() as failure:
        fail_after_write(failure,routes.chat_message_storage,'save')
        assert system.post('/api/chat',json={'message':'найди Агафонову'}).status_code==400
    assert sql_snapshot()==before
    assert ask(system,'найди Агафонову')['conversation_id']


def test_operation_commits_once_and_commit_failure_rolls_back(system,monkeypatch):
    session=db.session()
    before=sql_snapshot()
    def fail_commit():
        raise RuntimeError('injected commit failure')
    monkeypatch.setitem(system.application.config,'PROPAGATE_EXCEPTIONS',False)
    with monkeypatch.context() as failure:
        failure.setattr(session,'commit',fail_commit)
        assert system.post('/api/candidates/CV_ANNA/stage',json={
            'vacancy_id':'VAC_SYS','stage':'offer'}).status_code==500
    assert sql_snapshot()==before
    original=session.commit
    commits=[]
    def count_commit():
        commits.append(True)
        return original()
    monkeypatch.setattr(session,'commit',count_commit)
    assert system.post('/api/candidates/CV_ANNA/stage',json={
        'vacancy_id':'VAC_SYS','stage':'offer'}).status_code==200
    assert len(commits)==1


@pytest.mark.parametrize('endpoint',['/api/score','/api/candidates/manual','/api/simulate'])
@pytest.mark.parametrize('additional',[None,[],['Python']])
def test_vacancy_critical_filters_cannot_be_removed(system,monkeypatch,endpoint,additional):
    vacancy=routes.vacancy_service.get_by_id('VAC_SYS')
    routes.vacancy_storage.save({**vacancy,'critical_requirements':['Kubernetes']})
    monkeypatch.setattr(routes.random,'choice',lambda items:{'name':'Тест','text':'Python SQL'})
    body={'vacancy_id':'VAC_SYS','candidate_text':'Python SQL','resume_text':'Python SQL',
          'name':'Тест','position':'Разработчик'}
    if additional is not None:
        body['critical_requirements']=additional
    response=system.post(endpoint,json=body)
    assert response.status_code==(200 if endpoint=='/api/score' else 201),response.get_json()
    result=response.get_json()
    assert result['total']==0
    assert 'Kubernetes' in result['critical_failures']
    if endpoint!='/api/score':
        assert routes.candidate_vacancy_storage.find(result['id'],'VAC_SYS')['status']=='rejected'


@pytest.mark.parametrize('stage',['rejected','rejected_all','withdrawn','transferred','archived','offer','hired'])
def test_interview_requires_explicit_reopening_after_closed_stage(system,stage):
    routes.candidate_stage_service.transition('CV_ANNA','VAC_SYS',stage,source='hr')
    before=sql_snapshot()
    body={'candidate_id':'CV_ANNA','candidate_name':'Тест','vacancy_id':'VAC_SYS',
          'date':'2099-10-22','time':'16:00','duration':60,'format':'online'}
    response=system.post('/api/interviews',json=body)
    assert response.status_code==400
    assert 'верните кандидата в работу' in response.get_json()['error']
    assert sql_snapshot()==before
    assert system.post('/api/candidates/CV_ANNA/stage',json={
        'vacancy_id':'VAC_SYS','stage':'in_review'}).status_code==200
    assert system.post('/api/interviews',json=body).status_code==201
    assert routes.candidate_vacancy_storage.find('CV_ANNA','VAC_SYS')['status']=='interview'


@pytest.mark.parametrize('inactive',['candidate','vacancy','missing_candidate','missing_vacancy'])
def test_interview_rejects_inactive_or_missing_entities(system,inactive):
    if inactive=='candidate':
        candidate=routes.storage.get_candidate('CV_ANNA')
        routes.storage.save_candidate({**candidate,'lifecycle_status':'archived'})
    elif inactive=='vacancy':
        vacancy=routes.vacancy_service.get_by_id('VAC_SYS')
        routes.vacancy_storage.save({**vacancy,'status':'closed'})
    before=sql_snapshot()
    response=system.post('/api/interviews',json={
        'candidate_id':'missing' if inactive=='missing_candidate' else 'CV_ANNA',
        'candidate_name':'Тест','vacancy_id':'missing' if inactive=='missing_vacancy' else 'VAC_SYS',
        'date':'2099-10-22','time':'16:00','duration':60,'format':'online'})
    assert response.status_code==400
    assert sql_snapshot()==before


def test_cancelled_interview_cannot_be_reactivated_after_rejection(system):
    item=schedule(system)
    assert system.put('/api/interviews/'+item['id'],json={'status':'cancelled'}).status_code==200
    routes.candidate_stage_service.transition('CV_ANNA','VAC_SYS','rejected',source='hr')
    before=sql_snapshot()
    assert system.put('/api/interviews/'+item['id'],json={'status':'scheduled'}).status_code==400
    assert sql_snapshot()==before
    # Historical edits are allowed and must not reopen a closed application.
    assert system.put('/api/interviews/'+item['id'],json={'notes':'Причина отмены'}).status_code==200
    assert routes.candidate_vacancy_storage.find('CV_ANNA','VAC_SYS')['status']=='rejected'


@pytest.mark.parametrize('stage',['in_review','interview','interview_completed','offer','hired','rejected','withdrawn','transferred','archived'])
def test_rescoring_keeps_hr_stage_and_history(system,stage):
    routes.candidate_stage_service.transition('CV_ANNA','VAC_SYS',stage,source='hr')
    before=routes.candidate_stage_event_storage.list_by_candidate('CV_ANNA')
    record=routes.candidate_stage_service.register_scoring('CV_ANNA','VAC_SYS',{'total':90,'model_probability':.9})
    assert record['status']==stage
    assert record['total']==90
    assert routes.candidate_stage_event_storage.list_by_candidate('CV_ANNA')==before


def test_rescoring_does_not_add_fake_new_stage_and_respects_critical_failure(system):
    routes.candidate_stage_service.transition('CV_ANNA','VAC_SYS','scored')
    before=len(routes.candidate_stage_event_storage.list_by_candidate('CV_ANNA'))
    record=routes.candidate_stage_service.register_scoring('CV_ANNA','VAC_SYS',{'total':90,'critical_failures':['Kubernetes']})
    assert record['status']=='rejected'
    events=routes.candidate_stage_event_storage.list_by_candidate('CV_ANNA')
    assert len(events)==before+1
    assert events[-1]['from_stage']=='scored' and events[-1]['to_stage']=='rejected'


def test_closed_stage_cannot_be_bypassed_by_chat_or_calendar_edit(system):
    item=schedule(system)
    routes.candidate_stage_service.transition('CV_ANNA','VAC_SYS','rejected',source='hr')
    action=ask(system,'Переведи Агафонову на этап интервью')
    before=sql_snapshot()
    response=system.post('/api/chat/actions/confirm',json={
        'confirmation_token':action['suggested_action']['confirmation_token']})
    assert response.status_code==400
    assert sql_snapshot()==before
    assert system.put('/api/interviews/'+item['id'],json={'time':'18:00'}).status_code==400
    assert sql_snapshot()==before
    assert system.put('/api/interviews/'+item['id'],json={'status':'cancelled'}).status_code==200


@pytest.mark.parametrize('method,url',[
    ('POST','/api/chat'),('POST','/api/chat/actions/confirm'),
    ('POST','/api/chat/messages/1/feedback'),('POST','/api/score'),
    ('POST','/api/parse_requirements'),('POST','/api/parse_hh'),('POST','/api/upload'),
    ('POST','/api/candidates/manual'),('POST','/api/candidates/CV_ANNA/stage'),
    ('POST','/api/candidates/CV_ANNA/vacancies'),('POST','/api/interviews'),
    ('PUT','/api/interviews/unknown'),('POST','/api/feedback'),('POST','/api/feedback/decision'),
    ('POST','/api/vacancies'),('PUT','/api/vacancies/VAC_SYS'),
    ('POST','/api/templates'),('PUT','/api/templates/unknown'),('POST','/api/simulate'),
])
def test_api_rejects_non_object_and_broken_json_without_writes(system,method,url):
    before=sql_snapshot()
    for payload in ('[]','[1]','null','"hello"','12','true','{"broken":'):
        response=system.open(url,method=method,data=payload,content_type='application/json')
        assert response.status_code==400,(url,payload,response.get_data(as_text=True))
        assert response.is_json and response.get_json().get('error')
    assert sql_snapshot()==before


@pytest.mark.parametrize('url,payload',[
    ('/api/chat',{'message':123}),('/api/chat',{'history':[1]}),
    ('/api/chat',{'history':[{'role':'user','content':{}}]}),
    ('/api/chat',{'history':[{'role':{},'content':'hello'}]}),
    ('/api/score',{'candidate_text':None}),('/api/score',{'critical_requirements':{}}),
    ('/api/score',{'weights':'not-json'}),('/api/score',{'weights':[1]}),
    ('/api/score',{'weights':{'hard':float('nan')}}),
    ('/api/score',{'weights':{'hard':-1}}),('/api/score',{'weights':{'hard':True}}),
    ('/api/parse_hh',{'url':[]}),('/api/interviews',{'duration':False}),
    ('/api/interviews',{'duration':1.5}),('/api/interviews',{'duration':1441}),
    ('/api/interviews',{'duration':None}),('/api/interviews',{'date':'2026-02-30'}),
    ('/api/interviews',{'time':'25:00'}),('/api/interviews',{'date':'2026-1-1'}),
    ('/api/feedback',{'corrected_scores':[]}),
    ('/api/feedback/decision',{'decision':True}),
    ('/api/vacancies',{'min_experience':-1}),('/api/vacancies',{'min_salary':100,'max_salary':50}),
    ('/api/vacancies',{'management_required':'false'}),
])
def test_api_rejects_wrong_field_types_and_ranges(system,url,payload):
    before=sql_snapshot()
    response=system.post(url,json=payload)
    assert response.status_code==400,response.get_data(as_text=True)
    assert response.is_json and response.get_json()['error']
    assert sql_snapshot()==before


def test_api_file_errors_and_media_type_are_clear(system):
    for name,data in [('broken.pdf',b'broken'),('broken.docx',b'PKbroken'),
                      ('old.doc',b'old'),('bad.txt',b'\xff\xfe')]:
        response=system.post('/api/upload',data={'file':(BytesIO(data),name)})
        assert response.status_code==400 and response.is_json
    response=system.post('/api/chat',data='message=hello',content_type='application/x-www-form-urlencoded')
    assert response.status_code==415 and response.is_json


def test_missing_api_entities_return_404_without_partial_records(system):
    before=sql_snapshot()
    for url,payload in [('/api/score',{'candidate_text':'Python','vacancy_id':'missing'}),
                        ('/api/candidates/manual',{'name':'Тест','position':'IT','resume_text':'Python','vacancy_id':'missing'}),
                        ('/api/candidates/missing/stage',{'vacancy_id':'VAC_SYS','stage':'offer'}),
                        ('/api/feedback',{'candidate_id':'missing'}),
                        ('/api/feedback/decision',{'candidate_id':'missing','vacancy_id':'VAC_SYS','decision':1}),
                        ('/api/simulate',{'vacancy_id':'missing'}),
                        ('/api/vacancies',{'title':'Test','template_id':'missing'})]:
        assert system.post(url,json=payload).status_code==404,url
    assert sql_snapshot()==before


def test_missing_chat_vacancy_and_cancelled_interview_do_not_reach_fk_errors(system):
    before=sql_snapshot()
    response=system.post('/api/chat',json={'message':'Привет','vacancy_id':'missing'})
    assert response.status_code==400
    response=system.post('/api/interviews',json={'candidate_id':'missing','vacancy_id':'VAC_SYS',
        'candidate_name':'Тест','status':'cancelled','date':'2099-10-22','time':'16:00','duration':60,'format':'online'})
    assert response.status_code==400
    assert sql_snapshot()==before


def test_conflicting_delete_returns_409_and_preserves_records(system):
    before=sql_snapshot()
    response=system.delete('/api/vacancies/VAC_SYS')
    assert response.status_code==409,response.get_json()
    assert sql_snapshot()==before


def test_api_server_failure_does_not_expose_internal_details(system,monkeypatch):
    def fail(*args,**kwargs):
        raise RuntimeError('private-file-path-and-secret')
    monkeypatch.setattr(routes.scoring_service,'score_candidate',fail)
    response=system.post('/api/score',json={'candidate_text':'Python','vacancy_id':'VAC_SYS'})
    assert response.status_code==500 and response.is_json
    assert 'private-file-path-and-secret' not in response.get_data(as_text=True)


def test_hh_import_reports_timeouts_and_remote_errors(system,monkeypatch):
    import requests
    for error,status in [(requests.Timeout('private-timeout'),504),(requests.ConnectionError('private-host'),502)]:
        def fail(*args,**kwargs):
            raise error
        monkeypatch.setattr(routes,'parse_hh_url',fail)
        response=system.post('/api/parse_hh',json={'url':'https://hh.ru/resume/abc'})
        assert response.status_code==status and response.is_json
        assert 'private-' not in response.get_data(as_text=True)


def test_api_request_size_limit_returns_json(system,monkeypatch):
    monkeypatch.setitem(system.application.config,'MAX_CONTENT_LENGTH',128)
    response=system.post('/api/chat',json={'message':'x'*256})
    assert response.status_code==413 and response.is_json


def test_partial_vacancy_update_validates_resulting_range(system):
    vacancy=routes.vacancy_service.get_by_id('VAC_SYS')
    routes.vacancy_storage.save({**vacancy,'min_experience':0,'max_experience':5})
    before=sql_snapshot()
    response=system.put('/api/vacancies/VAC_SYS',json={'min_experience':10})
    assert response.status_code==400 and response.is_json
    assert sql_snapshot()==before


def test_blocked_score_has_saved_explanations_and_no_fake_criterion_zeros(system):
    vacancy=routes.vacancy_service.get_by_id('VAC_SYS')
    routes.vacancy_storage.save({**vacancy,'critical_requirements':['Python','Docker','SQL']})
    response=system.post('/api/candidates/manual',json={'name':'Проверка объяснения','position':'Стажёр',
        'resume_text':'Навыки: Python. Образование: высшее.','vacancy_id':'VAC_SYS'})
    assert response.status_code==201,response.get_json()
    candidate=response.get_json()
    assert candidate['critical_failures']==['Docker','SQL']
    assert candidate['score_status']=='blocked_by_requirements'
    assert candidate['scores']=={}
    assert all('Не оценивалось' in comment for comment in candidate['comments'].values())
    saved=routes.score_result_storage.list_by_candidate(candidate['id'])[0]
    assert saved['comments']==candidate['comments']
    assert saved['requirement_checks']==candidate['requirement_checks']
    assert saved['summary']==candidate['summary']
    page=system.get('/candidate/'+candidate['id']).get_data(as_text=True)
    assert 'Обоснование результата' in page and 'Docker — не подтверждено' in page and 'SQL — не подтверждено' in page
    assert 'Не оценивалось' in page and 'Почему кандидат в архиве' in page
    assert 'Комментарий будет добавлен после интервью' not in page
    from bs4 import BeautifulSoup
    assert not any(item.get_text(strip=True)=='0/10' for item in BeautifulSoup(page,'html.parser').find_all('span'))
    assert 'Оценка 0/100' not in page
    answer=ask(system,'объясни оценку '+candidate['id'])['answer']
    import re
    assert 'Docker' in answer and 'SQL' in answer and not re.search(r'(?<!\d)0/100',answer)


def test_legacy_blocked_card_explains_saved_filters_without_recalculation(system,monkeypatch):
    candidate=routes.storage.get_candidate('CV_ANNA')
    routes.storage.save_candidate({**candidate,'total':0,'scores':{},'comments':{},
                                  'critical_failures':['Docker'],'lifecycle_status':'archived',
                                  'archive_reason':'Не найдено подходящих активных вакансий'})
    before=sql_snapshot()
    def fail(*args,**kwargs):
        raise AssertionError('Viewing a historical score must not re-run inference')
    monkeypatch.setattr(routes.scoring_service,'score_candidate',fail)
    page=system.get('/candidate/CV_ANNA').get_data(as_text=True)
    assert 'Docker — не подтверждено' in page and 'Не оценивалось' in page
    assert '0/10' not in page and 'Оценка 0/100' not in page
    assert sql_snapshot()==before


def test_missing_old_score_is_not_displayed_as_measured_zero(system):
    candidate=routes.storage.get_candidate('CV_ANNA')
    routes.storage.save_candidate({**candidate,'scores':{},'comments':{}})
    page=system.get('/candidate/CV_ANNA').get_data(as_text=True)
    assert 'для критерия нет сохранённого результата' in page
    from bs4 import BeautifulSoup
    assert not any(item.get_text(strip=True)=='0/10' for item in BeautifulSoup(page,'html.parser').find_all('span'))



def test_edit_interview_form_and_full_update(system):
    item=schedule(system)
    page=system.get('/interviews').get_data(as_text=True)
    assert 'Редактировать' in page and 'editInterviewForm' in page
    assert 'data-interview=' in page and item['id'] in page
    response=system.put('/api/interviews/'+item['id'],json={'date':'2099-10-23','time':'12:30','duration':45,'format':'office','status':'scheduled','notes':'Обсудить Python'})
    assert response.status_code==200,response.get_json()
    updated=response.get_json()
    assert updated['id']==item['id'] and updated['candidate_id']=='CV_ANNA'
    assert updated['time']=='12:30' and updated['duration']==45 and updated['notes']=='Обсудить Python'
    assert len(system.get('/api/interviews').get_json())==1
    assert '2099-10-23 12:30' in ask(system,'дата интервью Агафоновой')['answer']


def test_edit_interview_conflict_keeps_original_values(system):
    first=schedule(system,time='16:00')
    second=schedule(system,time='17:00')
    response=system.put('/api/interviews/'+second['id'],json={'time':'16:30','duration':60})
    assert response.status_code==400
    saved=next(i for i in system.get('/api/interviews').get_json() if i['id']==second['id'])
    assert saved['time']=='17:00'



def test_document_rename_replace_delete_and_catalog_reload(system):
    response=system.post('/documents/upload',data={'file':(BytesIO('Старый порядок. Контрольное слово ананасы.'.encode()),'Порядок.txt')})
    assert 'uploaded=1' in response.location
    doc=next(d for d in routes._library_documents() if d.title=='Порядок')
    response=system.post(f'/documents/{doc.id}/rename',data={'title':'Порядок согласования'})
    assert 'updated=1' in response.location
    assert next(d for d in routes._library_documents() if d.id==doc.id).title=='Порядок согласования'
    assert 'Порядок согласования' in ask(system,'какие документы есть?')['answer']
    assert routes.rag_pipeline.ask('Порядок согласования').hits[0].chunk.doc_id==doc.id
    response=system.post(f'/documents/{doc.id}/replace',data={'file':(BytesIO('Новый порядок. Контрольное слово мандарины.'.encode()),'Новая версия.txt')})
    assert 'updated=1' in response.location
    updated=next(d for d in routes._library_documents() if d.id==doc.id)
    assert updated.title=='Порядок согласования' and 'мандарины' in updated.text
    assert len([d for d in routes._library_documents() if 'порядок' in d.text.casefold()])==1
    assert system.get(f'/documents/{doc.id}/download').data.decode()==updated.text
    assert not any(hit.chunk.doc_id==doc.id and 'ананасы' in hit.chunk.text for hit in routes.rag_pipeline.ask('ананасы').hits)
    before=len(routes._library_documents())
    response=system.post(f'/documents/{doc.id}/delete')
    assert 'error=' in response.location and len(routes._library_documents())==before
    response=system.post(f'/documents/{doc.id}/delete',data={'confirm':'yes'})
    assert 'updated=1' in response.location
    assert all(d.id!=doc.id for d in routes._library_documents())
    assert all(d['id']!=doc.id for d in routes.rag_pipeline.list_documents())
    assert system.get(f'/documents/{doc.id}').status_code==404
    # Прочитываем каталог с диска заново, как после перезапуска.
    rebuilt=RagPipeline(backend='tfidf');rebuilt.build_index(routes._library_documents())
    assert all(d['id']!=doc.id for d in rebuilt.list_documents())


def test_document_bad_replacement_keeps_old_version(system):
    original=next(d for d in routes._library_documents() if d.id=='interview_guide')
    response=system.post('/documents/interview_guide/replace',data={'file':(BytesIO(b'broken'),'broken.pdf')})
    assert 'error=' in response.location
    assert next(d for d in routes._library_documents() if d.id==original.id).text==original.text
    assert all(d.id!='broken' for d in routes._library_documents())
    response=system.post('/documents/interview_guide/rename',data={'title':' '})
    assert 'error=' in response.location
    assert next(d for d in routes._library_documents() if d.id==original.id).title==original.title


def test_builtin_document_management_preserves_original_file(system):
    original=next(d for d in routes._library_documents() if d.id=='corporate_code')
    original_bytes=Path(original.metadata['path']).read_bytes()
    response=system.post('/documents/corporate_code/rename',data={'title':'Корпоративный кодекс'})
    assert 'updated=1' in response.location
    response=system.post('/documents/corporate_code/replace',data={'file':(BytesIO('Новая корпоративная политика.'.encode()),'Кодекс.txt')})
    assert 'updated=1' in response.location
    response=system.post('/documents/corporate_code/replace',data={'file':(BytesIO('Последняя корпоративная политика.'.encode()),'Кодекс 2.txt')})
    assert 'updated=1' in response.location
    assert sum(d.id=='corporate_code' for d in routes._library_documents())==1
    assert not any('Новая корпоративная' in d.text for d in routes._library_documents())
    assert Path(original.metadata['path']).read_bytes()==original_bytes
    response=system.post('/documents/corporate_code/delete',data={'confirm':'yes'})
    assert 'updated=1' in response.location
    assert Path(original.metadata['path']).read_bytes()==original_bytes
    assert not any(d.id=='corporate_code' for d in routes._library_documents())



@pytest.mark.parametrize('transient_lock',[False,True])
def test_document_index_failure_does_not_commit_changes(system,monkeypatch,transient_lock):
    original=next(d for d in routes._library_documents() if d.id=='interview_guide')
    original_index=routes.rag_pipeline
    def fail(*args,**kwargs): raise RuntimeError('simulated indexing failure')
    monkeypatch.setattr(routes.RagPipeline,'build_index',fail)
    if transient_lock:
        unlink=Path.unlink
        blocked=[]
        def transient_unlink(path,*args,**kwargs):
            if path.suffix=='.txt' and not blocked:
                blocked.append(path)
                error=PermissionError('temporary Windows file lock')
                error.winerror=32
                raise error
            return unlink(path,*args,**kwargs)
        monkeypatch.setattr(Path,'unlink',transient_unlink)
    for endpoint,payload in [('/rename',{'title':'Новое название'}),('/replace',{'file':(BytesIO('Новая версия.'.encode()),'version.txt')}),('/delete',{'confirm':'yes'})]:
        response=system.post('/documents/interview_guide'+endpoint,data=payload)
        assert 'error=' in response.location
        current=next(d for d in routes._library_documents() if d.id==original.id)
        assert current.title==original.title and current.text==original.text
        assert routes.rag_pipeline is original_index
    assert not list(routes.UPLOAD_DOCS_DIR.glob('*.tmp'))
    assert not list(routes.UPLOAD_DOCS_DIR.glob('*.txt'))



def test_conversation_list_open_continue_and_new_context(system):
    empty=system.get('/api/chat/conversations').get_json()
    assert empty=={'conversations':[],'next_offset':None}
    first=ask(system,'найди Агафонову')
    second=ask(system,'найди Архипову')
    listing=system.get('/api/chat/conversations').get_json()['conversations']
    assert [item['id'] for item in listing]==[second['conversation_id'],first['conversation_id']]
    assert listing[0]['title']=='найди Архипову'
    assert listing[0]['candidate_name']=='Архипова Вера Ивановна'
    assert listing[0]['vacancy_title']=='Разработчик'
    assert listing[0]['message_count']==2
    continued=ask(system,'объясни её оценку',first['conversation_id'])
    assert 'Агафонова' in continued['answer']
    assert continued['context']['candidate']['id']=='CV_ANNA'
    listing=system.get('/api/chat/conversations').get_json()['conversations']
    assert listing[0]['id']==first['conversation_id']
    assert listing[0]['title']=='найди Агафонову' and listing[0]['message_count']==4
    new=ask(system,'Привет')
    assert new['conversation_id'] not in {first['conversation_id'],second['conversation_id']}
    assert new['context']['candidate'] is None
    old=system.get('/api/chat/conversations/'+second['conversation_id']).get_json()
    assert old['context']['candidate']['id']=='CV_VERA'
    assert len(old['messages'])==2


def test_conversation_list_pagination_and_legacy_titles(system):
    first=ask(system,'какие документы есть?')
    second=ask(system,'Привет')
    record=routes.chat_conversation_storage.get_by_id(first['conversation_id'])
    record.pop('title',None)
    routes.chat_conversation_storage.save(record)
    listing=system.get('/api/chat/conversations?limit=1').get_json()
    assert len(listing['conversations'])==1 and listing['next_offset']==1
    page=system.get('/api/chat/conversations?limit=1&offset=1').get_json()
    assert page['next_offset'] is None
    assert page['conversations'][0]['title']=='какие документы есть?'
    assert 'messages' not in page['conversations'][0]
    assert page['conversations'][0]['preview']
    for query in ['limit=0','limit=101','offset=-1','limit=bad']:
        assert system.get('/api/chat/conversations?'+query).status_code==400
    assert system.get('/api/chat/conversations/missing').status_code==404


def test_chat_history_controls_render(system):
    page=system.get('/chat').get_data(as_text=True)
    for marker in ['conversationList','loadMoreConversations','chatSidebar','currentConversationTitle','Новый диалог','История диалогов']:
        assert marker in page

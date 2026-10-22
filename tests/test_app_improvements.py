"""Сценарии доработок: изолированные хранилища, без изменения рабочей базы."""
from io import BytesIO
from types import SimpleNamespace
import pytest
from app import app
from src.routes import main as routes
from src.chat.resolution import resolve_candidate
from src.chat.service import ChatService
from src.core.rag_pipeline import RagPipeline
from src.services.interview_service import InterviewService
from src.storage.interview_storage import InterviewStorage
from src.services.chat_history_service import ChatHistoryService


@pytest.mark.parametrize("message,scenario", [
    ("покажи кандидатов для собеседования", "candidate_list"),
    ("покажи руководство по собеседованию", "document_search"),
    ("объясни её оценку", "score_explanation"),
    ("какой у него этап", "candidate_stage"),
    ("когда у него интервью", "candidate_interviews"),
    ("подготовь вопросы для собеседования", "interview_questions"),
    ("переведи на этап интервью", "action"),
    ("где в регламенте описана оценка", "document_search"),
])
def test_intents(message, scenario):
    assert ChatService._scenario(message) == scenario


def test_candidate_resolution_switch_missing_and_ambiguous():
    candidates = [{"id": "C1", "name": "Агафонова Анна"}, {"id": "C2", "name": "Бахрамова Вера"}]
    assert resolve_candidate("объясни оценку Агафановой", candidates)["id"] == "C1"
    assert resolve_candidate("найди Бахрамову", candidates)["id"] == "C2"
    assert resolve_candidate("объясни её оценку", candidates) is None
    with pytest.raises(ValueError, match="не найден"):
        resolve_candidate("найди Несуществующую", candidates)
    with pytest.raises(ValueError, match="несколько"):
        resolve_candidate("найди Агафанову", candidates + [{"id": "C3", "name": "Агафонова Вера"}])


@pytest.fixture
def document_client(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "DOCS_DIR", tmp_path / "samples")
    monkeypatch.setattr(routes, "UPLOAD_DOCS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(routes, "DOCUMENTS", [])
    monkeypatch.setattr(routes, "rag_pipeline", RagPipeline(backend="tfidf"))
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_document_upload_read_download_and_restart(document_client):
    text = 'Правила отпуска: согласуйте отпуск с руководителем.'
    response = document_client.post('/documents/upload', data={'file': (BytesIO(text.encode()), 'Правила отпуска.txt')})
    assert response.status_code == 302
    assert 'uploaded=1' in response.location
    catalog = routes.rag_pipeline.list_documents()
    assert catalog[0]['title'] == 'Правила отпуска'
    doc_id = catalog[0]['id']
    assert text in document_client.get('/documents/' + doc_id).get_data(as_text=True)
    assert document_client.get('/documents/' + doc_id + '/download').data.decode() == text
    assert routes.rag_pipeline.ask('отпуск').hits
    assert routes._library_documents()[0].title == 'Правила отпуска'
    assert document_client.get('/documents/not-found').status_code == 404


@pytest.mark.parametrize('name,data', [('bad.pdf', b'not a pdf'), ('empty.txt', b' '), ('bad.exe', b'content')])
def test_invalid_upload_does_not_pollute_catalog(document_client, name, data):
    response = document_client.post('/documents/upload', data={'file': (BytesIO(data), name)})
    assert 'error=' in response.location
    assert routes.rag_pipeline.list_documents() == []
    assert routes._library_documents() == []


def test_escape_document_highlighting():
    result = routes._highlight_text('<script>alert(1)</script> отпуск', 'отпуск')
    assert '<script>' not in result
    assert '&lt;script&gt;' in result


def interview_payload(**changes):
    return dict(candidate_id='C1', candidate_name='Анна', vacancy_id='V1', date='2099-01-01', time='10:00', duration=60, format='online', **changes)


def test_interview_overlap_and_back_to_back(tmp_path):
    service = InterviewService(InterviewStorage(tmp_path / 'interviews.json'))
    first = service.create(interview_payload())
    with pytest.raises(ValueError, match='уже назначено'):
        service.create({**interview_payload(), 'time': '10:30'})
    second = service.create({**interview_payload(), 'time': '11:00'})
    with pytest.raises(ValueError, match='уже назначено'):
        service.update(second['id'], {'time': '10:45'})
    service.update(first['id'], {'status': 'cancelled'})
    assert service.update(second['id'], {'time': '10:00'})
    with pytest.raises(ValueError, match='статус'):
        service.update(second['id'], {'status': 'unknown'})


def test_interview_warnings(tmp_path):
    service = InterviewService(InterviewStorage(tmp_path / 'interviews.json'))
    assert service.create({**interview_payload(), 'date': '2000-01-01'})['warnings']
    service.create(interview_payload())
    assert service.create({**interview_payload(), 'candidate_id': 'C2'})['warnings']


def test_stage_synchronization_does_not_regress_offer(monkeypatch):
    calls = []
    relation = {'status': 'interview'}
    monkeypatch.setattr(routes, 'candidate_vacancy_storage', SimpleNamespace(find=lambda *args: relation))
    monkeypatch.setattr(routes, 'interview_service', SimpleNamespace(list_by_candidate=lambda _: []))
    monkeypatch.setattr(routes, 'candidate_stage_service', SimpleNamespace(transition=lambda *args, **kwargs: calls.append(args)))
    routes._sync_interview_stage({'candidate_id': 'C1', 'vacancy_id': 'V1'})
    assert calls[-1][2] == 'in_review'
    relation['status'] = 'offer'
    routes._sync_interview_stage({'candidate_id': 'C1', 'vacancy_id': 'V1'})
    assert len(calls) == 1


def test_dashboard_counts_actual_interviews(monkeypatch):
    from datetime import datetime
    monkeypatch.setattr(routes, 'storage', SimpleNamespace(list_candidates=lambda: []))
    monkeypatch.setattr(routes, 'interview_service', SimpleNamespace(list_all=lambda: [
        {'date': datetime.now().strftime('%Y-%m-%d'), 'status': 'scheduled'},
        {'date': datetime.now().strftime('%Y-%m-%d'), 'status': 'cancelled'}]))
    monkeypatch.setattr(routes, '_available_vacancies', lambda: [])
    monkeypatch.setattr(routes, 'render_template', lambda name, **context: context)
    with app.test_request_context('/'):
        assert routes.index()['stats']['interviews_today'] == 1


def test_candidate_context_persists_and_switches(monkeypatch):
    class Store:
        def __init__(self): self.items = {}
        def get_by_id(self, key): return self.items.get(key)
        def list_all(self): return list(self.items.values())
        def save(self, record):
            record = dict(record)
            record.setdefault('id', str(len(self.items) + 1))
            self.items[record['id']] = record
            return record
        def list_by_conversation(self, key): return [i for i in self.items.values() if i.get('conversation_id') == key]
        def find_by_message(self, key): return next((i for i in self.items.values() if i.get('message_id') == key), None)
    conversations, messages, actions, feedback = Store(), Store(), Store(), Store()
    service = ChatHistoryService(conversations, messages, actions, feedback)
    candidates = [{'id': 'CV_1', 'name': 'Агафонова Анна', 'vacancy_id': 'V1'}, {'id': 'CV_2', 'name': 'Бахрамова Вера', 'vacancy_id': 'V2'}]
    monkeypatch.setattr(routes, 'storage', SimpleNamespace(list_candidates=lambda: candidates, get_candidate=lambda key: next((c for c in candidates if c['id'] == key), None)))
    monkeypatch.setattr(routes, 'vacancy_service', SimpleNamespace(get_by_id=lambda key: {'id': key, 'title': key}))
    monkeypatch.setattr(routes, '_chat_history_service', lambda: service)
    calls = []
    def ask(message, **kwargs):
        calls.append(kwargs)
        return {'answer': 'Ответ', 'sources': [], 'suggested_action': None}
    monkeypatch.setattr(routes, '_chat_service', lambda: SimpleNamespace(ask=ask))
    with app.test_client() as client:
        response = client.post('/api/chat', json={'message': 'найди Агафонову'}).get_json()
        conversation_id = response['conversation_id']
        assert response['context']['candidate']['id'] == 'CV_1'
        client.post('/api/chat', json={'message': 'объясни её оценку', 'conversation_id': str(conversation_id)})
        assert calls[-1]['candidate_id'] == 'CV_1'
        client.post('/api/chat', json={'message': 'найди Бахрамову', 'conversation_id': conversation_id})
        assert calls[-1]['candidate_id'] == 'CV_2'
        assert calls[-1]['vacancy_id'] == 'V2'
        selected = service.record_exchange(conversation_id, candidate_id='CV_2', vacancy_id='V2', user_message='найди Бахрамову', assistant_result={'answer':'Ответ'})
        assert selected['conversation']['candidate_id'] == 'CV_2'


def test_missing_candidate_does_not_open_first_record(monkeypatch):
    monkeypatch.setattr(routes, 'storage', SimpleNamespace(list_candidates=lambda: [{'id':'C1', 'name':'Анна'}]))
    with app.test_client() as client:
        assert client.get('/candidate/not-existing').status_code == 404


def test_document_title_is_searchable():
    from src.core.loaders import LoadedDocument
    rag = RagPipeline(backend='tfidf')
    rag.build_index([LoadedDocument('guide', 'Interview Guide', 'Руководство по собеседованию. Подготовка вопросов.', 'interview_guide.docx', 'docx')])
    assert rag.ask('Покажи документ Interview Guide').hits[0].score > .15


def test_history_restores_feedback_and_actions():
    conversation = {'id': 'CHAT_1', 'candidate_id': 'C1'}
    message = {'id': 1, 'role': 'assistant', 'sources': [{'source':'policy.txt'}]}
    feedback = {'message_id':1, 'rating':'useful'}
    action = {'id':'A1', 'message_id':1, 'status':'confirmed'}
    service = ChatHistoryService(SimpleNamespace(get_by_id=lambda _: conversation),
        SimpleNamespace(list_by_conversation=lambda _: [message]),
        SimpleNamespace(list_all=lambda: [action]),
        SimpleNamespace(find_by_message=lambda _: feedback))
    restored = service.conversation('CHAT_1')['messages'][0]
    assert restored['feedback']['rating'] == 'useful'
    assert restored['actions'][0]['status'] == 'confirmed'
    assert restored['sources'][0]['source'] == 'policy.txt'


def test_explain_zero_from_critical_filters():
    from src.chat.responses import structured_answer
    answer = structured_answer({'scenario':'score_explanation', 'candidate':{'name':'Анна'}, 'score':{'total':0, 'critical_failures':['Сертификат не подтверждён']}})
    assert 'Сертификат не подтверждён' in answer
    assert 'критическим фильтрам' in answer


@pytest.mark.parametrize('query', ['дата интервью Архиповой', 'во сколько собеседование Архиповой', 'покажи дату интервью Архиповой'])
def test_interview_date_query_uses_calendar(query):
    from src.chat.responses import structured_answer
    assert ChatService._scenario(query) == 'candidate_interviews'
    candidate = resolve_candidate(query, [{'id':'C1', 'name':'Архипова Валентина Викторовна'}])
    assert candidate['id'] == 'C1'
    answer = structured_answer({'scenario':'candidate_interviews', 'candidate':candidate,
        'interviews':[{'date':'2026-10-22', 'time':'17:00', 'duration':60, 'format':'online', 'status':'scheduled'}]})
    assert '2026-10-22 17:00' in answer
    assert 'Оценка:' not in answer


@pytest.mark.parametrize('message', ['дата интервью агафоновой и её оценка', 'оценка Агафоновой и дата собеседования', 'покажи дату интервью и оценку'])
def test_compound_interview_and_score(message):
    from src.chat.models import MockChatModel
    score = {'total':71, 'scores':{'hard':8.7}, 'used_weights':{'hard':100}}
    context = {'candidate':{'id':'C1','name':'Агафонова'}, 'vacancy':None, 'score':score,
        'score_explanation':[{'label':'Навыки','score':8.7,'weight':100}],
        'interviews':[{'date':'2026-10-22','time':'16:00','duration':60,'format':'online','status':'scheduled'}]}
    tools = SimpleNamespace(context=lambda *args, **kwargs: dict(context), propose_action=lambda *args: None)
    service = ChatService(MockChatModel(), tools, RagPipeline(backend='tfidf'))
    result = service.ask(message, candidate_id='C1')
    assert '2026-10-22 16:00' in result['answer']
    assert '71/100' in result['answer']
    assert 'запланировано' in result['answer']
    assert result['sources'] == []
    context['interviews'] = []
    context['score'] = {}
    result = service.ask(message, candidate_id='C1')
    assert 'нет назначенных интервью' in result['answer']
    assert 'нет сохранённой оценки' in result['answer']

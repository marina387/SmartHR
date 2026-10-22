import unittest
from pathlib import Path
from types import SimpleNamespace
from src.chat.models import TransformersChatModel
from src.chat.service import ChatService
from src.core.rag_pipeline import RagPipeline

class DocumentSearchRegressionTests(unittest.TestCase):
    def service(self):
        rag = RagPipeline(backend='tfidf')
        rag.build_index({'onboarding': 'Адаптация нового сотрудника. В первый рабочий день наставник знакомит сотрудника с командой.', 'interview': 'Проведение интервью: подготовка вопросов и обсуждение опыта кандидата.'})
        tools = SimpleNamespace(context=lambda *a, **kw: {}, propose_action=lambda *a: None)
        model = TransformersChatModel(Path('unused'), {})
        model._load = lambda: self.fail('Document lookup should not load LLM')
        return ChatService(model, tools, rag)

    def test_find_document_is_not_candidate_search(self):
        result = self.service().ask('Найди в документах про адаптацию сотрудника')
        self.assertIn('наставник', result['answer'])
        self.assertEqual(result['sources'][0]['id'], 'onboarding')

    def test_vague_query_asks_for_topic(self):
        result = self.service().ask('Найди информацию в HR-документах')
        self.assertIn('Уточните', result['answer'])
        self.assertEqual(result['sources'], [])

    def test_document_priority_over_score_keywords(self):
        self.assertEqual(ChatService._scenario('Объясни регламент оценки'), 'document_search')

    def test_inflected_topic_without_document_keyword(self):
        result = self.service().ask('Что сказано об адаптации?')
        self.assertEqual(result['sources'][0]['id'], 'onboarding')

    def test_interview_candidate_list_is_not_document_search(self):
        from src.chat.tools import SmartHRChatTools
        candidates = SimpleNamespace(list_candidates=lambda: [
            {'id': '1', 'name': 'Анна'}, {'id': '2', 'name': 'Борис'},
            {'id': '3', 'name': 'Вера', 'lifecycle_status': 'archived'}])
        relations = SimpleNamespace(list_all=lambda: [
            {'candidate_id': '1', 'vacancy_id': 'v1', 'status': 'interview'},
            {'candidate_id': '2', 'vacancy_id': 'v1', 'status': 'interview_completed'},
            {'candidate_id': '3', 'vacancy_id': 'v1', 'status': 'interview'}])
        service = self.service()
        service.tools = SmartHRChatTools(candidates, None, relations, None, None, None)
        for query in ['покажи список кандидатов для собеседования', 'покажи кандидатов на интервью']:
            result = service.ask(query)
            self.assertIn('Анна', result['answer'])
            self.assertNotIn('Борис', result['answer'])
            self.assertNotIn('Вера', result['answer'])
            self.assertEqual(result['sources'], [])
        self.assertIn('нет кандидатов', service.ask(query, vacancy_id='missing')['answer'])
        self.assertEqual(ChatService._scenario('покажи руководство по собеседованию кандидатов'), 'document_search')

    def test_score_explanation_includes_weights_and_saved_evidence(self):
        from src.chat.tools import SmartHRChatTools
        model = TransformersChatModel(Path('unused'), {})
        model._load = lambda: self.fail('Structured explanation should not load LLM')
        score = {'total': 71, 'scores': {'hard': 8.7, 'soft': 5, 'management': 5, 'education': 10, 'salary': 5}, 'used_weights': {'hard': 50, 'soft': 30, 'management': 10, 'education': 5, 'salary': 5}, 'evidence': {'management': 'Управленческий опыт не обнаружен'}}
        context = {'scenario': 'score_explanation', 'candidate': {'name': 'Анна'}, 'score': score, 'score_explanation': SmartHRChatTools.explain_score(score)}
        answer = model.generate([{'role': 'user', 'content': 'объясни оценку Анны'}], context)
        for expected in ['71/100', '8.7/10', '50%', '43.5', 'Управленческий опыт не обнаружен']:
            self.assertIn(expected, answer)
        context['score_explanation'] = []
        self.assertIn('не сохранена', model.generate([], context))
        context['score'] = {}
        self.assertIn('нет сохранённой оценки', model.generate([], context))

    def test_document_availability_followup_after_catalog(self):
        from src.core.loaders import load_hr_documents
        service = self.service()
        service.rag.build_index(load_hr_documents(Path(__file__).resolve().parents[1] / 'docs' / 'sample_docs'))
        history = [{'role':'user', 'content':'какие документы есть в базе?'}, {'role':'assistant', 'content':'В базе есть документы...'}]
        for query, expected in [('а трудовой кодекс?', False), ('а корпоративный кодекс?', True)]:
            result = service.ask(query, history=history)
            self.assertEqual(result['answer'], 'Да, документ есть в базе.' if expected else 'Нет, документа в базе нет.')
        result = service.ask('Покажи корпоративный кодекс', history=history)
        self.assertIn('Источник:', result['answer'])

    def test_document_listing_is_separate_from_availability(self):
        service = self.service()
        for query in ['а какие документы есть?', 'какие документы есть в базе?', 'покажи список документов', 'покажи все документы']:
            result = service.ask(query)
            self.assertIn('• onboarding', result['answer'])
            self.assertIn('• interview', result['answer'])
        service.rag.build_index({})
        self.assertEqual(service.ask('какие документы есть?')['answer'], 'В базе пока нет документов.')

    def test_document_availability_uses_catalog_not_contents(self):
        from src.core.loaders import load_hr_documents
        service = self.service()
        service.rag.build_index(load_hr_documents(Path(__file__).resolve().parents[1] / 'docs' / 'sample_docs'))
        for query, expected in [('в базе есть трудовой кодекс?', False), ('в базе есть корпоративный кодекс?', True), ('есть руководство по собеседованию?', True)]:
            result = service.ask(query)
            self.assertEqual(result['answer'], 'Да, документ есть в базе.' if expected else 'Нет, документа в базе нет.')
            self.assertEqual(result['sources'], [])

    def test_user_interview_guide_requests(self):
        from src.core.loaders import load_hr_documents
        service = self.service()
        service.rag.build_index(load_hr_documents(Path(__file__).resolve().parents[1] / 'docs' / 'sample_docs'))
        for query in ['дай руководство по собеседованию', 'покажи руководство по собеседованию']:
            result = service.ask(query)
            self.assertEqual(result['sources'][0]['id'], 'interview_guide')
            self.assertIn('Источник:', result['answer'])

    def test_project_documents_rank_and_reject_unrelated_topics(self):
        from src.core.loaders import load_hr_documents
        service = self.service()
        service.rag.build_index(load_hr_documents(Path(__file__).resolve().parents[1] / 'docs' / 'sample_docs'))
        for query, expected in [('Найди в документах про адаптацию сотрудника', 'onboarding_guide'), ('Как проводится интервью?', 'interview_guide')]:
            self.assertEqual(service.ask(query)['sources'][0]['id'], expected)
        self.assertEqual(service.ask('Найди в документах квантовую хромодинамику')['sources'], [])

    def test_unrelated_query_does_not_invent_answer(self):
        result = self.service().ask('Найди в документах квантовую хромодинамику')
        self.assertEqual(result['sources'], [])
        self.assertIn('не найден', result['answer'])

if __name__ == '__main__':
    unittest.main()

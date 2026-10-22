import sys
sys.path.append('.')

from src.matching_service import MatchingService
import pandas as pd

def test_prediction():
    """Тестирование предсказаний"""
    print(" Инициализация сервиса...")
    service = MatchingService()

    # Загружаем датасеты для теста
    candidates = pd.read_csv('data/candidates.csv')
    vacancies = pd.read_csv('data/vacancies.csv')

    print(f" Загружено кандидатов: {len(candidates)}")
    print(f" Загружено вакансий: {len(vacancies)}")

    # Тест 1: Одиночное предсказание
    print("\n Тест 1: Одиночное предсказание")
    result = service.predict_match(candidate_id=1, vacancy_id=1)
    print(f"Кандидат: {result['candidate_name']}")
    print(f"Вакансия: {result['vacancy_title']}")
    print(f"Вероятность: {result['match_probability']}")
    print(f"Решение: {result['decision']}")
    print(f"Детали: {result['details']}")

    # Тест 2: Batch prediction
    print("\n Тест 2: Массовое предсказание")
    candidate_ids = [1, 2, 3, 4, 5]
    results = service.batch_predict(candidate_ids, vacancy_id=1)

    for r in results:
        status = "✅" if r['decision'] == 'invite' else "❌"
        print(f"{status} Кандидат {r['candidate_name']}: {r['match_probability']}")

    # Тест 3: Поиск лучших кандидатов
    print("\n Тест 3: Топ-5 кандидатов для вакансии")
    best = service.find_best_candidates(vacancy_id=1, top_n=5)

    for i, c in enumerate(best, 1):
        print(f"{i}. {c['candidate_name']} - {c['match_probability']}")

    print("\n✅ Тестирование завершено!")

if __name__ == '__main__':
    test_prediction()

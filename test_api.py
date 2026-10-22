import requests
import json

print(" Тестирование SmartHR API...")
print("=" * 50)

try:
    response = requests.post("http://localhost:5000/match", timeout=10)

    if response.status_code == 200:
        data = response.json()

        print(f" Сервер работает!")
        print(f" Всего комбинаций: {data['total_pairs']}")
        print(f" Приглашений: {data['invites']}")
        print(f"\n Топ-5 лучших совпадений:")
        print("-" * 50)

        for i, result in enumerate(data['results'][:5], 1):
            print(f"\n{i}. {result['details']['name']} → {result['details']['position']}")
            print(f"    Совпадение: {result['match_score']:.1%}")
            print(f"   {' ПРИГЛАШЕН' if result['invited'] else '❌ ОТКЛОНЕН'}")
            print(f"    Навыки: {result['details']['skills_match']:.0%} | Опыт: {result['details']['experience_score']:.0%} | Зарплата: {result['details']['salary_score']:.0%}")
    else:
        print(f" Ошибка: {response.status_code}")

except requests.exceptions.ConnectionError:
    print(" Не удалось подключиться к серверу!")
    print("Убедитесь, что сервер запущен на http://localhost:5000")
except Exception as e:
    print(f" Ошибка: {e}")

print("\n" + "=" * 50)
print(" Совет: Откройте http://localhost:5000 в браузере")

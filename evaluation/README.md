# Оценка базовой модели

Запуск:

```bash
python evaluation/evaluate_model.py
```

Скрипт загружает готовую `models/matching_model.pkl`, восстанавливает исходную
тестовую часть с `random_state=42` и создаёт отчёт в `evaluation/results`.
Метод `fit` не вызывается, файл модели не изменяется.

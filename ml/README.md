# ML-компонент

## Структура папок

Структура каталога ML-компонента следующая:

```text
ml/
├── data/
│   ├── raw/
│   ├── processed/
│   └── training/
├── notebooks/
├── src/
├── models/
├── config.py
└── README.md
```

- data/raw/ — исходные CSV-файлы с данными
- data/processed/ — промежуточные и очищенные данные
- data/training/ — данные, подготовленные для обучения
- notebooks/ — Jupyter-ноутбуки для анализа и экспериментов
- src/ — исходный код для очистки, признаков, обучения и инференса
- models/ — папка для сохранённых моделей

## Источник данных

Данные предполагается брать с портала «Работа в России» (Роструд).

Ожидаемые исходные файлы:

- vacancies.csv
- curricula_vitae.csv
- workexp.csv
- edu.csv
- responses.csv

## Формат данных

Ниже описаны основные таблицы, которые используются в ML-пайплайне.

### Резюме (resumes_features.csv)

| Колонка | Тип | Пример значения |
|---|---|---|
| resume_id | string | "res_001" |
| region | string | "Москва" |
| profession | string | "Python-разработчик" |
| salary_expectation | float | 180000.0 |
| education_level | string | "Высшее" |
| education_profession | string | "Информатика" |
| total_experience_years | int | 3 |
| companies_count | int | 2 |
| position_names | string | "Backend Developer" |
| duties_text | string | "Разработка API" |
| skills_text | string | "Python, FastAPI, SQL" |

### Вакансии (vacancies_features.csv)

| Колонка | Тип | Пример значения |
|---|---|---|
| vacancy_id | string | "vac_001" |
| region | string | "Санкт-Петербург" |
| profession | string | "Data Scientist" |
| salary_from | float | 200000.0 |
| salary_to | float | 250000.0 |
| experience_required | string | "3-6 лет" |
| employment | string | "Полная занятость" |
| schedule | string | "Удалённо" |
| key_skills_text | string | "Python, ML, SQL" |
| requirements_text | string | "Опыт с scikit-learn" |
| duties_text | string | "Разработка моделей" |

### Обучающие пары (full_dataset.csv)

| Колонка | Тип | Пример значения |
|---|---|---|
| resume_id | string | "res_001" |
| vacancy_id | string | "vac_001" |
| region_match | int | 1 |
| salary_diff | float | 20000.0 |
| experience_match | int | 1 |
| skills_match | float | 0.75 |
| target | int | 1 |

## Порядок работы

Выполнять действия в следующем порядке:

```bash
# 1. Положить CSV-файлы в папку data/raw/

# 2. Запустить очистку данных
python -m ml.src.data_cleaner

# 3. Сформировать признаки
python -m ml.src.features

# 4. Обучить модель
python -m ml.src.train

# 5. Получить предсказания
python -m ml.src.predict
```

## Целевая переменная

Целевая переменная `target` задаёт результат взаимодействия:

- `target = 1` — был отклик
- `target = 0` — отклика не было

## Ожидаемые метрики

| Метрика | Целевое значение |
|---|---:|
| Accuracy | > 0.85 |
| Precision | > 0.80 |
| Recall | > 0.75 |
| F1-score | > 0.77 |
| ROC-AUC | > 0.90 |

## Конфигурация

Пример содержимого файла `config.py`:

```python
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DATA_RAW = BASE_DIR / "data" / "raw"
DATA_PROCESSED = BASE_DIR / "data" / "processed"
DATA_TRAINING = BASE_DIR / "data" / "training"
MODELS_DIR = BASE_DIR / "models"

RANDOM_SEED = 42
TEST_SIZE = 0.2
TARGET_COLUMN = "target"
```

## TODO для разработчиков

Список задач для дальнейшей реализации:

- очистка и нормализация исходных данных
- создание и проверка признаков
- обучение модели на подготовленных данных
- реализация инференса для новых пар резюме/вакансий
- логирование процесса обучения и предсказания
- покрытие ключевых сценариев тестами

## Источники

- Портал «Работа в России» (Роструд): https://trudvsem.ru/
- Документация по структуре данных и формату выгрузок: https://trudvsem.ru/

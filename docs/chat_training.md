# Обучение чат-модели SmartHR

Контур рассчитан на дообучение готовой instruct-модели методом LoRA или QLoRA.
Полное обучение языковой модели с нуля не требуется.

## 1. Установка окружения

```bash
pip install -r requirements-training.txt
```

Для QLoRA дополнительно устанавливается версия `bitsandbytes`, совместимая с CUDA и
операционной системой команды обучения. Если она недоступна, в конфигурации выбирают
`method: lora`.

## 2. Получение реальных примеров из SmartHR

Только ответы с исправлением HR и флагом разрешения экспортируются командой:

```bash
python scripts/export_chat_training_data.py
```

Результат попадает в `data/chat/raw/approved_chat_feedback.jsonl`. Несмотря на ручное
подтверждение, файл обязательно проходит обезличивание:

```bash
python scripts/anonymize_chat_data.py
python scripts/validate_chat_dataset.py data/chat/anonymized --require-approved
python scripts/prepare_chat_dataset.py
```

## 3. Конфигурация

Скопируйте `configs/chat_training.example.yaml` в `configs/chat_training.yaml` и
укажите идентификатор базовой модели. Пути к данным, выходной каталог, метод и
гиперпараметры изменяются без редактирования Python-кода.

Текущая конфигурация использует подготовленный синтетический набор и разрешает
неподтверждённые записи только при одновременном наличии `synthetic: true`.
Параметр `allow_unapproved_synthetic: true` не разрешает добавлять в обучение
непроверенные реальные диалоги.

Проверка без обучения:

```bash
python scripts/train_chat_model.py --config configs/chat_training.yaml --check
```

## 4. Обучение

```bash
python scripts/train_chat_model.py --config configs/chat_training.yaml
```

Продолжение с последней контрольной точки:

```bash
python scripts/train_chat_model.py --config configs/chat_training.yaml --resume
```

Скрипт сохраняет LoRA-адаптер, токенизатор и `smarthr_model_metadata.json` в
`output_dir`. Исходная модель не перезаписывается.

## 5. Независимая оценка

```bash
python scripts/evaluate_chat_model.py --model models/chat_model_candidate --test data/chat/test.jsonl
```

В `evaluation/chat` создаются:

- `metrics.json` — точное совпадение, token F1 и доля пустых ответов;
- `predictions.jsonl` — ответы модели и эталоны;
- `hr_review.csv` — таблица ручной проверки фактов, источников, безопасности и пользы.

Автоматические текстовые метрики являются вспомогательными. Решение об установке
модели принимается после ручной проверки HR.

## 6. Проверка и установка

```bash
python scripts/install_chat_model.py models/chat_model_candidate --check-only
python scripts/install_chat_model.py models/chat_model_candidate --smoke-test
```

Установщик проверяет структуру, метаданные, веса и токенизатор. Существующая модель
перемещается в каталог `chat_model_backup_YYYYMMDD_HHMMSS`, после чего новый артефакт
копируется в `models/chat_model`. При ошибке старая версия восстанавливается.

После перезапуска SmartHR автоматически определит полную модель или LoRA-адаптер.
Изменять API, интерфейс или исходный код не требуется.

## Ограничения

- реальные резюме и диалоги не добавляются в Git;
- один кандидат не может находиться одновременно в train и test;
- в финальное обучение допускаются записи `approved_by_hr: true`; для первого
  эксперимента отдельно разрешаются явно помеченные записи `synthetic: true`;
- автоматическое обезличивание всегда дополняется ручной проверкой;
- пароли, токены доступа и персональные данные не включаются в промпты и метаданные;
- параметры QLoRA зависят от конкретной GPU и версии CUDA.

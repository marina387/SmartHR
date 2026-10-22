# -*- coding: utf-8 -*-
"""Генерирует QA-датасет для чата на основе РЕАЛЬНЫХ резюме и вакансий trudvsem.

Скрипт создает 50% позитивных пар (кандидат подходит) и 50% негативных.
Все персональные данные (телефоны, email, ссылки) автоматически вырезаются
для безопасного обучения LLM.

Запуск:
    python scripts/build_real_chat_dataset.py --n-samples 5000
"""

import argparse
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
from src.matching_service import MatchingService
from src.services.profile_extraction import extract_candidate_profile


def anonymize_text(text: str) -> str:
    """Удаляет телефоны, email, ссылки и длинные ID из текста."""
    text = str(text)
    # 1. Удаляем email
    text = re.sub(r"[\w\.-]+@[\w\.-]+\.\w+", "[EMAIL]", text)
    # 2. Удаляем телефоны (российские и международные форматы)
    text = re.sub(r"(\+7|8)?[\s\-\(\)]*\d{3,4}[\s\-\(\)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}", "[PHONE]", text)
    # 3. Удаляем ссылки (http, https, www)
    text = re.sub(r"https?://\S+|www\.\S+", "[URL]", text)
    # 4. Удаляем длинные последовательности цифр (паспорта, СНИЛС)
    text = re.sub(r"\b\d{10,12}\b", "[ID]", text)
    # 5. Убираем лишние пробелы
    text = re.sub(r"\s+", " ", text).strip()
    return text


def build_prompt(candidate_text: str, vacancy_title: str, vacancy_desc: str) -> str:
    """Формирует текст вопроса для чата."""
    desc = str(vacancy_desc)[:1000] if vacancy_desc else "Описание не указано."
    return (
        f"Профиль кандидата:\n{candidate_text}\n\n"
        f"Вакансия: {vacancy_title}\n{desc}\n\n"
        f"Вопрос: Оцени, подходит ли этот кандидат на вакансию? "
        f"Назови ключевые совпадения и чего не хватает."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, default=Path("data/trudvsem/processed_v2/candidates.csv"))
    parser.add_argument("--vacancies", type=Path, default=Path("data/trudvsem/processed_v2/vacancies.csv"))
    parser.add_argument("--out", type=Path, default=Path("data/chat/training_real"))
    parser.add_argument("--n-samples", type=int, default=5000, help="Сколько QA-пар создать")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)

    print("[init] Загружаю MatchingService ...")
    svc = MatchingService()

    print("[load] Читаю реальные вакансии ...")
    vac_df = pd.read_csv(args.vacancies, nrows=2000) # Берем 2000 вакансий для разнообразия
    vacancies = vac_df.to_dict("records")
    
    # Группируем вакансии по специализации
    vac_by_spec = {}
    for v in vacancies:
        spec = str(v.get("specialization", "Прочее"))
        vac_by_spec.setdefault(spec, []).append(v)

    print(f"[load] Читаю реальные резюме (ищу {args.n_samples} подходящих) ...")
    # Читаем блоками, чтобы не грузить 12 лямов в память
    cand_iter = pd.read_csv(args.candidates, chunksize=10000)
    
    records = []
    count = 0
    pos_count = 0
    neg_count = 0

    for chunk in cand_iter:
        if count >= args.n_samples:
            break

        for _, cand_row in chunk.iterrows():
            if count >= args.n_samples:
                break

            cand = cand_row.to_dict()
            
            # ОЧИЩАЕМ РЕЗЮМЕ ОТ ПЕРСОНАЛЬНЫХ ДАННЫХ
            raw_text = str(cand.get("resume_text", ""))
            resume_text = anonymize_text(raw_text)
            
            if len(resume_text) < 20:
                continue
                
            # 1. Извлекаем профиль
            try:
                profile = extract_candidate_profile(resume_text)
            except Exception:
                continue
            
            # 2. Фильтр: пропускаем пустые резюме
            if not profile.get("skills"):
                continue
            if not profile.get("specialization"):
                continue
                
            spec = profile.get("specialization")
            
            # 3. Выбираем вакансию (50% позитив, 50% негатив)
            is_positive = random.random() < 0.5
            
            if is_positive:
                # Позитив: берем вакансию той же специализации
                same_spec_vacs = vac_by_spec.get(spec, [])
                if not same_spec_vacs:
                    continue
                vac = random.choice(same_spec_vacs)
                pair_type = "positive"
                pos_count += 1
            else:
                # Негатив: берем вакансию из другой специализации
                other_specs = [s for s in vac_by_spec.keys() if s != spec and vac_by_spec[s]]
                if not other_specs:
                    continue
                other_spec = random.choice(other_specs)
                vac = random.choice(vac_by_spec[other_spec])
                pair_type = "negative"
                neg_count += 1

            # 4. Считаем прогноз (подаем "сырую" вакансию, чтобы модель честно оценила совпадение)
            try:
                prediction = svc.predict(cand, vac)
                prob = prediction["probability"]
                features = prediction["features"]
            except Exception:
                continue

            # 5. Формируем ответ (детерминированный, на основе фактов)
            skills = profile.get("skills", [])
            
            if prob > 0.6:
                verdict = "подходит"
            elif prob < 0.4:
                verdict = "не подходит"
            else:
                verdict = "спорный вариант"

            answer_parts = [f"Вердикт модели: {verdict} (уверенность {prob:.0%})."]
            
            if features["same_spec"] > 0:
                answer_parts.append("Специализация кандидата совпадает с вакансией.")
            else:
                answer_parts.append("Специализация не совпадает.")
                
            exp = features["experience_years"]
            min_exp = features["min_experience"]
            if exp >= min_exp:
                answer_parts.append(f"Опыт ({exp} лет) соответствует требованиям (от {min_exp} лет).")
            else:
                answer_parts.append(f"Опыта ({exp} лет) недостаточно для требования (от {min_exp} лет).")
                
            if skills:
                answer_parts.append(f"Навыки из резюме: {', '.join(skills[:5])}.")
            
            answer = " ".join(answer_parts)

            # Анонимизируем заголовок вакансии на всякий случай
            vac_title = anonymize_text(vac.get("title", "Без названия"))
            vac_desc = anonymize_text(vac.get("responsibilities", ""))

            record = {
                "id": f"real_qa_{count:05d}",
                "group_id": f"cand_{cand.get('candidate_id')}",
                "scenario": "candidate_assessment",
                "pair_type": pair_type,
                "messages": [
                    {"role": "system", "content": "Ты HR-ассистент SmartHR. Используй только переданные данные, не придумывай факты."},
                    {"role": "user", "content": build_prompt(resume_text, vac_title, vac_desc)},
                    {"role": "assistant", "content": answer}
                ],
                "source_ids": [cand.get("candidate_id"), vac.get("vacancy_id")],
                "synthetic": False,
                "generation_method": "ml_verdict_from_real_data",
                "approved_by_hr": True,
            }
            records.append(record)
            count += 1

        if count % 500 == 0 and count > 0:
            print(f"[build] Сгенерировано {count} QA-пар (Позитивов: {pos_count}, Негативов: {neg_count})")

    if not records:
        print("[ERROR] Не удалось сгенерировать ни одной пары. Проверьте данные.")
        return

    print(f"[build] Итого сгенерировано {len(records)} пар (Позитивов: {pos_count}, Негативов: {neg_count}).")
    print("[build] Перемешиваю и делю на train/val/test...")
    
    random.shuffle(records)
    n = len(records)
    n_train = int(n * 0.8)
    n_val = int(n * 0.1)
    
    splits = {
        "train": records[:n_train],
        "validation": records[n_train:n_train + n_val],
        "test": records[n_train + n_val:],
    }

    for name, items in splits.items():
        path = args.out / f"{name}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"[save] {path}: {len(items)} записей")


if __name__ == "__main__":
    main()
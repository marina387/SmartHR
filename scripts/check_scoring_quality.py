"""Read-only diagnostic examples, not a hiring benchmark or training dataset."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.services.profile_extraction import extract_candidate_profile
from src.services.scoring import CandidateScoringService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'data/test-runs/scoring-quality')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    artifacts = [ROOT/'models/matching_model.pkl', ROOT/'models/model_metadata.json']
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}
    service = CandidateScoringService()
    weights = dict(service.default_weights)
    rows = []
    for level, minimum in [('intern', 0), ('junior', 1), ('senior', 3)]:
        vacancy = dict(id='CONTROL_'+level, title=level+' Python / data', specialization='IT',
                       min_experience=minimum, max_experience=40, required_education='none',
                       required_skills=['Python', 'SQL', 'Excel'], critical_requirements=['Python'],
                       management_required=False, max_salary=0)
        for kind, experience, skills in [
            ('suitable', minimum+1 if minimum else 0, 'Python, SQL, Excel'),
            ('borderline', 0, 'Python'),
            ('unsuitable', 0, 'Word')]:
            text = (f'Специализация: IT\nОпыт: {experience} лет\nНавыки: {skills}\n'
                    'Образование: бакалавр\nАнглийский: B1\n'
                    'Учебный проект: очистка таблиц, анализ данных и проверка качества модели.')
            result = service.score_candidate(text, [], weights, vacancy=vacancy)
            rows.append(dict(id=f'{level}_{kind}', level=level, expectation=kind,
                             resume=text, vacancy=vacancy, profile=extract_candidate_profile(text), result=result))
    # Same numerical profile, only the vacancy's seniority wording changes.
    base = rows[0]
    renamed = {**base['vacancy'], 'title': 'Senior Python Developer',
               'description': 'Архитектура, промышленная разработка, самостоятельное ведение сложных проектов.'}
    title_result = service.score_candidate(base['resume'], [], weights, vacancy=renamed)
    probes = {}
    for name, text in {
        'missing_experience': base['resume'].replace('Опыт: 0 лет\n', ''),
        'negated_management': base['resume'] + '\nОпыта управления командой нет.',
    }.items():
        probes[name] = dict(profile=extract_candidate_profile(text),
                            result=service.score_candidate(text, [], weights, vacancy=base['vacancy']))
    payload = dict(scope='Synthetic diagnostic examples; expectations are hypotheses, not hiring labels.',
                   artifact_sha256=hashes, cases=rows, probes=probes,
                   title_only_probe=dict(original=base['result'], renamed=title_result))
    assert hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}
    (args.output/'results.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# Контрольные примеры оценки', '',
             'Синтетическая диагностика текущей модели. Это не оценка точности на реальных кандидатах. '
             'Названия suitable/borderline/unsuitable — предположения для проверки, не эталонные решения о найме.', '',
             '| Пример | Стаж | Совпадение навыков | Итог | Вероятность | Фильтр |',
             '|---|---:|---:|---:|---:|---|']
    for row in rows:
        r = row['result']
        probability = r.get('model_probability')
        probability_text = 'не рассчитывалась' if probability is None else f'{probability*100:.4f}%'
        lines.append(f"| {row['id']} | {row['profile']['experience_years']} | "
                     f"{r.get('features', {}).get('skills_match', '—')} | {r['total']} | "
                     f"{probability_text} | {', '.join(r['critical_failures']) or 'пройден'} |")
    lines += ['', 'Полные исходные тексты, вакансии, распознанные профили, признаки и комментарии — в results.json.',
              '', f"Проверка изменения только названия и описания: {base['result']['total']} → {title_result['total']}; "
              f"вероятность {base['result'].get('model_probability')} → {title_result.get('model_probability')}.",
              '']
    for name, probe in probes.items():
        result = probe['result']
        lines.append(f"Проба {name}: итог {result['total']}; вероятность {result.get('model_probability')}; "
                     f"управление {result['scores'].get('management')}; стаж {probe['profile']['experience_years']}.")
    lines += ['', 'Хеши модели и метаданных после проверки совпадают с исходными. База данных не открывалась.']
    (args.output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('Reports: ' + str(args.output))


if __name__ == '__main__':
    main()

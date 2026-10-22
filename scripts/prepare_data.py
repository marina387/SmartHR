import pandas as pd
import numpy as np
from faker import Faker
import random
from pathlib import Path

fake = Faker('ru_RU')

def create_candidates(num=1000):
    """Создание датасета кандидатов"""
    specializations = ['IT', 'Marketing', 'Finance', 'HR', 'Sales', 'Design', 'Management', 'Analytics']
    skills_pool = {
        'IT': ['Python', 'SQL', 'Java', 'JavaScript', 'Machine Learning', 'Docker', 'Kubernetes', 'AWS', 'Django', 'React', 'Node.js', 'Go', 'C++', 'Ruby', 'TypeScript'],
        'Marketing': ['SEO', 'SMM', 'Google Ads', 'Analytics', 'Content', 'Email', 'PPC', 'Branding', 'Copywriting', 'CRM'],
        'Finance': ['Excel', '1C', 'GAAP', 'IFRS', 'Audit', 'Tax', 'Financial Modeling', 'SAP', 'QuickBooks'],
        'HR': ['Recruiting', 'Onboarding', 'Performance Review', 'HR Analytics', 'Talent Management', 'Labor Law'],
        'Sales': ['CRM', 'Negotiation', 'Cold Calling', 'Presentation', 'B2B', 'B2C', 'Account Management'],
        'Design': ['Figma', 'Photoshop', 'Illustrator', 'UI/UX', 'Sketch', 'Prototyping', 'Design Systems'],
        'Management': ['Project Management', 'Agile', 'Scrum', 'Kanban', 'Team Leadership', 'Strategic Planning', 'Budgeting'],
        'Analytics': ['SQL', 'Python', 'Tableau', 'Power BI', 'Statistics', 'A/B Testing', 'Data Visualization', 'R']
    }

    candidates = []
    for i in range(num):
        spec = random.choice(specializations)
        exp = random.randint(0, 20)
        skills = random.sample(skills_pool[spec], min(random.randint(3, 8), len(skills_pool[spec])))

        candidate = {
            'candidate_id': i + 1,
            'name': fake.name(),
            'experience_years': exp,
            'skills': ', '.join(skills),
            'education': random.choice(['bachelor', 'master', 'phd', 'none']),
            'specialization': spec,
            'expected_salary': int(random.randint(30, 300) * (1 + exp * 0.05)),
            'last_position': fake.job(),
            'english_level': random.choices(['A1', 'A2', 'B1', 'B2', 'C1', 'C2'], weights=[5, 10, 30, 30, 15, 10])[0],
            'has_portfolio': random.choice([0, 1]),
            'soft_skills': ', '.join(random.sample(['Communication', 'Teamwork', 'Problem Solving', 'Leadership', 'Time Management', 'Adaptability', 'Creativity'], random.randint(2, 5))),
            'certifications': ', '.join(random.sample(['AWS Certified', 'PMP', 'Google Analytics', 'IELTS', 'CPA', 'CFA', 'Scrum Master', 'ITIL'], random.randint(0, 3)))
        }
        candidates.append(candidate)

    df = pd.DataFrame(candidates)
    Path('data').mkdir(exist_ok=True)
    df.to_csv('data/candidates.csv', index=False)
    print(f"✅ Создано {num} кандидатов")
    return df

def create_vacancies(num=50):
    """Создание датасета вакансий"""
    specializations = ['IT', 'Marketing', 'Finance', 'HR', 'Sales', 'Design', 'Management', 'Analytics']
    titles = {
        'IT': ['Python Developer', 'Data Scientist', 'Frontend Developer', 'DevOps Engineer', 'Backend Developer', 'Full Stack Developer', 'ML Engineer'],
        'Marketing': ['Marketing Manager', 'SEO Specialist', 'SMM Manager', 'Content Manager', 'PPC Specialist'],
        'Finance': ['Financial Analyst', 'Accountant', 'Auditor', 'CFO Assistant', 'Risk Manager'],
        'HR': ['HR Manager', 'Recruiter', 'HR Business Partner', 'Talent Acquisition Specialist'],
        'Sales': ['Sales Manager', 'Account Manager', 'Business Development', 'Sales Representative'],
        'Design': ['UX/UI Designer', 'Graphic Designer', 'Product Designer', 'Web Designer'],
        'Management': ['Project Manager', 'Product Manager', 'Team Lead', 'Operations Manager'],
        'Analytics': ['Data Analyst', 'Business Analyst', 'Analytics Manager', 'BI Developer']
    }

    vacancies = []
    for i in range(num):
        spec = random.choice(specializations)
        title = random.choice(titles[spec])
        min_exp = random.randint(0, 3)
        max_exp = min_exp + random.randint(1, 5)

        skills_pool = {
            'IT': ['Python', 'SQL', 'Java', 'JavaScript', 'Machine Learning', 'Docker', 'Kubernetes', 'AWS', 'Django', 'React', 'Node.js', 'Git', 'Linux'],
            'Marketing': ['SEO', 'SMM', 'Google Ads', 'Analytics', 'Content Strategy', 'CRM'],
            'Finance': ['Excel', '1C', 'Financial Analysis', 'Budgeting', 'Reporting'],
            'HR': ['Recruiting', 'Onboarding', 'HR Analytics', 'Labor Law', 'Interviewing'],
            'Sales': ['CRM', 'Negotiation', 'B2B Sales', 'Presentation'],
            'Design': ['Figma', 'Photoshop', 'UI/UX', 'Prototyping', 'Design Systems'],
            'Management': ['Agile', 'Scrum', 'Team Management', 'Strategic Planning'],
            'Analytics': ['SQL', 'Python', 'Data Visualization', 'Statistics', 'A/B Testing']
        }

        required_skills = random.sample(skills_pool[spec], min(random.randint(4, 8), len(skills_pool[spec])))

        vacancy = {
            'vacancy_id': i + 1,
            'title': title,
            'required_skills': ', '.join(required_skills),
            'min_experience': min_exp,
            'max_experience': max_exp,
            'min_salary': random.randint(50, 150) * 1000,
            'max_salary': random.randint(150, 400) * 1000,
            'required_education': random.choice(['bachelor', 'master', 'phd', 'any']),
            'english_required': random.choices(['A1', 'A2', 'B1', 'B2', 'C1', 'C2', 'any'], weights=[2, 5, 20, 30, 25, 15, 3])[0],
            'specialization': spec,
            'responsibilities': ', '.join(random.sample(['Development', 'Analysis', 'Planning', 'Coordination', 'Reporting', 'Support', 'Optimization'], random.randint(3, 5))),
            'company': fake.company()
        }
        vacancies.append(vacancy)

    df = pd.DataFrame(vacancies)
    Path('data').mkdir(exist_ok=True)
    df.to_csv('data/vacancies.csv', index=False)
    print(f"✅ Создано {num} вакансий")
    return df

def create_matches(candidates_df, vacancies_df, num_matches=5000):
    """Создание размеченных пар кандидат-вакансия с решением"""
    matches = []

    edu_levels = {'none': 0, 'bachelor': 1, 'master': 2, 'phd': 3}
    eng_levels = {'A1': 1, 'A2': 2, 'B1': 3, 'B2': 4, 'C1': 5, 'C2': 6}

    for match_id in range(1, num_matches + 1):
        candidate = candidates_df.sample(1).iloc[0]
        vacancy = vacancies_df.sample(1).iloc[0]

        # 1. Skills match (40% веса)
        cand_skills = set(s.strip().lower() for s in candidate['skills'].split(','))
        vac_skills = set(s.strip().lower() for s in vacancy['required_skills'].split(','))
        skills_overlap = len(cand_skills & vac_skills) / max(len(vac_skills), 1)

        # 2. Experience match (25% веса)
        if vacancy['min_experience'] <= candidate['experience_years'] <= vacancy['max_experience']:
            exp_score = 1.0
        elif candidate['experience_years'] < vacancy['min_experience']:
            exp_score = max(0, 1 - (vacancy['min_experience'] - candidate['experience_years']) / 5)
        else:
            exp_score = 0.8  # overqualified, но всё ещё неплохо

        # 3. Salary match (15% веса)
        cand_salary = candidate['expected_salary'] * 1000
        if cand_salary <= vacancy['max_salary']:
            salary_score = 1.0 if cand_salary >= vacancy['min_salary'] else 0.7
        else:
            salary_score = max(0, 1 - (cand_salary - vacancy['max_salary']) / vacancy['max_salary'])

        # 4. Education match (10% веса)
        req_edu = vacancy['required_education']
        if req_edu == 'any':
            edu_score = 1.0
        else:
            cand_edu = edu_levels.get(candidate['education'], 0)
            vac_edu = edu_levels.get(req_edu, 1)
            edu_score = 1.0 if cand_edu >= vac_edu else 0.5

        # 5. English match (10% веса)
        req_eng = vacancy['english_required']
        if req_eng == 'any':
            eng_score = 1.0
        else:
            cand_eng = eng_levels.get(candidate['english_level'], 0)
            vac_eng = eng_levels.get(req_eng, 0)
            eng_score = 1.0 if cand_eng >= vac_eng else max(0, 1 - (vac_eng - cand_eng) * 0.2)

        # Специализация (дополнительный буст)
        spec_bonus = 0.2 if candidate['specialization'] == vacancy['specialization'] else 0

        # Финальный скор
        match_score = (
            0.4 * skills_overlap +
            0.25 * exp_score +
            0.15 * salary_score +
            0.10 * edu_score +
            0.10 * eng_score +
            spec_bonus
        )
        match_score = min(1.0, match_score)  # Клиппинг до 1.0

        # Порог для решения
        decision = 1 if match_score > 0.6 else 0

        # Причина решения
        if decision == 1:
            reason = "Подходит по всем ключевым параметрам"
        else:
            reasons = []
            if skills_overlap < 0.6:
                reasons.append("Недостаточное совпадение навыков")
            if exp_score < 0.7:
                reasons.append("Опыт не соответствует требованиям")
            if salary_score < 0.7:
                reasons.append("Зарплатные ожидания выше бюджета")
            if edu_score < 0.7:
                reasons.append("Образование ниже требуемого уровня")
            if eng_score < 0.7:
                reasons.append("Уровень английского недостаточен")
            if not reasons:
                reasons.append("Общий балл ниже порогового значения")
            reason = "; ".join(reasons)

        matches.append({
            'match_id': match_id,
            'candidate_id': candidate['candidate_id'],
            'vacancy_id': vacancy['vacancy_id'],
            'match_score': round(match_score, 3),
            'decision': decision,
            'reason': reason
        })

    df = pd.DataFrame(matches)
    Path('data').mkdir(exist_ok=True)
    df.to_csv('data/matches.csv', index=False)
    print(f"✅ Создано {num_matches} размеченных пар")
    return df

if __name__ == '__main__':
    print("🚀 Генерация датасетов...")

    # Создаем датасеты
    candidates = create_candidates(1000)
    vacancies = create_vacancies(50)

    # Создаем размеченные пары
    matches = create_matches(candidates, vacancies, 5000)

    print("\n📊 Статистика датасетов:")
    print(f"   Кандидаты: {len(candidates)}")
    print(f"   Вакансии: {len(vacancies)}")
    print(f"   Размеченные пары: {len(matches)}")
    print(f"   Приглашено: {matches['decision'].sum()} ({matches['decision'].mean()*100:.1f}%)")
    print("\n✅ Все датасеты успешно созданы!")

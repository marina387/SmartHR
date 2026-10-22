# scripts/inspect_trudvsem.py
import pandas as pd

print("=== ВАКАНСИИ ===")
v = pd.read_csv("data/trudvsem/processed/vacancies.csv")
print(f"строк: {len(v):,}")
print(f"уникальных title: {v['title'].nunique():,}")
print(f"со skills: {(v['required_skills'].str.len() > 2).sum():,}")
print(f"со salary_min > 0: {(v['min_salary'] > 0).sum():,}")
print(f"education distribution:\n{v['required_education'].value_counts().head(10)}")
print(f"specialization distribution:\n{v['specialization'].value_counts().head(10)}")
print(f"experience distribution:\n{v['min_experience'].describe()}")

print("\n=== РЕЗЮМЕ (первые 100k) ===")
c = pd.read_csv("data/trudvsem/processed/candidates.csv", nrows=100_000)
print(f"строк: {len(c):,}")
print(f"со skills: {(c['skills'].str.len() > 2).sum():,}")
print(f"education distribution:\n{c['education'].value_counts().head(10)}")
print(f"specialization distribution:\n{c['specialization'].value_counts().head(10)}")
print(f"experience distribution:\n{c['experience_years'].describe()}")
print(f"english distribution:\n{c['english_level'].value_counts().head(10)}")
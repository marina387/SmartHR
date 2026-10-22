# -*- coding: utf-8 -*-
import pandas as pd

print("=== VACANCIES ===")
v = pd.read_csv("data/trudvsem/processed_v2/vacancies.csv")
print(f"строк: {len(v):,}")
print(f"skills непустых: {(v['required_skills'].astype(str).str.len() > 2).sum():,}")
print("\nspecialization:")
print(v["specialization"].value_counts().head(10))
print("\nrequired_education:")
print(v["required_education"].value_counts())
print("\nmin_experience:")
print(v["min_experience"].describe())

print("\n=== RESUMES (100k) ===")
c = pd.read_csv("data/trudvsem/processed_v2/candidates.csv", nrows=100_000)
print(f"строк: {len(c):,}")
print(f"skills непустых: {(c['skills'].astype(str).str.len() > 2).sum():,}")
print("\nspecialization:")
print(c["specialization"].value_counts().head(10))
print("\neducation:")
print(c["education"].value_counts())
print("\nexperience_years:")
print(c["experience_years"].describe())
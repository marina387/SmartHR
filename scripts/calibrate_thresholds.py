# -*- coding: utf-8 -*-
"""Строит threshold_metrics.csv для новой модели на pairs.csv.

Запуск:
    python scripts/calibrate_thresholds.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score

from src.matching_service import MatchingService


def main() -> None:
    print("[load] MatchingService ...")
    svc = MatchingService()
    print(f"[load] features: {len(svc.feature_names)}")

    print("[load] pairs.csv ...")
    df = pd.read_csv("data/trudvsem/processed_v2/pairs.csv", nrows=200_000)
    print(f"[load] строк: {len(df):,}")

    print("[features] готовлю ...")
    X = []
    for _, row in df.iterrows():
        cand = {
            "experience_years": row["experience_years"],
            "skills": str(row["skills"]),
            "education": row["education"],
            "specialization": row["specialization"],
            "expected_salary": row["expected_salary"],
        }
        vac = {
            "min_experience": row["min_experience"],
            "max_experience": row["max_experience"],
            "required_skills": str(row["required_skills"]),
            "max_salary": row["max_salary"],
            "required_education": row["required_education"],
            "specialization": row["specialization_vac"],
        }
        X.append(svc.prepare_features(cand, vac).iloc[0].values)
    X = np.array(X)

    print("[labels] считаю ...")
    exp = df["experience_years"].clip(0, 60).fillna(0)
    min_e = df["min_experience"].clip(0, 60).fillna(0)
    max_e = df["max_experience"].clip(0, 60).fillna(0)
    salary_ratio = np.where(
        df["max_salary"].fillna(0) > 0,
        df["expected_salary"].fillna(0) / df["max_salary"].fillna(1),
        1.0,
    )
    exp_ok = ((exp >= min_e) & (exp <= max_e)).astype(int)
    sal_ok = (salary_ratio <= 1.3).astype(int)
    edu_ok = (
        df["education"].apply(svc._edu_idx) >= df["required_education"].apply(svc._edu_idx)
    ).astype(int)
    spec_ok = (df["specialization"] == df["specialization_vac"]).astype(int)
    y = (exp_ok & sal_ok & edu_ok & spec_ok).values
    print(f"[labels] позитивов: {y.sum():,} / {len(y):,} ({y.mean()*100:.1f}%)")

    print("[predict] ...")
    prob = svc.model.predict_proba(X)[:, 1]
    print(f"[predict] roc_auc: {roc_auc_score(y, prob):.4f}")

    print("[thresholds] перебираю ...")
    rows = []
    for t in np.arange(0.05, 0.96, 0.05):
        pred = (prob >= t).astype(int)
        rows.append({
            "threshold": round(float(t), 2),
            "precision": float(precision_score(y, pred, zero_division=0)),
            "recall": float(recall_score(y, pred, zero_division=0)),
            "f1": float(f1_score(y, pred, zero_division=0)),
        })
    metrics = pd.DataFrame(rows)
    print(metrics.to_string())

    out = Path("evaluation/results/threshold_metrics.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(out, index=False)
    best = metrics.loc[metrics["f1"].idxmax()]
    print(f"\n[save] {out}")
    print(f"Лучший F1: threshold={best['threshold']:.2f}, "
          f"precision={best['precision']:.4f}, recall={best['recall']:.4f}, f1={best['f1']:.4f}")


if __name__ == "__main__":
    main()